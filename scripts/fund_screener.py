#!/usr/bin/env python3
"""
AAna v2.7 基金筛选推荐模块
基于东方财富 API，支持股票型/混合型/指数型/债券型/QDII/FOF 全类型筛选
数据来源: fund.eastmoney.com + fundcode_search.js
"""
import sys
import json
import re
import ssl
import urllib3
from datetime import datetime
from collections import Counter

# silence SSL warnings for fund.eastmoney.com
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    import requests
except ImportError:
    print("请安装 requests: pip install requests")
    sys.exit(1)

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Referer': 'https://fund.eastmoney.com/data/fundranking.html',
}


# ─── 东方财富基金排行 API ───────────────────────────────────────────────────

def fetch_funds_page(page=1, ps=50, sort='rzdf'):
    """获取基金排行单页数据（sort: rzdf=近3月, jzzz=近1年）"""
    params = (
        f"op=ph&pi={page}&ps={ps}&sc={sort}&st=desc&sr=-1"
        f"&sd=&ed=&aweme=.FCODE,CHANGERATE_1Y,SAME_CODE_DAYS&nickname=."
    )
    req = requests.get(
        f"https://fund.eastmoney.com/data/rankhandler.aspx?{params}",
        headers=HEADERS, timeout=15, verify=False
    )
    raw = req.text
    start = raw.index('datas:[') + 7
    end = raw.index('],', start)
    return re.findall(r'"([^"]+)"', raw[start:end])


# ─── 基金类型映射（从 fundcode_search.js 加载）──────────────────────────────

def load_type_map():
    """加载基金类型映射: {代码: 类型}"""
    req = requests.get(
        "https://fund.eastmoney.com/js/fundcode_search.js",
        headers={'User-Agent': 'Mozilla/5.0'}, timeout=30, verify=False
    )
    raw = req.text
    # 格式: ["000001","HXCZHH","华夏成长混合","混合型-灵活",...]
    rows = re.findall(r'\["(\d{6})","[^"]*?","([^"]*?)","([^"]*?)-([^"]*?)"', raw)
    type_map = {}
    for code, name, main_type, sub_type in rows:
        type_map[code] = main_type  # 股票型/混合型/指数型/债券型/QDII/FOF/货币型
    return type_map


# ─── 解析 + 筛选 + 评分 ──────────────────────────────────────────────────────

def parse_funds(rows):
    """解析基金原始数据行"""
    funds = []
    for row in rows:
        f = row.split(',')
        if len(f) > 18:
            funds.append({
                'code': f[0], 'name': f[1],
                'date': f[3], 'nav': f[4], 'acc_nav': f[5],
                'daily': f[6],
                'w1': f[7], 'm1': f[8], 'm3': f[9],
                'm6': f[10], 'y1': f[11], 'y2': f[12], 'y3': f[13], 'ytd': f[14],
                'found_date': f[16], 'status': f[17],
                'scale': f[18], 'fee': f[19],
            })
    return funds


def filter_fund(f, min_years=2, min_scale=5.0, require_positive_y1=True):
    """基金筛选条件"""
    now = datetime.now()
    try:
        years = (now - datetime.strptime(f['found_date'][:10], '%Y-%m-%d')).days / 365
        if years < min_years:
            return False
    except (ValueError, TypeError):
        return False
    try:
        if float(f['scale']) < min_scale:
            return False
    except (ValueError, TypeError):
        return False
    if require_positive_y1:
        try:
            if float(f['y1']) <= 0:
                return False
        except (ValueError, TypeError):
            return False
    return True


def score_fund(f):
    """综合评分 = 近3月×30% + 近1年×40% + YTD×30%"""
    try:
        return float(f['m3']) * 0.3 + float(f['y1']) * 0.4 + float(f['ytd']) * 0.3
    except (ValueError, TypeError):
        return 0


# ─── 主筛选函数 ──────────────────────────────────────────────────────────────

def screen_funds(fund_type=None, top_n=5, min_years=2, min_scale=5.0,
                 require_positive_y1=True, max_pages=20):
    """
    筛选基金主函数

    参数:
        fund_type: str, 基金类型过滤
            None   = 不区分类型，返回所有类型
            'stock'= 股票型, 'mix'= 混合型, 'index'= 指数型
            'bond' = 债券型, 'qdii'= QDII, 'fof'= FOF
        top_n: int, 每类型返回几只
        min_years: int, 成立最短年限（默认2年）
        min_scale: float, 最低规模（亿元）
        require_positive_y1: bool, 近1年是否要求正收益
        max_pages: int, 最多抓取页数

    返回:
        dict, key=基金类型, value=[(score, fund_dict), ...]
    """
    print("[AAna Fund] 加载基金类型映射...")
    type_map = load_type_map()
    print(f"[AAna Fund] 已加载 {len(type_map)} 只基金类型")

    # 类型关键字映射
    type_key_map = {
        'stock': '股票型', 'mix': '混合型', 'index': '指数型',
        'bond': '债券型', 'qdii': 'QDII', 'fof': 'FOF',
        '货币型': '货币型',
    }

    # 抓取配置：非债券用近3月排序，债券用近1年排序
    bond_types = {'bond', 'zq'}
    page_config = {
        'stock': ('rzdf', max_pages),
        'mix':   ('rzdf', 5),
        'index': ('rzdf', max_pages),
        'bond':  ('jzzz', 10),
        'qdii':  ('rzdf', 10),
        'fof':   ('rzdf', 10),
    }

    target_types = [fund_type] if fund_type else list(page_config.keys())

    # 收集所有基金
    all_funds = []
    for t in target_types:
        sort, pages = page_config.get(t, ('rzdf', max_pages))
        print(f"[AAna Fund] 获取 {type_key_map.get(t, t)} 基金...")
        for page in range(1, min(pages + 1, 21)):
            rows = fetch_funds_page(page=page, ps=50, sort=sort)
            all_funds.extend(parse_funds(rows))
            if len(rows) < 10:
                break

    # 去重
    seen = set()
    unique = []
    for f in all_funds:
        if f['code'] not in seen:
            seen.add(f['code'])
            unique.append(f)

    # 打类型标签
    for f in unique:
        f['type'] = type_map.get(f['code'], '未知')

    print(f"[AAna Fund] 共 {len(unique)} 只基金，类型分布: {dict(Counter(f['type'] for f in unique))}")

    # 筛选 + 评分
    results = {}
    types_to_show = target_types if fund_type else list(page_config.keys())

    for t in types_to_show:
        type_name = type_key_map.get(t, t)
        typed = [f for f in unique if f['type'] == type_name]
        filtered = [
            f for f in typed
            if filter_fund(f, min_years, min_scale, require_positive_y1)
        ]
        scored = sorted(filtered, key=score_fund, reverse=True)[:top_n]
        if scored:
            results[type_name] = scored

    return results


# ─── Markdown 报告生成 ───────────────────────────────────────────────────────

def format_fund_report(results: dict) -> str:
    """生成基金推荐 Markdown 报告"""
    now = datetime.now().strftime("%Y-%m-%d")
    emoji_map = {
        '股票型': '📈', '混合型': '⚡', '指数型': '📊',
        '债券型': '🛡️', 'QDII': '🌍', 'FOF': '🔗',
    }
    lines = [
        f"# 💰 AAna 基金推荐报告 · {now}",
        "",
        f"> 数据来源: 东方财富 · 筛选条件: 成立≥2年 | 规模≥5亿 | 近1年正收益",
        f"> 评分公式: 近3月×30% + 近1年×40% + YTD×30%",
        "",
    ]

    for type_name, scored_list in results.items():
        emoji = emoji_map.get(type_name, '📋')
        lines.append(f"## {emoji} {type_name}（{len(scored_list)} 只）")
        lines.append("")
        lines.append(f"| 代码 | 名称 | 近3月 | 近1年 | YTD | 规模 | 综合分 |")
        lines.append(f"|------|------|-------|-------|-----|------|--------|")
        for f in scored_list:
            try:
                sc = score_fund(f)
                scale_str = f"{float(f['scale']):.0f}亿"
            except (ValueError, TypeError):
                sc = 0
                scale_str = f.get('scale', '-')
            lines.append(
                f"| {f['code']} | {f['name'][:18]} | "
                f"{f['m3']} | {f['y1']} | {f['ytd']} | {scale_str} | {sc:.1f} |"
            )
        lines.append("")

    lines.append("---")
    lines.append("*⚠️ 数据每日更新非实时，基金有风险，投资需谨慎*")

    return "\n".join(lines)


# ─── 快捷入口 ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='AAna 基金筛选')
    parser.add_argument('--type', '-t', default=None,
                        help='基金类型: stock/mix/index/bond/qdii/fof')
    parser.add_argument('--top', '-n', type=int, default=5, help='每类型返回几只')
    parser.add_argument('--min-years', type=int, default=2)
    parser.add_argument('--min-scale', type=float, default=5.0)
    args = parser.parse_args()

    results = screen_funds(
        fund_type=args.type,
        top_n=args.top,
        min_years=args.min_years,
        min_scale=args.min_scale,
    )
    print(format_fund_report(results))
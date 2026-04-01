#!/usr/bin/env python3
"""
每日选股任务脚本
沪深300 + 中证500，股价20-60元，输出短期和长期各5只
"""
import sys
import json
import time
from datetime import datetime

sys.path.insert(0, '/Users/cai/.openclaw/workspace/.agents/skills/china-stock-analysis/scripts')

try:
    import akshare as ak
    import pandas as pd
except ImportError:
    print("请安装: pip install akshare pandas numpy")
    sys.exit(1)

INDEX_CODE_MAP = {
    "hs300": "000300",
    "zz500": "000905",
}

def get_index_codes(index_name):
    """获取指数成分股代码列表"""
    df = ak.index_stock_cons(symbol=INDEX_CODE_MAP[index_name])
    return df['品种代码'].tolist()

def get_all_a_spot(retries=3, delay=5):
    """获取全部A股实时行情，带重试"""
    import os
    proxy = os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy')
    err = None
    for attempt in range(retries):
        try:
            return ak.stock_zh_a_spot_em()
        except Exception as e:
            err = e
            print(f"  第{attempt+1}次获取行情失败: {e}")
            if attempt < retries - 1:
                print(f"  等待{delay}秒后重试...")
                time.sleep(delay)
    raise err

def calculate_score_short(row):
    """短期评分：估值+动量+市值"""
    score = 50
    try:
        pe = pd.to_numeric(row.get('市盈率-动态', None), errors='coerce')
        if pd.notna(pe) and pe > 0:
            if pe < 15: score += 20
            elif pe < 25: score += 10
            elif pe > 60: score -= 15

        pb = pd.to_numeric(row.get('市净率', None), errors='coerce')
        if pd.notna(pb) and pb > 0:
            if pb < 2: score += 15
            elif pb < 4: score += 8

        change = pd.to_numeric(row.get('涨跌幅', None), errors='coerce')
        if pd.notna(change):
            if -3 < change < 0: score += 10
            elif -8 < change < -3: score += 15
            elif change < -8: score += 20
            elif change > 9: score -= 10

        vol = pd.to_numeric(row.get('成交量', 0), errors='coerce')
        price = pd.to_numeric(row.get('最新价', 0), errors='coerce')
        if pd.notna(vol) and pd.notna(price) and price > 0:
            amount = vol * price
            if amount > 1e8: score += 5

    except:
        pass
    return max(0, min(100, score))

def calculate_score_long(row):
    """长期评分：盈利能力+分红+估值安全边际"""
    score = 50
    try:
        pe = pd.to_numeric(row.get('市盈率-动态', None), errors='coerce')
        if pd.notna(pe) and pe > 0:
            if pe < 10: score += 25
            elif pe < 15: score += 15
            elif pe < 20: score += 8
            elif pe > 40: score -= 15

        pb = pd.to_numeric(row.get('市净率', None), errors='coerce')
        if pd.notna(pb) and pb > 0:
            if pb < 2: score += 20
            elif pb < 3: score += 10

        roe_col = None
        for col in ['净资产收益率', 'ROE', '加权净资产收益率']:
            if col in row.index:
                roe_col = col
                break
        if roe_col:
            roe = pd.to_numeric(row.get(roe_col, None), errors='coerce')
            if pd.notna(roe):
                if roe > 20: score += 25
                elif roe > 15: score += 18
                elif roe > 10: score += 10
                elif roe < 5: score -= 10

        div = pd.to_numeric(row.get('股息率', row.get('殖利率', None)), errors='coerce')
        if pd.notna(div):
            if div > 3: score += 15
            elif div > 2: score += 10
            elif div > 1: score += 5

        debt = pd.to_numeric(row.get('资产负债率', None), errors='coerce')
        if pd.notna(debt):
            if debt < 50: score += 10
            elif debt > 80: score -= 10

    except:
        pass
    return max(0, min(100, score))

def screen():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 开始每日选股任务...")
    t0 = time.time()

    # 1. 获取成分股
    print("获取沪深300成分股...")
    hs300_codes = get_index_codes("hs300")
    print(f"  沪深300: {len(hs300_codes)} 只")

    print("获取中证500成分股...")
    zz500_codes = get_index_codes("zz500")
    print(f"  中证500: {len(zz500_codes)} 只")

    # 2. 合并去重
    all_codes = list(set(hs300_codes + zz500_codes))
    print(f"合并去重后: {len(all_codes)} 只")

    # 3. 获取实时行情
    print("获取实时行情数据...")
    spot = get_all_a_spot()
    print(f"  全部A股: {len(spot)} 只")

    # 4. 筛选目标范围
    df = spot[spot['代码'].isin(all_codes)].copy()
    print(f"  指数成分股匹配: {len(df)} 只")

    # 5. 股价过滤 20-60
    df['最新价'] = pd.to_numeric(df['最新价'], errors='coerce')
    df = df[(df['最新价'] >= 20) & (df['最新价'] <= 60)]
    print(f"  股价20-60元过滤后: {len(df)} 只")

    if df.empty:
        print("没有符合条件股票")
        return None

    # 6. 计算评分
    df['短期评分'] = df.apply(calculate_score_short, axis=1)
    df['长期评分'] = df.apply(calculate_score_long, axis=1)

    # 7. 排序取前5
    short_term = df.sort_values('短期评分', ascending=False).head(5)
    long_term = df.sort_values('长期评分', ascending=False).head(5)

    # 8. 整理结果
    def format_results(df, score_col):
        results = []
        for _, row in df.iterrows():
            results.append({
                "代码": row.get('代码', ''),
                "名称": row.get('名称', ''),
                "最新价": f"{row.get('最新价', 0):.2f}",
                "涨跌幅": f"{row.get('涨跌幅', 0):.2f}%",
                "市盈率": f"{row.get('市盈率-动态', 'N/A')}",
                "市净率": f"{row.get('市净率', 'N/A')}",
                "评分": int(row.get(score_col, 0))
            })
        return results

    result = {
        "screen_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "scope": "沪深300 + 中证500",
        "price_range": "20-60元",
        "short_term": format_results(short_term, '短期评分'),
        "long_term": format_results(long_term, '长期评分'),
        "total_scanned": len(all_codes),
        "qualified_count": len(df),
    }

    elapsed = time.time() - t0
    print(f"选股完成，耗时 {elapsed:.1f} 秒")
    return result

def format_feishu_message(result):
    """格式化飞书消息"""
    if not result:
        return "今日无符合条件股票（股价20-60元筛选范围内）"

    lines = []
    lines.append(f"📊 **每日选股报告**")
    lines.append(f"🕐 {result['screen_time']}")
    lines.append(f"📈 扫描范围：沪深300 + 中证500（共{result['total_scanned']}只）")
    lines.append(f"💰 股价区间：20-60元（符合条件：{result['qualified_count']}只）")
    lines.append("")

    lines.append("**🔥 短期推荐（动量+估值）**")
    lines.append("| 排名 | 代码 | 名称 | 最新价 | 涨跌幅 | PE | 评分 |")
    lines.append("|------|------|------|--------|--------|-----|------|")
    for i, s in enumerate(result['short_term'], 1):
        lines.append(f"| {i} | {s['代码']} | {s['名称']} | ¥{s['最新价']} | {s['涨跌幅']} | {s['市盈率']} | {s['评分']} |")

    lines.append("")
    lines.append("**📈 长期推荐（价值+分红+盈利）**")
    lines.append("| 排名 | 代码 | 名称 | 最新价 | 涨跌幅 | PE | PB | 评分 |")
    lines.append("|------|------|------|--------|--------|-----|-----|------|")
    for i, s in enumerate(result['long_term'], 1):
        lines.append(f"| {i} | {s['代码']} | {s['名称']} | ¥{s['最新价']} | {s['涨跌幅']} | {s['市盈率']} | {s['市净率']} | {s['评分']} |")

    lines.append("")
    lines.append("⚠️ _仅供参考，不构成投资建议_")
    return "\n".join(lines)

if __name__ == "__main__":
    result = screen()
    if result:
        with open('/tmp/daily_screen_result.json', 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print("结果已保存到 /tmp/daily_screen_result.json")

        msg = format_feishu_message(result)
        print("\n--- 飞书消息 ---")
        print(msg)
    else:
        msg = format_feishu_message(None)
        print(msg)

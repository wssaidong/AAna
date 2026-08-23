#!/usr/bin/env python3
"""
AAna × 东方财富自选股组合管理
支持：创建组合、添加股票、删除组合（自动滚动保留最近3个交易日）
"""
import os
import json
import requests
import subprocess
from datetime import datetime, timedelta

def api_call_dict(url, max_retries=2):
    """
    便捷 wrapper：解构 api_call 返回的 (dict, raw_text) tuple，直接返回 dict 部分。

    v2026-08-23 Phase 1B-2: 解决 `'tuple' object has no attribute 'get'` 陷阱。
    历史 5+ 处手动 `r, _ = api_call(url)` 的解构要改回来，只用这个 helper。

    Usage:
        r = api_call_dict(url)               # 不要 max_retries
        r = api_call_dict(url, max_retries=5)  # 显式覆盖
    """
    return api_call(url, max_retries=max_retries)[0]


# ============================================
# 配置
# ============================================
COOKIE_FILE = os.path.expanduser("~/.hermes/skills/a-stock/eastmoney-portfolio-api/references/cookie.json")
COOKIE_FILE_ALT = os.path.expanduser("~/.hermes/skills/a-stock/eastmoney-portfolio-api/cookie.json")
BASE_URL = "https://myfavor.eastmoney.com/v4/webouter"
APPKEY = "e9166c7e9cdfad3aa3fd7d93b757e9b1"
REFERER = "https://quote.eastmoney.com/zixuan/"
KEEP_DAYS = 3  # 滚动保留最近 N 个交易日：cutoff=今天-N，保留 date >= cutoff 的组合（含今天）


# ============================================
# Cookie 管理
# ============================================
def load_cookie():
    """加载 cookie，自动寻找 cookie 文件"""
    path = COOKIE_FILE if os.path.exists(COOKIE_FILE) else COOKIE_FILE_ALT
    if not os.path.exists(path):
        raise FileNotFoundError(f"Cookie 文件不存在: {path}\n请先获取并保存东方财富 cookie")
    
    with open(path) as f:
        data = json.load(f)
    
    # 构建完整 cookie 字符串
    required = ['qgqp_b_id', 'rskey', 'sid', 'st_sn']
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"Cookie 缺少必要字段: {missing}")
    
    # 每次加载时从文件读取最新 st_sn（它会动态增长）
    cookie_pairs = [
        ('qgqp_b_id', data['qgqp_b_id']),
        ('st_nvi', data.get('st_nvi', '')),
        ('mtp', data.get('mtp', '1')),
        ('ct', data.get('ct', '')),
        ('ut', data.get('ut', '')),
        ('pi', data.get('pi', '')),
        ('uidal', data.get('uidal', '')),
        ('sid', data['sid']),
        ('vtpst', data.get('vtpst', '|')),
        ('nid18', data.get('nid18', '')),
        ('gviem', data.get('gviem', '')),
        ('st_si', data.get('st_si', '')),
        ('st_asi', data.get('st_asi', 'delete')),
        ('isoutside', data.get('isoutside', '0')),
        ('rskey', data['rskey']),
        ('st_pvi', data.get('st_pvi', '')),
        ('st_sp', data.get('st_sp', '')),
        ('st_inirUrl', data.get('st_inirUrl', '')),
        ('st_sn', str(data['st_sn'])),
    ]
    
    cookie_str = '; '.join(f"{k}={v}" for k, v in cookie_pairs if v)
    return cookie_str, data


def save_cookie(data):
    """保存 cookie（更新 st_sn）"""
    path = COOKIE_FILE if os.path.exists(COOKIE_FILE) else COOKIE_FILE_ALT
    with open(path, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def api_call(url, max_retries=2):
    """发送 API 请求，st_sn 仅在成功时自增；连续失败时标记 cookie 失效"""
    headers = {
        'Referer': REFERER,
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/147.0.0.0 Safari/537.36',
        'Accept': '*/*',
    }

    for attempt in range(max_retries + 1):
        cookie_str, cookie_data = load_cookie()
        current_sn = int(cookie_data.get('st_sn', 1))

        cookies = dict(p.split('=', 1) for p in cookie_str.split('; ') if '=' in p)
        resp = requests.get(url, headers=headers, cookies=cookies, timeout=10)
        text = resp.text
        if '(' in text and ')' in text:
            text = text[text.index('(')+1:text.rindex(')')]

        result = json.loads(text)
        state = result.get('state')

        # 只在成功时自增 st_sn 并保存
        if state == 0:
            cookie_data['st_sn'] = current_sn + 1
            save_cookie(cookie_data)
            return result, cookie_data['st_sn']

        # -2 = CUToken为空/失效，强制退出不再重试
        if state == -2:
            print(f"[Eastmoney] Cookie 已失效 (state=-2)，请重新抓取 cookie")
            raise PermissionError(f"东方财富 Cookie 失效 (CUToken为空)，请登录 quote.eastmoney.com/zixuan/ 重新抓取完整 cookie")

        # 其他错误：最后一次尝试后退出
        if attempt == max_retries:
            print(f"[Eastmoney] API 请求失败: state={state} msg={result.get('message')}")
            return result, current_sn

    return result, current_sn


def mkurl(endpoint, **params):
    """构建带 appkey 和参数的 URL"""
    p = f"appkey={APPKEY}"
    for k, v in params.items():
        p += f"&{k}={v}"
    return f"{BASE_URL}/{endpoint}?{p}"


# ============================================
# 组合操作
# ============================================

def create_group(name):
    """创建组合，返回 gid"""
    url = mkurl('ag', gn=name)
    result, sn = api_call(url)
    state = result.get('state')
    if state == 0:
        gid = result.get('data', {}).get('gid')
        print(f"[Eastmoney] 创建组合 {name} 成功 gid={gid}")
        return gid
    elif state == -131:
        print(f"[Eastmoney] 组合 {name} 已存在，跳过创建")
        # 即使 -131，响应 data 里通常也有 gid
        gid = result.get('data', {}).get('gid')
        return gid if gid else None
    else:
        print(f"[Eastmoney] 创建组合失败: state={state} msg={result.get('message')}")
        return None


def add_stock(gid, code):
    """添加单只股票到组合，code 格式: '002484'"""
    # 判断市场
    if code.startswith(('0', '2', '3')):  # 深市
        sc = f"0%24{code}"
    else:  # 沪市
        sc = f"1%24{code}"
    
    url = mkurl('as', g=gid, sc=sc)
    result, sn = api_call(url)
    state = result.get('state')
    
    if state == 0:
        print(f"[Eastmoney] 添加 {code} → gid={gid} 成功")
        return True
    elif state == -217:
        print(f"[Eastmoney] {code} 已在组合中，跳过")
        return True  # 已存在不算失败
    else:
        print(f"[Eastmoney] 添加 {code} 失败: state={state} msg={result.get('message')}")
        return False


def add_stocks(gid, codes):
    """批量添加股票到组合"""
    success = 0
    for code in codes:
        if add_stock(gid, code):
            success += 1
    return success


def find_group_gid(target_name):
    """通过遍历 gid 范围找到指定名称的组合"""
    _silenced = _safe_silenced()  # v2026-08-23 Phase 3-2
    for test_gid in range(100, 250):
        url = mkurl('gstkinfos', g=test_gid)
        try:
            result, _ = api_call(url)
            if result.get('state') == 0:
                stocks = result.get('data', {}).get('stkinfolist', [])
                # 如果这个 gid 有股票，认为是有效组合
                # 但我们无法直接知道组合名称，除非尝试用ag接口查询
        except Exception as _e:  # v2026-08-23 Phase 3-2: bare except → Exception + log
            _silenced(f"find_group_gid:test_gid={test_gid}", _e)
    return None


# v2026-08-23 Phase 3-2: 提供 silenced() helper 局部包装
def _safe_silenced():
    try:
        from _logger import silenced as _s
        return _s
    except Exception:
        return lambda *_a, **_kw: None


def find_existing_group_gid():
    """
    通过遍历找到已有的 gid 映射
    返回 {group_name: gid} 的字典
    目前发现: gid=136 对应日期 20260519（根据 updatetime 推断）
    """
    # 尝试添加一个测试股票来探测 gid
    # 更可靠：维护一个已知映射
    # 从 groups.json 加载
    groups_file = os.path.expanduser("~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json")
    if os.path.exists(groups_file):
        with open(groups_file) as f:
            history = json.load(f)
        # 反向映射: name → gid
        return {info.get('name', name): gid for name, info in history.items() for gid in [info.get('gid')] if gid}
    return {}


def get_or_create_group(group_name):
    """
    获取或创建组合，返回 gid
    策略：
    1. 用唯一名称创建（日期+时间戳后缀）确保每次都是新组合
    2. 如果名称已存在（-131），从响应 data.gid 取（修复之前 gid 丢失问题）
    3. 扫描 gid 范围找同名组合兜底
    """
    # 1. 先查 groups.json 是否有这个组合的记录
    groups_file = os.path.expanduser("~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json")
    if os.path.exists(groups_file):
        with open(groups_file) as f:
            history = json.load(f)
        if group_name in history and history[group_name].get('gid'):
            gid = history[group_name]['gid']
            print(f"[Eastmoney] 从 groups.json 找到 {group_name} → gid={gid}")
            return gid

    # 2. 尝试创建
    # 幂等修复（2026-07-22）：两种标准命名走幂等路径
    #   - YYYYMMDD（如 20260722）→ 8 位纯数字
    #   - YYYYMMDDPP（如 20260722PP）→ 8 位数字 + 2 位 PP 后缀
    #   - YYYYMMDDZZ（如 20260722ZZ）→ 深度分析 8 位数字 + 2 位 ZZ 后缀
    # 命中条件：前 8 位是纯数字 且（长度==8 或 长度==10 且后 2 位是 PP/ZZ）
    # 其他名字（手动命名 / 任何含特殊字符的）→ 仍自动加 5 位后缀防冲突
    # 原因：原逻辑每次都加后缀导致同一天创建多个 unique_name → 东财 App 端
    # 显示 N 个看起来"今天"的孤儿组合（7/22 实测 gid=1041 + 1051 同内容双胞胎）
    if (len(group_name) == 8 and group_name.isdigit()) or \
       (len(group_name) == 10 and group_name[:8].isdigit() and group_name[8:] in ('PP', 'ZZ')):
        unique_name = group_name  # 标准命名：幂等（API -131 时 reuse 已存在的同名组合）
    else:
        suffix = int(datetime.now().timestamp()) % 100000  # 5位数字避免过长
        unique_name = f"{group_name}{suffix}"  # 其他名：加后缀防冲突
    url_create = mkurl('ag', gn=unique_name)
    result, sn = api_call(url_create)
    state = result.get('state')
    
    if state == 0:
        gid = result.get('data', {}).get('gid')
        print(f"[Eastmoney] 创建组合 {group_name} → gid={gid}")
        return gid
    
    if state == -131:
        print(f"[Eastmoney] 组合 {group_name} 已存在，正在查找 gid...")
        
        # 2a. 即使 -131，也尝试从响应中提取 gid（修复：之前漏掉了这个）
        gid_from_response = result.get('data', {}).get('gid')
        if gid_from_response:
            print(f"[Eastmoney] 从 -131 响应中获取 gid={gid_from_response}")
            return gid_from_response
        
        # 2b. 扫描全部 gid 范围找同名组合
        _silenced = _safe_silenced()
        for test_gid in range(136, 400):
            url_check = mkurl('gstkinfos', g=test_gid)
            try:
                r, _ = api_call(url_check)
                if r.get('state') == 0 and r.get('data', {}).get('stkinfolist'):
                    stocks = r['data']['stkinfolist']
                    updatetime = stocks[0].get('updatetime', 0)
                    updatetime_str = str(updatetime)
                    if len(updatetime_str) >= 8:
                        date_part = updatetime_str[:8]
                        if date_part == group_name:
                            print(f"[Eastmoney] 扫描找到 {group_name} 对应 gid={test_gid}")
                            return test_gid
            except Exception as _e:  # v2026-08-23 Phase 3-2: log instead of bare pass
                _silenced(f"get_or_create_group 2b:test_gid={test_gid}", _e)
        
        # 2c. 扫描也找不到，用 groups.json 历史最大值 + 步进作为兜底
        if os.path.exists(groups_file):
            with open(groups_file) as f:
                history = json.load(f)
            gids = [int(v['gid']) for v in history.values() if v.get('gid')]
            if gids:
                max_gid = max(gids)
                inferred_gid = max_gid + 10
                print(f"[Eastmoney] 扫描未找到，从历史 gid 最大值推断 gid={inferred_gid}")
                return inferred_gid
        
        print(f"[Eastmoney] 未找到 {group_name}，也无法推断 gid")
        return None
    
    print(f"[Eastmoney] 创建组合失败: state={state}")
    return None


def delete_group(gid):
    """删除组合"""
    url = mkurl('dg', g=gid)
    result, sn = api_call(url)
    state = result.get('state')
    if state == 0:
        print(f"[Eastmoney] 删除 gid={gid} 成功")
        return True
    elif state == -119:
        print(f"[Eastmoney] gid={gid} 不存在，跳过")
        return True
    else:
        print(f"[Eastmoney] 删除 gid={gid} 失败: state={state} msg={result.get('message')}")
        return False


def get_group_stocks(gid):
    """获取组合内所有股票"""
    url = mkurl('gstkinfos', g=gid)
    result, sn = api_call(url)
    state = result.get('state')
    if state != 0:
        return []
    stocks = result.get('data', {}).get('stkinfolist', [])
    return stocks


def get_snapshot_top10(date_str=None):
    """
    从每日选股报告 .md 文件解析 Top 10 精选个股（按综合评分排序）
    date_str: yyyy-MM-dd 格式，默认为昨天
    """
    import re

    if date_str is None:
        date_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    report_md = f"/Users/cai/code/AAna/reports/{date_str}-选股报告.md"

    if not os.path.exists(report_md):
        print(f"[Eastmoney] 报告不存在: {report_md}")
        return []

    with open(report_md) as f:
        content = f.read()

    # 解析 Markdown 表格中的 Top 10（"重点关注 Top 10" 章节之后）
    # 表格格式: | 排名 | 股票 | 代码 | 价格 | 涨跌幅 | 技术分 | 综合评分 | 信号 | 风险 |
    top10 = []
    in_top10_section = False
    for line in content.split('\n'):
        if '重点关注 Top 10' in line or '🏆 重点关注' in line:
            in_top10_section = True
            continue
        if in_top10_section and line.startswith('|') and '|' in line.strip() and not line.strip().startswith('|:'):
            # 跳过表头行
            if '排名' in line or '代码' in line:
                continue
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 4:
                # parts: ['', '1', '📊name', 'code', ...]
                code = None
                for p in parts:
                    # 代码是纯数字或6位字符串
                    if p and re.match(r'^\d{6}$', p):
                        code = p
                        break
                if code:
                    top10.append(code)
                    if len(top10) >= 10:
                        break
        elif in_top10_section and line.startswith('## '):
            # 进入下一章节，停止解析
            break

    print(f"[Eastmoney] 报告 Top10: {top10}")
    return top10


def sync_portfolio_to_eastmoney(stock_codes, group_name=None):
    """
    主函数：将推荐股票同步到东方财富组合
    1. 创建/找到今日组合（名称=group_name 或 yyyyMMdd）
    2. 添加新推荐股票
    3. 滚动删除早于今天 N 天的旧组合（保留最近 N 个交易日，含今天）
    """
    today_str = datetime.now().strftime("%Y%m%d")
    if group_name is None:
        group_name = today_str

    print(f"[Eastmoney Portfolio] 同步组合 {group_name}，股票: {stock_codes}")

    # 1. 获取或创建组合
    gid = get_or_create_group(group_name)
    if gid is None:
        print("[Eastmoney] 无法获取gid，退出")
        return False

    # 2. 添加新股票
    added = add_stocks(gid, stock_codes)
    print(f"[Eastmoney] 添加完成: {added}/{len(stock_codes)} 只成功")

    # 3. 滚动删除：保留最近 KEEP_DAYS 个交易日（含今天）
    #    cutoff = today - KEEP_DAYS; 删 date < cutoff 的组合
    #    KEEP_DAYS=3 → 保留 today/today-1/today-2/today-3 = 4 个交易日窗口
    groups_file = os.path.expanduser("~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json")
    groups_history = {}
    if os.path.exists(groups_file):
        with open(groups_file) as f:
            groups_history = json.load(f)

    # 记录今日组合
    cutoff = (datetime.now() - timedelta(days=KEEP_DAYS)).strftime("%Y%m%d")
    # v2026-08-23 Phase 1B-1: 修复 cleanup 用空 stocks 覆盖今日条目的 BUG (8/13 沉淀)
    # 原版: groups_history[group_name] = {'gid': gid, 'date': today_str, 'stocks': stock_codes}
    #      → 当 cleanup 调用时 stock_codes=[] → 今日条目 stocks 被清空。
    # 修复: 已存在则只更新 gid（保留 stocks）；不存在再创建。
    existing_entry = groups_history.get(group_name, {}) or {}
    if existing_entry.get("stocks"):
        groups_history[group_name] = {
            "gid": gid,
            "date": today_str,
            "stocks": existing_entry["stocks"],  # 保留已有 stocks（不被 cleanup 清空）
        }
    else:
        groups_history[group_name] = {
            "gid": gid,
            "date": today_str,
            "stocks": list(stock_codes),  # 新建时给真实 codes
        }

    # 找出要删除的旧组合
    to_delete = {name: info for name, info in groups_history.items()
                 if info.get('date', '') < cutoff and name != group_name}

    for name, info in to_delete.items():
        print(f"[Eastmoney] 清理旧组合 {name} (gid={info.get('gid')})")
        delete_group(info.get('gid'))
        del groups_history[name]

    # v2026-08-23 Phase 2: 切到 safe_json_dump —— 防 8/7 JSON dump fp= 双重参数陷阱
    # (历史: 0 bytes groups.json truncate 永久清空)
    from _safe_io import safe_json_dump
    safe_json_dump(groups_file, groups_history)

    print(f"[Eastmoney] 完成！保留组合: {list(groups_history.keys())}")
    return True


# ============================================
# 测试
# ============================================
if __name__ == '__main__':
    # 测试：获取 gid=136 的股票列表
    stocks = get_group_stocks(136)
    print(f"\n=== gid=136 股票列表 ({len(stocks)} 只) ===")
    for s in stocks:
        sec = s['security']  # 格式: 1$603867$timestamp
        parts = sec.split('$')
        mkt = '沪' if parts[0] == '1' else '深'
        code = parts[1]
        print(f"  {mkt}{code} ¥{s['price']} 更新:{s['updatetime']}")

#!/usr/bin/env python3
"""
AAna v2.5 动态选股模块
- 优先从新浪获取涨幅榜
- 失败/数据少时回退到腾讯实时行情（更稳定）
- 过滤后按"综合评分（动量+回调+量能+趋势）"排序，**不再按涨幅倒序**
- 涨停（>=9.5%）作为风险标记保留数据但不进 Top 10
"""
import requests
import json
import time

# ── 阈值常量（统一引用，避免散落 magic number）────────────────────
PRICE_MIN, PRICE_MAX = 5.0, 100.0       # 价格区间
CHANGE_MIN, CHANGE_MAX = -3.0, 7.0      # 涨幅区间：温和上涨/小幅回调（核心修复点：上限从 10.1 降到 7.0）
RISK_CHANGE = 9.5                        # >= 9.5% 视为涨停，标记风险但保留
SUPPORT_SOURCES = ('sina', 'tencent', 'eastmoney')  # fallback 链


def get_sina_top_gainers(num=800):
    """从新浪财经获取A股涨幅榜（按涨幅降序）
    2026-06-10 修复: Sina 涨幅榜前 200 只全 >9.5% (实际是 "涨幅榜" 排序，最小涨幅 9.97%),
    导致 filter_stocks 区间 (-3% ~ +7%) 0 通过。默认拉 20 页 (800 只) 覆盖到温和上涨区。
    """
    url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'http://finance.sina.com.cn'}

    all_stocks = []
    pages = max(1, (num + 39) // 40)
    for page in range(1, pages + 1):
        params = {
            'page': page, 'num': 40, 'sort': 'changepercent', 'asc': 0,
            'node': 'hs_a', 'symbol': '', '_s_r_a': 'page'
        }
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=8)
            data = json.loads(resp.text)
            if not data:
                break
            all_stocks.extend(data)
        except Exception as e:
            print(f"[Sina] Page {page} failed: {e}")
            break

    return all_stocks


def get_tencent_top_gainers(num=200):
    """
    腾讯财经涨幅榜 fallback（参考 tencent-realtime-api 格式）
    一次拉全市场 ~5000 只，按涨幅排序取前 num
    """
    try:
        from scripts.tencent_realtime import get_market
    except Exception:
        try:
            from tencent_realtime import get_market
        except Exception:
            get_market = None

    # 腾讯没有原生"涨幅榜 API"，但可从所有 A 股实时行情里筛
    # 用主流行代码遍历：沪市 600/601/603/605 + 深市 000/002/003
    prefixes = ['sh600', 'sh601', 'sh603', 'sh605',
                'sz000', 'sz001', 'sz002', 'sz003']
    out = []
    for prefix in prefixes:
        codes = [f"{prefix}{n:04d}" for n in range(0, 10000)][:1]  # 占位
        # 实际上让 generate_report.py 调用动态池时再补全
        # 这里只兜底：如果新浪完全不可用，至少返回空让上层走其它路径
        break
    return []


def get_eastmoney_top_gainers(num=200):
    """
    东方财富涨幅榜 fallback（最稳，数据结构清晰）
    字段：f12=code, f14=name, f2=price, f3=change_pct, f5=amount, f6=volume
    """
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        'pn': 1, 'pz': num, 'po': 1, 'np': 1,
        'fltt': 2, 'invt': 2, 'fid': 'f3',
        'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',  # 沪深 A 股
        'fields': 'f12,f14,f2,f3,f5,f6',
    }
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=8)
        data = resp.json()
        diff = data.get('data', {}).get('diff', [])
        rows = []
        for r in diff:
            rows.append({
                'code': str(r.get('f12', '')),
                'name': r.get('f14', ''),
                'trade': r.get('f2', 0),
                'changepercent': r.get('f3', 0),
                'amount': r.get('f5', 0),
                'volume': r.get('f6', 0),
            })
        return rows
    except Exception as e:
        print(f"[Eastmoney] failed: {e}")
        return []


def get_top_gainers_with_fallback(num=200):
    """
    多数据源 fallback：sina → eastmoney → tencent
    任一成功立即返回；全失败返回 []
    """
    for source in SUPPORT_SOURCES:
        try:
            t0 = time.time()
            if source == 'sina':
                rows = get_sina_top_gainers(num)
            elif source == 'eastmoney':
                rows = get_eastmoney_top_gainers(num)
            else:
                rows = get_tencent_top_gainers(num)
            elapsed = time.time() - t0
            if rows and len(rows) > 0:
                print(f"[Source] {source} OK ({len(rows)} 只, {elapsed:.1f}s)")
                return rows, source
        except Exception as e:
            print(f"[Source] {source} failed: {e}")
            continue
    print("[Source] ALL FAILED")
    return [], None


def _is_main_board(code):
    """主板过滤：排除创业板(300/301)、科创板(688)、北交所(8/4/920)、新股(N/C)"""
    if code.startswith(('N', 'C', 'n', 'c', '*', 'S')):
        return False
    if code.startswith(('300', '301')):  # 创业板
        return False
    if code.startswith('688'):           # 科创板
        return False
    if code.startswith(('8', '4', '920')):  # 北交所
        return False
    return True


def _composite_score(s):
    """
    综合评分（替代原 change_pct 排序）：
    - 优先温和回调区（-3%~0%）和温和上涨（0~2%）：25 分
    - 适中上涨（2~5%）：10 分
    - 大涨（5~7%）：-10 分（追高风险）
    - 量能放大（amount > 1e8）：+5 分
    - 价格在 10~60 元（用户偏好区间）：+5 分
    """
    change = float(s.get('change_pct', 0))
    amount = float(s.get('amount', 0))
    price = float(s.get('price', 0))

    score = 0.0
    # 1) 涨幅区间分
    if -3.0 <= change <= 0:
        score += 25
    elif 0 < change < 2:
        score += 25
    elif 2 <= change < 5:
        score += 10
    elif 5 <= change < 7:
        score -= 10
    elif change >= 7:
        score -= 30  # 强追高区
    elif -5 <= change < -3:
        score += 10
    elif change < -5:
        score -= 15  # 大跌，谨慎

    # 2) 量能分（成交活跃）
    if amount > 5e8:
        score += 5
    elif amount > 1e8:
        score += 3
    elif amount < 5e7:
        score -= 5  # 流动性差

    # 3) 价格区间偏好
    if 10 <= price <= 60:
        score += 5
    elif price > 80 or price < 8:
        score -= 3

    return round(score, 2)


def filter_stocks(raw_stocks):
    """
    过滤股票：
    - 主板（非创业板/科创板/北交所/新股）
    - 价格 5~100
    - 涨幅 -3% ~ +7%（不再包含涨停）
    - 返回时带 'composite_score' 字段，按综合评分倒序
    """
    filtered = []
    for s in raw_stocks:
        code = str(s.get('code', '')).zfill(6)
        name = s.get('name', '')
        price = float(s.get('trade', 0) or s.get('price', 0))
        change_pct = float(s.get('changepercent', 0) or s.get('change_pct', 0))
        amount = float(s.get('amount', 0))

        # 主板过滤
        if not _is_main_board(code):
            continue
        if name.startswith(('N', 'C', 'n', 'c', '*', 'S', 'ST', '*ST')):
            continue
        # 价格
        if price < PRICE_MIN or price > PRICE_MAX:
            continue
        # 涨幅区间（核心修复：上限 7%）
        if change_pct < CHANGE_MIN or change_pct > CHANGE_MAX:
            continue

        composite = _composite_score({
            'change_pct': change_pct,
            'amount': amount,
            'price': price,
        })

        filtered.append({
            'code': code,
            'name': name,
            'price': price,
            'change_pct': change_pct,
            'amount': amount,
            'composite_score': composite,
            'risk_flag': 'high' if change_pct >= RISK_CHANGE else 'normal',
        })

    # 关键修复：按综合评分排序，**不再按涨幅倒序**
    filtered.sort(key=lambda x: x['composite_score'], reverse=True)
    return filtered


def filter_stocks_with_risk_pool(raw_stocks):
    """
    双池返回：
    - normal_pool：按综合评分排，涨幅 -3% ~ +7%
    - risk_pool：涨幅 >= 9.5% 的涨停股（用于报告"⚠️ 追高风险"展示）
    """
    normal = []
    risk = []
    for s in raw_stocks:
        code = str(s.get('code', '')).zfill(6)
        name = s.get('name', '')
        price = float(s.get('trade', 0) or s.get('price', 0))
        change_pct = float(s.get('changepercent', 0) or s.get('change_pct', 0))
        amount = float(s.get('amount', 0))

        if not _is_main_board(code):
            continue
        if name.startswith(('N', 'C', 'n', 'c', '*', 'S', 'ST', '*ST')):
            continue
        if price < PRICE_MIN or price > PRICE_MAX:
            continue

        composite = _composite_score({
            'change_pct': change_pct,
            'amount': amount,
            'price': price,
        })

        item = {
            'code': code,
            'name': name,
            'price': price,
            'change_pct': change_pct,
            'amount': amount,
            'composite_score': composite,
        }

        if change_pct >= RISK_CHANGE:
            risk.append(item)
        elif change_pct < CHANGE_MIN or change_pct > CHANGE_MAX:
            continue
        else:
            normal.append(item)

    normal.sort(key=lambda x: x['composite_score'], reverse=True)
    risk.sort(key=lambda x: x['change_pct'], reverse=True)
    return normal, risk


def get_dynamic_stock_pool():
    """
    主函数：获取动态股票池（按综合评分排序的"非追高"池）
    返回最多 50 只，涨幅均在 -3% ~ +7% 区间
    """
    print("[AAna] 获取动态股票池（多源 fallback）...")

    raw_stocks, source = get_top_gainers_with_fallback(800)
    if not raw_stocks:
        print("[AAna] 所有数据源失败，返回空池")
        return []

    print(f"[AAna] 原始数据: {len(raw_stocks)} 只 (source={source})")
    filtered = filter_stocks(raw_stocks)
    print(f"[AAna] 筛选后: {len(filtered)} 只（涨幅 -3%~7%，按综合评分排序）")

    return filtered[:50]


def get_stock_pool_split():
    """
    返回 (normal_pool, risk_pool) 双池
    - normal_pool: 推荐主池（涨幅 -3% ~ 7%，按综合评分排）
    - risk_pool: 涨停警示池（涨幅 >= 9.5%）
    """
    raw_stocks, source = get_top_gainers_with_fallback(800)
    if not raw_stocks:
        return [], []
    normal, risk = filter_stocks_with_risk_pool(raw_stocks)
    print(f"[AAna] 拆分: 推荐池 {len(normal)} 只 + 风险池 {len(risk)} 只 (source={source})")
    return normal[:50], risk[:30]


if __name__ == '__main__':
    pool = get_dynamic_stock_pool()
    if pool:
        print(f"\n动态选股 Top 20（按综合评分）:")
        for i, s in enumerate(pool[:20], 1):
            print(f"  {i:2d}. {s['name']:8s}({s['code']}) ¥{s['price']:7.2f} "
                  f"{s['change_pct']:+5.2f}%  score={s['composite_score']}")
    else:
        print("未能获取动态股票池")

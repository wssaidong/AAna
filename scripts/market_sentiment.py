#!/usr/bin/env python3
"""
AAna v2.5 市场情绪 + 板块轮动模块
功能：
  1. 大盘情绪评分（0-100）
  2. 热点板块排名（东方财富）
  3. 涨停股池（选股源增强）
  4. 北向资金（沪深港通）
"""

import requests
import json
import subprocess
from datetime import datetime

HEADERS = {
    'User-Agent': 'Mozilla/5.0',
    'Referer': 'https://www.eastmoney.com',
}

# ── 1. 大盘情绪评分 ────────────────────────────────────────────

def get_market_sentiment() -> dict:
    """
    返回市场情绪字典：
    {
        score: 0-100,           # 情绪总分
        label: "冰点|分歧|回暖|亢奋",
        description: str,
        sentiment_zh: "看空|中性|看多",
        long_sentiment: str,    # "做多|空仓观望"
        indices: [{name, change, volume_ratio}, ...],
        sentiment_sensitive: bool,  # 情绪敏感标记（冰点/亢奋）
        avoid_trading: bool,        # 建议停止交易
    }
    """
    indices = get_index_data()
    if not indices:
        return _default_sentiment()

    avg_change = sum(i['change'] for i in indices) / len(indices)
    rising = sum(1 for i in indices if i['change'] > 0)
    falling = sum(1 for i in indices if i['change'] < 0)

    # ── 涨跌停数量 ──
    zt_count, dt_count, limit_data_source = get_limit_counts()
    print(f"[情绪] 涨停:{zt_count} 跌停:{dt_count} 上证:{avg_change:+.2f}% [数据源:{limit_data_source}]")

    # ── 情绪分计算 ──
    score = 50  # 基础分

    # 大盘涨跌
    if avg_change >= 2:
        score += 25
    elif avg_change >= 1:
        score += 15
    elif avg_change >= 0.3:
        score += 8
    elif avg_change >= 0:
        score += 3
    elif avg_change >= -0.5:
        score -= 5
    elif avg_change >= -1:
        score -= 15
    elif avg_change >= -2:
        score -= 25
    else:
        score -= 35

    # 涨跌停比（衡量市场活跃度）— P1 修复：数据缺失 (-1) 时跳过该项评分
    if zt_count < 0:
        # 数据缺失，不基于涨跌停调整情绪分
        pass
    elif zt_count >= 80:
        score += 15  # 极度亢奋
    elif zt_count >= 50:
        score += 10
    elif zt_count >= 30:
        score += 5
    elif zt_count >= 15:
        score += 0
    elif zt_count >= 5:
        score -= 10
    else:
        score -= 20  # 冰点

    # 跌停惩罚
    if dt_count >= 50:
        score -= 20
    elif dt_count >= 20:
        score -= 10
    elif dt_count >= 10:
        score -= 5

    score = max(0, min(100, score))

    # ── 标签判断 ──
    if score >= 75:
        label = "亢奋"
        sentiment_zh = "看多"
        long_sentiment = "高仓操作"
        description = "市场情绪高涨，涨停潮持续，赚钱效应强"
        sentiment_sensitive = True
        avoid_trading = False
    elif score >= 55:
        label = "回暖"
        sentiment_zh = "偏多"
        long_sentiment = "半仓操作"
        description = "市场情绪好转，热点明确，可适当参与"
        sentiment_sensitive = False
        avoid_trading = False
    elif score >= 40:
        label = "分歧"
        sentiment_zh = "中性"
        long_sentiment = "轻仓观望"
        description = "市场分化，热点散乱，控制仓位为主"
        sentiment_sensitive = True
        avoid_trading = False
    else:
        label = "冰点"
        sentiment_zh = "看空"
        long_sentiment = "空仓观望"
        description = "市场情绪低迷，亏钱效应明显，谨慎操作"
        sentiment_sensitive = True
        avoid_trading = True

    # 涨停/跌停同时过多 = 极端市场，全市场大起大落
    if zt_count >= 50 and dt_count >= 20:
        label = "极端"
        long_sentiment = "空仓观望"
        avoid_trading = True
        description = "多空双方极度分歧，暴涨暴跌，方向不明"

    return {
        "score": score,
        "label": label,
        "description": description,
        "sentiment_zh": sentiment_zh,
        "long_sentiment": long_sentiment,
        "indices": indices,
        "zt_count": zt_count,
        "dt_count": dt_count,
        "sentiment_sensitive": sentiment_sensitive,
        "avoid_trading": avoid_trading,
        "avg_change": round(avg_change, 2),
        "rising_count": rising,
        "falling_count": falling,
        "timestamp": datetime.now().isoformat(),
    }


def _default_sentiment() -> dict:
    return {
        "score": 50, "label": "未知",
        "description": "数据获取失败，默认中性",
        "sentiment_zh": "中性", "long_sentiment": "半仓观望",
        "indices": [], "zt_count": 0, "dt_count": 0,
        "sentiment_sensitive": False, "avoid_trading": False,
        "avg_change": 0.0, "rising_count": 0, "falling_count": 0,
        "timestamp": datetime.now().isoformat(),
    }


# ── 2. 主要指数行情 ──────────────────────────────────────────────

def get_index_data() -> list:
    """
    获取主要指数实时数据。
    v2.5.1 修复（2026-06-12）：弃用 sina hq 接口（字段错位 bug 算出 -98% 误判冰点），
    改用腾讯 qt.gtimg.cn（字段稳定，change_pct 索引=32 已知正确）。
    同时加 sanity check：单指数涨跌 > 10% 视为数据脏，跳过。
    """
    indices = []

    # 源 1: 腾讯 qt.gtimg.cn（首选，字段稳定）
    try:
        url = "https://qt.gtimg.cn/q=sh000001,sz399001,sz399006,sh000300"
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
        resp.encoding = 'gbk'
        for line in resp.text.strip().split(';'):
            if '=' not in line or '"' not in line:
                continue
            vals = line.split('"')[1].split('~')
            if len(vals) < 50:
                continue
            try:
                name = vals[1]
                price = float(vals[3])
                change = float(vals[32])  # 涨跌幅%
            except (ValueError, IndexError):
                continue
            # sanity check: 指数单日波动不可能 > 10%
            if abs(change) > 10:
                print(f"[情绪] ⚠️ 指数 {name} 涨跌 {change:+.2f}% 超出合理范围，丢弃")
                continue
            indices.append({
                "name": name, "change": round(change, 2),
                "price": price, "volume_ratio": 1.0,
            })
        if indices:
            return indices
    except Exception as e:
        print(f"[情绪] 腾讯指数源失败: {e}")

    # 源 2: 东财 push2（备用，解析 f3=涨跌幅）
    try:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1", "pz": "10", "po": "1", "np": "1",
            "fltt": "2", "invt": "2", "fid": "f3",
            "fs": "m:1+t:2,m:0+t:2",  # 沪深主要指数
            "fields": "f12,f14,f2,f3",
        }
        resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
        items = resp.json().get('data', {}).get('diff', [])
        for item in items:
            try:
                change = float(item.get('f3', 0))
                price = float(item.get('f2', 0))
            except (ValueError, TypeError):
                continue
            if abs(change) > 10:
                continue
            indices.append({
                "name": item.get('f14', ''),
                "change": round(change, 2),
                "price": price,
                "volume_ratio": 1.0,
            })
        if indices:
            return indices
    except Exception as e:
        print(f"[情绪] 东财指数源失败: {e}")

    # 双源都失败
    if not indices:
        print("[情绪] ❌ 指数数据双源 fallback")
    return indices


# ── 3. 涨跌停数量 ────────────────────────────────────────────────

def get_limit_counts() -> tuple:
    """返回 (涨停数, 跌停数, 数据源)
    v2.5.1 P0 修复（2026-07-08）：加同花顺备用源，9 天连续 fallback 终结
    """
    import time as _t

    # 数据源标记（供 main() 判断是否降级使用）
    # 源 1: 东方财富（首选）—— 数据最全
    for attempt in range(2):
        try:
            url = "https://push2.eastmoney.com/api/qt/clist/get"
            params = {
                "pn": 1, "pz": 1, "po": 1, "np": 1,
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": 2, "invt": 2, "fid": "f3",
                "fs": "m:0+t:6+f:!+,+m:0+t:13+f:!+,+m:0+t:80+f:!+,+m:1+t:2+f:!+,+m:1+t:23+f:!+,+m:1+t:A+f:!+",
                "fields": "f1",
                "_": int(datetime.now().timestamp() * 1000),
            }
            resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
            zt = resp.json().get('data', {}).get('total', 0)

            params2 = dict(params)
            params2["fs"] = "m:0+t:6+f:!-,+m:0+t:13+f:!-,+m:0+t:80+f:!-,+m:1+t:2+f:!-,+m:1+t:23+f:!-,+m:1+t:A+f:!-"
            resp2 = requests.get(url, params=params2, headers=HEADERS, timeout=8)
            dt = resp2.json().get('data', {}).get('total', 0)
            return zt, dt, "eastmoney"
        except Exception as e:
            if attempt < 1: _t.sleep(1.0); continue

    # 源 2: 同花顺（fallback，7/8 实测可用）
    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        url = f"http://zx.10jqka.com.cn/event/api/getharden/date/{today_str}/orderby/date/orderway/desc/charset/GBK/"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        rows = resp.json().get("data") or []
        zt = len(rows)
        # 同花顺跌停接口未实测可用，跌停 fallback 到"涨停数 / 10 估算"（v2.5.1 简化）
        dt = max(0, round(zt / 10))
        return zt, dt, "ths"
    except Exception as e:
        # v2026-08-23 Phase 3-2: silent swallow 加 stderr 日志 — 不抛但留痕
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from _logger import silenced
            silenced("market_sentiment.py:283 ths_zt_dt fallback", e)
        except Exception:
            pass  # 日志模块没装也别炸

    # 源 3: 全部失败 — 返回 -1 触发 fallback 路径（main() 已有 sanity check）
    print("[情绪] 涨跌停统计：所有源失败，返回 -1")
    return -1, -1, "fallback"


# ── 4. 热点板块 ──────────────────────────────────────────────────

def get_hot_sectors(limit: int = 10) -> list:
    """
    获取东方财富行业板块涨幅榜
    返回: [{name, change, lead_stock, zt_count}, ...]
    """
    try:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": 1, "pz": limit, "po": 1, "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2, "invt": 2, "fid": "f3",
            "fs": "m:90+t:2+f:!50,m:90+t:4+f:!50,m:90+t:5+f:!50,m:90+t:6+f:!50,m:90+t:7+f:!50,m:90+t:9+f:!50",
            "fields": "f12,f14,f3,f132,f128,f140",
            "_": int(datetime.now().timestamp() * 1000),
        }
        resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
        data = resp.json()
        sectors = []
        for item in data.get('data', {}).get('diff', []):
            sectors.append({
                'name': item.get('f14', ''),
                'change': round(float(item.get('f3', 0)), 2),
                'lead_stock': item.get('f132', ''),
                'zt_count': item.get('f140', 0),
            })
        sectors.sort(key=lambda x: x['change'], reverse=True)
        return sectors
    except Exception as e:
        print(f"[情绪] 板块数据失败: {e}")
        return []


# ── 5. 北向资金（沪深港通）───────────────────────────────────────

def get_north_money() -> dict:
    """
    返回北向资金数据：
    {hgt: float(万元), sgt: float(万元), total: float(万元),
     direction: "净流入"|"净流出", magnitude: "大"|"中"|"小"}
    """
    try:
        url = "https://push2.eastmoney.com/api/qt/kamt.rtmin/get"
        params = {"fields": "f1,f2,f3,f4",
                   "_": int(datetime.now().timestamp() * 1000)}
        resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
        d = resp.json().get('data', {})
        hgt = float(d.get('f2', 0) or 0)   # 沪股通
        sgt = float(d.get('f4', 0) or 0)   # 深股通
        total = hgt + sgt
        return {
            "hgt": hgt, "sgt": sgt, "total": total,
            "direction": "净流入" if total >= 0 else "净流出",
            "magnitude": "大" if abs(total) > 30000 else ("中" if abs(total) > 10000 else "小"),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        print(f"[情绪] 北向资金失败: {e}")
        return {"hgt": 0, "sgt": 0, "total": 0,
                "direction": "未知", "magnitude": "小",
                "timestamp": datetime.now().isoformat()}


# ── 6. 涨停股池（选股源增强）────────────────────────────────────

def get_zt_pool(limit: int = 50) -> list:
    """
    获取今日涨停股池（除ST/新股/科创板/创业板）
    返回: [{code, name, change, reason}, ...]
    """
    try:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": 1, "pz": limit, "po": 1, "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2, "invt": 2, "fid": "f3",
            "fs": "m:0+t:6+f:!+,+m:0+t:13+f:!+,+m:0+t:80+f:!+,+m:1+t:2+f:!+,+m:1+t:23+f:!+,+m:1+t:A+f:!+",
            "fields": "f12,f14,f3,f17,f18,f132",
            "_": int(datetime.now().timestamp() * 1000),
        }
        resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
        stocks = []
        for item in resp.json().get('data', {}).get('diff', []):
            code = str(item.get('f12', ''))
            name = item.get('f14', '')
            change = float(item.get('f3', 0) or 0)
            reason = item.get('f132', '') or item.get('f18', '')
            # 过滤
            if code.startswith(('N', 'C', 'n', 'c', 'bj', '8', '9')):
                continue
            if name.startswith(('N', 'C', '*', 'S')):
                continue
            if code.startswith('688'):
                continue
            if code.startswith(('300', '301')):
                continue
            stocks.append({
                'code': code.zfill(6),
                'name': name,
                'change': round(change, 2),
                'reason': reason,
            })
        return stocks
    except Exception as e:
        print(f"[情绪] 涨停股池失败: {e}")
        return []


# ── 7. 资金流向（个股超大单）────────────────────────────────────

def get_money_flow(codes: list) -> dict:
    """
    获取个股超大单资金流向
    codes: 股票代码列表
    返回: {code: {super_big_in, super_big_out, net_in, net_in_pct}}
    """
    if not codes:
        return {}
    result = {}
    try:
        # 东方财富资金流向接口
        fs = '+'.join([f'b:{c}' for c in codes])
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2, "invt": 2,
            "fields": "f12,f14,f62,f66,f72,f184",
            "secids": f"1.{codes[0]}" if codes[0].startswith('6') else f"0.{codes[0]}",
            "_": int(datetime.now().timestamp() * 1000),
        }
        # 批量用另一个接口
        url2 = "https://push2.eastmoney.com/api/qt/clist/get"
        code_str = ','.join([f'b:{c}' for c in codes])
        params2 = {
            "pn": 1, "pz": len(codes), "po": 1, "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2, "invt": 2, "fid": "f62",
            "fs": code_str,
            "fields": "f12,f14,f62,f66,f72",
            "_": int(datetime.now().timestamp() * 1000),
        }
        resp = requests.get(url2, params=params2, headers=HEADERS, timeout=10)
        for item in resp.json().get('data', {}).get('diff', []):
            code = str(item.get('f12', ''))
            super_big_in = float(item.get('f62', 0) or 0)   # 超大单流入（万元）
            super_big_out = float(item.get('f66', 0) or 0)  # 超大单流出
            net = super_big_in + super_big_out  # 流出是负数
            result[code] = {
                'super_big_in': super_big_in,
                'super_big_out': super_big_out,
                'net_in': net,
                'net_in_pct': round(net / (abs(super_big_in) + abs(super_big_out) + 1) * 100, 2),
            }
    except Exception as e:
        print(f"[资金流] 获取失败: {e}")
    # 补全未查到的股票
    for code in codes:
        if code not in result:
            result[code] = {'super_big_in': 0, 'super_big_out': 0, 'net_in': 0, 'net_in_pct': 0}
    return result


# ── 8. 综合选股源整合 ───────────────────────────────────────────

def get_enhanced_stock_pool(include_zt: bool = True) -> list:
    """
    整合多维度选股源：
    1. 新浪涨幅榜（已有）
    2. 涨停股池（新增）
    3. 去重后按综合质量排序
    """
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from dynamic_stocks import get_sina_top_gainers, filter_stocks

    pool = []

    # 来源1：新浪涨幅榜（2026-07-10 修复 num 200→800：7/10 普涨大阳日
    # 7/9 涨幅榜前 200 只全部 +8.6% 以上，filter_stocks 上限 7% 全过滤掉，
    # 导致 dynamic_stocks 0 只 → Top10 空。800 只后能看到 -3%~+7% 的回调股）
    try:
        raw = get_sina_top_gainers(800)
        filtered = filter_stocks(raw)
        for s in filtered:
            s['_source'] = '涨幅榜'
        pool.extend(filtered)
    except Exception as e:
        print(f"[选股源] 新浪涨幅榜失败: {e}")

    # 来源2：涨停股池（仅在情绪非冰点时加入，避免高位接盘）
    if include_zt:
        sentiment = get_market_sentiment()
        if not sentiment.get('avoid_trading') and sentiment.get('zt_count', 0) >= 5:
            try:
                zt_stocks = get_zt_pool(30)
                existing = {s['code'] for s in pool}
                for s in zt_stocks:
                    if s['code'] not in existing:
                        s['change_pct'] = s['change']
                        s['_source'] = '涨停池'
                        pool.append(s)
            except Exception as e:
                print(f"[选股源] 涨停池失败: {e}")

    # 去重
    seen, unique = {}, []
    for s in pool:
        if s['code'] not in seen:
            seen[s['code']] = s
            unique.append(s)
    return unique


# ── 入口函数 ────────────────────────────────────────────────────

if __name__ == '__main__':
    print("=== 市场情绪 ===")
    s = get_market_sentiment()
    print(f"情绪分: {s['score']} | {s['label']} | {s['long_sentiment']}")
    print(f"涨停: {s['zt_count']} 跌停: {s['dt_count']}")

    print("\n=== 热点板块 ===")
    sects = get_hot_sectors(5)
    for sec in sects:
        print(f"  {sec['name']}: {sec['change']:+.2f}%")

    print("\n=== 北向资金 ===")
    m = get_north_money()
    print(f"沪股通: {m['hgt']/10000:.2f}亿 | 深股通: {m['sgt']/10000:.2f}亿 | 合计: {m['total']/10000:.2f}亿 {m['direction']}")

    print("\n=== 涨停股池 ===")
    zt = get_zt_pool(5)
    for s in zt:
        print(f"  {s['name']}({s['code']}): {s['change']:+.2f}%")

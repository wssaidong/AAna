#!/usr/bin/env python3
"""
AAna 数据源模块 — 基于 a-stock-data skill
零 akshare 依赖，全部直连 HTTP API

来源：a-stock-data SKILL.md V3.0 (2026-05-17)
已验证数据源：
  - 腾讯财经：PE/PB/市值/换手率/涨跌停/指数/ETF
  - 同花顺热点：当日强势股 + 题材归因 reason tags
  - 东财行业：行业板块涨跌幅排名
  - 东财 datacenter：龙虎榜/北向资金分钟流向
  - 百度股市通：概念板块归属 + K线带MA5/10/20

依赖：pip install requests pandas stockstats
"""

import os
import sys
import time
import json
import math
import warnings
import re
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

warnings.filterwarnings('ignore')

# ============================================
# 全局常量
# ============================================
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
SINA_HQ_URL = "http://hq.sinajs.cn/list="
THS_HOT_URL = "http://zx.10jqka.com.cn/event/api/getharden/"
HSGT_URL = "https://data.hexin.cn/market/hsgtApi/method/dayChart/"
BAIDU_PAE_URL = "https://finance.pae.baidu.com/api/getrelatedblock"
BAIDU_KLINE_URL = "https://finance.pae.baidu.com/selfselect/getstockquotation"
BAIDU_FUND_URL = "https://finance.pae.baidu.com/vapi/v1/fundflow"
BAIDU_FUND_HIST_URL = "https://finance.pae.baidu.com/vapi/v1/fundsortlist"
EM_DATACENTER = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EM_PUSH2 = "https://push2.eastmoney.com/api/qt/stock/get"
EM_PUSH2HIS = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
EM_PUSH2IND = "https://push2.eastmoney.com/api/qt/clist/get"
EM_REPORT = "https://reportapi.eastmoney.com/report/list"
CURL_PAPER = "https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022"
CNINFO_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"

# ============================================
# 工具函数
# ============================================

def safe_float(value) -> Optional[float]:
    """安全转换为浮点数"""
    if value is None or value == '' or value == '--' or value == '-':
        return None
    try:
        if isinstance(value, str):
            value = value.replace('%', '').replace(',', '').replace('亿', '').replace('万', '')
        return float(value)
    except (ValueError, TypeError):
        return None


def get_prefix(code: str) -> str:
    """6位代码 → 市场前缀"""
    if code.startswith(("6", "9")):
        return "sh"
    elif code.startswith("8"):
        return "bj"
    else:
        return "sz"


def normalize_code(code: str) -> str:
    """代码归一化为6位纯数字（保留前导零用于 key 匹配）"""
    code = code.strip().upper()
    for sep in ['.', 'SH', 'SZ', 'BJ']:
        if code.endswith(sep):
            code = code[:-len(sep)]
    return code.zfill(6)  # 保留前导零，000858 → "000858"


def eastmoney_datacenter(report_name: str, columns: str = "ALL",
                          filter_str: str = "", page_size: int = 50,
                          sort_columns: str = "", sort_types: str = "-1") -> list:
    """东财数据中心统一查询 — 龙虎榜/解禁/融资融券/大宗交易/股东户数/分红 共用"""
    params = {
        "reportName": report_name,
        "columns": columns,
        "filter": filter_str,
        "pageNumber": "1",
        "pageSize": str(page_size),
        "sortColumns": sort_columns,
        "sortTypes": sort_types,
        "source": "WEB",
        "client": "WEB",
    }
    try:
        import requests
        r = requests.get(EM_DATACENTER, params=params, headers={"User-Agent": UA}, timeout=15)
        d = r.json()
        if d.get("result") and d["result"].get("data"):
            return d["result"]["data"]
    except Exception:
        pass
    return []


# ============================================
# Layer 1: 行情层（实时，不封IP）
# ============================================

def tencent_quote(codes: list) -> dict:
    """
    批量拉取腾讯财经实时行情。
    codes: ["688017", "300476", "002463"]
    也支持指数: ["000001", "000300", "399006"]
    也支持ETF: ["510050", "510300"]
    返回: {code: {name, price, pe_ttm, pb, mcap_yi, float_mcap_yi, turnover_pct, limit_up, limit_down, ...}}
    """
    import requests

    prefixed = []
    for c in codes:
        c = normalize_code(c)
        if c.startswith(("6", "9")):
            prefixed.append(f"sh{c}")
        elif c.startswith("8"):
            prefixed.append(f"bj{c}")
        else:
            prefixed.append(f"sz{c}")

    result = {}
    try:
        url = TENCENT_QUOTE_URL + ",".join(prefixed)
        req = requests.Request('GET', url, headers={"User-Agent": UA})
        resp = requests.Session().send(req.prepare(), timeout=10)
        data = resp.content.decode("gbk")
    except Exception as e:
        print(f"[data_sources] 腾讯API失败: {e}")
        return result

    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]  # 去掉 sh/sz/bj 前缀

        try:
            yesterday_close = safe_float(vals[4]) or 0
            price = safe_float(vals[3]) or 0
            change_pct_raw = safe_float(vals[32])  # 腾讯已返回百分比格式
            if price and yesterday_close and change_pct_raw is None:
                # 兜底：手动计算
                change_pct = round((price - yesterday_close) / yesterday_close * 100, 2)
            else:
                change_pct = change_pct_raw
            result[code] = {
                "name":          vals[1],
                "price":         price,
                "last_close":    yesterday_close,
                "open":          safe_float(vals[5]),
                "change_amt":    safe_float(vals[31]),
                "change_pct":    change_pct,
                "high":          safe_float(vals[33]),
                "low":           safe_float(vals[34]),
                "amount_wan":    safe_float(vals[37]),
                "turnover_pct":  safe_float(vals[38]),
                "pe_ttm":        safe_float(vals[39]),
                "amplitude_pct": safe_float(vals[43]),
                "mcap_yi":       safe_float(vals[44]),
                "float_mcap_yi": safe_float(vals[45]),
                "pb":            safe_float(vals[46]),
                "limit_up":      safe_float(vals[47]),
                "limit_down":    safe_float(vals[48]),
                "vol_ratio":     safe_float(vals[49]),
                "pe_static":     safe_float(vals[52]),
            }
        except (IndexError, ValueError):
            continue

    return result


def sina_quote(codes: list) -> dict:
    """
    新浪实时行情（基础版）。
    返回: {code: {name, price, yesterday_close, change_pct, amount, open, high, low}}
    """
    import requests

    results = {}
    formatted = []
    for c in codes:
        c = normalize_code(c)
        prefix = get_prefix(c)
        formatted.append(f"{prefix}{c}")

    try:
        url = SINA_HQ_URL + ",".join(formatted)
        resp = requests.get(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'http://finance.sina.com.cn'
        }, timeout=10)
        resp.encoding = 'gbk'
        lines = resp.text.strip().split('\n')

        for i, line in enumerate(lines):
            if '=' not in line or i >= len(codes):
                continue
            code = normalize_code(codes[i])
            parts = line.split('=')[1].strip('";"\n ').split(',')
            if len(parts) < 10:
                results[code] = {'code': code, 'name': '', 'price': 0, 'change_pct': 0, 'amount': 0}
                continue
            price = safe_float(parts[2]) or 0
            yesterday_close = safe_float(parts[1]) or 0
            if price and yesterday_close:
                change_pct = round((price - yesterday_close) / yesterday_close * 100, 2)
            else:
                change_pct = 0
            results[code] = {
                'code': code,
                'name': parts[0],
                'price': price,
                'yesterday_close': yesterday_close,
                'open': safe_float(parts[3]),
                'high': safe_float(parts[4]),
                'low': safe_float(parts[5]),
                'change_pct': change_pct,
                'change_amt': round(price - yesterday_close, 2) if price and yesterday_close else 0,
                'amount': (safe_float(parts[9]) or 0) * 10000,
            }
    except Exception as e:
        print(f"[data_sources] 新浪API失败: {e}")
        for c in codes:
            c = normalize_code(c)
            results[c] = {'code': c, 'name': '', 'price': 0, 'change_pct': 0, 'amount': 0}

    return results


# ============================================
# Layer 2: 同花顺热点（题材归因 — 独家能力）
# ============================================

def ths_hot_reason(date_str: str = None) -> dict:
    """
    同花顺当日强势股归因。
    date: 'YYYY-MM-DD' 格式，None=今天
    返回: dict {
        'stocks': [{code, name, reason, close, zhangfu, huanshou, chengjiaoe, ddejingliang, market}, ...],
        'total': int,
        'tag_freq': Counter of reason tags
    }
    """
    import requests
    from collections import Counter

    if date_str is None:
        date_str = date.today().strftime("%Y-%m-%d")

    url = f"{THS_HOT_URL}date/{date_str}/orderby/date/orderway/desc/charset/GBK/"
    try:
        r = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36"
        }, timeout=10)
        data = r.json()
        if data.get("errocode", 0) != 0:
            return {"stocks": [], "total": 0, "tag_freq": Counter(), "error": data.get("errormsg", "")}
    except Exception as e:
        return {"stocks": [], "total": 0, "tag_freq": Counter(), "error": str(e)}

    rows = data.get("data") or []
    stocks = []
    all_tags = []
    for row in rows:
        code = str(row.get("code", "")).zfill(6)
        name = row.get("name", "")
        reason = row.get("reason", "")
        # 解析 reason tags
        tags = [t.strip() for t in str(reason).split("+") if t.strip()]
        all_tags.extend(tags)
        stocks.append({
            "code": code,
            "name": name,
            "reason": reason,
            "tags": tags,
            "close": safe_float(row.get("close")),
            "zhangfu": safe_float(row.get("zhangfu")),
            "huanshou": safe_float(row.get("huanshou")),
            "chengjiaoe": row.get("chengjiaoe"),
            "ddejingliang": row.get("ddejingliang"),
            "market": row.get("market", ""),
        })

    return {
        "stocks": stocks,
        "total": len(stocks),
        "tag_freq": Counter(dict(Counter(all_tags))),
        "date": date_str,
    }


# ============================================
# Layer 3: 东财行业板块排名
# ============================================

def industry_comparison(top_n: int = 20) -> dict:
    """
    全行业涨跌幅排名（东财行业板块，~100个行业）。
    返回: {top: [...], bottom: [...], total: int}
    """
    import requests

    url = EM_PUSH2IND
    params = {
        "pn": "1", "pz": "100", "po": "1", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:90+t:2",
        "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141,f207",
    }
    try:
        r = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=15)
        d = r.json()
        items = d.get("data", {}).get("diff", [])
    except Exception as e:
        return {"top": [], "bottom": [], "total": 0, "error": str(e)}

    if not items:
        return {"top": [], "bottom": [], "total": 0}

    rows = []
    for i, item in enumerate(items):
        rows.append({
            "rank": i + 1,
            "name": item.get("f14", ""),
            "change_pct": item.get("f3", 0),
            "code": item.get("f12", ""),
            "up_count": item.get("f104", 0),
            "down_count": item.get("f105", 0),
            "leader": item.get("f140", ""),
            "leader_change": item.get("f136", 0),
        })

    return {
        "top": rows[:top_n],
        "bottom": rows[-top_n:],
        "total": len(rows),
    }


# ============================================
# Layer 3: 北向资金（自缓存模式）
# ============================================

def _northbound_cache_path() -> Path:
    p = Path.home() / ".tradingagents" / "cache" / "northbound_daily.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def hsgt_realtime() -> dict:
    """
    沪深股通当日实时分钟流向（含集合竞价 09:10–15:00，262个时间点）。
    返回: {times: [...], hgt_yi: [...], sgt_yi: [...], last_hgt, last_sgt}
    """
    import requests

    try:
        r = requests.get(HSGT_URL, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36",
            "Host": "data.hexin.cn",
            "Referer": "https://data.hexin.cn/",
        }, timeout=10)
        d = r.json()
    except Exception as e:
        return {"times": [], "hgt_yi": [], "sgt_yi": [], "error": str(e)}

    times = d.get("time", [])
    hgt = d.get("hgt", [])
    sgt = d.get("sgt", [])
    n = len(times)

    hgt_yi = hgt[:n] + [None] * max(0, n - len(hgt))
    sgt_yi = sgt[:n] + [None] * max(0, n - len(sgt))

    # 找最后一个非空值
    last_hgt = next((v for v in reversed(hgt_yi) if v is not None), 0)
    last_sgt = next((v for v in reversed(sgt_yi) if v is not None), 0)

    return {
        "times": times,
        "hgt_yi": hgt_yi,
        "sgt_yi": sgt_yi,
        "last_hgt": last_hgt,
        "last_sgt": last_sgt,
        "total_hgt_sgt": round(last_hgt + last_sgt, 2),
    }


def save_northbound_snapshot(date_str: str, hgt: float, sgt: float):
    """写入/更新当天北向收盘数据到 CSV"""
    path = _northbound_cache_path()
    rows = {}
    if path.exists():
        for line in path.read_text().strip().split("\n")[1:]:
            parts = line.split(",")
            if len(parts) == 3:
                rows[parts[0]] = line
    rows[date_str] = f"{date_str},{hgt},{sgt}"
    with open(path, "w") as f:
        f.write("date,hgt,sgt\n")
        for d in sorted(rows.keys()):
            f.write(rows[d] + "\n")


def load_northbound_history(n: int = 20) -> list:
    """读取最近 N 天北向历史"""
    path = _northbound_cache_path()
    if not path.exists():
        return []
    try:
        import csv
        with open(path) as f:
            reader = csv.DictReader(f)
            return list(reader)[-n:]
    except Exception:
        return []


# ============================================
# Layer 3: 百度概念板块归属
# ============================================

_BAIDU_HEADERS = {
    "Host": "finance.pae.baidu.com",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0",
    "Accept": "application/vnd.finance-web.v1+json",
    "Origin": "https://gushitong.baidu.com",
    "Referer": "https://gushitong.baidu.com/",
}


def baidu_concept_blocks(code: str) -> dict:
    """
    百度股市通概念板块归属。
    返回: {industry: [...], concept: [...], region: [...], concept_tags: [...]}
    """
    import requests

    url = f"{BAIDU_PAE_URL}?code={code}&market=ab&typeCode=all&finClientType=pc"
    try:
        r = requests.get(url, headers=_BAIDU_HEADERS, timeout=10)
        d = r.json()
    except Exception as e:
        return {"industry": [], "concept": [], "region": [], "concept_tags": [], "error": str(e)}

    if str(d.get("ResultCode", -1)) != "0":
        return {"industry": [], "concept": [], "region": [], "concept_tags": [], "error": str(d)}

    result = {"industry": [], "concept": [], "region": [], "concept_tags": []}
    for block in d.get("Result", []):
        block_type = block.get("type", "")
        for item in block.get("list", []):
            entry = {
                "name": item.get("name", ""),
                "change_pct": item.get("increase", ""),
                "desc": item.get("desc", ""),
            }
            if "行业" in block_type:
                result["industry"].append(entry)
            elif "概念" in block_type:
                result["concept"].append(entry)
                result["concept_tags"].append(entry["name"])
            elif "地域" in block_type:
                result["region"].append(entry)
    return result


# ============================================
# Layer 3: 百度个股资金流向（分钟级）
# ============================================

def baidu_fund_flow_realtime(code: str, date_str: str) -> list:
    """
    个股资金流向（分钟级）。
    date_str: YYYYMMDD 紧凑格式
    返回: [{time, mainForce, retail, super, large, price}, ...]
    """
    import requests

    url = f"{BAIDU_FUND_URL}?code={code}&market=ab&date={date_str}&finClientType=pc"
    try:
        r = requests.get(url, headers=_BAIDU_HEADERS, timeout=10)
        d = r.json()
    except Exception:
        return []

    if str(d.get("ResultCode", -1)) != "0":
        return []

    raw = d.get("Result", {}).get("update_data", "")
    if not raw:
        return []

    rows = []
    for segment in raw.split(";"):
        parts = segment.split(",")
        if len(parts) >= 9:
            rows.append({
                "time": parts[0],
                "mainForce": safe_float(parts[2]),
                "retail": safe_float(parts[3]),
                "super": safe_float(parts[4]),
                "large": safe_float(parts[5]),
                "price": safe_float(parts[8]),
            })
    return rows


def baidu_fund_flow_history(code: str, days: int = 20) -> list:
    """
    个股资金流向（日级，最近N交易日）。
    返回: [{date, close, change_pct, superNetIn, largeNetIn, mediumNetIn, littleNetIn, mainIn}, ...]
    """
    import requests

    url = f"{BAIDU_FUND_HIST_URL}?code={code}&market=ab&pn=0&rn={days}&finClientType=pc"
    try:
        r = requests.get(url, headers=_BAIDU_HEADERS, timeout=10)
        d = r.json()
    except Exception:
        return []

    if str(d.get("ResultCode", -1)) != "0":
        return []

    rows = []
    for item in d.get("Result", {}).get("list", []):
        rows.append({
            "date": item.get("showtime", ""),
            "close": item.get("closepx", ""),
            "change_pct": item.get("ratio", ""),
            "superNetIn": item.get("superNetIn", ""),
            "largeNetIn": item.get("largeNetIn", ""),
            "mediumNetIn": item.get("mediumNetIn", ""),
            "littleNetIn": item.get("littleNetIn", ""),
            "mainIn": item.get("extMainIn", ""),
        })
    return rows


# ============================================
# Layer 3: 龙虎榜
# ============================================

def daily_dragon_tiger(trade_date: str = None, min_net_buy: float = None) -> dict:
    """
    全市场龙虎榜。
    返回: {date, total_records, stocks: [{code, name, reason, close, change_pct, net_buy_wan, buy_wan, sell_wan, turnover_pct}]}
    """
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y-%m-%d")

    data = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE>='{trade_date}')(TRADE_DATE<='{trade_date}')",
        page_size=500,
        sort_columns="BILLBOARD_NET_AMT",
        sort_types="-1",
    )
    if not data:
        return {"date": trade_date, "total_records": 0, "stocks": [], "note": "无数据（非交易日或盘后未更新）"}

    actual_date = str(data[0].get("TRADE_DATE", ""))[:10] if data else trade_date
    stocks = []
    for row in data:
        net_buy = (row.get("BILLBOARD_NET_AMT") or 0) / 10000
        if min_net_buy is not None and net_buy < min_net_buy:
            continue
        stocks.append({
            "code": row.get("SECURITY_CODE", ""),
            "name": row.get("SECURITY_NAME_ABBR", ""),
            "reason": row.get("EXPLANATION", ""),
            "close": row.get("CLOSE_PRICE") or 0,
            "change_pct": round(float(row.get("CHANGE_RATE") or 0), 2),
            "net_buy_wan": round(net_buy, 1),
            "buy_wan": round((row.get("BILLBOARD_BUY_AMT") or 0) / 10000, 1),
            "sell_wan": round((row.get("BILLBOARD_SELL_AMT") or 0) / 10000, 1),
            "turnover_pct": round(float(row.get("TURNOVERRATE") or 0), 2),
        })
    return {"date": actual_date, "total_records": len(stocks), "stocks": stocks}


# ============================================
# Layer 4: 资金面（融资融券/大宗交易/股东户数/分红）
# ============================================

def margin_trading(code: str, page_size: int = 30) -> list:
    """融资融券明细（日级）"""
    data = eastmoney_datacenter(
        "RPTA_WEB_RZRQ_GGMX",
        filter_str=f'(SCODE="{code}")',
        page_size=page_size,
        sort_columns="DATE",
        sort_types="-1",
    )
    rows = []
    for row in data:
        rows.append({
            "date": str(row.get("DATE", ""))[:10],
            "rzye": row.get("RZYE", 0),
            "rzmre": row.get("RZMRE", 0),
            "rqye": row.get("RQYE", 0),
            "rzrqye": row.get("RZRQYE", 0),
        })
    return rows


def holder_num_change(code: str, page_size: int = 10) -> list:
    """股东户数变化（季度级）"""
    data = eastmoney_datacenter(
        "RPT_HOLDERNUMLATEST",
        filter_str=f'(SECURITY_CODE="{code}")',
        page_size=page_size,
        sort_columns="END_DATE",
        sort_types="-1",
    )
    rows = []
    for row in data:
        rows.append({
            "date": str(row.get("END_DATE", ""))[:10],
            "holder_num": row.get("HOLDER_NUM", 0),
            "change_ratio": row.get("HOLDER_NUM_RATIO", 0),
            "avg_shares": row.get("AVG_FREE_SHARES", 0),
        })
    return rows


def dividend_history(code: str, page_size: int = 20) -> list:
    """分红送转历史"""
    data = eastmoney_datacenter(
        "RPT_SHAREBONUS_DET",
        filter_str=f'(SECURITY_CODE="{code}")',
        page_size=page_size,
        sort_columns="EX_DIVIDEND_DATE",
        sort_types="-1",
    )
    rows = []
    for row in data:
        rows.append({
            "date": str(row.get("EX_DIVIDEND_DATE", ""))[:10],
            "bonus_rmb": row.get("PRETAX_BONUS_RMB", 0),
            "transfer_ratio": row.get("TRANSFER_RATIO", 0),
            "bonus_ratio": row.get("BONUS_RATIO", 0),
            "plan": row.get("ASSIGN_PROGRESS", ""),
        })
    return rows


def stock_fund_flow_120d(code: str) -> list:
    """个股资金流（日级，最近120个交易日）"""
    import requests

    market_code = 1 if code.startswith("6") else 0
    url = EM_PUSH2HIS
    params = {
        "secid": f"{market_code}.{code}",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "lmt": "120",
    }
    try:
        r = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=15)
        d = r.json()
        klines = d.get("data", {}).get("klines", [])
    except Exception:
        return []

    rows = []
    for line in klines:
        parts = line.split(",")
        if len(parts) >= 7:
            rows.append({
                "date": parts[0],
                "main_net": safe_float(parts[1]),
                "small_net": safe_float(parts[2]),
                "mid_net": safe_float(parts[3]),
                "large_net": safe_float(parts[4]),
                "super_net": safe_float(parts[5]),
            })
    return rows


# ============================================
# Layer 5: 新闻（财联社/东财）
# ============================================

def cls_telegraph(page_size: int = 50) -> list:
    """财联社电报（全市场实时快讯）"""
    import requests

    url = "https://www.cls.cn/nodeapi/telegraphList"
    params = {"rn": str(page_size), "page": "1"}
    try:
        r = requests.get(url, params=params, headers={
            "User-Agent": UA,
            "Referer": "https://www.cls.cn/"
        }, timeout=10)
        d = r.json()
    except Exception:
        return []

    rows = []
    for item in d.get("data", {}).get("roll_data", []):
        rows.append({
            "title": item.get("title", "") or item.get("brief", ""),
            "content": item.get("content", "") or item.get("brief", ""),
            "time": item.get("ctime", ""),
        })
    return rows


def eastmoney_global_news(page_size: int = 50) -> list:
    """东方财富全球财经资讯（7x24滚动）"""
    import requests

    url = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
    params = {
        "client": "web", "biz": "web_724",
        "fastColumn": "102", "sortEnd": "",
        "pageSize": str(page_size),
    }
    try:
        r = requests.get(url, params=params, headers={
            "User-Agent": UA,
            "Referer": "https://kuaixun.eastmoney.com/"
        }, timeout=10)
        d = r.json()
    except Exception:
        return []

    rows = []
    for item in d.get("data", {}).get("fastNewsList", []):
        rows.append({
            "title": item.get("title", ""),
            "summary": item.get("summary", "")[:200],
            "time": item.get("showTime", ""),
        })
    return rows


# ============================================
# Layer 6: 基础数据（东财个股信息/巨潮公告）
# ============================================

def eastmoney_stock_info(code: str) -> dict:
    """东财个股基本面信息"""
    import requests

    market_code = 1 if code.startswith("6") else 0
    url = EM_PUSH2
    params = {
        "fltt": "2", "invt": "2",
        "fields": "f57,f58,f84,f85,f127,f116,f117,f189,f43",
        "secid": f"{market_code}.{code}",
    }
    try:
        r = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=10)
        d = r.json().get("data", {})
    except Exception:
        return {}

    return {
        "code": d.get("f57", ""),
        "name": d.get("f58", ""),
        "industry": d.get("f127", ""),
        "total_shares": d.get("f84", 0),
        "float_shares": d.get("f85", 0),
        "mcap": d.get("f116", 0),
        "float_mcap": d.get("f117", 0),
        "list_date": str(d.get("f189", "")),
        "price": d.get("f43", 0),
    }


def cninfo_announcements(code: str, page_size: int = 30) -> list:
    """巨潮公告全文检索"""
    import requests

    if code.startswith("6"):
        plate = "sh"
    elif code.startswith("8"):
        plate = "bj"
    else:
        plate = "sz"

    payload = {
        "stock": f"{code},{plate}",
        "tabName": "fulltext",
        "pageSize": str(page_size),
        "pageNum": "1",
        "column": plate.upper() + "E" if plate == "sz" else plate.upper() + "E",
        "category": "",
        "plate": "",
        "seDate": "",
        "searchkey": "",
        "secid": "",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    try:
        r = requests.post(CNINFO_URL, data=payload, headers={
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://www.cninfo.com.cn/new/disclosure",
            "Origin": "https://www.cninfo.com.cn",
        }, timeout=15)
        d = r.json()
    except Exception:
        return []

    rows = []
    for item in d.get("announcements", []) or []:
        rows.append({
            "title": item.get("announcementTitle", ""),
            "type": item.get("announcementTypeName", ""),
            "date": item.get("announcementTime", ""),
            "url": f"https://www.cninfo.com.cn/new/disclosure/detail?annoId={item.get('announcementId', '')}",
        })
    return rows


# ============================================
# 估值计算（基于腾讯+东财数据）
# ============================================

def forward_pe(price: float, eps_forecast: float) -> Optional[float]:
    """前向PE = 当前股价 / 未来年度一致预期EPS"""
    if eps_forecast <= 0:
        return None
    return round(price / eps_forecast, 2)


def pe_digestion(current_pe: float, cagr: float, target_pe: float = 30) -> Optional[float]:
    """当前PE消化到目标PE需要多少年"""
    if current_pe <= target_pe:
        return 0.0
    if cagr <= 0:
        return None
    return round(math.log(current_pe / target_pe) / math.log(1 + cagr), 1)


def calc_peg(pe: float, cagr: float) -> Optional[float]:
    """PEG = 前向PE / (CAGR * 100)"""
    if cagr <= 0:
        return None
    peg = pe / (cagr * 100)
    return round(peg, 2)


# ============================================
# 批量增强报价（腾讯+新浪融合）
# ============================================

def get_enhanced_quotes(codes: list) -> dict:
    """
    融合腾讯行情（含PE/PB/市值）和新浪实时价格。
    返回: {code: {name, price, change_pct, pe_ttm, pb, mcap_yi, limit_up, limit_down, ...}}
    """
    import requests

    # 腾讯行情（估值层）
    tencent_data = tencent_quote(codes)
    # 新浪行情（实时层）
    sina_data = sina_quote(codes)

    result = {}
    for code in codes:
        code = normalize_code(code)
        tc = tencent_data.get(code, {})
        sn = sina_data.get(code, {})

        # 优先用新浪价格（实时性强），估值数据用腾讯
        price = sn.get('price') or tc.get('price') or 0
        change_pct = sn.get('change_pct') or tc.get('change_pct') or 0

        result[code] = {
            'code': code,
            'name': tc.get('name') or sn.get('name', ''),
            'price': price,
            'change_pct': change_pct,
            'yesterday_close': sn.get('yesterday_close') or tc.get('last_close'),
            'open': sn.get('open') or tc.get('open'),
            'high': sn.get('high') or tc.get('high'),
            'low': sn.get('low') or tc.get('low'),
            'amount': sn.get('amount') or tc.get('amount_wan', 0) * 10000,
            'pe_ttm': tc.get('pe_ttm'),
            'pb': tc.get('pb'),
            'mcap_yi': tc.get('mcap_yi'),
            'float_mcap_yi': tc.get('float_mcap_yi'),
            'turnover_pct': tc.get('turnover_pct'),
            'limit_up': tc.get('limit_up'),
            'limit_down': tc.get('limit_down'),
            'vol_ratio': tc.get('vol_ratio'),
            'pe_static': tc.get('pe_static'),
        }

    return result


# ============================================
# 完整单票调研（新标的快速调研）
# ============================================

def full_stock_research(code: str, trade_date: str = None) -> dict:
    """
    单票完整数据调研（整合所有数据层）。
    trade_date: YYYY-MM-DD 格式
    """
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y-%m-%d")

    compact_date = trade_date.replace("-", "")

    # Layer 1: 行情
    quotes = get_enhanced_quotes([code])
    quote = quotes.get(code, {})

    # Layer 3: 概念板块 + 资金流
    blocks = baidu_concept_blocks(code)
    fund_hist = baidu_fund_flow_history(code)
    fund_realtime = baidu_fund_flow_realtime(code, compact_date)

    # Layer 3: 龙虎榜
    dtb = daily_dragon_tiger(trade_date)

    # Layer 4: 资金面
    margin = margin_trading(code, page_size=5)
    holders = holder_num_change(code)
    dividends = dividend_history(code)
    fund_120d = stock_fund_flow_120d(code)

    # Layer 6: 基本信息
    em_info = eastmoney_stock_info(code)

    # Layer 5: 新闻
    news = cls_telegraph(page_size=10)

    return {
        "code": code,
        "trade_date": trade_date,
        "quote": quote,
        "concept_blocks": blocks.get("concept_tags", []),
        "industry": [b["name"] for b in blocks.get("industry", [])],
        "fund_flow": {
            "history": fund_hist[:5],
            "realtime": fund_realtime[-5:] if fund_realtime else [],
            "120d": fund_120d[-5:] if fund_120d else [],
        },
        "dragon_tiger": dtb,
        "margin": margin[:3] if margin else [],
        "holders": holders[:3] if holders else [],
        "dividends": dividends[:3] if dividends else [],
        "em_info": em_info,
        "news": news[:5],
    }


# ============================================
# CLI 入口
# ============================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AAna 数据源测试")
    parser.add_argument("--code", type=str, help="股票代码")
    parser.add_argument("--codes", type=str, help="逗号分隔的股票代码")
    parser.add_argument("--hot", action="store_true", help="测试同花顺热点")
    parser.add_argument("--industry", action="store_true", help="测试行业板块排名")
    parser.add_argument("--northbound", action="store_true", help="测试北向资金")
    parser.add_argument("--quote", action="store_true", help="测试增强行情")
    parser.add_argument("--research", action="store_true", help="完整调研")
    args = parser.parse_args()

    if args.hot:
        print("=== 同花顺热点 ===")
        r = ths_hot_reason()
        print(f"共 {r['total']} 只强势股")
        print("题材词频 TOP 10:")
        for tag, cnt in r['tag_freq'].most_common(10):
            print(f"  {tag}: {cnt}")
        print("\n前5只股票:")
        for s in r['stocks'][:5]:
            print(f"  {s['name']}({s['code']}): {s['zhangfu']}% | {s['reason']}")

    elif args.industry:
        print("=== 东财行业板块排名 ===")
        r = industry_comparison(10)
        print(f"共 {r['total']} 个行业")
        print("涨幅 TOP 10:")
        for s in r['top'][:10]:
            print(f"  {s['rank']}. {s['name']}: {s['change_pct']}% 涨{s['up_count']}跌{s['down_count']} 领涨:{s['leader']}({s['leader_change']}%)")

    elif args.northbound:
        print("=== 北向资金 ===")
        r = hsgt_realtime()
        print(f"沪股通累计: {r['last_hgt']} 亿")
        print(f"深股通累计: {r['last_sgt']} 亿")
        print(f"合计: {r['total_hgt_sgt']} 亿")
        hist = load_northbound_history(5)
        print("历史最近5天:")
        for h in hist:
            print(f"  {h.get('date')}: 沪股通={h.get('hgt')}亿 深股通={h.get('sgt')}亿")

    elif args.quote:
        codes = []
        if args.code:
            codes = [args.code]
        elif args.codes:
            codes = [c.strip() for c in args.codes.split(",")]
        if codes:
            print("=== 增强行情 ===")
            r = get_enhanced_quotes(codes)
            for code, q in r.items():
                print(f"\n{q['name']}({code}):")
                print(f"  价格: {q['price']} 涨跌幅: {q['change_pct']}%")
                print(f"  PE(TTM): {q['pe_ttm']} PB: {q['pb']} 市值: {q['mcap_yi']}亿")
                print(f"  涨停价: {q['limit_up']} 跌停价: {q['limit_down']}")
                print(f"  换手率: {q['turnover_pct']}% 量比: {q['vol_ratio']}")

    elif args.research:
        if not args.code:
            print("--research 需要 --code 参数")
            sys.exit(1)
        print("=== 单票完整调研 ===")
        r = full_stock_research(args.code)
        q = r['quote']
        print(f"\n{q['name']}({r['code']}) 收盘: {q['price']} {q['change_pct']}%")
        print(f"PE(TTM): {q['pe_ttm']} PB: {q['pb']} 市值: {q['mcap_yi']}亿")
        print(f"概念板块: {', '.join(r['concept_blocks'][:5])}")
        print(f"行业: {', '.join(r['industry'])}")
        if r['fund_flow']['history']:
            h = r['fund_flow']['history'][0]
            print(f"资金流向: 主力={h.get('mainIn')}万 超大单={h.get('superNetIn')}万")
        print(f"龙虎榜: {r['dragon_tiger']['total_records']} 条记录")
        print(f"最新融资余额: {r['margin'][0]['rzye']/1e8:.2f}亿 (如有)")
        print(f"股东数: {r['holders'][0]['holder_num']} (如有)")

    else:
        parser.print_help()

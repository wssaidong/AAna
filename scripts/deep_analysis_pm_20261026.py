#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
尾盘深度分析 2026-10-26 PM — 基于尾盘选股 Top5 (14:47 报告)
输入: reports/2026-10-26-尾盘选股.md Top5 = 603348/603882/603355/001239/603037
方法: tencent_quote 行情 + 腾讯日K(120d qfq) 技术面 + akshare 财务摘要 基本面
输出: data/deep_analysis_pm_20261026.json (评分汇总, 由 gen_deep_reports 渲染报告)
评分: 技术面50% + 基本面30% + 估值20%, 评级 买入>=75 增持>=65 中性>=50 减持<50
铁律: 亏损股 (PE<=0) 估值面 0 分, 基本面 ROE/增速 负增长 0 分 → 天然降权
"""
import sys, os, json, re, time
import requests

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import data_sources as ds

TODAY = "2026-10-26"
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
OUT_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_pm_20261026.json")

# (code, name, v24_score, v24_stop, v24_target, chg_pct) — 来自尾盘报告 Top5
CANDIDATES = [
    ("603348", "文灿股份", 100, 13.92, 16.47, 1.91),
    ("603882", "金域医学", 100, 29.59, 35.00, 3.99),
    ("603355", "莱克电气", 100, 31.39, 37.12, 3.18),
    ("001239", "永达股份", 100, 11.82, 13.98, 2.17),
    ("603037", "凯众股份", 100, 9.99, 11.81, 2.78),
]

# 行业 → rec_tuning sector_stats 主键 (67 键)
SECTOR_MAP = {
    "603348": ("汽车零部件-铝合金压铸/一体化压铸", "汽车零部件"),
    "603882": ("医疗服务-第三方医学检验(ICL)", None),
    "603355": ("小家电-电机/锂电工具/空气压缩机", "小家电"),
    "001239": ("汽车服务-汽车经销与维修", None),
    "603037": ("汽车零部件-制动系统精密件", "汽车零部件"),
}


def kline(code, days=120):
    # v2: fqkline qfq 端点 10-26 PM 实测 WAF 501 (tencent waf), 切 kline/kline 非复权端点 (200 ok 实测)
    prefix = ds.get_prefix(code)
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
           f"?param={prefix}{code},day,,,{days},")
    r = requests.get(url, timeout=10,
                     headers={"User-Agent": "Mozilla/5.0"})
    m = re.search(r'"day"\s*:\s*(\[\[.*?\]\])', r.text)
    if not m:
        raise ValueError(f"kline/kline 无 day 数据: {r.status_code}")
    kl = json.loads(m.group(1))
    return [[k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in kl]


def rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(-period, 0):
        chg = closes[i] - closes[i - 1]
        gains.append(max(chg, 0)); losses.append(max(-chg, 0))
    ag, al = sum(gains) / period, sum(losses) / period
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def ma(closes, n):
    return sum(closes[-n:]) / n if len(closes) >= n else None


def tech_score(kl, cur_price):
    closes = [k[2] for k in kl]
    vols = [k[5] for k in kl]
    s = 0; notes = []
    ma5, ma10, ma20, ma60 = ma(closes, 5), ma(closes, 10), ma(closes, 20), ma(closes, 60)
    if ma5 and ma20 and ma5 > ma20 and cur_price > ma5:
        s += 15; notes.append("均线多头(MA5>MA20, 价>MA5)")
    elif ma20 and cur_price > ma20:
        s += 8; notes.append("价>MA20")
    else:
        notes.append("均线偏弱")
    r = rsi(closes)
    if 45 <= r <= 65:
        s += 15; notes.append(f"RSI={r:.0f} 健康")
    elif 65 < r <= 75:
        s += 8; notes.append(f"RSI={r:.0f} 偏热")
    elif r > 75:
        s += 0; notes.append(f"RSI={r:.0f} 超买")
    else:
        s += 5; notes.append(f"RSI={r:.0f} 偏弱")
    hi20 = max(k[3] for k in kl[-20:]); lo20 = min(k[4] for k in kl[-20:])
    pos20 = (cur_price - lo20) / (hi20 - lo20) * 100 if hi20 > lo20 else 50
    if pos20 >= 80:
        s += 12; notes.append(f"20日区间位置 {pos20:.0f}% 突破区")
    elif pos20 >= 50:
        s += 8; notes.append(f"20日区间位置 {pos20:.0f}% 中上")
    else:
        s += 3; notes.append(f"20日区间位置 {pos20:.0f}% 偏低")
    chg60 = (closes[-1] / closes[-61] - 1) * 100 if len(closes) > 61 else 0
    if 0 <= chg60 <= 30:
        s += 8; notes.append(f"60日涨幅 {chg60:+.0f}% 健康")
    elif -10 <= chg60 < 0:
        s += 6; notes.append(f"60日涨幅 {chg60:+.0f}% 回调")
    elif 30 < chg60 <= 60:
        s += 4; notes.append(f"60日涨幅 {chg60:+.0f}% 偏热")
    elif chg60 > 60:
        s += 0; notes.append(f"60日涨幅 {chg60:+.0f}% 严重透支")
    else:
        s += 2; notes.append(f"60日涨幅 {chg60:+.0f}% 弱势")
    vr = vols[-1] / (sum(vols[-6:-1]) / 5) if len(vols) > 6 else 1
    if 0.6 <= vr <= 2.0:
        s += 5; notes.append(f"量能比 {vr:.2f} 正常")
    elif vr > 3.0:
        s += 0; notes.append(f"量能比 {vr:.2f} 爆量")
    else:
        s += 3; notes.append(f"量能比 {vr:.2f}")
    return s, notes, {"rsi": round(r, 1), "pos20": round(pos20, 0),
                      "chg60": round(chg60, 1), "vol_ratio_5d": round(vr, 2),
                      "ma5": round(ma5, 2) if ma5 else None,
                      "ma20": round(ma20, 2) if ma20 else None,
                      "ma60": round(ma60, 2) if ma60 else None,
                      "hi20": hi20, "lo20": lo20,
                      "last_kline_date": kl[-1][0]}


def fund_score(code):
    out = {"roe": None, "ni_growth": None, "rev_growth": None}
    try:
        import akshare as ak
        df = ak.stock_financial_abstract(symbol=code)
        cols = [c for c in df.columns if c not in ('选项', '指标', '指标说明')]
        latest = cols[0] if cols else None

        def pick_exact(names):
            for n in names:
                row = df[df['指标'] == n]
                if row.empty:
                    row = df[df['指标'].str.contains(
                        n.replace('(', '\\(').replace(')', '\\)'), na=False, regex=True)]
                if not row.empty:
                    try:
                        return float(row.iloc[0][latest])
                    except Exception:
                        return None
            return None

        out["roe"] = pick_exact(["净资产收益率(ROE)", "摊薄净资产收益率"])
        out["ni_growth"] = pick_exact(["归属母公司净利润增长率", "净利润增长率"])
        out["rev_growth"] = pick_exact(["营业总收入增长率", "营业收入增长率"])
        out["report_date"] = str(latest)
    except Exception as e:
        out["error"] = str(e)[:80]
    s = 0; notes = []
    roe, nig, reg = out["roe"], out["ni_growth"], out["rev_growth"]
    if roe is not None:
        if roe >= 15: s += 12; notes.append(f"ROE {roe:.1f}% 优秀")
        elif roe >= 8: s += 8; notes.append(f"ROE {roe:.1f}% 良好")
        elif roe >= 4: s += 4; notes.append(f"ROE {roe:.1f}% 一般")
        else: s += 0; notes.append(f"ROE {roe:.1f}% 弱/亏损")
    else:
        s += 4; notes.append("ROE 缺失")
    if nig is not None:
        if nig >= 30: s += 12; notes.append(f"净利增速 +{nig:.0f}%")
        elif nig >= 10: s += 8; notes.append(f"净利增速 +{nig:.0f}%")
        elif nig >= 0: s += 4; notes.append(f"净利增速 +{nig:.0f}%")
        else: s += 0; notes.append(f"净利增速 {nig:.0f}% 负增长")
    else:
        s += 4; notes.append("净利增速缺失")
    if reg is not None:
        if reg >= 15: s += 6; notes.append(f"营收增速 +{reg:.0f}%")
        elif reg >= 0: s += 3; notes.append(f"营收增速 +{reg:.0f}%")
        else: s += 0; notes.append(f"营收增速 {reg:.0f}%")
    else:
        s += 2; notes.append("营收增速缺失")
    return s, notes, out


def val_score(pe_ttm, pb):
    s = 0; notes = []
    if pe_ttm is None: pe_ttm = 0
    if 0 < pe_ttm <= 30: s += 8; notes.append(f"PE {pe_ttm:.0f} 合理")
    elif 30 < pe_ttm <= 50: s += 5; notes.append(f"PE {pe_ttm:.0f} 偏高")
    elif 50 < pe_ttm <= 80: s += 2; notes.append(f"PE {pe_ttm:.0f} 高")
    elif pe_ttm <= 0: s += 0; notes.append(f"PE {pe_ttm:.1f} 亏损(估值面 0 分)")
    else: s += 0; notes.append(f"PE {pe_ttm:.0f} 过高/异常")
    if pb is not None:
        if pb <= 3: s += 7; notes.append(f"PB {pb:.2f} 合理")
        elif pb <= 5: s += 4; notes.append(f"PB {pb:.2f} 中等")
        else: s += 1; notes.append(f"PB {pb:.2f} 偏高")
    return s, notes


def rating_of(score):
    if score >= 75: return "买入"
    if score >= 65: return "增持"
    if score >= 50: return "中性"
    return "减持"


def main():
    results = []
    for code, name, v24s, stop, target, chg in CANDIDATES:
        print(f"--- {code} {name} ---", flush=True)
        try:
            q = ds.tencent_quote([code]).get(code, {})
        except Exception as e:
            q = {}; print(f"  quote fail: {e}")
        price = q.get("price")
        if not price:
            price = target / 1.10
        pe, pb = q.get("pe_ttm"), q.get("pb")
        try:
            kl = kline(code)
            ts, tnotes, tstat = tech_score(kl, price)
        except Exception as e:
            ts, tnotes, tstat = 25, [f"K线失败: {e}"], {}
        try:
            fs, fnotes, fstat = fund_score(code)
        except Exception as e:
            fs, fnotes, fstat = 10, [f"财务失败: {e}"], {}
        vs, vnotes = val_score(pe, pb)
        total = round(ts / 55 * 50 + fs / 30 * 30 + vs / 15 * 20, 1)
        rating = rating_of(total)
        tgt_tech = tstat.get("hi20") if tstat.get("hi20") else price * 1.05
        tgt = round(min(target, max(tgt_tech, price * 1.05)), 2)
        rec = {"code": code, "name": name, "price": price, "pe_ttm": pe, "pb": pb,
               "mcap_yi": q.get("mcap_yi"), "v24_score": v24s,
               "tech_score": ts, "fund_score": fs, "val_score": vs,
               "total": total, "rating": rating, "target": tgt, "stop": stop,
               "tech_notes": tnotes, "fund_notes": fnotes, "val_notes": vnotes,
               "tech_stat": tstat, "fund_stat": fstat, "chg_pct": chg,
               "live_chg_pct": q.get("change_pct"),
               "industry": SECTOR_MAP.get(code, (None, None))[0],
               "sector_key": SECTOR_MAP.get(code, (None, None))[1]}
        results.append(rec)
        print(f"  技术面 {ts}/55 基本面 {fs}/30 估值 {vs}/15 => {total} {rating}", flush=True)
        print(f"  目标 {tgt} 止损 {stop} PE {pe} PB {pb}", flush=True)
    results.sort(key=lambda x: (-x["total"], -x["v24_score"]))
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump({"date": TODAY, "generated": time.strftime("%H:%M:%S"),
                   "results": results}, f, ensure_ascii=False, indent=1)
    print("\n=== 排名 ===")
    for i, r in enumerate(results, 1):
        print(f"{i}. {r['code']} {r['name']} 深度评分 {r['total']} {r['rating']} "
              f"原评分 {r['v24_score']} 现价 {r['price']} 目标 {r['target']} 止损 {r['stop']}")
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()

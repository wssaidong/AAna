#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
尾盘深度分析 2026-10-16 PM — 基于尾盘选股 Top5 (剔除 ST 后 4 只)
输入: 尾盘选股报告 Top5 = 002674/000909(ST,剔)/603101/002264/002270
方法: tencent_quote 行情 + 腾讯日K(120d) 技术面 + akshare 财务摘要 基本面
输出: 每只 reports/2026-10-16-深度分析-{code}.md + data 汇总 JSON
评分: 技术面50% + 基本面30% + 估值20%, 评级 买入>=75 增持>=65 中性>=50 减持<50
"""
import sys, os, json, re, time
import requests

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import data_sources as ds

TODAY = "2026-10-16"
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
OUT_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_pm_20261016.json")
CANDIDATES = [
    # (code, name, v24_score, v24_stop, v24_target, chg_pct)
    ("002674", "兴业科技", 100, 19.6, 23.19, 4.62),
    ("603101", "汇嘉时代", 93, 7.25, 8.58, 3.72),
    ("002264", "新华都", 93, 7.25, 8.58, 3.72),
    ("002270", "华明装备", 93, 17.47, 20.66, 3.70),
]

def kline(code, days=120):
    prefix = ds.get_prefix(code)
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?_var=kline_dayqfq&param={prefix}{code},day,,,{days},qfq")
    r = requests.get(url, timeout=10,
                     headers={"User-Agent": "Mozilla/5.0"})
    m = re.search(r'=(.+)$', r.text.strip())
    data = json.loads(m.group(1))
    kl = data['data'][f"{prefix}{code}"].get("qfqday") or \
         data['data'][f"{prefix}{code}"].get("day")
    return [[k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in kl]

def rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(-period, 0):
        chg = closes[i] - closes[i-1]
        gains.append(max(chg, 0)); losses.append(max(-chg, 0))
    ag, al = sum(gains)/period, sum(losses)/period
    if al == 0:
        return 100.0
    return 100 - 100/(1 + ag/al)

def ma(closes, n):
    return sum(closes[-n:])/n if len(closes) >= n else None

def tech_score(kl, cur_price):
    closes = [k[2] for k in kl]
    vols = [k[5] for k in kl]
    s = 0; notes = []
    ma5, ma10, ma20, ma60 = ma(closes,5), ma(closes,10), ma(closes,20), ma(closes,60)
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
    chg60 = (closes[-1]/closes[-61] - 1)*100 if len(closes) > 61 else 0
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
    vr = vols[-1]/(sum(vols[-6:-1])/5) if len(vols) > 6 else 1
    if 0.6 <= vr <= 2.0:
        s += 5; notes.append(f"量能比 {vr:.2f} 正常")
    elif vr > 3.0:
        s += 0; notes.append(f"量能比 {vr:.2f} 爆量")
    else:
        s += 3; notes.append(f"量能比 {vr:.2f}")
    return s, notes, {"rsi": round(r,1), "pos20": round(pos20,0),
                      "chg60": round(chg60,1), "vol_ratio_5d": round(vr,2),
                      "ma5": round(ma5,2) if ma5 else None,
                      "ma20": round(ma20,2) if ma20 else None,
                      "ma60": round(ma60,2) if ma60 else None,
                      "hi20": hi20, "lo20": lo20}

def fund_score(code):
    """akshare 财务摘要: ROE + 净利增速 + 营收增速"""
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
                    row = df[df['指标'].str.contains(n.replace('(', '\\(').replace(')', '\\)'), na=False, regex=True)]
                if not row.empty:
                    v = row.iloc[0][latest]
                    try: return float(v)
                    except Exception: return None
            return None
        out["roe"] = pick_exact(["净资产收益率(ROE)", "摊薄净资产收益率"])
        out["ni_growth"] = pick_exact(["归属母公司净利润增长率", "净利润增长率"])
        out["rev_growth"] = pick_exact(["营业总收入增长率", "营业收入增长率"])
    except Exception as e:
        out["error"] = str(e)[:80]
    s = 0; notes = []
    roe, nig, reg = out["roe"], out["ni_growth"], out["rev_growth"]
    if roe is not None:
        if roe >= 15: s += 12; notes.append(f"ROE {roe:.1f}% 优秀")
        elif roe >= 8: s += 8; notes.append(f"ROE {roe:.1f}% 良好")
        elif roe >= 4: s += 4; notes.append(f"ROE {roe:.1f}% 一般")
        else: s += 0; notes.append(f"ROE {roe:.1f}% 弱")
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
            q = {}
            print(f"  quote fail: {e}")
        price = q.get("price")
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
        # 归一化到 0-100: 技术面50% + 基本面30% + 估值20%
        total = round(ts/55*50 + fs/30*30 + vs/15*20, 1)
        rating = rating_of(total)
        # 目标价: min(v24目标, 20日高点+5%缓冲); 止损: max(v24止损, MA20下方7%)
        tgt_tech = round(tstat.get("hi20", target)*1.0, 2) if tstat.get("hi20") else target
        tgt = round(min(target, max(tgt_tech, price*1.05)), 2)
        stp = stop
        rec = {"code": code, "name": name, "price": price, "pe_ttm": pe, "pb": pb,
               "mcap_yi": q.get("mcap_yi"), "v24_score": v24s,
               "tech_score": ts, "fund_score": fs, "val_score": vs,
               "total": total, "rating": rating, "target": tgt, "stop": stp,
               "tech_notes": tnotes, "fund_notes": fnotes, "val_notes": vnotes,
               "tech_stat": tstat, "fund_stat": fstat, "chg_pct": chg}
        results.append(rec)
        print(f"  技术面 {ts}/55 基本面 {fs}/30 估值 {vs}/15 => {total} {rating}")
        print(f"  目标 {tgt} 止损 {stp}")
        time.sleep(0.5)
    results.sort(key=lambda x: (-x["total"], -x["v24_score"]))
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump({"date": TODAY, "generated": time.strftime("%H:%M:%S"),
                   "results": results}, f, ensure_ascii=False, indent=1)
    print(f"\n=== 排名 ===")
    for i, r in enumerate(results, 1):
        print(f"{i}. {r['code']} {r['name']} 深度评分 {r['total']} {r['rating']} "
              f"原评分 {r['v24_score']} 现价 {r['price']} 目标 {r['target']} 止损 {r['stop']}")
    print(f"JSON: {OUT_JSON}")

if __name__ == "__main__":
    main()

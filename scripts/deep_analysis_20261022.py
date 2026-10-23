#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-10-22 (周四交易日盘前) — 当日报告 2026-10-22-选股报告.md (Top10 仅 3 只有数据)
候选池 = 当日报告 "重点关注 Top 10" 全部 3 只:
  603466 风语筑 (Top10#1+强势榜: 今日强势上涨+放量) / 603992 松霖科技 (Top10#2+活跃榜: 量比放大+趋势良好)
  000028 国药一致 (Top10#3+活跃榜: 量比放大+趋势良好)
  (10-21 涨跌幅全部为正 +1.69%~+1.99%, 报告综合分 65/65/64, 技术分均 78, 信号均为 MA多头MACD金叉)
方法: 腾讯行情 + 腾讯日K(120d qfq) 技术面 + akshare 财务摘要 基本面 + rec_tuning 板块胜率
评分: 技术面50% + 基本面30% + 估值20%, 评级 买入>=75 增持>=65 中性>=50 减持<50
铁律: Top1 必须 10-21 当日胜出 + 正盈利 (报告涨跌幅列 = 10-21 周三收盘口径, K线末日 10-21)
板块映射 (industry_cache + 人工核对 rec_tuning 64 键, 10-22 rec_optimizer 去重后库 285 笔):
  603466 装修装饰 100% (1/1) / 603992 其他家用轻工 0% (0/1, 邻近键 小家电 100% 1/1) / 000028 医药商业 100% (2/2)
Kimi: multica 平台未注册 kimi runtime (仅 Claude/Hermes/Pi), 本机无 kimi CLI / moonshot key (10-22 08:33 复核)
"""
import sys, os, json, re, time
import requests

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import data_sources as ds

TODAY = "2026-10-22"
BASE_DATE = "2026-10-21"
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
OUT_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_20261022.json")
BASE_REPORT = os.path.join(REPORT_DIR, f"{BASE_DATE}-选股报告.md")

# (code, name, 来源评分, 止损, 来源)
CANDIDATES = [
    ("603466", "风语筑", 65, 14.04, "当日报告Top10#1+强势股榜"),
    ("603992", "松霖科技", 65, 22.59, "当日报告Top10#2+活跃股榜"),
    ("000028", "国药一致", 64, 19.91, "当日报告Top10#3+活跃股榜"),
]

# 行业 (industry_cache.json + 人工核对) → rec_tuning sector_stats 映射
SECTOR_MAP = {
    "603466": ("建筑装饰-数字展示", "装修装饰"),
    "603992": ("轻工-厨卫家居", "其他家用轻工"),
    "000028": ("医药-医药商业流通", "医药商业"),
}


def kline(code, days=120):
    prefix = ds.get_prefix(code)
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?_var=kline_dayqfq&param={prefix}{code},day,,,{days},qfq")
    r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
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
    # 当日涨跌 (最后一天 vs 前一天) — 用于"当日胜出+正盈利"验证
    chg_1d = (closes[-1] / closes[-2] - 1) * 100 if len(closes) >= 2 else 0.0
    last_date = kl[-1][0]
    return s, notes, {"rsi": round(r, 1), "pos20": round(pos20, 0),
                      "chg60": round(chg60, 1), "vol_ratio_5d": round(vr, 2),
                      "ma5": round(ma5, 2) if ma5 else None,
                      "ma20": round(ma20, 2) if ma20 else None,
                      "ma60": round(ma60, 2) if ma60 else None,
                      "hi20": hi20, "lo20": lo20,
                      "chg_1d": round(chg_1d, 2), "last_date": last_date,
                      "kline_len": len(kl)}


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
                    try:
                        return float(v)
                    except Exception:
                        return None
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


def load_sector_stats():
    p = os.path.expanduser("~/code/AAna/data/rec_tuning.json")
    with open(p) as f:
        rt = json.load(f)
    return rt.get("sector_stats", {}), rt.get("overall_win_rate"), rt.get("total_records")


def main():
    print("=" * 78)
    print(f"AAna 深度分析 — {TODAY} (周四交易日盘前, 当日报告 Top10 仅 3 只, 数据基准 10-21)")
    print(f"Run: autopilot ca411dd3 深度分析 01a16104-4cc8-7451-9a39-a9a327ba70b8")
    print("=" * 78)
    # autopilot 强制要求: 打印报告名称防错
    today_report = os.path.join(REPORT_DIR, f"{TODAY}-选股报告.md")
    tsz, tmt = (os.path.getsize(today_report),
                time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(today_report)))) \
        if os.path.exists(today_report) else (0, None)
    print(f"📄 当日报告: {today_report}")
    print(f"   大小: {tsz} 字节 | 修改: {tmt} | Top10 仅 3 只 → 候选池 = 当日报告 Top10 全部 3 只")
    sz, mt = (os.path.getsize(BASE_REPORT),
              time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(BASE_REPORT)))) \
        if os.path.exists(BASE_REPORT) else (0, None)
    print(f"📄 基准报告: {BASE_REPORT}")
    print(f"   大小: {sz} 字节 | 修改: {mt}")
    sector_stats, overall_wr, n_rec = load_sector_stats()
    print(f"📊 板块胜率库 (10-22 rec_optimizer 去重后): {len(sector_stats)} 板块 | 整体胜率 {overall_wr:.1f}% ({n_rec} 笔)")

    results = []
    for code, name, v24s, stop, src in CANDIDATES:
        print(f"--- {code} {name} ({src}) ---", flush=True)
        try:
            q = ds.tencent_quote([code]).get(f"{code}", {})
        except Exception as e:
            q = {}; print(f"  quote fail: {e}")
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
        total = round(ts / 55 * 50 + fs / 30 * 30 + vs / 15 * 20, 1)
        rating = rating_of(total)
        target = round(max(price * 1.05, tstat.get("hi20") or price * 1.05), 2)
        industry, stat_key = SECTOR_MAP.get(code, (None, None))
        sec = sector_stats.get(stat_key, {}) if stat_key else {}
        sec_wr = (f"{sec.get('win_rate'):.0f}% ({sec.get('win_count')}/{sec.get('count')})"
                  if sec else "无记录(冷启动)")
        rec = {"code": code, "name": name, "price": price, "pe_ttm": pe, "pb": pb,
               "mcap_yi": q.get("mcap_yi"), "float_mcap_yi": q.get("float_mcap_yi"),
               "turnover_pct": q.get("turnover_pct"), "vol_ratio": q.get("vol_ratio"),
               "v24_score": v24s, "src": src,
               "tech_score": ts, "fund_score": fs, "val_score": vs,
               "total": total, "rating": rating, "target": target, "stop": stop,
               "tech_notes": tnotes, "fund_notes": fnotes, "val_notes": vnotes,
               "tech_stat": tstat, "fund_stat": fstat,
               "chg_pct": tstat.get("chg_1d"), "chg_date": tstat.get("last_date"),
               "industry": industry, "sector_stat_key": stat_key, "sector_win_rate": sec_wr}
        results.append(rec)
        print(f"  10-21 涨跌 {tstat.get('chg_1d', 0):+.2f}% (K线末日 {tstat.get('last_date')}, K线 {tstat.get('kline_len')} 根)")
        print(f"  技术面 {ts}/55 基本面 {fs}/30 估值 {vs}/15 => {total} {rating}")
        print(f"  板块: {industry} → 胜率 {sec_wr}")
        time.sleep(0.4)

    # 铁律过滤: Top1 必须 10-21 当日正盈利 (胜出 = 涨幅为正且居候选池前列)
    positive = [r for r in results if (r["chg_pct"] or 0) > 0]
    results.sort(key=lambda x: (-x["total"], -x["v24_score"], -(x["chg_pct"] or 0)))
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump({"date": TODAY, "base_date": BASE_DATE, "base_report": BASE_REPORT,
                   "generated": time.strftime("%H:%M:%S"),
                   "overall_win_rate": overall_wr, "total_records": n_rec,
                   "results": results}, f, ensure_ascii=False, indent=1)
    print("\n=== 排名 (全部候选) ===")
    for i, r in enumerate(results, 1):
        pos = "✅正盈利" if (r["chg_pct"] or 0) > 0 else "❌当日下跌"
        print(f"{i}. {r['code']} {r['name']} 深度评分 {r['total']} {r['rating']} "
              f"| 10-21 {r['chg_pct']:+.2f}% {pos} | 板块 {r['industry']} 胜率 {r['sector_win_rate']}")
    print(f"\n正盈利候选: {len(positive)}/{len(results)}")
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()

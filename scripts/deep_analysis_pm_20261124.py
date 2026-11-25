#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
尾盘深度分析 2026-11-24 PM — 基于尾盘选股报告 Top5 (14:46 生成)
输入: reports/2026-11-23-尾盘选股.md Top5 = 000410/603767/002674/603270/002048
方法: 复用 deep_analysis_20261022 评分引擎 (技术面50% + 基本面30% + 估值20%)
      + 估值面失真修正 v1 (10-28 PM 规则)
      + 扣非/OCF 增长质量修正 v1 (11-10 规则)
      + PE 过低陷阱 v1 (11-17 规则: 归母TTM/营收TTM>3 → 估值面不得给满分)
      + 腾讯行情实时快照 + 腾讯日K(120d) + akshare 财务摘要 + sina/东财 行业双源
      + rec_tuning 板块胜率
输出: data/deep_analysis_pm_20261124.json
"""
import sys, os, json, re, time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import data_sources as ds
from deep_analysis_20261022 import tech_score, fund_score, val_score, rating_of

TODAY = "2026-11-24"
OUT_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_pm_20261124.json")

# (code, name, v24_score, stop, target, chg_pct) — 来自 2026-11-23 尾盘报告 Top5
CANDIDATES = [
    ("001328", "登康口腔", 100, 33.75, 39.92, 2.51),
    ("002960", "青鸟智控", 92, 8.12, 9.60, 2.11),
    ("603118", "共进股份", 88, 12.26, 14.50, 3.53),
    ("600201", "生物股份", 88, 11.40, 13.49, 3.37),
    ("002351", "漫步者", 88, 11.16, 13.20, 3.09),
]

SECTOR_CANDIDATES = {
    "001328": ["口腔护理", "日用化工", "美容护理", "食品综合", "饮料制造", "中药"],
    "002960": ["电网设备", "电气设备", "输变电设备", "智能电网", "电力设备"],
    "603118": ["通信设备", "通信传输设备", "通信配套服务", "光通信", "电子零部件制造"],
    "600201": ["生物制品", "动物保健", "兽药", "化学制药", "中药"],
    "002351": ["消费电子", "电子元件", "小家电", "家用轻工", "光学元件"],
}

SECTOR_NEAR = {
    "001328": [("食品综合", "食品邻近键"), ("调味发酵品", "调味品邻近键"), ("白酒", "消费邻近键")],
    "002960": [("工控自动化", "工控邻近键"), ("仪器仪表", "仪表邻近键"), ("电机", "电机邻近键")],
    "603118": [("通信传输设备", "通信设备邻近键"), ("通信配套服务", "通信服务邻近键"), ("电子零部件制造", "电子邻近键")],
    "600201": [("化学制药", "制药邻近键"), ("中药", "中药邻近键"), ("其他化学制品", "化工邻近键")],
    "002351": [("小家电", "小家电邻近键"), ("光学元件", "光学邻近键"), ("电子零部件制造", "电子邻近键")],
}

_AK_CACHE = {}


def fetch_kline(code, days=120):
    import requests
    prefix = ds.get_prefix(code)
    sym = f"{prefix}{code}"
    last = None
    variants = (
        ("fqkline/get", "kline_dayqfq", f"{sym},day,,,{days},qfq"),
        ("kline/kline", "kline_day", f"{sym},day,,,{days},"),
        ("kline/kline", "kline_day", f"{sym},day,,,{days},qfq"),
    )
    for path, var, param in variants:
        try:
            url = f"https://web.ifzq.gtimg.cn/appstock/app/{path}?_var={var}&param={param}"
            r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            data = json.loads(re.search(r'=(.+)$', r.text.strip()).group(1))
            kl0 = data['data'][sym]
            kl = [[k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])]
                  for k in (kl0.get("qfqday") or kl0.get("day") or [])]
            if kl:
                return kl
        except Exception as e:
            last = e
    raise RuntimeError(f"K线获取失败: {last}")


def ak_abstract(code):
    if code in _AK_CACHE:
        return _AK_CACHE[code]
    df = None
    err = None
    try:
        import akshare as ak
        df = ak.stock_financial_abstract(symbol=code)
    except Exception as e:
        err = str(e)[:120]
    _AK_CACHE[code] = (df, err)
    return _AK_CACHE[code]


def _pick_row(df, names):
    for n in names:
        row = df[df['指标'] == n]
        if not row.empty:
            return row.iloc[0]
        try:
            pat = n.replace('(', r'\(').replace(')', r'\)')
            row = df[df['指标'].astype(str).str.contains(pat, na=False, regex=True)]
        except Exception:
            row = df.iloc[0:0]
        if not row.empty:
            return row.iloc[0]
    return None


def _f(row, col):
    if row is None:
        return None
    try:
        v = float(row[col])
        return v
    except Exception:
        return None


def quality_fetch(code):
    """拉 扣非/归母/OCF/营收 累计 + 去年同期 + 单季 + TTM"""
    df, err = ak_abstract(code)
    if df is None:
        return {"code": code, "error": err or "abstract unavailable"}
    try:
        cols = [c for c in df.columns if c not in ('选项', '指标', '指标说明')]
        latest = cols[0]
        prev_cum_col = cols[1] if len(cols) > 1 else None
        ym = str(latest)[:6]
        prior_col = None
        for c in cols:
            s = str(c)
            if len(s) == 8 and s[:6] == ym and s != latest:
                prior_col = c
                break
        if prior_col is None:
            try:
                y, m = int(str(latest)[:4]), str(latest)[4:6]
                tgt = f"{y-1}{m}"
                for c in cols:
                    s = str(c)
                    if len(s) == 8 and s[:6] == tgt:
                        prior_col = c
                        break
            except Exception:
                pass

        r_kf = _pick_row(df, ["扣非净利润", "扣除非经常性损益的净利润", "扣除非经常性损益后的净利润"])
        r_gm = _pick_row(df, ["归母净利润", "归属母公司净利润"])
        r_ocf = _pick_row(df, ["经营活动产生的现金流量净额", "经营现金流"])
        r_rev = _pick_row(df, ["营业总收入"])
        r_roe = _pick_row(df, ["净资产收益率(ROE)", "净资产收益率"])

        out = {"code": code, "latest_col": str(latest), "prior_col": str(prior_col) if prior_col else None}
        out["kf_cum"] = _f(r_kf, latest); out["gm_cum"] = _f(r_gm, latest)
        out["ocf_cum"] = _f(r_ocf, latest); out["rev_cum"] = _f(r_rev, latest)
        out["roe"] = _f(r_roe, latest)
        if prior_col:
            out["kf_prior"] = _f(r_kf, prior_col); out["gm_prior"] = _f(r_gm, prior_col)
            out["rev_prior"] = _f(r_rev, prior_col)
        if out.get("kf_cum") is not None and out.get("kf_prior") not in (None, 0):
            out["kf_yoy"] = (out["kf_cum"] / out["kf_prior"] - 1) * 100
        if out.get("gm_cum") is not None and out.get("gm_prior") not in (None, 0):
            out["gm_yoy"] = (out["gm_cum"] / out["gm_prior"] - 1) * 100
        if out.get("rev_cum") is not None and out.get("rev_prior") not in (None, 0):
            out["rev_yoy"] = (out["rev_cum"] / out["rev_prior"] - 1) * 100
        # 单季 (最新期累计 - 上期累计)
        if prev_cum_col:
            out["q_kf"] = (out["kf_cum"] or 0) - (_f(r_kf, prev_cum_col) or 0)
            out["q_gm"] = (out["gm_cum"] or 0) - (_f(r_gm, prev_cum_col) or 0)
            out["q_rev"] = (out["rev_cum"] or 0) - (_f(r_rev, prev_cum_col) or 0)
            out["prev_cum_col"] = str(prev_cum_col)
            # 去年同期单季 (prior_col 累计 - 其上期累计) — 找 prior_col 的前一列
            try:
                idx = cols.index(prior_col)
                if idx + 1 < len(cols):
                    out["q_kf_prior"] = (out["kf_prior"] or 0) - (_f(r_kf, cols[idx + 1]) or 0)
                    out["q_gm_prior"] = (out["gm_prior"] or 0) - (_f(r_gm, cols[idx + 1]) or 0)
            except Exception:
                pass
        # 扣非 TTM = FY去年 + 最新累计 - 去年同期累计
        fy_col = None
        for c in cols:
            s = str(c)
            if len(s) == 8 and s.endswith("1231"):
                fy_col = c
                break
        if fy_col:
            out["fy_col"] = str(fy_col)
            out["kf_fy"] = _f(r_kf, fy_col)
            out["gm_fy"] = _f(r_gm, fy_col)
            if out.get("kf_fy") is not None and out.get("kf_cum") is not None and out.get("kf_prior") is not None:
                out["kf_ttm"] = out["kf_fy"] + out["kf_cum"] - out["kf_prior"]
            if out.get("gm_fy") is not None and out.get("gm_cum") is not None and out.get("gm_prior") is not None:
                out["gm_ttm"] = out["gm_fy"] + out["gm_cum"] - out["gm_prior"]
        return out
    except Exception as e:
        return {"code": code, "error": str(e)[:120]}


def fund_score_with(ni_growth, roe, rev_growth):
    s, notes = 0, []
    if roe is not None:
        if roe >= 15: s += 12; notes.append(f"ROE {roe:.1f}% 优秀")
        elif roe >= 8: s += 8; notes.append(f"ROE {roe:.1f}% 良好")
        elif roe >= 4: s += 4; notes.append(f"ROE {roe:.1f}% 一般")
        else: s += 0; notes.append(f"ROE {roe:.1f}% 弱")
    else:
        s += 4; notes.append("ROE 缺失")
    if ni_growth is not None:
        if ni_growth >= 30: s += 12; notes.append(f"净利增速 +{ni_growth:.0f}%")
        elif ni_growth >= 10: s += 8; notes.append(f"净利增速 +{ni_growth:.0f}%")
        elif ni_growth >= 0: s += 4; notes.append(f"净利增速 +{ni_growth:.0f}%")
        else: s += 0; notes.append(f"净利增速 {ni_growth:.0f}% 负增长")
    else:
        s += 4; notes.append("净利增速缺失")
    if rev_growth is not None:
        if rev_growth >= 15: s += 6; notes.append(f"营收增速 +{rev_growth:.0f}%")
        elif rev_growth >= 0: s += 3; notes.append(f"营收增速 +{rev_growth:.0f}%")
        else: s += 0; notes.append(f"营收增速 {rev_growth:.0f}% 负增长")
    else:
        s += 2; notes.append("营收增速缺失")
    return s, notes


def main_business(code):
    try:
        import akshare as ak
        df = ak.stock_zyjs_ths(symbol=code)
        if df is None or df.empty:
            return None
        cols = list(df.columns)
        item_col = next((c for c in cols if "项目" in c or "主营" in c), cols[0])
        val_col = next((c for c in cols if "收入-占比" in c or "占比" in c), None)
        recs = []
        for _, row in df.iterrows():
            name = str(row[item_col]).strip()
            if name in ("行业", "产品", "地区", "合计"):
                continue
            pct = row[val_col] if val_col and val_col in df.columns else None
            try:
                pct = float(pct)
            except Exception:
                pct = None
            recs.append((name, pct))
        recs = [r for r in recs if r[0] and r[0] != "nan"]
        if not recs:
            return None
        recs.sort(key=lambda x: (x[1] is not None, x[1] or 0), reverse=True)
        return " / ".join([f"{n} {p:.2f}%" if p is not None else n for n, p in recs[:4]])
    except Exception as e:
        return {"error": str(e)[:80]}


def load_sector_stats():
    p = os.path.expanduser("~/code/AAna/data/rec_tuning.json")
    with open(p) as f:
        rt = json.load(f)
    return rt.get("sector_stats", {}), rt.get("overall_win_rate"), rt.get("total_records")


def analyze(code, name, v24s, stop, target, chg, sector_stats):
    print(f"--- {code} {name} (尾盘评分 {v24s}) ---", flush=True)
    try:
        q = ds.tencent_quote([code]).get(code, {})
    except Exception as e:
        q = {}
        print(f"  quote fail: {e}")
    price = q.get("price") or (target / 1.10)
    pe, pb = q.get("pe_ttm"), q.get("pb")

    try:
        kl = fetch_kline(code)
        ts_, tnotes, tstat = tech_score(kl, price)
    except Exception as e:
        ts_, tnotes, tstat = 25, [f"K线失败: {e}"], {}

    try:
        fs_, fnotes, fstat = fund_score(code)
    except Exception as e:
        fs_, fnotes, fstat = 10, [f"财务失败: {e}"], {}

    vs_raw, vnotes = val_score(pe, pb)

    try:
        ind_sina = ds.industry_for_code(code)
    except Exception:
        ind_sina = None
    try:
        ind_em = (ds.eastmoney_stock_info(code) or {}).get("industry") or None
    except Exception:
        ind_em = None
    print(f"  行业双源: sina[{ind_sina}] 东财[{ind_em}]")

    biz = main_business(code)
    qual = quality_fetch(code)

    # --- PE 过低陷阱 v1 (11-17 规则): 归母TTM/营收TTM > 3 → 利润非主业, PE 失去意义 ---
    gm_ttm = qual.get("gm_ttm")
    rev_cum = qual.get("rev_cum")
    rev_yoy = qual.get("rev_yoy")
    rev_ttm = None
    fy_col = qual.get("fy_col")
    if fy_col is not None and rev_cum is not None and qual.get("rev_prior") is not None:
        try:
            rev_fy = _f(_pick_row(ak_abstract(code)[0], ["营业总收入"]), fy_col)
            if rev_fy is not None:
                rev_ttm = rev_fy + rev_cum - qual.get("rev_prior")
        except Exception:
            rev_ttm = None
    pe_low_trap = False
    if gm_ttm and rev_ttm and rev_ttm > 0 and (gm_ttm / rev_ttm) > 3:
        pe_low_trap = True

    # --- 增长质量修正 v1 (11-10 规则) ---
    gm_yoy = qual.get("gm_yoy")
    kf_yoy = qual.get("kf_yoy")
    ocf = qual.get("ocf_cum")
    gmc = qual.get("gm_cum")
    gap = (gm_yoy - kf_yoy) if (gm_yoy is not None and kf_yoy is not None) else None
    ratio = (abs(ocf) / abs(gmc)) if (ocf is not None and gmc not in (None, 0)) else None
    triggered = bool(gap is not None and gap >= 15 and ocf is not None and ocf < 0
                      and ratio is not None and ratio >= 0.5)

    # --- 低基数/负基数修正 v2 (11-09 教训 + 本日实证) ---
    # 归母增速虚高但基数年被非经常项压低 (上期归母 << 上期扣非) → 归母增速无意义, 必须按扣非增速重算
    gm_prior = qual.get("gm_prior")
    kf_prior = qual.get("kf_prior")
    base_depressed = bool(gm_prior is not None and kf_prior is not None and gm_prior > 0
                           and kf_prior > 0 and gm_prior < 0.5 * kf_prior)
    low_base_trigger = bool(gap is not None and gap >= 15 and base_depressed
                            and kf_yoy is not None and kf_yoy < 0)
    if low_base_trigger and not triggered:
        triggered = True
        trigger_reason = "低基数(负基数)修正: 归母增速系基数年非经常项压低所致, 按扣非增速重算"
    elif triggered:
        trigger_reason = "增长质量修正: 归母-扣非增速差 ≥15pp + OCF<0 + |OCF|/归母 ≥50%"
    else:
        trigger_reason = None

    total_raw = round(ts_ / 55 * 50 + fs_ / 30 * 30 + vs_raw / 15 * 20, 1)
    rating_raw = rating_of(total_raw)

    if triggered:
        fs_adj, fnotes_adj = fund_score_with(kf_yoy, qual.get("roe"), qual.get("rev_yoy"))
        total = round(ts_ / 55 * 50 + fs_adj / 30 * 30 + vs_raw / 15 * 20, 1)
        fnotes = fnotes_adj + [f"[{trigger_reason}] 归母增速 {gm_yoy:+.1f}% → 扣非增速 {kf_yoy:+.1f}% 重算"]
        fs_ = fs_adj
    else:
        total, fnotes = total_raw, fnotes

    # --- 估值面失真修正 v1 (10-28 PM 规则) ---
    q_gm = qual.get("q_gm")
    ni_growth = fstat.get("ni_growth")
    distorted = bool(q_gm is not None and q_gm < 0 and ni_growth is not None and ni_growth < -50)
    vs_adj = vs_raw
    if distorted:
        pb_score = 7 if (pb is not None and pb <= 3) else (4 if (pb is not None and pb <= 5) else 1)
        vs_adj = pb_score
        total = round(ts_ / 55 * 50 + fs_ / 30 * 30 + vs_adj / 15 * 20, 1)
        vnotes = list(vnotes) + [
            f"估值面失真修正: 单季归母 {q_gm/1e8:.3f} 亿转亏 + 净利同比 {ni_growth:.0f}% "
            f"→ PE(TTM) {pe} 系峰值盈利滞后口径记 0 分, 只保留 PB"]

    rating = rating_of(total)
    # --- PE 过低陷阱 (11-17): 估值面不得给满分, PE 记 0 只留 PB ---
    if pe_low_trap:
        pb_score = 7 if (pb is not None and pb <= 3) else (4 if (pb is not None and pb <= 5) else 1)
        if vs_adj > pb_score:
            vs_adj = pb_score
            total = round(ts_ / 55 * 50 + fs_ / 30 * 30 + vs_adj / 15 * 20, 1)
            vnotes = list(vnotes) + [
                f"PE过低陷阱: 归母TTM {gm_ttm/1e8:.2f}亿 / 营收TTM {rev_ttm/1e8:.2f}亿 = "
                f"{gm_ttm/rev_ttm:.2f}x (>3) → 利润非主业, PE {pe} 失去意义, 估值面 PE 记 0 只保留 PB"]
    rating = rating_of(total)
    tgt_tech = tstat.get("hi20") if tstat.get("hi20") else price * 1.05
    tgt = round(min(target, max(tgt_tech, price * 1.05)), 2)

    stat_key = next((k for k in SECTOR_CANDIDATES.get(code, []) if k in sector_stats), None)
    sec = sector_stats.get(stat_key, {}) if stat_key else {}
    sec_wr = (f"{sec.get('win_rate'):.0f}% ({sec.get('win_count')}/{sec.get('count')}"
              if sec else "无记录(冷启动)")
    near_wr = ""
    for nk, nd in SECTOR_NEAR.get(code, []):
        ns = sector_stats.get(nk, {})
        if ns:
            near_wr += f" | {nd}[{nk}] {ns.get('win_rate'):.0f}% ({ns.get('win_count')}/{ns.get('count')})"

    def yi(x):
        return round(x / 1e8, 3) if x is not None else None

    rec = {"code": code, "name": name, "price": price, "pe_ttm": pe, "pb": pb,
           "mcap_yi": q.get("mcap_yi"), "float_mcap_yi": q.get("float_mcap_yi"),
           "turnover_pct": q.get("turnover_pct"), "vol_ratio": q.get("vol_ratio"),
           "v24_score": v24s, "ind_sina": ind_sina, "ind_em": ind_em,
           "business": (biz if isinstance(biz, str) else None),
           "tech_score": ts_, "fund_score": fs_, "val_score": vs_adj, "val_score_raw": vs_raw,
           "distorted": distorted, "pe_low_trap": pe_low_trap,
           "total": total, "rating": rating, "total_raw": total_raw, "rating_raw": rating_raw,
           "target": tgt, "stop": stop,
           "tech_notes": tnotes, "fund_notes": fnotes, "val_notes": vnotes,
           "tech_stat": tstat, "fund_stat": fstat,
           "chg_pct": q.get("change_pct"), "chg_report": chg,
           "sector_stat_key": stat_key, "sector_win_rate": sec_wr,
           "sector_near": near_wr.strip(" |") if near_wr else None,
           "quality": {
               "gm_yoy": gm_yoy, "kf_yoy": kf_yoy, "gap_pp": round(gap, 2) if gap is not None else None,
               "ocf_cum_yi": yi(ocf), "gm_cum_yi": yi(gmc), "kf_cum_yi": yi(qual.get("kf_cum")),
               "rev_cum_yi": yi(qual.get("rev_cum")),
               "q_gm_yi": yi(q_gm), "q_kf_yi": yi(qual.get("q_kf")), "q_rev_yi": yi(qual.get("q_rev")),
               "q_gm_yoy": (round((qual["q_gm"] / qual["q_gm_prior"] - 1) * 100, 2)
                            if qual.get("q_gm_prior") not in (None, 0) and qual.get("q_gm") is not None else None),
               "q_kf_yoy": (round((qual["q_kf"] / qual["q_kf_prior"] - 1) * 100, 2)
                            if qual.get("q_kf_prior") not in (None, 0) and qual.get("q_kf") is not None else None),
               "kf_ttm_yi": yi(qual.get("kf_ttm")), "gm_ttm_yi": yi(qual.get("gm_ttm")),
               "rev_ttm_yi": yi(rev_ttm), "gm_rev_ratio": round(gm_ttm / rev_ttm, 2) if (gm_ttm and rev_ttm) else None,
               "roe": qual.get("roe"), "rev_yoy": qual.get("rev_yoy"),
               "ocf_ratio": round(ratio, 4) if ratio is not None else None,
               "triggered": triggered, "applied": triggered,
               "latest_col": qual.get("latest_col"), "prior_col": qual.get("prior_col"),
               "error": qual.get("error"),
           },
           "stop_broken": (stop is not None and price is not None and price < stop)}
    print(f"  现价 {price} ({q.get('change_pct')}%) PE {pe} PB {pb} 市值 {q.get('mcap_yi')} 亿")
    print(f"  技术 {ts_}/55 基本面 {fs_}/30 估值 {vs_adj}/15 => {total} {rating} | 目标 {tgt} 止损 {stop}")
    print(f"  质量: 归母 {gm_yoy if gm_yoy is None else round(gm_yoy,1)}% 扣非 {kf_yoy if kf_yoy is None else round(kf_yoy,1)}% "
          f"gap {round(gap,1) if gap is not None else 'NA'} OCF {yi(ocf)} 亿 触发={triggered}")
    print(f"  板块 {stat_key or '(无键)'} → 胜率 {sec_wr}{near_wr}")
    print(f"  主营: {rec['business']}")
    return rec


def main():
    sector_stats, overall_wr, total_rec = load_sector_stats()
    print("=" * 78)
    print(f"AAna 尾盘深度分析 — {TODAY} (14:5x 盘中快照, 尾盘报告 14:47)")
    print(f"候选池 Top5 = {[c[0] for c in CANDIDATES]}")
    print(f"胜率库: {len(sector_stats)} 键 / {total_rec} 笔 / 整体 {overall_wr:.2f}%")
    print("=" * 78)

    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = [ex.submit(analyze, *c, sector_stats) for c in CANDIDATES]
        results = []
        for f in futs:
            try:
                results.append(f.result())
            except Exception as e:
                print(f"  单只失败跳过: {e}")

    results.sort(key=lambda x: (-x["total"], -x["v24_score"]))
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump({"date": TODAY, "generated": time.strftime("%H:%M:%S"),
                   "sector_stats_n": len(sector_stats), "overall_win_rate": overall_wr,
                   "results": results}, f, ensure_ascii=False, indent=1)
    print("\n=== 深度排名 (技术50% + 基本面30% + 估值20%) ===")
    for i, r in enumerate(results, 1):
        marks = ""
        if r.get("quality", {}).get("applied"): marks += " [质量修正]"
        if r.get("distorted"): marks += " [失真修正]"
        print(f"{i}. {r['code']} {r['name']} 深度评分 {r['total']} {r['rating']} "
              f"(原 {r['total_raw']}) 现价 {r['price']} 目标 {r['target']} 止损 {r['stop']}{marks}")
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()

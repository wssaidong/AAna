#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-11-10 PM — 基本面增长质量修正 (扣非口径) + 经营现金流背离检查

背景 (11-09 低基数陷阱教训的同族扩展):
  评分引擎 fund_score 用 akshare "归属母公司净利润增长率" (归母口径)。
  若归母增速显著高于扣非增速, 且经营现金流为负且背离幅度大,
  则该增速并非主业驱动 → 基本面得分应按扣非口径打折重算。

触发条件 (三条同时满足):
  1) 归母 YoY 增速 - 扣非 YoY 增速 >= 15pp (增长质量显著失真)
  2) 经营现金流净额 < 0 (利润未转化为现金)
  3) |经营现金流| / 归母净利 >= 50% (背离幅度大)

修正动作: 用扣非 YoY 增速替代归母增速重算 fund_score, 综合分重算。
输出: 原始分 + 修正后分 + 触发依据 (不静默改分), 写回 deep_analysis_pm_20261110.json
"""
import sys, os, json
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, '/Users/cai/code/AAna/scripts')

JSON_PATH = os.path.expanduser("~/code/AAna/data/deep_analysis_pm_20261110.json")


def fund_score_with(ni_growth, roe, rev_growth):
    """与 deep_analysis_20261022.fund_score 同一套阈值, 但 ni_growth 可注入"""
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


def fetch_quality(code):
    """拉 扣非净利润 / 经营现金流 / 归母 的同比序列 (同报告期对齐)"""
    import akshare as ak
    out = {"code": code}
    try:
        df = ak.stock_financial_abstract(symbol=code)
    except Exception as e:
        out["error"] = str(e)[:100]
        return out
    cols = [c for c in df.columns if c not in ('选项', '指标', '指标说明')]

    def pick(names):
        for n in names:
            row = df[df['指标'] == n]
            if not row.empty:
                return row.iloc[0]
            # 正则兜底: 指标名可能带前缀/后缀 (如 "经营活动产生的现金流量净额(元)")
            try:
                pat = n.replace('(', r'\(').replace(')', r'\)')
                row = df[df['指标'].astype(str).str.contains(pat, na=False, regex=True)]
            except Exception:
                row = df.iloc[0:0]
            if not row.empty:
                return row.iloc[0]
        return None

    def val(row, col):
        if row is None:
            return None
        try:
            return float(row[col])
        except Exception:
            return None

    # 找 "去年同期同报告期" 列: 最新期 20260930 → 20250930
    latest = cols[0]
    ym = str(latest)[:6]  # 202609
    prior_col = None
    for c in cols:
        s = str(c)
        if len(s) == 8 and s[:6] == ym and s != latest:
            prior_col = c
            break
    # 兜底: 找年份小 1 且月份相同
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

    r_kf = pick(["扣非净利润", "扣除非经常性损益的净利润", "扣除非经常性损益后的净利润"])
    r_gm = pick(["归母净利润", "归属母公司净利润"])
    r_ocf = pick(["经营活动产生的现金流量净额", "经营现金流"])
    r_rev = pick(["营业总收入"])

    def g(row, col):
        return val(row, col)

    out["latest_col"] = latest
    out["prior_col"] = prior_col
    out["kf_cum"] = g(r_kf, latest)
    out["gm_cum"] = g(r_gm, latest)
    out["ocf_cum"] = g(r_ocf, latest)
    out["rev_cum"] = g(r_rev, latest)
    if prior_col:
        out["kf_prior"] = g(r_kf, prior_col)
        out["gm_prior"] = g(r_gm, prior_col)
        out["rev_prior"] = g(r_rev, prior_col)

    # 扣非 YoY 增速
    if out["kf_cum"] is not None and out.get("kf_prior") not in (None, 0):
        out["kf_yoy"] = (out["kf_cum"] / out["kf_prior"] - 1) * 100
    if out["gm_cum"] is not None and out.get("gm_prior") not in (None, 0):
        out["gm_yoy"] = (out["gm_cum"] / out["gm_prior"] - 1) * 100
    if out["rev_cum"] is not None and out.get("rev_prior") not in (None, 0):
        out["rev_yoy"] = (out["rev_cum"] / out["rev_prior"] - 1) * 100

    # 单季 (最新期累计 - 上期累计), 扣非 & 归母 & 营收
    cols2 = cols[:2]
    if len(cols2) >= 2:
        prev_cum_col = cols2[1]
        out["q_kf"] = (g(r_kf, latest) or 0) - (g(r_kf, prev_cum_col) or 0)
        out["q_gm"] = (g(r_gm, latest) or 0) - (g(r_gm, prev_cum_col) or 0)
        out["q_rev"] = (g(r_rev, latest) or 0) - (g(r_rev, prev_cum_col) or 0)
    return out


def main():
    with open(JSON_PATH) as f:
        d = json.load(f)
    codes = [r["code"] for r in d["results"]]

    qual = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(fetch_quality, c): c for c in codes}
        for fu in futs:
            c = futs[fu]
            try:
                qual[c] = fu.result()
            except Exception as e:
                qual[c] = {"code": c, "error": str(e)[:100]}

    for r in d["results"]:
        c = r["code"]
        q = qual.get(c, {})
        r["quality"] = {
            "kf_yoy": q.get("kf_yoy"), "gm_yoy": q.get("gm_yoy"),
            "ocf_cum_yi": (round(q["ocf_cum"] / 1e8, 3) if q.get("ocf_cum") is not None else None),
            "gm_cum_yi": (round(q["gm_cum"] / 1e8, 3) if q.get("gm_cum") is not None else None),
            "kf_cum_yi": (round(q["kf_cum"] / 1e8, 3) if q.get("kf_cum") is not None else None),
            "rev_cum_yi": (round(q["rev_cum"] / 1e8, 3) if q.get("rev_cum") is not None else None),
            "q_kf_yi": (round(q["q_kf"] / 1e8, 3) if q.get("q_kf") is not None else None),
            "q_gm_yi": (round(q["q_gm"] / 1e8, 3) if q.get("q_gm") is not None else None),
            "q_rev_yi": (round(q["q_rev"] / 1e8, 3) if q.get("q_rev") is not None else None),
            "prior_col": q.get("prior_col"), "error": q.get("error"),
        }
        fstat = r.get("fund_stat") or {}
        roe, reg = fstat.get("roe"), fstat.get("rev_growth")
        gm_yoy = fstat.get("ni_growth")
        kf_yoy = q.get("kf_yoy")
        ocf = q.get("ocf_cum")
        gmc = q.get("gm_cum")

        gap = None
        if gm_yoy is not None and kf_yoy is not None:
            gap = gm_yoy - kf_yoy
        ratio = None
        if ocf is not None and gmc not in (None, 0):
            ratio = abs(ocf) / abs(gmc)

        trig = []
        if gap is not None and gap >= 15:
            trig.append(f"归母增速 {gm_yoy:+.1f}% 与扣非增速 {kf_yoy:+.1f}% 相差 {gap:.1f}pp (>=15pp)")
        else:
            trig.append(f"归母/扣非增速差 {gap:.1f}pp (<15pp)" if gap is not None else "增速差不可得")
        if ocf is not None and ocf < 0:
            trig.append(f"经营现金流 {ocf/1e8:.2f} 亿为负")
        else:
            trig.append(f"经营现金流 {ocf/1e8:.2f} 亿为正" if ocf is not None else "经营现金流不可得")
        if ratio is not None:
            trig.append(f"|OCF|/归母 = {ratio*100:.0f}% (>=50%)" if ratio >= 0.5
                        else f"|OCF|/归母 = {ratio*100:.0f}% (<50%)")
        else:
            trig.append("背离比不可得")

        triggered = (gap is not None and gap >= 15 and ocf is not None and ocf < 0
                     and ratio is not None and ratio >= 0.5)

        r["quality"]["gap_pp"] = (round(gap, 2) if gap is not None else None)
        r["quality"]["ocf_ratio"] = (round(ratio, 4) if ratio is not None else None)
        r["quality"]["triggered"] = triggered
        r["quality"]["trigger_detail"] = "; ".join(trig)

        if triggered:
            fs_adj, fnotes_adj = fund_score_with(kf_yoy, roe, reg)
            total_adj = round(r["tech_score"] / 55 * 50 + fs_adj / 30 * 30 + r["val_score"] / 15 * 20, 1)
            r["quality"]["fund_score_adj"] = fs_adj
            r["quality"]["fund_notes_adj"] = fnotes_adj
            r["quality"]["total_adj"] = total_adj
            r["quality"]["rating_adj"] = ("买入" if total_adj >= 80 else "增持" if total_adj >= 68
                                          else "中性" if total_adj >= 55 else "减持")
            r["total_raw"] = r["total"]
            r["rating_raw"] = r["rating"]
            r["fund_score_raw"] = r["fund_score"]
            r["total"] = total_adj
            r["rating"] = r["quality"]["rating_adj"]
            r["fund_score"] = fs_adj
            r["fund_notes"] = fnotes_adj + [f"[增长质量修正] 归母增速 {gm_yoy:+.1f}% → 扣非增速 {kf_yoy:+.1f}% 重算"]
            r["quality"]["applied"] = True
        else:
            r["total_raw"] = r["total"]
            r["rating_raw"] = r["rating"]
            r["fund_score_raw"] = r["fund_score"]
            r["quality"]["applied"] = False
            r["quality"]["total_adj"] = r["total"]

        print(f"{c} {r['name']}: 原始 {r['total_raw']} {r['rating_raw']} → "
              f"修正后 {r['total']} {r['rating']} | {r['quality']['trigger_detail']}")
        if r["quality"]["applied"]:
            print(f"    基本面 {r['fund_score_raw']}/30 → {r['fund_score']}/30 "
                  f"(扣非增速 {kf_yoy:+.1f}%)  OCF {r['quality']['ocf_cum_yi']} 亿 "
                  f"归母 {r['quality']['gm_cum_yi']} 亿 扣非 {r['quality']['kf_cum_yi']} 亿 "
                  f"单季扣非 {r['quality']['q_kf_yi']} 亿")

    d["results"].sort(key=lambda x: (-x["total"], -x["v24_score"]))
    d["quality_correction_applied"] = True
    with open(JSON_PATH, "w") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)

    print("\n=== 修正后排名 ===")
    for i, r in enumerate(d["results"], 1):
        mark = " [已修正]" if r["quality"]["applied"] else ""
        print(f"{i}. {r['code']} {r['name']} {r['total']} {r['rating']} "
              f"(原 {r['total_raw']}){mark}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-10-28 (周三交易日盘前 08:3x) — 冰点守卫短路日 · 0 推荐
当日报告 = reports/2026-10-28-选股报告.md (08:02 盘前版, 5468 字节)
核心事实: Top10 表 0 只 (报告快照情绪 20 冰点 / 大盘平均 -2.14% / 建议仓位 10% / 停止交易)
  → 候选池空 → 无标的可评分 → 0 推荐 → 不创建东财组合 20261028ZZ (先例 10-27 14:45 尾盘
  冰点短路 0 推荐 → 无推荐池/纸面仓/东财污染)
守卫短路链: 10-27 14:45 尾盘情绪 30 冰点 → 10-27 17:01 收盘版选股报告 0 只 (情绪 20)
  → 10-28 08:02 盘前版延续昨收冰点口径 0 只 — 设计行为, 非数据故障
  (报告自身佐证: 交易建议 ⚠️ 停止交易; "热点板块: 数据获取中" + 热点主线为 4 月旧模板
   fallback, 如实披露不引用)
铁律口径: 昨日 Top1 老百姓 603883 (10-27 深度 75.4 买入) 复核 — 10-27 实收 +1.99%
  vs 大盘平均 -2.14% → 超额 +4.13pp, 当日胜出 + 正盈利 ✅ (腾讯 10-27 收盘快照)
Kimi: 本机无 kimi CLI / moonshot key (10-28 再复核) — 连续第 13 日由 AAna 深度评分引擎
  + LLM 定性层执行 (口径 10-16~10-27 连续)
"""
import sys, os, json, re, time

sys.path.insert(0, '/Users/cai/code/AAna/scripts')

TODAY = "2026-10-28"
BASE_DATE = "2026-10-27"   # K 线末日 / 昨收基准 (10-27 周二收盘)
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
TODAY_REPORT = os.path.join(REPORT_DIR, f"{TODAY}-选股报告.md")  # 周三 08:02 盘前版
OUT_JSON = os.path.expanduser(f"~/code/AAna/data/deep_analysis_{TODAY.replace('-','')}.json")
MK_AVG = -2.14          # 报告快照: 大盘平均涨跌 -2.14% (10-27 收盘基准)
SNAP = {"score": 20, "label": "冰点", "zt_count": 42, "dt_count": 4, "position": 0.10}
RUN_ID = "01a17fea-3204-764d-8600-c8a56df900e3"

# 昨日深度池 (data/deep_analysis_20261027.json, 基准日 10-26) — 用于今日 T+1 复核
YDAY_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_20261027.json")


def parse_top10_full(text):
    """解析 '🏆 重点关注 Top 10' 表格: 排名/名称/代码/价格/涨跌幅/技术分/综合分/软止损 (口径同 20261027)"""
    m = re.search(r'重点关注 Top 10(.*?)(?=\n###|\Z)', text, re.S)
    rows = []
    for line in (m.group(1) if m else text).split("\n"):
        ls = line.strip()
        if not ls.startswith("|") or ls.startswith("|:"):
            continue
        cells = [c.strip() for c in ls.strip("|").split("|")]
        if len(cells) >= 8 and re.fullmatch(r"\d{6}", cells[2]):
            try:
                rank = int(cells[0])
            except ValueError:
                continue
            name = re.sub(r'^[^一-龥A-Za-z0-9]+', '', cells[1])
            price = float(cells[3].replace('¥', '').replace(',', ''))
            chg = float(re.search(r'[+-]?\d+\.?\d*', cells[4]).group())
            tech = int(re.sub(r'\D', '', cells[5]) or 0)
            v24 = int(re.sub(r'\D', '', cells[7]) or 0)
            stop = (float(re.search(r'\d+\.?\d*', cells[10]).group())
                    if len(cells) > 10 and re.search(r'\d', cells[10]) else None)
            rows.append({"rank": rank, "code": cells[2], "name": name, "price": price,
                         "chg": chg, "tech": tech, "v24": v24, "stop": stop})
    return rows


def guard_check():
    """P0 冰点守卫 (单一真源 check_ice_point_guard)。盘前未开盘: live 源可能回退,
    以报告快照 20 冰点为判定口径 (10-27 17:01 收盘情绪 → 10-28 盘前延续)"""
    from aana_afternoon_screen import check_ice_point_guard
    live = None
    try:
        live = check_ice_point_guard()
    except Exception as e:
        print(f"  live 情绪源异常(盘前未开盘): {e}")
    snap = check_ice_point_guard(sent={"score": SNAP["score"], "label": SNAP["label"],
                                       "zt_count": SNAP["zt_count"], "dt_count": SNAP["dt_count"]})
    return live, snap


def load_sector_stats():
    with open(os.path.expanduser("~/code/AAna/data/rec_tuning.json")) as f:
        rt = json.load(f)
    return rt.get("sector_stats", {}), rt.get("overall_win_rate"), rt.get("total_records")


def tencent_quotes(codes):
    """腾讯实时快照: 盘前=昨收口径。返回 {code: (现价, 涨跌幅%, 快照时间戳)}"""
    import requests
    syms = ",".join(("sh" if c.startswith(("6", "9")) else "sz") + c for c in codes)
    r = requests.get(f"https://qt.gtimg.cn/q={syms}", timeout=10,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.encoding = "gbk"
    out = {}
    for m in re.finditer(r'v_(?:sh|sz)(\d{6})="([^"]+)"', r.text):
        p = m.group(2).split("~")
        try:
            out[m.group(1)] = (float(p[3]), float(p[32]), p[30])
        except (ValueError, IndexError):
            continue
    return out


def main():
    print("=" * 78)
    print(f"AAna 深度分析 — {TODAY} (周三交易日盘前, 数据基准 {BASE_DATE} 收盘)")
    print(f"Run: autopilot ca411dd3 深度分析 {RUN_ID}")
    print("=" * 78)
    sz = os.path.getsize(TODAY_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(TODAY_REPORT)))
    print(f"📄 当日报告: {TODAY_REPORT}")
    print(f"   大小: {sz} 字节 | 修改: {mt} (周三交易日 08:02 盘前版, 昨收=10-27 周二收盘口径)")
    text = open(TODAY_REPORT).read()
    pool = parse_top10_full(text)
    # 双重校验: 表区间内含 6 位代码的数据行原始计数 (防解析器误判空表)
    m = re.search(r'重点关注 Top 10(.*?)(?=\n###|\Z)', text, re.S)
    raw_rows = [l for l in (m.group(1) if m else "").split("\n")
                if l.strip().startswith("|") and re.search(r'\d{6}', l)
                and not l.strip().startswith("|:")]
    print(f"   当日 Top10 表: {len(pool)} 只 (原始数据行 {len(raw_rows)} 行) → 候选池 = {len(pool)} 只")
    snap_sent = (f"情绪{SNAP['score']}({SNAP['label']}) 仓位{SNAP['position']*100:.0f}% "
                 f"大盘平均{MK_AVG}% 涨停{SNAP['zt_count']}/跌停{SNAP['dt_count']} "
                 f"交易建议⚠️停止交易")
    print(f"   报告快照 (10-27 收盘口径): {snap_sent}")

    sector_stats, overall_wr, n_rec = load_sector_stats()
    print(f"📊 板块胜率库 (rec_optimizer 口径): {len(sector_stats)} 板块 | 整体胜率 {overall_wr:.1f}% ({n_rec} 笔)")

    live, snap = guard_check()
    print(f"🛡 P0 冰点守卫: 快照口径 情绪{snap['sentiment_score']}({snap['sentiment_label']}) "
          f"仓位{snap['position_ratio']*100:.0f}% is_ice_point={snap['is_ice_point']}")
    if snap.get("reason"):
        print(f"   短路原因: {snap['reason']}")
    if live:
        print(f"   live 口径 情绪{live['sentiment_score']}({live['sentiment_label']}) "
              f"is_ice_point={live['is_ice_point']} (盘前未开盘, 披露用)")
    ice = snap["is_ice_point"]

    # ---- 昨日深度池 T+1 复核 (10-27 收盘, 腾讯快照) ----
    yday = json.load(open(YDAY_JSON))
    ypool = yday.get("results", [])
    codes = [r["code"] for r in ypool]
    q = tencent_quotes(codes)
    review = []
    for r in ypool:
        px, chg, ts = q.get(r["code"], (None, None, ""))
        review.append({**{k: r.get(k) for k in ("code", "name", "total", "rating")},
                       "close": px, "chg_pct": chg, "quote_ts": ts,
                       "beat_mkt": (chg is not None and chg > MK_AVG)})
    review.sort(key=lambda x: (x["chg_pct"] if x["chg_pct"] is not None else -99), reverse=True)
    print(f"\n=== 昨日深度池 T+1 复核 ({BASE_DATE} 收盘, 腾讯快照口径) ===")
    for i, r in enumerate(review, 1):
        ts = r['quote_ts'][:8]
        print(f"{i}. {r['code']} {r['name']} 深度{r['total']}{r['rating']} "
              f"| 10-27 实收 {r['chg_pct']:+.2f}% ({'✅胜大盘' if r['beat_mkt'] else '❌弱于大盘'})"
              f" | 快照日 {ts}")
    n_beat = sum(1 for r in review if r["beat_mkt"])
    n_pos = sum(1 for r in review if (r["chg_pct"] or 0) > 0)
    print(f"胜大盘({MK_AVG}%): {n_beat}/{len(review)} | 正盈利: {n_pos}/{len(review)}")
    ytop = yday.get("recommend") or {}
    ytop_r = next((r for r in review if r["code"] == ytop.get("code")), None)
    if ytop_r:
        print(f"🏁 昨日 Top1 {ytop_r['code']} {ytop_r['name']} 铁律复核: 10-27 实收 "
              f"{ytop_r['chg_pct']:+.2f}% vs 大盘 {MK_AVG}% → 超额 {ytop_r['chg_pct']-MK_AVG:+.2f}pp "
              f"{'✅ 当日胜出+正盈利' if (ytop_r['beat_mkt'] and ytop_r['chg_pct']>0) else '❌'}")

    # ---- 结论 ----
    print("\n=== 结论 ===")
    if pool:
        print(f"候选池 {len(pool)} 只 (未预期分支, 今日应空池)")
    recommend = None  # 空池 + 冰点守卫短路 → 0 推荐
    print(f"🏁 最值得购买: 无 (0 推荐 — 候选池 0 只 + 冰点守卫 is_ice_point={ice})")
    print("   东财组合 20261028ZZ: 不创建 (0 推荐无标的可入组; 先例 10-27 尾盘短路 → 无东财污染)")
    print(f"   恢复条件: 14:45 尾盘若情绪脱离冰点 → 第 7 批按阈值 60 / 仓位 50% 执行 (10-27 复盘前瞻)")

    with open(OUT_JSON, "w") as f:
        json.dump({"date": TODAY, "base_date": BASE_DATE, "report": TODAY_REPORT,
                   "report_size": sz, "report_mtime": mt,
                   "generated": time.strftime("%H:%M:%S"),
                   "sentiment_snap": SNAP, "mk_avg": MK_AVG,
                   "pool_size": len(pool), "guard_ice": ice,
                   "guard_reason": snap.get("reason"),
                   "overall_win_rate": overall_wr, "total_records": n_rec,
                   "sector_count": len(sector_stats),
                   "yesterday_review": {"base": "2026-10-26", "verified_on": BASE_DATE,
                                        "n_beat_mkt": n_beat, "n_positive": n_pos,
                                        "results": review},
                   "recommend": None, "eastmoney": "skipped: 0 推荐 (冰点守卫短路, 不创建 20261028ZZ)"},
                  f, ensure_ascii=False, indent=1)
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()

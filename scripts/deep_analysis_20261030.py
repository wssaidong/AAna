#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-10-30 (周五交易日盘前 08:3x) — 冰点守卫短路日 · 0 推荐
当日报告 = reports/2026-10-30-选股报告.md (08:01 盘前版)
核心事实: Top10 表 0 只 (报告快照情绪 20 冰点 / 大盘平均 -2.30% / 建议仓位 10% / 停止交易)
  → 候选池空 → 无标的可评分 → 0 推荐 → 不创建东财组合 20261030ZZ (先例 10-27 尾盘 /
  10-28 盘前两次冰点短路 → 无推荐池/纸面仓/东财污染)
守卫短路链: 10-29 情绪 75(亢奋) → 09:38 开盘后版 15(冰点) → 14:45 尾盘守卫第 3 次实战短路
  (第 8 批不建·空仓过夜) → 10-29 收盘 20(冰点) → 10-30 08:01 盘前版延续冰点口径 0 只
  — 单日塌方 75→15→20 后冰点第 2 日, 设计行为非数据故障 (live+快照双口径 is_ice_point=True)
铁律口径: 昨日 Top1 创维数字 000810 (10-29 深度 70.4 增持·四关全过·同步东财 20261029ZZ
  gid=1811) 复核 — 10-29 实收 -4.17% vs 大盘平均 -2.30% → 负盈利 + 弱于大盘 + 收 10.58
  破软止损 10.71 → 未达铁律 (10-29 报告§八回吐预警原文应验); 池 4 只正盈利 1/4 胜大盘 1/4,
  唯一命中为减持级九阳股份 +2.77% — 连续 2 日"低评分表现反超"(10-28 尾盘国机精工 +8.24%
  同型), 亢奋→塌方转换日 α/β 错位, 与 10-27 普跌日 Top1 唯一正盈利对照: 深度评分区分度
  集中在弱市/分化日, 极端转换日失效 — 如实披露
Kimi: 本机无 kimi CLI / moonshot key (10-30 再复核: which kimi 无, env 无) — 连续第 15 日
  由 AAna 深度评分引擎 + LLM 定性层执行 (口径 10-16~10-29 连续)
胜率库: 10-29 夜间扩容 83→88 键 / 354→367 笔, 整体 48.9%→49.9%
"""
import sys, os, json, re, time

sys.path.insert(0, '/Users/cai/code/AAna/scripts')

TODAY = "2026-10-30"
BASE_DATE = "2026-10-29"   # K 线末日 / 昨收基准 (10-29 周四收盘)
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
TODAY_REPORT = os.path.join(REPORT_DIR, f"{TODAY}-选股报告.md")  # 周五 08:01 盘前版
OUT_JSON = os.path.expanduser(f"~/code/AAna/data/deep_analysis_{TODAY.replace('-','')}.json")
MK_AVG = -2.30          # 报告快照: 大盘平均涨跌 -2.30% (10-29 收盘基准)
SNAP = {"score": 20, "label": "冰点", "zt_count": 39, "dt_count": 4, "position": 0.10}
RUN_ID = "01a18a36-e787-715e-b3d3-be9b8a9df6f1"

# 昨日深度池 (data/deep_analysis_20261029.json, 基准日 10-28) — 用于今日 T+1 复核
YDAY_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_20261029.json")

# 昨日池行业键 (东财 f127 10-29 核验) → rec_tuning sector_stats (88 键 367 笔) 映射
SECTOR_MAP = {
    "603683": ("化学-其他化学制品(功能性胶粘材料/电子胶带)", "其他化学制品"),
    "002242": ("家电-小家电(厨房小家电双品牌)", "小家电"),
    "000810": ("家电-其它视听器材(机顶盒/宽带终端/VR)", None),
    "001233": ("汽车-轮胎", None),
}


def parse_top10_full(text):
    """解析 '🏆 重点关注 Top 10' 表格 (口径同 10-27~10-29)"""
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
            rows.append({"rank": rank, "code": cells[2]})
    return rows


def guard_check():
    """P0 冰点守卫 (单一真源 check_ice_point_guard)。盘前未开盘: live 与快照双口径披露"""
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
    print(f"AAna 深度分析 — {TODAY} (周五交易日盘前, 数据基准 {BASE_DATE} 收盘)")
    print(f"Run: autopilot ca411dd3 深度分析 {RUN_ID}")
    print("=" * 78)
    sz = os.path.getsize(TODAY_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(TODAY_REPORT)))
    print(f"📄 当日报告: {TODAY_REPORT}")
    print(f"   大小: {sz} 字节 | 修改: {mt} (周五交易日 08:01 盘前版, 昨收=10-29 周四收盘口径)")
    text = open(TODAY_REPORT).read()
    pool = parse_top10_full(text)
    # 双重校验: 表区间内含 6 位代码的数据行原始计数 (防解析器误判空表, 10-28 口径)
    m = re.search(r'重点关注 Top 10(.*?)(?=\n###|\Z)', text, re.S)
    raw_rows = [l for l in (m.group(1) if m else "").split("\n")
                if l.strip().startswith("|") and re.search(r'\d{6}', l)
                and not l.strip().startswith("|:")]
    print(f"   当日 Top10 表: {len(pool)} 只 (原始数据行 {len(raw_rows)} 行) → 候选池 = {len(pool)} 只")
    snap_sent = (f"情绪{SNAP['score']}({SNAP['label']}) 仓位{SNAP['position']*100:.0f}% "
                 f"大盘平均{MK_AVG}% 涨停{SNAP['zt_count']}/跌停{SNAP['dt_count']} "
                 f"交易建议⚠️停止交易")
    print(f"   报告快照 (10-29 收盘口径): {snap_sent}")

    sector_stats, overall_wr, n_rec = load_sector_stats()
    print(f"📊 板块胜率库 (rec_optimizer 口径): {len(sector_stats)} 板块 | 整体胜率 {overall_wr:.1f}% ({n_rec} 笔)")

    live, snap = guard_check()
    print(f"🛡 P0 冰点守卫: 快照口径 情绪{snap['sentiment_score']}({snap['sentiment_label']}) "
          f"仓位{snap['position_ratio']*100:.0f}% is_ice_point={snap['is_ice_point']}")
    if snap.get("reason"):
        print(f"   短路原因: {snap['reason']}")
    if live:
        print(f"   live 口径 情绪{live['sentiment_score']}({live['sentiment_label']}) "
              f"is_ice_point={live['is_ice_point']} (盘前未开盘, 双口径一致)")
    ice = snap["is_ice_point"]

    # ---- 昨日深度池 T+1 复核 (10-29 收盘, 腾讯快照) ----
    yday = json.load(open(YDAY_JSON))
    ypool = sorted(yday.get("results", []), key=lambda r: -r["total"])
    codes = [r["code"] for r in ypool]
    q = tencent_quotes(codes)
    review = []
    for r in ypool:
        px, chg, ts = q.get(r["code"], (None, None, ""))
        stop = r.get("stop")
        industry, skey = SECTOR_MAP.get(r["code"], (None, None))
        sec = sector_stats.get(skey, {}) if skey else {}
        sec_wr = (f"{sec.get('win_rate'):.0f}% ({sec.get('win_count')}/{sec.get('count')})"
                  if sec else "无记录(冷启动)")
        review.append({"code": r["code"], "name": r["name"], "total": r["total"],
                       "rating": r["rating"], "stop": stop,
                       "industry": industry, "sector_stat_key": skey,
                       "sector_win_rate": sec_wr,
                       "close": px, "chg_pct": chg, "quote_ts": ts,
                       "beat_mkt": (chg is not None and chg > MK_AVG),
                       "stop_broken": (stop is not None and px is not None and px < stop)})
    review.sort(key=lambda x: (x["chg_pct"] if x["chg_pct"] is not None else -99), reverse=True)
    print(f"\n=== 昨日深度池 T+1 复核 ({BASE_DATE} 收盘, 腾讯快照口径) ===")
    for i, r in enumerate(review, 1):
        ts = r['quote_ts'][:8]
        stop_mark = ("🔴收%.2f破止损%.2f" % (r['close'], r['stop'])) if r['stop_broken'] else "止损未破"
        print(f"{i}. {r['code']} {r['name']} 深度{r['total']}{r['rating']} "
              f"| 10-29 实收 {r['chg_pct']:+.2f}% ({'✅胜大盘' if r['beat_mkt'] else '❌弱于大盘'}) "
              f"{stop_mark} | 板块[{r['sector_stat_key'] or '冷启动'}]{r['sector_win_rate']} | 快照日 {ts}")
    n_beat = sum(1 for r in review if r["beat_mkt"])
    n_pos = sum(1 for r in review if (r["chg_pct"] or 0) > 0)
    avg_chg = sum(r["chg_pct"] for r in review) / len(review) if review else 0
    print(f"胜大盘({MK_AVG}%): {n_beat}/{len(review)} | 正盈利: {n_pos}/{len(review)} "
          f"| 池均值 {avg_chg:+.2f}% → 超额 {avg_chg-MK_AVG:+.2f}pp")
    ytop = yday.get("recommend") or {}
    ytop_r = next((r for r in review if r["code"] == ytop.get("code")), None)
    if ytop_r:
        verdict = "✅ 当日胜出+正盈利" if (ytop_r["beat_mkt"] and ytop_r["chg_pct"] > 0) else "❌ 未达铁律"
        print(f"🏁 昨日 Top1 {ytop_r['code']} {ytop_r['name']} 铁律复核: 10-29 实收 "
              f"{ytop_r['chg_pct']:+.2f}% vs 大盘 {MK_AVG}% → 超额 {ytop_r['chg_pct']-MK_AVG:+.2f}pp "
              f"{verdict} (收 {ytop_r['close']} {'🔴破' if ytop_r['stop_broken'] else '未破'}软止损 {ytop_r['stop']})")

    # ---- 结论 ----
    print("\n=== 结论 ===")
    if pool:
        print(f"候选池 {len(pool)} 只 (未预期分支, 今日应空池)")
    print(f"🏁 最值得购买: 无 (0 推荐 — 候选池 0 只 + 冰点守卫 is_ice_point={ice})")
    print("   东财组合 20261030ZZ: 不创建 (0 推荐无标的可入组; 先例 10-27/10-28 冰点短路 → 无东财污染)")
    print("   20261029ZZ gid=1811 保留 (创维数字 10-29 已破软止损 10.71, 止损纪律执行, 组不撤仅记录)")

    with open(OUT_JSON, "w") as f:
        json.dump({"date": TODAY, "base_date": BASE_DATE, "report": TODAY_REPORT,
                   "report_size": sz, "report_mtime": mt,
                   "generated": time.strftime("%H:%M:%S"),
                   "sentiment_snap": SNAP, "mk_avg": MK_AVG,
                   "pool_size": len(pool), "guard_ice": ice,
                   "guard_reason": snap.get("reason"),
                   "guard_live": (None if not live else {
                       "score": live.get("sentiment_score"),
                       "label": live.get("sentiment_label"),
                       "is_ice_point": live.get("is_ice_point")}),
                   "overall_win_rate": overall_wr, "total_records": n_rec,
                   "sector_count": len(sector_stats),
                   "yesterday_review": {"base": "2026-10-28", "verified_on": BASE_DATE,
                                        "n_beat_mkt": n_beat, "n_positive": n_pos,
                                        "pool_avg_chg": round(avg_chg, 2),
                                        "results": review},
                   "recommend": None,
                   "eastmoney": "skipped: 0 推荐 (冰点守卫短路, 不创建 20261030ZZ; 20261029ZZ gid=1811 保留)"},
                  f, ensure_ascii=False, indent=1)
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()

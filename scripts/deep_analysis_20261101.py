#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-11-01 (周日非交易日 08:3x) — 冰点延续空仓过周末第 2 日 · 0 推荐
当日报告口径: 11-01 为周日非交易日, reports/ 无 2026-11-01-选股报告.md (已核实)
  → 采用最近交易日报告 reports/2026-10-30-选股报告.md (17:02 盘后版, 与 10-31 周六同源)
核心事实: 10-30 报告 Top10 表 0 只 (冰点守卫短路设计行为) → 今日候选池继承为空
  → 无标的可评分 → 0 推荐 (连续第 4 个 0 推荐日: 10-28 起四连空)
铁律口径: 昨日 (10-31 周六) 深度池 0 只 → 无 Top1 可复核; 转对最后有效池 (10-29, 4 只)
  的周日快照零变动复核 (周日腾讯快照=周五收盘口径, 与昨日周六快照逐股比对)
周一 11-02 前瞻 (复盘 e2e7db7 口径): 冰点第 2 日后修复窗口 (10-28 V 型修复 20→58→75
  先例, 修复日第 2 日可放行); 情绪回 30+ 断点 + 进攻主线为修复信号; T+1 复核无对象
  (周五池 0 只); 快照 09:00 链 day6 预防为最后窗口; ⑩-h 追高池第 3 样本风险自查
东财: 不创建 20261101ZZ (0 推荐无标的可入组 + 周日非交易日双重理由; 先例 10-27/10-28/
  10-30/10-31 → 无东财污染); 20261029ZZ gid=1811 (创维数字) 保留止损纪律记录
Kimi: 本机无 kimi CLI / moonshot key (11-01 再复核) — 连续第 17 日由 AAna 深度评分
  引擎 + LLM 定性层执行
胜率库: 88 键 / 367 笔 / 整体 49.9% (10-29 夜间扩容后口径, 周末无新记录)
"""
import sys, os, json, re, time

sys.path.insert(0, '/Users/cai/code/AAna/scripts')

TODAY = "2026-11-01"
BASE_DATE = "2026-10-30"   # K 线末日 / 最近收盘基准 (10-30 周五收盘, 周日快照同源)
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
TODAY_REPORT = os.path.join(REPORT_DIR, f"{TODAY}-选股报告.md")     # 预期不存在 (周日)
USED_REPORT = os.path.join(REPORT_DIR, "2026-10-30-选股报告.md")     # 最近交易日 17:02 盘后版
OUT_JSON = os.path.expanduser(f"~/code/AAna/data/deep_analysis_{TODAY.replace('-','')}.json")
MK_AVG = -2.42          # 10-30 报告快照: 大盘平均涨跌 -2.42%
SH_CLOSE = -1.44        # 上证 -1.44% (盘后战报口径)
SNAP = {"score": 20, "label": "冰点", "zt_count": 49, "dt_count": 5, "position": 0.10}
RUN_ID = "01a19483-db72-7dcd-bc3e-1c7452277cf9"

# 昨日深度池 = 0 只 (data/deep_analysis_20261031.json) → 无 Top1 复核
YDAY_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_20261031.json")
# 最后有效池 = 10-29 深度池 (data/deep_analysis_20261029.json, 基准日 10-28) — 周日零变动复核
LAST_POOL_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_20261029.json")

# 最后有效池行业键 (东财 f127 10-29 核验) → rec_tuning sector_stats (88 键 367 笔) 映射
SECTOR_MAP = {
    "603683": ("化学-其他化学制品(功能性胶粘材料/电子胶带)", "其他化学制品"),
    "002242": ("家电-小家电(厨房小家电双品牌)", "小家电"),
    "000810": ("家电-其它视听器材(机顶盒/宽带终端/VR)", None),
    "001233": ("汽车-轮胎", None),
}


def parse_top10_full(text):
    """解析 '🏆 重点关注 Top 10' 表格 (口径同 10-27~10-31)"""
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
    """P0 冰点守卫 (单一真源 check_ice_point_guard)。周日休市: 仅快照口径 (周五收盘)"""
    from aana_afternoon_screen import check_ice_point_guard
    snap = check_ice_point_guard(sent={"score": SNAP["score"], "label": SNAP["label"],
                                       "zt_count": SNAP["zt_count"], "dt_count": SNAP["dt_count"]})
    return snap


def load_sector_stats():
    with open(os.path.expanduser("~/code/AAna/data/rec_tuning.json")) as f:
        rt = json.load(f)
    return rt.get("sector_stats", {}), rt.get("overall_win_rate"), rt.get("total_records")


def tencent_quotes(codes):
    """腾讯快照: 周日休市=周五收盘口径。返回 {code: (现价, 涨跌幅%, 快照时间戳)}"""
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
    print(f"AAna 深度分析 — {TODAY} (周日非交易日, 数据基准 {BASE_DATE} 周五收盘)")
    print(f"Run: autopilot ca411dd3 深度分析 {RUN_ID}")
    print("=" * 78)

    # ---- 报告确认 (autopilot 强制: 打印报告名称防错) ----
    has_today = os.path.exists(TODAY_REPORT)
    print(f"📄 当日报告检索: {TODAY_REPORT} → {'存在' if has_today else '不存在 (周日非交易日, 符合预期)'}")
    sz = os.path.getsize(USED_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(USED_REPORT)))
    print(f"   采用报告: {USED_REPORT}")
    print(f"   大小: {sz} 字节 | 修改: {mt} (周五 17:02 盘后版, 昨收/收盘=10-30 周五收盘口径, 与 10-31 周六同源)")
    text = open(USED_REPORT).read()
    pool = parse_top10_full(text)
    m = re.search(r'重点关注 Top 10(.*?)(?=\n###|\Z)', text, re.S)
    raw_rows = [l for l in (m.group(1) if m else "").split("\n")
                if l.strip().startswith("|") and re.search(r'\d{6}', l)
                and not l.strip().startswith("|:")]
    print(f"   报告 Top10 表: {len(pool)} 只 (原始数据行 {len(raw_rows)} 行) → 今日候选池 = {len(pool)} 只")
    snap_sent = (f"情绪{SNAP['score']}({SNAP['label']}) 仓位{SNAP['position']*100:.0f}% "
                 f"大盘平均{MK_AVG}% 涨停{SNAP['zt_count']}/跌停{SNAP['dt_count']} "
                 f"上证{SH_CLOSE}% 交易建议⚠️停止交易")
    print(f"   报告快照 (10-30 周五收盘口径): {snap_sent}")

    sector_stats, overall_wr, n_rec = load_sector_stats()
    print(f"📊 板块胜率库 (rec_optimizer 口径): {len(sector_stats)} 板块 | 整体胜率 {overall_wr:.1f}% ({n_rec} 笔)")

    snap = guard_check()
    print(f"🛡 P0 冰点守卫 (周五收盘快照口径): 情绪{snap['sentiment_score']}({snap['sentiment_label']}) "
          f"仓位{snap['position_ratio']*100:.0f}% is_ice_point={snap['is_ice_point']}")
    if snap.get("reason"):
        print(f"   短路原因: {snap['reason']} — 冰点收盘连续第 2 日, 周末休市第 2 日延续")
    ice = snap["is_ice_point"]

    # ---- 昨日深度池: 0 只 → 无 Top1 铁律复核 ----
    yday = json.load(open(YDAY_JSON))
    print(f"\n=== 昨日 (10-31 周六) 深度池: {yday['pool_size']} 只 → 无 Top1 铁律复核 ===")
    print("   10-31 候选池 0 只 (周六非交易日 + 10-30 报告空表), 无推荐即无标的可判「当日胜出+正盈利」")

    # ---- 最后有效池 (10-29, 4 只) 周日快照零变动复核 ----
    last = json.load(open(LAST_POOL_JSON))
    lpool = sorted(last.get("results", []), key=lambda r: -r["total"])
    yrev = {r["code"]: r for r in (yday.get("last_pool_review", {}).get("results") or [])}
    codes = [r["code"] for r in lpool]
    q = tencent_quotes(codes)
    review = []
    n_unchanged = 0
    for r in lpool:
        px, chg, ts = q.get(r["code"], (None, None, ""))
        stop = r.get("stop")
        industry, skey = SECTOR_MAP.get(r["code"], (None, None))
        sec = sector_stats.get(skey, {}) if skey else {}
        sec_wr = (f"{sec.get('win_rate'):.0f}% ({sec.get('win_count')}/{sec.get('count')})"
                  if sec else "无记录(冷启动)")
        y = yrev.get(r["code"], {})
        same = (px is not None and y.get("close") is not None and abs(px - y["close"]) < 0.005
                and ts[:8] == "20261030")
        if same:
            n_unchanged += 1
        review.append({"code": r["code"], "name": r["name"], "total": r["total"],
                       "rating": r["rating"], "stop": stop,
                       "industry": industry, "sector_stat_key": skey,
                       "sector_win_rate": sec_wr,
                       "close": px, "chg_pct": chg, "quote_ts": ts,
                       "beat_mkt": (chg is not None and chg > MK_AVG),
                       "beat_sh": (chg is not None and chg > SH_CLOSE),
                       "stop_broken": (stop is not None and px is not None and px < stop),
                       "unchanged_vs_sat": same})
    review.sort(key=lambda x: (x["chg_pct"] if x["chg_pct"] is not None else -99), reverse=True)
    print(f"\n=== 最后有效池 (10-29) 周日快照零变动复核 (基准 {BASE_DATE} 周五收盘) ===")
    for i, r in enumerate(review, 1):
        ts = r['quote_ts'][:8]
        stop_mark = ("🔴收%.2f破止损%.2f" % (r['close'], r['stop'])) if r['stop_broken'] else "止损未破"
        same_mark = "✔与周六记录零变动" if r['unchanged_vs_sat'] else "⚠️与周六记录有出入"
        print(f"{i}. {r['code']} {r['name']} 深度{r['total']}{r['rating']} "
              f"| 10-30 收盘 {r['chg_pct']:+.2f}% ({'✅胜大盘均' if r['beat_mkt'] else '❌弱于大盘均'}) "
              f"{stop_mark} | 板块[{r['sector_stat_key'] or '冷启动'}]{r['sector_win_rate']} | 快照日 {ts} {same_mark}")
    n_beat = sum(1 for r in review if r["beat_mkt"])
    n_pos = sum(1 for r in review if (r["chg_pct"] or 0) > 0)
    avg_chg = sum(r["chg_pct"] for r in review) / len(review) if review else 0
    print(f"正盈利: {n_pos}/{len(review)} (铁律全灭) | 胜大盘均({MK_AVG}%): {n_beat}/{len(review)} "
          f"| 胜上证({SH_CLOSE}%): {sum(1 for r in review if r['beat_sh'])}/{len(review)} "
          f"| 池均值 {avg_chg:+.2f}% → 超额(上证) {avg_chg-SH_CLOSE:+.2f}pp "
          f"| 周日 vs 周六零变动 {n_unchanged}/{len(review)}")
    lrec = last.get("recommend") or {}
    print(f"🏁 最后有效 Top1: {lrec.get('code')} {lrec.get('name')} (10-29 深度 {lrec.get('total')} {lrec.get('rating')}, "
          f"东财 20261029ZZ gid=1811) — 10-29 破软止损 10.71 后 10-30 收 10.00 连续 2 日领跌, "
          f"止损纪律已执行, 卖出腿归 daily_v24_sell (非本任务范围)")

    # ---- 结论 ----
    print("\n=== 结论 ===")
    if pool:
        print(f"候选池 {len(pool)} 只 (未预期分支, 今日应空池)")
    print(f"🏁 最值得购买: 无 (0 推荐 — 11-01 周日非交易日 + 候选池 0 只 + 冰点守卫 is_ice_point={ice})")
    print("   东财组合 20261101ZZ: 不创建 (0 推荐无标的可入组 + 非交易日; 先例 10-27/10-28/10-30/10-31 → 无东财污染)")
    print("   20261029ZZ gid=1811 保留 (创维数字止损纪律记录, 组不撤仅记录)")
    print("   空仓过周末第 2 日 (周五零隔周末敞口, 持仓 0 只), 全周敞口仅 10-28 一晚 (批 7 已结算)")
    print("   周一 11-02 08:30 盘前恢复四关铁律全量评分 (≥增持 + 正盈利 + 胜出 + 未破止损 + 守卫放行)")
    print("   修复窗口先例: 10-28 V 型修复 20→58→75, 冰点第 2 日后修复日可放行 — 情绪回 30+ 断点 + 进攻主线为信号")
    print("   周一遗留关注: 快照 09:00 链 day6 预防最后窗口 · T+1 复核无对象 (周五池 0 只) · ⑩-h 追高池第 3 样本风险自查")

    with open(OUT_JSON, "w") as f:
        json.dump({"date": TODAY, "base_date": BASE_DATE,
                   "report": USED_REPORT, "report_today_exists": has_today,
                   "report_size": sz, "report_mtime": mt,
                   "trading_day": False,
                   "generated": time.strftime("%H:%M:%S"),
                   "sentiment_snap": SNAP, "mk_avg": MK_AVG, "sh_close_pct": SH_CLOSE,
                   "pool_size": len(pool), "guard_ice": ice,
                   "guard_reason": snap.get("reason"),
                   "yesterday_pool_size": yday["pool_size"],
                   "overall_win_rate": overall_wr, "total_records": n_rec,
                   "sector_count": len(sector_stats),
                   "last_pool_review": {"pool_date": "2026-10-29", "verified_on": TODAY,
                                        "base_date": BASE_DATE,
                                        "n_beat_mkt": n_beat, "n_positive": n_pos,
                                        "n_unchanged_vs_sat": n_unchanged,
                                        "pool_avg_chg": round(avg_chg, 2),
                                        "results": review},
                   "recommend": None,
                   "eastmoney": ("skipped: 0 推荐 (周日非交易日 + 冰点守卫, 不创建 20261101ZZ; "
                                 "20261029ZZ gid=1811 保留)")},
                  f, ensure_ascii=False, indent=1)
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()

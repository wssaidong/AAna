#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-11-16 (周一交易日盘前 08:3x) — 情绪 30 冰点 · 建议仓位 10% · 停止交易 · 池 0 只 · 守卫短路日
当日报告 = reports/2026-11-16-选股报告.md (11-16 08:02 盘前版, 涨跌幅=昨收=11-13 周五收盘口径)
候选池 = 当日报告 Top10 表 → **0 只** (表体空, 原始数据行 0; 情绪 30 冰点/仓位 10%/交易建议 ⚠️停止交易,
         报告自带"今日无明显回调机会, 关注明日开盘"; 快照涨停 38/跌停 4/-1.66% 与 11-13 盘后档逐字一致
         = 正确的 11-13 收盘残留口径, 非异常; 另披露: 热点板块"数据获取中" + 热点主线表标注"2026年4月"
         陈旧静态文案 + agents/premarket_agent.py 缺失致盘前 agent cron 持续报错 — 数据链缺失迹象)
铁律: 最值得购买者需基准交易日 11-13 当日胜出 (强于四均+上证) + 正盈利 + 深度评级 ≥增持(65) + 未破止损
      + 守卫放行 → 今日池 0 只 + 冰点守卫双口径短路 (快照 30 冰点 + live ths 盘前=11-13 收盘口径)
      → **0 推荐 → 不创建东财 20261116ZZ 组合** (先例: 11-13/11-14/11-15 守卫短路日不建组)
昨日 (11-13) 复核: 早盘腿 AM 池 0 只 (deep_analysis_20261113.json pool_size=0, recommend=null) →
      无 T+1 复核对象; 尾盘腿 11-13 14:46 尾盘报告"今日无符合条件的尾盘买入机会" → 无池 — 两腿均 N/A
信息产品 T+1 状态 (透明度披露, 非推荐池): 09:38 重跑版 Top10 = 东财 gid=1991 组, T+0 终局判决已于
      11-14/11-15 以 11-13 收盘执行 (胜四均 9/10 · 胜上证 5/10 · 正盈利 3/10 · 均值 -0.29%);
      今日盘前未开盘, 腾讯快照=11-13 收盘价无新信息 → T+1 判决推迟至 11-16 收盘后 (盘后战报口径)
Kimi: 本机无 kimi CLI / moonshot key (连续第 33 日) — 由 AAna 引擎 + LLM 定性层执行
东财: 0 推荐日不同步; groups.json 只读预检 20261116* 占用 (预期无)
"""
import sys, os, json, re, time
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, '/Users/cai/code/AAna/scripts')

TODAY = "2026-11-16"
BASE_DATE = "2026-11-13"   # K 线末日 / 昨收基准 (11-13 周五收盘, 最后交易日)
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
TODAY_REPORT = os.path.join(REPORT_DIR, f"{TODAY}-选股报告.md")  # 今日 08:02 盘前版
OUT_JSON = os.path.expanduser(f"~/code/AAna/data/deep_analysis_{TODAY.replace('-', '')}.json")
YDAY_AM_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_20261113.json")
YDAY_PM_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_pm_20261113.json")  # 预期不存在 (11-13 尾盘无机会)
MK_FOUR_AVG = -2.06   # 11-13 收盘四均 (复盘报告 17:00 口径: 上证-0.59/深成-2.05/创业板-3.32/科创50-2.30)
SH_CLOSE = -0.59      # 上证 11-13 收盘
SNAP = {"score": 30, "label": "冰点", "zt_count": 38, "dt_count": 4, "position": 0.10}
RUN_ID = "01a1e1c3-1b64-7337-a000-16ba521bc79f"
GROUPS_FILE = os.path.expanduser(
    "~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json")

# 信息产品 gid=1991 组 (09:38 重跑版, 11-14/11-15 已 T+0 判决) — 仅快照核对价格口径用
GID1991_CODES = ["002050", "002181", "002714", "002979", "601689",
                 "603019", "603131", "603179", "603662", "603667"]
GID1991_T0 = {"n_beat_four": 9, "n_beat_sh": 5, "n_positive": 3, "mean_chg": -0.29,
              "judged_on": "2026-11-13"}


def parse_top10_full(text):
    """解析 '🏆 重点关注 Top 10' 表格 (口径同 deep_analysis_20261113)。"""
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


def raw_row_count(text):
    """双重校验: 表区间内含 6 位代码的数据行原始计数 (防解析器误判, 10-28 口径)。
    区间截至下一个任意级别标题 (##/###) — 11-13 踩坑: 只截 ### 会把后续基金推荐表 9 行误计入。"""
    m = re.search(r'重点关注 Top 10(.*?)(?=\n#{2,3} |\Z)', text, re.S)
    return [l for l in (m.group(1) if m else "").split("\n")
            if l.strip().startswith("|") and re.search(r'\d{6}', l)
            and not l.strip().startswith("|:")]


def guard_check():
    """P0 冰点守卫 (单一真源 check_ice_point_guard)。盘前未开盘: live 源 (ths) = 11-13 收盘口径,
    与报告快照 30 冰点互为双口径。"""
    from aana_afternoon_screen import check_ice_point_guard
    live = None
    try:
        live = check_ice_point_guard()
    except Exception as e:
        print(f"  live 情绪源异常(盘前未开盘): {e}")
    snap = check_ice_point_guard(sent={"score": SNAP["score"], "label": SNAP["label"],
                                       "zt_count": SNAP["zt_count"], "dt_count": SNAP["dt_count"]})
    return live, snap


def tencent_quotes(codes):
    """腾讯实时快照: 盘前=昨收(11-13 收盘)口径。返回 {code: (现价, 涨跌幅%, 快照时间戳, 昨收)}"""
    import requests
    syms = ",".join(("sh" if c.startswith(("6", "9")) else "sz") + c for c in codes)
    r = requests.get(f"https://qt.gtimg.cn/q={syms}", timeout=10,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.encoding = "gbk"
    out = {}
    for m in re.finditer(r'v_(?:sh|sz)(\d{6})="([^"]+)"', r.text):
        p = m.group(2).split("~")
        try:
            out[m.group(1)] = (float(p[3]), float(p[32]), p[30], float(p[4]))
        except (ValueError, IndexError):
            continue
    return out


def groups_occupancy():
    """东财 groups.json 只读预检: 20261116* 占用 (预期无 — 0 推荐日不建组)。"""
    try:
        with open(GROUPS_FILE) as f:
            hist = json.load(f)
        hits = {k: v.get("gid") for k, v in hist.items() if k.startswith("20261116")}
        latest = max((int(v.get("gid", 0)) for v in hist.values()
                      if str(v.get("gid", "")).isdigit()), default=None)
        return hits, latest, len(hist)
    except Exception as e:
        return {"error": str(e)[:60]}, None, 0


def main():
    print("=" * 78)
    print(f"AAna 深度分析 — {TODAY} (周一交易日盘前, 数据基准 {BASE_DATE} 收盘)")
    print(f"Run: autopilot ca411dd3 深度分析 {RUN_ID}")
    print("=" * 78)

    # ---- 报告确认 (autopilot 强制: 打印报告名称防错) ----
    sz = os.path.getsize(TODAY_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(TODAY_REPORT)))
    print(f"📄 当日报告: {TODAY_REPORT}")
    print(f"   → 存在 | 大小: {sz} 字节 | 修改: {mt} (今日 08:02 盘前版, '涨跌幅'=昨收=11-13 收盘口径)")
    text = open(TODAY_REPORT).read()
    pool = parse_top10_full(text)
    raws = raw_row_count(text)
    print(f"   当日 Top10 表: {len(pool)} 只 (原始数据行 {len(raws)} 行) → 候选池 = {len(pool)} 只")
    print(f"   报告快照 (= 11-13 周五收盘/早盘档口径): 情绪{SNAP['score']}({SNAP['label']}) "
          f"仓位{SNAP['position']*100:.0f}% 涨停{SNAP['zt_count']}/跌停{SNAP['dt_count']} "
          f"上证{SH_CLOSE:+.2f}% 收3634.35 交易建议⚠️停止交易")
    print("   ⚠️ 报告异常披露: ① '热点板块: 数据获取中' = 08:02 生成链数据缺失迹象; "
          "② 热点主线表标注「2026年4月」为陈旧静态文案 (AI算力/人形机器人/半导体设备 非当日热点); "
          "③ agents/premarket_agent.py 缺失, 盘前 agent cron 持续报错; "
          "④ 快照'大盘平均 -1.66%'/涨停38/跌停4 与 11-13 盘后档逐字一致 = 11-13 收盘残留, 口径正常非异常")
    print("   链路状态: 11-12 盘前 80 亢奋被开盘证伪 → 11-12 14:45 冰点守卫首次实战拦截 → 11-13 全日冰点延续 "
          "(AM 池 0/尾盘无机会/T+0 信息产品均值 -0.29%) → 今晨 08:02 报告情绪 30 冰点延续, Top10 空表 "
          "— 守卫语境一致, 非孤立信号")

    # ---- 胜率库 / 调参披露 ----
    with open(os.path.expanduser("~/code/AAna/data/rec_tuning.json")) as f:
        rt = json.load(f)
    sector_stats = rt.get("sector_stats", {})
    print(f"\n📊 板块胜率库 (rec_optimizer 口径, generated_at {rt.get('generated_at')}): "
          f"{len(sector_stats)} 板块 | 整体胜率 {rt.get('overall_win_rate'):.1f}% ({rt.get('total_records')} 笔)")
    with open(os.path.expanduser("~/code/AAna/data/next_day_strategy.json")) as f:
        nds = json.load(f)
    weak_l = nds.get("weak_sectors", [])
    print(f"   调参披露 (next_day_strategy {nds.get('generated_at')}): v24 阈值 {nds.get('score_threshold')} | "
          f"cold_sectors {len(nds.get('cold_sectors', []))} 个 | weak_sectors {len(weak_l)} 个 "
          f"({'/'.join(weak_l[:6])}{'…' if len(weak_l) > 6 else ''})")

    # ---- 冰点守卫 (双口径) ----
    live, snap = guard_check()
    print(f"\n🛡 P0 冰点守卫: 快照口径 情绪{snap['sentiment_score']}({snap['sentiment_label']}) "
          f"仓位{snap.get('position_ratio', SNAP['position'])*100:.0f}% is_ice_point={snap['is_ice_point']}")
    if snap.get("reason"):
        print(f"   短路原因: {snap['reason']}")
    if live:
        print(f"   live 口径 情绪{live['sentiment_score']}({live['sentiment_label']}) "
              f"is_ice_point={live['is_ice_point']} (ths 源盘前=11-13 收盘口径)")
    ice = snap["is_ice_point"] and (live["is_ice_point"] if live else True)

    # ---- 昨日 (11-13) 池复核: 两腿均无池 ----
    am_pool_size = None
    if os.path.exists(YDAY_AM_JSON):
        with open(YDAY_AM_JSON) as f:
            yday = json.load(f)
        am_pool_size = yday.get("pool_size")
    pm_exists = os.path.exists(YDAY_PM_JSON)
    print(f"\n=== 昨日 (11-13) 复核范围 ===")
    print(f"   早盘腿: 11-13 盘前深度池 {am_pool_size} 只 (deep_analysis_20261113.json pool_size, "
          f"recommend=null) → 无 T+1 复核对象 — 交易日盘前池空 N/A 第 2 日")
    print(f"   尾盘腿: {'存在 (异常, 预期拦截无池)' if pm_exists else '11-13 14:46 尾盘报告「今日无符合条件的尾盘买入机会」→ 无推荐池, deep_analysis_pm_20261113.json 不存在, N/A'}")

    # ---- 信息产品 gid=1991: 盘前快照口径核对 (T+1 判决待今收) ----
    q = tencent_quotes(GID1991_CODES)
    ts_set = {v[2][:8] for v in q.values() if v[2]}
    print(f"\n=== 信息产品 gid=1991 组盘前快照核对 (透明度披露, 非推荐池) ===")
    print(f"    T+0 终局判决已于 11-14/11-15 以 11-13 收盘执行: 胜四均 {GID1991_T0['n_beat_four']}/10 · "
          f"胜上证 {GID1991_T0['n_beat_sh']}/10 · 正盈利 {GID1991_T0['n_positive']}/10 · "
          f"均值 {GID1991_T0['mean_chg']:+.2f}% (judged_on {GID1991_T0['judged_on']})")
    print(f"    盘前腾讯快照 {len(q)}/10 只, 时间戳 {sorted(ts_set) if ts_set else 'N/A'} "
          f"(盘前未开盘 = 11-13 收盘价, 无新信息) → T+1 判决推迟至 11-16 收盘后 (盘后战报口径)")

    # ---- 逐股深度评分: 池 0 只 → 无评分对象 ----
    results = []
    print(f"\n=== 逐股深度评分 (技术50%+基本面30%+估值20%): 池 {len(pool)} 只 → 无评分对象 ===")

    # 铁律合成 (池空 → eligible 空; 守卫短路同样 0 推荐)
    positive = [r for r in results if (r.get("chg_pct") or 0) > 0]
    eligible = [r for r in results
                if (r.get("chg_pct") or 0) > 0 and r.get("beat_mkt")
                and r["total"] >= 65 and not r.get("stop_broken") and not ice]
    recommend = eligible[0] if eligible else None

    # ---- 东财 groups 只读预检 ----
    occ, latest_gid, n_groups = groups_occupancy()
    print(f"\n📁 东财 groups.json 只读预检: 共 {n_groups} 组 | 最新 gid {latest_gid} | "
          f"20261116* 占用: {occ if occ else '无 (0 推荐日不建组, 与 11-13/11-14/11-15 先例一致)'}")

    with open(OUT_JSON, "w") as f:
        json.dump({"date": TODAY, "base_date": BASE_DATE, "report": TODAY_REPORT,
                   "report_size": sz, "report_mtime": mt,
                   "trading_day": True, "session": "pre_market",
                   "generated": time.strftime("%H:%M:%S"),
                   "sentiment_snap": SNAP, "mk_four_avg_close": MK_FOUR_AVG,
                   "sh_close_pct": SH_CLOSE,
                   "pool_size": len(pool), "guard_ice": ice,
                   "guard_reason": snap.get("reason"),
                   "guard_live": ({"score": live["sentiment_score"], "label": live["sentiment_label"],
                                   "is_ice_point": live["is_ice_point"]} if live else None),
                   "run_id": RUN_ID,
                   "report_anomalies": ["热点板块=数据获取中 (08:02 生成链数据缺失迹象)",
                                        "热点主线表标注「2026年4月」为陈旧静态文案",
                                        "agents/premarket_agent.py 缺失, 盘前 agent cron 报错"],
                   "overall_win_rate": rt.get("overall_win_rate"),
                   "total_records": rt.get("total_records"),
                   "sector_count": len(sector_stats),
                   "rec_tuning_generated_at": rt.get("generated_at"),
                   "nds_tuning": {"score_threshold": nds.get("score_threshold"),
                                  "cold_sectors": nds.get("cold_sectors", []),
                                  "weak_sectors": weak_l},
                   "yesterday_review": {
                       "am_pool_size_1113": am_pool_size,
                       "am_leg": f"N/A — 11-13 盘前池 {am_pool_size} 只, 无 T+1 复核对象 (交易日盘前池空 N/A 第 2 日)",
                       "pm_leg": "N/A — 11-13 14:46 尾盘「今日无符合条件的尾盘买入机会」, 无推荐池"},
                   "gid1991_info_product": {
                       "t0_verdict": GID1991_T0,
                       "pre_open_snapshot_n": len(q),
                       "snapshot_ts": sorted(ts_set),
                       "t1_due": "2026-11-16 收盘后 (盘后战报口径)"},
                   "recommend": None, "eligible_pool": [], "results": results,
                   "eastmoney_sync": {"action": "skip",
                                      "reason": "0 推荐 (池 0 只 + 冰点守卫双口径短路) → 不创建 20261116ZZ",
                                      "groups_20261116_occupied": occ}}, f, ensure_ascii=False, indent=1)

    print(f"\n=== 深度排名: 池 0 只, 无排名 ===")
    print(f"正盈利: {len(positive)}/{len(results)} | 强于四均({MK_FOUR_AVG:+.2f}%): 0/0")
    print(f"铁律合格池 (≥增持65+正盈利+胜出+未破止损+守卫放行): []")
    if ice:
        print(f"\n🏁 0 推荐 → 不创建东财组合 {TODAY.replace('-', '')}ZZ "
              f"(P0 冰点守卫短路: 情绪{snap['sentiment_score']}{snap['sentiment_label']}/"
              f"仓位{snap.get('position_ratio', SNAP['position'])*100:.0f}%/{snap.get('reason') or '⚠️停止交易'}; "
              f"且当日报告 Top10 表 0 只, 无可分析标的 — 双重独立归因)")
    else:
        print(f"\n🏁 0 推荐 → 不创建东财组合 (当日报告 Top10 表 0 只, 无标的满足铁律)")
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()

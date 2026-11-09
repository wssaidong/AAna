#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-11-09 (周一交易日盘前 08:3x) — 0 推荐 · 冰点第 3 日盘前口径 · 周一剧本检查日
当日报告 = reports/2026-11-09-选股报告.md (11-09 08:02 盘前版, 当日报告即今日报告 —
           区别于周末"最新即当日"口径; 自 11-06 以来首个当日新报告)
核心事实: Top10 表 0 只 (报告快照情绪 20 冰点 / 大盘平均 -2.27% / 仓位 10% / ⚠️停止交易,
          快照 = 11-06 周五收盘冻结口径, 盘前副标题明示"涨跌幅=昨收涨跌幅")
         → 候选池空 → 无标的可评分 → 0 推荐 → 不创建东财组合 20261109ZZ
铁律: 0 推荐 → 不创建 20261109ZZ (0推荐铁律 第 9 例, 先例 10-27/10-28/10-30/10-31/
      11-01/11-06盘前gid1896退役/11-07/11-08 → 无东财污染)
昨日 (11-08 周日) 深度池 = 0 只 → 无 Top1 可 T+1 复核; 转对最后有效池 (11-06 早盘池 3 只)
      做周一盘前冻结重放复核 (盘前 08:3x 腾讯快照仍 = 11-06 收盘定格, 与 11-07 T+1 复核/
      11-08 周日重放逐股比对, 预期零变动 — 连续第 3 日冻结校验; 真实新数据点 = 今日收盘,
      由 17:03 复盘链完成 T+2 定论)
周一剧本盘前检查 (昨日三剧本): 盘前情绪续 20 冰点 (live ths 源 + 报告快照双口径), V 型修复
      信号 (情绪回 30+ 断点) 盘前未现 → 剧本③ 守卫短路盘前口径领先; 但冰点第 2 日后分叉
      的定论在盘中/尾盘 (14:45 尾盘守卫) 与收盘 (17:03 复盘), 盘前不下最终结论
Kimi: 本机无 kimi CLI / moonshot key (11-09 再复核: which kimi 无, env 无, ~/.kimi 不存在)
      — 连续第 25 日由 AAna 深度评分引擎 + LLM 定性层执行
链路语境: 11-04 亢奋 85 → 11-05 回暖 73 → 11-06 冰点 20 (隔日塌方第 3 次) → 周末双日 20 续;
      周六复盘 (83da58e): 守卫放行批 4/4 亏损 (-¥827, 最近批 0胜10负) vs 冰点短路日零亏损;
      昨日 (13b096f) 透传周一若修复放行 = 第 5 样本, 需 baseline 涨幅约束自查 — 今日盘前
      未现修复, 暂不触发放行自查, 待盘中验证
"""
import sys, os, json, re, time
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, '/Users/cai/code/AAna/scripts')

TODAY = "2026-11-09"
BASE_DATE = "2026-11-06"   # K 线/快照末端 (11-06 周五收盘冻结; 今日盘前未开盘, 无新数据点)
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
TODAY_REPORT = os.path.join(REPORT_DIR, f"{TODAY}-选股报告.md")  # 今日 08:02 盘前版 (当日报告)
OUT_JSON = os.path.expanduser(f"~/code/AAna/data/deep_analysis_{TODAY.replace('-','')}.json")
YDAY_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_20261108.json")
MK_AVG = -2.27            # 报告快照: 大盘平均涨跌 -2.27% (11-06 收盘基准, 盘前冻结)
SH_CLOSE = -1.10          # 上证 -1.10% 收 3649.18 (11-06 收盘基准)
IDX_AVG = -2.56           # 四大核心指数平均 (11-06 盘后战报口径, 今日报告沿用同一基准)
SNAP = {"score": 20, "label": "冰点", "zt_count": 33, "dt_count": 3, "position": 0.10}
RUN_ID = "01a1bdb6-cd44-73b1-afad-200226b7d702"

# 最后有效池 = 11-06 早盘深度池 3 只 (11-07 T+1 复核 + 11-08 周日重放均已完成;
# 今日周一盘前第 3 次冻结重放, 预期零变动)
LAST_POOL = [
    {"code": "600633", "name": "浙数文化", "total": 80.0, "rating": "买入", "stop": 11.01,
     "entry": 11.35, "group": "20261106ZZ(gid=1901)", "rank": 1},
    {"code": "603258", "name": "电魂网络", "total": 69.3, "rating": "增持", "stop": 16.34,
     "entry": 16.85, "group": None, "rank": 2},
    {"code": "600506", "name": "统一股份", "total": 47.7, "rating": "减持", "stop": 18.43,
     "entry": 19.0, "group": None, "rank": 3},
]
LAST_RECOMMEND = "600633"  # 11-06 最值得购买 → 东财 20261106ZZ

# 板块胜率键 (11-06~11-08 深度分析同口径; 周末零回归, gen 11-06T20:00)
SECTOR_KEYS = {
    "600633": ("移动互联网服务", [("传媒", "邻近键-传媒(数字文化)"), ("影视动漫", "警戒键-影视动漫(weak)")]),
    "603258": ("移动互联网服务", [("传媒", "邻近键-传媒(网络游戏)"), ("影视动漫", "警戒键-影视动漫(weak 在列)")]),
    "600506": (None, [("chem", "邻近键-化工大类(冷样本)"), ("涂料油漆油墨制造", "邻近键-化学制品同类(1/1)")]),
}


def parse_top10_full(text):
    """解析 '🏆 重点关注 Top 10' 表格 (口径同 10-27~11-08)"""
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


def tencent_quotes(codes):
    """腾讯快照: 周一盘前=周五(11-06)收盘冻结口径。返回 {code: (现价, 涨跌幅%, 快照时间戳, 昨收)}"""
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


def guard_check():
    """P0 冰点守卫 (单一真源 check_ice_point_guard)。周一盘前 live 源 (ths) 无新快照,
    仍以 11-06 收盘口径计算; 快照口径 = 今日报告快照 20 冰点"""
    from aana_afternoon_screen import check_ice_point_guard
    live = None
    try:
        live = check_ice_point_guard()
    except Exception as e:
        print(f"  live 情绪源异常(盘前): {e}")
    snap = check_ice_point_guard(sent={"score": SNAP["score"], "label": SNAP["label"],
                                       "zt_count": SNAP["zt_count"], "dt_count": SNAP["dt_count"]})
    return live, snap


def load_sector_stats():
    with open(os.path.expanduser("~/code/AAna/data/rec_tuning.json")) as f:
        rt = json.load(f)
    return rt.get("sector_stats", {}), rt.get("overall_win_rate"), rt.get("total_records"), rt.get("generated_at")


def load_nds():
    with open(os.path.expanduser("~/code/AAna/data/next_day_strategy.json")) as f:
        return json.load(f)


def frozen_review(pool, title, mk_avg):
    """周一盘前冻结重放: 11-06 收盘冻结快照 vs 昨日 (11-08 周日重放) 结果逐股比对 (第 3 日校验)"""
    q = tencent_quotes([r["code"] for r in pool])
    yday = {}
    try:
        with open(YDAY_JSON) as f:
            for r in json.load(f)["frozen_review"]["results"]:
                yday[r["code"]] = r
    except Exception as e:
        print(f"  ⚠️ 昨日 JSON 读取异常: {e}")
    review = []
    for r in pool:
        px, chg, ts, prev = q.get(r["code"], (None, None, "", None))
        y = yday.get(r["code"], {})
        review.append({**r, "close": px, "prev_close": prev, "chg_pct": chg, "quote_ts": ts,
                       "yday_close": y.get("close"), "yday_chg": y.get("chg_pct"),
                       "unchanged": (px is not None and y.get("close") is not None
                                     and abs(px - y["close"]) < 1e-6),
                       "beat_mkt": (chg is not None and chg > mk_avg),
                       "pos": (chg is not None and chg > 0),
                       "pnl_vs_entry": (round((px / r["entry"] - 1) * 100, 2) if px else None)})
    review.sort(key=lambda x: (x["chg_pct"] if x["chg_pct"] is not None else -99), reverse=True)
    print(f"\n=== {title} (11-06 收盘冻结, 腾讯快照口径; 基准=大盘平均 {mk_avg:+.2f}%) ===")
    for i, r in enumerate(review, 1):
        ts = r['quote_ts'][:8]
        uc = '🔒零变动' if r['unchanged'] else '⚠️与昨快照有差异'
        print(f"{i}. {r['code']} {r['name']} 深度{r['total']}{r['rating']}"
              f"{' [11-06最值得购买→' + r['group'] + ']' if r['code'] == LAST_RECOMMEND else ''}"
              f" | 11-06 实收 {r['chg_pct']:+.2f}% (昨重放 {r['yday_chg'] if r['yday_chg'] is None else format(r['yday_chg'], '+.2f') + '%'})"
              f" {uc}"
              f"({'✅胜大盘(' + format(mk_avg, '+.2f') + '%)' if r['beat_mkt'] else '❌弱于大盘'})"
              f"{' ✅正盈利' if r['pos'] else ' ❌负'} | vs 建仓参考 {r['entry']} → {r['pnl_vs_entry']:+.2f}%"
              f" | 快照日 {ts}"
              f"{' 🔴破软止损' + str(r['stop']) if (r['stop'] and (r['close'] or 0) < r['stop']) else ''}")
    n_beat = sum(1 for r in review if r["beat_mkt"])
    n_pos = sum(1 for r in review if r["pos"])
    n_unch = sum(1 for r in review if r["unchanged"])
    print(f"胜大盘({mk_avg:+.2f}%): {n_beat}/{len(review)} | 正盈利: {n_pos}/{len(review)} "
          f"| 快照零变动: {n_unch}/{len(review)} (周一盘前休市预期, 连续第 3 日冻结)")
    return review


def main():
    print("=" * 78)
    print(f"AAna 深度分析 — {TODAY} (周一交易日盘前, 数据基准 {BASE_DATE} 收盘冻结)")
    print(f"Run: autopilot ca411dd3 深度分析 {RUN_ID}")
    print("=" * 78)

    # ---- 报告确认 (autopilot 强制: 打印报告名称防错) ----
    sz = os.path.getsize(TODAY_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(TODAY_REPORT)))
    print(f"📄 当日报告: {TODAY_REPORT}")
    print(f"   → 存在 | 大小: {sz} 字节 | 修改: {mt}")
    print("   (今日 08:02 盘前版 — 当日报告即今日报告, 自 11-06 以来首个当日新报告;")
    print("    盘前副标题明示 '涨跌幅'=昨收涨跌幅, 即 11-06 收盘冻结口径)")
    text = open(TODAY_REPORT).read()
    pool = parse_top10_full(text)
    pm_today = os.path.join(REPORT_DIR, f"{TODAY}-尾盘选股.md")
    pm_exists = os.path.exists(pm_today)
    pm_zero_prev = "今日无符合条件的尾盘买入机会" in open(
        os.path.join(REPORT_DIR, "2026-11-06-尾盘选股.md")).read()
    snap_sent = (f"情绪{SNAP['score']}({SNAP['label']}) 仓位{SNAP['position']*100:.0f}% "
                 f"大盘平均{MK_AVG:+.2f}% 涨停{SNAP['zt_count']}/跌停{SNAP['dt_count']} "
                 f"上证{SH_CLOSE:+.2f}% 收3649.18 交易建议⚠️停止交易")
    print(f"   当日 Top10 表: {len(pool)} 只 (表体仅表头·冰点守卫短路设计行为)")
    print(f"   尾盘腿: 11-09 尾盘选股 (14:46) 未生成 → 盘前无交叉验证;"
          f" 最近口径 11-06 尾盘选股 0 推荐{' (『今日无符合条件的尾盘买入机会』)' if pm_zero_prev else ' ⚠️表述异常'}")
    print(f"   报告快照 (= 11-06 周五收盘口径): {snap_sent}")
    print("   链路状态: 11-04 亢奋 85 → 11-05 回暖 73 → 11-06 冰点 20 → 周末双日 20 续 (冰点第 3 日盘前);")
    print("     周六复盘 (83da58e): 守卫放行批 4/4 亏损 (-¥827/占23.4%) vs 冰点短路日零亏损;")
    print("     空仓过周末后零隔夜敞口, 今日为冰点后分叉验证日")

    sector_stats, overall_wr, n_rec, rt_gen = load_sector_stats()
    print(f"📊 板块胜率库 (rec_optimizer 口径, generated_at {rt_gen}): {len(sector_stats)} 板块 | "
          f"整体胜率 {overall_wr:.1f}% ({n_rec} 笔) [盘前未回填 — 反馈档 15:00/16:05 未到, 预期内]")
    nds = load_nds()
    print(f"   调参披露 (next_day_strategy): v24 阈值 {nds.get('score_threshold')} "
          f"| cold_sectors {len(nds.get('cold_sectors', []))} 个 | weak_sectors {len(nds.get('weak_sectors', []))} 个")

    live, snap = guard_check()
    print(f"🛡 P0 冰点守卫: 快照口径 情绪{snap['sentiment_score']}({snap['sentiment_label']}) "
          f"仓位{snap['position_ratio']*100:.0f}% is_ice_point={snap['is_ice_point']}")
    if snap.get("reason"):
        print(f"   短路原因: {snap['reason']}")
    if live:
        print(f"   live 口径 情绪{live['sentiment_score']}({live['sentiment_label']}) "
              f"is_ice_point={live['is_ice_point']} (ths 源盘前仍为 11-06 收盘口径; 开盘后以 live 为准)")
    ice = snap["is_ice_point"] and (live["is_ice_point"] if live else True)

    # ---- 最后有效池 (11-06 早盘 3 只) 周一盘前冻结重放复核 (第 3 日) ----
    fr = frozen_review(LAST_POOL, "最后有效池 3 只周一盘前冻结重放复核 (11-06 早盘深度池; 11-07 T+1 + 11-08 重放已完成)", MK_AVG)
    a = next(r for r in fr if r["code"] == LAST_RECOMMEND)
    print(f"🏁 11-06 最值得购买 600633 浙数文化 铁律复核 (盘前冻结重放): 11-06 实收 {a['chg_pct']:+.2f}% "
          f"vs 大盘 {MK_AVG:+.2f}% → 超额 {a['chg_pct']-MK_AVG:+.2f}pp "
          f"{'✅ 当日胜出' if a['beat_mkt'] else '❌ 未胜出'}"
          f"{' + 正盈利 ✅' if a['pos'] else ' 但 ❌负盈利 (极冰点系统性回撤, 全池无幸免)'} "
          f"(vs 入场参考 {a['entry']} → {a['pnl_vs_entry']:+.2f}%; 软止损 {a['stop']} "
          f"{'🔴已破' if (a['close'] or 0) < a['stop'] else '未破'})")
    print("   ↳ 口径提示: 11-07 已完成同基准 T+1 复盘, 11-08/今日为冻结重放·零变动校验 (非新复核);")
    print("     真实新数据点 = 今日 11-09 收盘, 由 17:03 复盘链对 20261106ZZ (gid=1901) 做 T+2 定论;")
    print("     600633 止损 11.01 未破 (收 11.15) → 组合持仓纪律记录保留")

    # 板块胜率关联 (最后有效池板块键, 盘前零回归口径)
    print(f"\n=== 板块胜率关联 (11-06 池板块键, 11-06 晚回填后·周末+盘前零回归) ===")
    for r in fr:
        key, nears = SECTOR_KEYS[r["code"]]
        sec = sector_stats.get(key, {}) if key else {}
        wr = (f"{sec.get('win_rate'):.0f}% ({sec.get('win_count')}/{sec.get('count')})" if sec
              else "无记录(冷启动)")
        near_wr = ""
        for nk, nd in nears:
            ns = sector_stats.get(nk, {})
            if ns:
                near_wr += f" | {nd} {ns.get('win_rate'):.0f}% ({ns.get('win_count')}/{ns.get('count')})"
        print(f"   {r['code']} {r['name']} [{key or '无主键'}] {wr}{near_wr} "
              f"| 11-06 实收 {r['chg_pct']:+.2f}%")
    print("   ↳ 移动互联网服务键 50%(3/6) 维持; 板块≠个股, 冰点日系统性贝塔压倒板块阿尔法;")

    # ---- 周一剧本盘前检查 (昨日三剧本) ----
    print(f"\n=== 周一剧本盘前检查 (昨日 11-08 三剧本, 盘前口径) ===")
    print(f"   ① V 型修复剧本 (参照 10-30→11-02, 20→85): 盘前未现 — live/快照情绪均续 20 冰点,")
    print(f"      修复信号 (情绪回 30+ 断点 + 进攻性主线) 需盘中验证, 盘前不判死;")
    print(f"   ② 修复放行=第 5 样本风险自查: 未触发放行 (盘前池 0 只, 无 baseline 涨幅分布可查) —")
    print(f"      若盘中修复且尾盘放行建批, 自查项 (baseline 涨幅/弱势 6 板块重合/减半对照) 移交 14:45 尾盘腿;")
    print(f"   ③ 情绪续冰点 → 守卫继续短路不抢反弹: 盘前口径 ✅ 当前领先 (双口径 is_ice_point=True)。")

    # ---- 铁律合成 ----
    results = []
    with open(OUT_JSON, "w") as f:
        json.dump({"date": TODAY, "base_date": BASE_DATE, "report": TODAY_REPORT,
                   "report_size": sz, "report_mtime": mt,
                   "trading_day": True, "session": "pre_market",
                   "generated": time.strftime("%H:%M:%S"),
                   "sentiment_snap": SNAP, "mk_avg": MK_AVG, "sh_close_pct": SH_CLOSE,
                   "idx_avg": IDX_AVG, "pool_size": len(pool),
                   "pm_screen_today_exists": pm_exists, "pm_screen_zero_rec_prev": pm_zero_prev,
                   "guard_ice": ice,
                   "guard_reason": snap.get("reason"), "run_id": RUN_ID,
                   "overall_win_rate": overall_wr, "total_records": n_rec,
                   "sector_count": len(sector_stats), "rec_tuning_generated_at": rt_gen,
                   "nds_tuning": {"score_threshold": nds.get("score_threshold"),
                                  "cold_sectors": nds.get("cold_sectors"),
                                  "weak_sectors": nds.get("weak_sectors")},
                   "yday_deep_pool_size": 0,
                   "frozen_review": {"source": "11-06 早盘深度池 (最后有效池, 11-07 T+1 + 11-08 重放已完成)",
                                     "verified_on": BASE_DATE, "replay_day": 3,
                                     "recommend": LAST_RECOMMEND,
                                     "n_beat_mkt": sum(1 for r in fr if r["beat_mkt"]),
                                     "n_positive": sum(1 for r in fr if r["pos"]),
                                     "n_unchanged": sum(1 for r in fr if r["unchanged"]),
                                     "results": fr},
                   "recommend": None, "eligible_pool": [], "results": results}, f,
                  ensure_ascii=False, indent=1)

    print(f"\n=== 深度排名 (技术50%+基本面30%+估值20%) ===")
    print(f"   候选池 0 只 — 无可评分标的 (当日报告 Top10 空表 + 冰点守卫双口径短路)")
    print(f"\n🏁 0 推荐 → 不创建东财组合 {TODAY.replace('-','')}ZZ "
          f"(双重短路: ① 当日报告 0 推荐 (情绪 20 冰点/仓位 10%/⚠️停止交易) "
          f"② P0 冰点守卫 is_ice_point=True 快照+live 双口径; 0推荐铁律 第 9 例, "
          f"先例 10-27/10-28/10-30/10-31/11-01/11-06盘前/11-07/11-08)")
    print(f"   东财组现状: 20261106ZZ (gid=1901, 11-06 建, 1 只 600633) 保持不动 (止损 11.01 未破, "
          f"今日收盘 T+2 定论); 裸日期 20261106 (gid=1896 已退役) / 20261105 (gid=1891) 严禁触碰")
    print(f"   今日后续链路: 09:30 开盘 → 14:45 尾盘守卫 (冰点第 3 日是否修复定论点) → "
          f"17:03 复盘 (11-06 池 T+2 定论 + 周一剧本归档); 若尾盘修复放行建批 = 第 5 样本自查移交")
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()

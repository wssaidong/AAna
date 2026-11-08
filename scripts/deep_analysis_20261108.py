#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-11-08 (周日非交易日 08:3x) — 0 推荐 · 冰点空仓过周末第 2 日 · 周一 11-09 前瞻
当日报告 = reports/2026-11-06-选股报告.md (11-06 17:03 盘后版, 周末无新报告 → 最新即当日;
           周日 reports/ 无 2026-11-08-*.md, 11-07 亦零 md — 主链非交易日跳过, 11-07 复盘实证)
候选池 = 当日报告 Top10 表 0 只 (情绪 20 冰点 / 仓位 10% / ⚠️停止交易, 表体仅表头设计行为)
         + 11-06 尾盘选股 (14:46) 同 0 推荐 → 两腿双零, 与周六深度分析 (4552d6a) 同口径
铁律: 0 推荐 → 不创建东财组合 20261108ZZ (0推荐铁律; 先例 10-27/10-28/10-30/10-31/
      11-01/11-06盘前gid1896退役/11-07 → 今日第 8 例, 无东财污染)
昨日 (11-07 周六) 深度池 = 0 只 → 无 Top1 可 T+1 复核; 转对最后有效池 (11-06 早盘池 3 只)
      做周日快照零变动复核 (周日腾讯快照 = 11-06 周五收盘定格, 与昨日周六复核逐股比对,
      预期零变动 — 11-01 周日先例同构)
Kimi: 本机无 kimi CLI / moonshot key (11-08 复核: which kimi 无, env 无, ~/.kimi 不存在)
      — 连续第 24 日由 AAna 深度评分引擎 + LLM 定性层执行
链路语境: 11-04 亢奋 85 → 11-05 回暖 73 → 11-06 冰点 20 (隔日塌方第 3 次复现); 周六复盘
      (83da58e) 新结论: 守卫放行批 4/4 亏损 (-¥827, 最近批 0胜10负) vs 冰点短路日零亏损
      — 周一 11-09 若修复放行 = 该模式第 5 样本, 需 baseline 涨幅约束自查
周一前瞻: 冰点第 2 日后分叉 — 参照 10-30 冰点第2日→周末→11-02 V型修复 (20→85);
      修复信号 = 情绪回 30+ 断点 + 进攻性主线; 情绪续冰点则守卫继续短路不抢反弹
"""
import sys, os, json, re, time
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, '/Users/cai/code/AAna/scripts')

TODAY = "2026-11-08"
BASE_DATE = "2026-11-06"   # K 线/快照末日 (11-06 周五收盘, 周末冻结)
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
TODAY_REPORT = os.path.join(REPORT_DIR, f"{BASE_DATE}-选股报告.md")  # 周日无新报告 → 最近交易日盘后版
OUT_JSON = os.path.expanduser(f"~/code/AAna/data/deep_analysis_{TODAY.replace('-','')}.json")
YDAY_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_20261107.json")
MK_AVG = -2.27            # 报告快照: 大盘平均涨跌 -2.27% (11-06 收盘基准)
SH_CLOSE = -1.10          # 上证 -1.10% 收 3649.18 (11-06 收盘基准)
IDX_AVG = -2.56           # 四大核心指数平均 (盘后战报口径)
SNAP = {"score": 20, "label": "冰点", "zt_count": 33, "dt_count": 3, "position": 0.10}
RUN_ID = "01a1b890-676d-7b57-a271-44d6aaa064ca"

# 最后有效池 = 11-06 早盘深度池 3 只 (昨日已做 T+1 复核; 今日周日零变动复核, 预期与昨一致)
LAST_POOL = [
    {"code": "600633", "name": "浙数文化", "total": 80.0, "rating": "买入", "stop": 11.01,
     "entry": 11.35, "group": "20261106ZZ(gid=1901)", "rank": 1},
    {"code": "603258", "name": "电魂网络", "total": 69.3, "rating": "增持", "stop": 16.34,
     "entry": 16.85, "group": None, "rank": 2},
    {"code": "600506", "name": "统一股份", "total": 47.7, "rating": "减持", "stop": 18.43,
     "entry": 19.0, "group": None, "rank": 3},
]
LAST_RECOMMEND = "600633"  # 11-06 最值得购买 → 东财 20261106ZZ

# 板块胜率键 (11-06/11-07 深度分析同口径; 11-06 晚间反馈闭环回填后, 周末零回归)
SECTOR_KEYS = {
    "600633": ("移动互联网服务", [("传媒", "邻近键-传媒(数字文化)"), ("影视动漫", "警戒键-影视动漫(weak)")]),
    "603258": ("移动互联网服务", [("传媒", "邻近键-传媒(网络游戏)"), ("影视动漫", "警戒键-影视动漫(weak 在列)")]),
    "600506": (None, [("chem", "邻近键-化工大类(冷样本)"), ("涂料油漆油墨制造", "邻近键-化学制品同类(1/1)")]),
}


def parse_top10_full(text):
    """解析 '🏆 重点关注 Top 10' 表格 (口径同 10-27~11-06)"""
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
    """腾讯快照: 周日=周五(11-06)收盘冻结口径。返回 {code: (现价, 涨跌幅%, 快照时间戳, 昨收)}"""
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
    """P0 冰点守卫 (单一真源 check_ice_point_guard)。周日休市: live 源无新快照,
    以 11-06 收盘报告快照 20 冰点为判定口径"""
    from aana_afternoon_screen import check_ice_point_guard
    live = None
    try:
        live = check_ice_point_guard()
    except Exception as e:
        print(f"  live 情绪源异常(周日休市): {e}")
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
    """周日零变动复核: 11-06 收盘冻结快照 vs 昨日 (11-07) 复核结果逐股比对"""
    q = tencent_quotes([r["code"] for r in pool])
    yday = {}
    try:
        with open(YDAY_JSON) as f:
            for r in json.load(f)["yesterday_review"]["am_pool"]["results"]:
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
              f" | 11-06 实收 {r['chg_pct']:+.2f}% (昨复核 {r['yday_chg'] if r['yday_chg'] is None else format(r['yday_chg'], '+.2f') + '%'})"
              f" {uc}"
              f"({'✅胜大盘(' + format(mk_avg, '+.2f') + '%)' if r['beat_mkt'] else '❌弱于大盘'})"
              f"{' ✅正盈利' if r['pos'] else ' ❌负'} | vs 建仓参考 {r['entry']} → {r['pnl_vs_entry']:+.2f}%"
              f" | 快照日 {ts}"
              f"{' 🔴破软止损' + str(r['stop']) if (r['stop'] and (r['close'] or 0) < r['stop']) else ''}")
    n_beat = sum(1 for r in review if r["beat_mkt"])
    n_pos = sum(1 for r in review if r["pos"])
    n_unch = sum(1 for r in review if r["unchanged"])
    print(f"胜大盘({mk_avg:+.2f}%): {n_beat}/{len(review)} | 正盈利: {n_pos}/{len(review)} "
          f"| 快照零变动: {n_unch}/{len(review)} (周日休市预期)")
    return review


def main():
    print("=" * 78)
    print(f"AAna 深度分析 — {TODAY} (周日非交易日, 数据基准 {BASE_DATE} 收盘冻结)")
    print(f"Run: autopilot ca411dd3 深度分析 {RUN_ID}")
    print("=" * 78)

    # ---- 报告确认 (autopilot 强制: 打印报告名称防错) ----
    sz = os.path.getsize(TODAY_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(TODAY_REPORT)))
    print(f"📄 当日报告: {TODAY_REPORT}")
    print(f"   → 存在 | 大小: {sz} 字节 | 修改: {mt}")
    print("   (周日休市无新报告 → 当日报告 = 11-06 周五 17:03 盘后版, '涨跌幅'=11-06 收盘口径;")
    print("    周日 reports/ 无 2026-11-08-*.md, 11-07 亦零 md (主链非交易日跳过, 11-07 复盘实证))")
    text = open(TODAY_REPORT).read()
    pool = parse_top10_full(text)
    pm_text = open(os.path.join(REPORT_DIR, "2026-11-06-尾盘选股.md")).read()
    pm_zero = "今日无符合条件的尾盘买入机会" in pm_text
    snap_sent = (f"情绪{SNAP['score']}({SNAP['label']}) 仓位{SNAP['position']*100:.0f}% "
                 f"大盘平均{MK_AVG:+.2f}% 涨停{SNAP['zt_count']}/跌停{SNAP['dt_count']} "
                 f"上证{SH_CLOSE:+.2f}% 收3649.18 交易建议⚠️停止交易")
    print(f"   当日 Top10 表: {len(pool)} 只 (表体仅表头·冰点守卫短路设计行为)")
    print(f"   尾盘腿交叉验证: 11-06 尾盘选股 (14:46) 同为 0 推荐"
          f"{' (『今日无符合条件的尾盘买入机会』)' if pm_zero else ' ⚠️表述异常'}")
    print(f"   报告快照 (= 11-06 周五收盘口径): {snap_sent}")
    print("   链路状态: 11-04 亢奋 85 → 11-05 回暖 73 → 11-06 冰点 20 (隔日塌方第3次复现);")
    print("     周六复盘 (83da58e) 新结论: 守卫放行批 4/4 亏损 (-¥827/占23.4%) vs 冰点短路日零亏损 —")
    print("     守卫只挡冰点日, 放行日 T+1 竞价卖系统性负α, 升级 P1; 空仓过周末第 2 日零敞口")

    sector_stats, overall_wr, n_rec, rt_gen = load_sector_stats()
    print(f"📊 板块胜率库 (rec_optimizer 口径, generated_at {rt_gen}): {len(sector_stats)} 板块 | "
          f"整体胜率 {overall_wr:.1f}% ({n_rec} 笔) [与周六零回归 — 周末无 15:00/16:05 反馈档, 预期内]")
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
              f"is_ice_point={live['is_ice_point']} (周日休市, 披露用)")
    ice = snap["is_ice_point"]

    # ---- 最后有效池 (11-06 早盘 3 只) 周日零变动复核 (11-06 收盘冻结快照) ----
    fr = frozen_review(LAST_POOL, "最后有效池 3 只周日零变动复核 (11-06 早盘深度池; 昨日已完成 T+1 复盘)", MK_AVG)
    a = next(r for r in fr if r["code"] == LAST_RECOMMEND)
    print(f"🏁 11-06 最值得购买 600633 浙数文化 铁律复核 (周日冻结重放): 11-06 实收 {a['chg_pct']:+.2f}% "
          f"vs 大盘 {MK_AVG:+.2f}% → 超额 {a['chg_pct']-MK_AVG:+.2f}pp "
          f"{'✅ 当日胜出' if a['beat_mkt'] else '❌ 未胜出'}"
          f"{' + 正盈利 ✅' if a['pos'] else ' 但 ❌负盈利 (极冰点系统性回撤, 全池无幸免)'} "
          f"(vs 入场参考 {a['entry']} → {a['pnl_vs_entry']:+.2f}%; 软止损 {a['stop']} "
          f"{'🔴已破' if (a['close'] or 0) < a['stop'] else '未破'})")
    print("   ↳ 口径提示: 昨日 (11-07) T+1 复核已完成且为同一 11-06 收盘基准, 今日为冻结重放·零变动")
    print("     校验 (非新交易日复核); 600633 止损 11.01 未破 → 20261106ZZ (gid=1901) 持仓纪律记录保留")

    # 板块胜率关联 (最后有效池板块键, 周末零回归口径)
    print(f"\n=== 板块胜率关联 (11-06 池板块键, 11-06 晚间回填后·周末零回归) ===")
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
    print("   ↳ 移动互联网服务键 50%(3/6) 周末维持; 板块≠个股, 冰点日系统性贝塔压倒板块阿尔法;")

    # ---- 铁律合成 ----
    results = []
    with open(OUT_JSON, "w") as f:
        json.dump({"date": TODAY, "base_date": BASE_DATE, "report": TODAY_REPORT,
                   "report_size": sz, "report_mtime": mt,
                   "trading_day": False, "session": "weekend",
                   "generated": time.strftime("%H:%M:%S"),
                   "sentiment_snap": SNAP, "mk_avg": MK_AVG, "sh_close_pct": SH_CLOSE,
                   "idx_avg": IDX_AVG, "pool_size": len(pool),
                   "pm_screen_zero_rec": pm_zero, "guard_ice": ice,
                   "guard_reason": snap.get("reason"), "run_id": RUN_ID,
                   "overall_win_rate": overall_wr, "total_records": n_rec,
                   "sector_count": len(sector_stats), "rec_tuning_generated_at": rt_gen,
                   "nds_tuning": {"score_threshold": nds.get("score_threshold"),
                                  "cold_sectors": nds.get("cold_sectors"),
                                  "weak_sectors": nds.get("weak_sectors")},
                   "yday_deep_pool_size": 0,
                   "frozen_review": {"source": "11-06 早盘深度池 (最后有效池, 昨日已 T+1 复核)",
                                     "verified_on": BASE_DATE, "recommend": LAST_RECOMMEND,
                                     "n_beat_mkt": sum(1 for r in fr if r["beat_mkt"]),
                                     "n_positive": sum(1 for r in fr if r["pos"]),
                                     "n_unchanged": sum(1 for r in fr if r["unchanged"]),
                                     "results": fr},
                   "recommend": None, "eligible_pool": [], "results": results}, f,
                  ensure_ascii=False, indent=1)

    print(f"\n=== 深度排名 (技术50%+基本面30%+估值20%) ===")
    print(f"   候选池 0 只 — 无可评分标的 (报告 Top10 空表 + 尾盘 0 推荐 + 冰点守卫短路)")
    print(f"\n🏁 0 推荐 → 不创建东财组合 {TODAY.replace('-','')}ZZ "
          f"(双重短路: ① 当日报告 0 推荐 (情绪 20 冰点/仓位 10%/⚠️停止交易) "
          f"② P0 冰点守卫 is_ice_point={ice}; 0推荐铁律, 先例 10-27/10-28/10-30/10-31/11-01/11-07)")
    print(f"   东财组现状: 20261106ZZ (gid=1901, 11-06 建, 1 只 600633) 保持不动 (止损 11.01 未破); "
          f"裸日期 20261106 (gid=1896 已退役) / 20261105 (gid=1891) 严禁触碰")
    print(f"   下一交易日: 周一 2026-11-09 — 冰点第 2 日后分叉:")
    print(f"     ① 参照先例 10-30 冰点第2日→周末→11-02 V型修复 (20→85), 修复信号=情绪回30+断点+进攻主线;")
    print(f"     ② 🔴 若修复放行建批 = 放行批模式第 5 样本 (前 4 批 -¥827/4胜全亏, 最近批 0胜10负) —")
    print(f"        建仓前自查: 盘前池 baseline 涨幅分布 (+4~7% 追高结构即⑩-h 第5样本) / 弱势6板块重合度 /")
    print(f"        或减半仓位·仅记录不建仓作对照样本;")
    print(f"     ③ 情绪续冰点 → 守卫继续短路不抢反弹, 非冰点不开。")
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()

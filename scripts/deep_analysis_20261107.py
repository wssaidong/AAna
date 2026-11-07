#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-11-07 (周六休市日 08:3x) — 0 推荐冰点日 · 无候选池 · T+1 铁律复核
当日报告 = reports/2026-11-06-选股报告.md (11-06 17:03 盘后版, 周六无新报告 → 最新即当日)
候选池 = 当日报告 Top10 表 0 只 (情绪 20 冰点 / 建议仓位 10% / ⚠️停止交易);
         11-06 尾盘选股 (14:46) 同样 0 推荐 ("今日无符合条件的尾盘买入机会")
         → 两腿同日双零推荐, 引擎在极冰点行情一致收敛
方法: 报告解析 + P0 冰点守卫 + 昨日深度池 T+1 复核 (腾讯 11-06 收盘快照)
      + rec_tuning 板块胜率 (11-06 晚间反馈闭环更新: 104 键 405 笔 49.38%)
铁律: 0 推荐 → 不创建东财组合 20261107ZZ (0推荐铁律, 先例 11-06 盘前 gid=1896 空占位组退役不重建)
T+1 复核 (11-06 收盘快照, 基准=大盘平均 -2.27% / 上证 -1.10% / 四大核心指数平均 -2.56%):
      昨早盘池 (11-06 深度分析, 报告 Top10 3 只):
        600633 浙数文化 80.0 买入 (昨最值得购买 → 东财 20261106ZZ gid=1901)
        603258 电魂网络 69.3 增持 | 600506 统一股份 47.7 减持
      昨尾盘池: 0 只 (11-06 尾盘选股无符合条件标的, 无 PM 深度分析)
      11-05 尾盘池 5 只已于 11-06 09:30 T1 开盘卖出 (10 笔全负 -0.47%~-4.29%, 盘后战报口径)
Kimi: 本机无 kimi CLI / moonshot key (11-07 复核: which kimi 无, env 无, ~/.kimi 不存在)
      — 连续第 23 日由 AAna 深度评分引擎 + LLM 定性层执行
链路语境: 11-04 亢奋 85 → 11-05 降温回暖 73 → 11-06 冰点 20 (隔日塌方兑现, 上证 -1.10%
      创业板 -3.96%); 昨日"亢奋隔日未塌方"判断在 11-06 被证伪, 追高风险披露应验:
      昨全池 11-05 +4.5~4.8% → 11-06 全数回吐转负; 情绪三日内 85→73→20 巨震,
      周末消息面未明, 周一 (11-09) 观察是否复制 11-04 V 型修复
"""
import sys, os, json, re, time
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, '/Users/cai/code/AAna/scripts')

TODAY = "2026-11-07"
BASE_DATE = "2026-11-06"   # K 线/快照末日 (11-06 周五收盘)
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
TODAY_REPORT = os.path.join(REPORT_DIR, f"{BASE_DATE}-选股报告.md")  # 周六无新报告 → 最新盘后版
OUT_JSON = os.path.expanduser(f"~/code/AAna/data/deep_analysis_{TODAY.replace('-','')}.json")
MK_AVG = -2.27            # 报告快照: 大盘平均涨跌 -2.27% (11-06 收盘基准)
SH_CLOSE = -1.10          # 上证 -1.10% 收 3649.18 (11-06 收盘基准)
IDX_AVG = -2.56           # 四大核心指数平均 (盘后战报口径)
SNAP = {"score": 20, "label": "冰点", "zt_count": 33, "dt_count": 3, "position": 0.10}
RUN_ID = "01a1b36a-01ad-745b-99ab-0879b4724fba"

# 昨日 (11-06 早盘) 深度池 3 只 — 今日 T+1 复核池 (11-06 收盘快照 vs 大盘平均 -2.27%)
YDAY_AM_POOL = [
    {"code": "600633", "name": "浙数文化", "total": 80.0, "rating": "买入", "stop": 11.01,
     "entry": 11.35, "group": "20261106ZZ(gid=1901)", "rank": 1},
    {"code": "603258", "name": "电魂网络", "total": 69.3, "rating": "增持", "stop": 16.34,
     "entry": 16.85, "group": None, "rank": 2},
    {"code": "600506", "name": "统一股份", "total": 47.7, "rating": "减持", "stop": 18.43,
     "entry": 19.0, "group": None, "rank": 3},
]
YDAY_RECOMMEND = "600633"  # 昨最值得购买 → 东财 20261106ZZ

# 板块胜率键 (11-06 深度分析口径; 11-06 晚间反馈闭环回填后)
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
    """腾讯快照: 周六=周五(11-06)收盘口径。返回 {code: (现价, 涨跌幅%, 快照时间戳, 昨收)}"""
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
    """P0 冰点守卫 (单一真源 check_ice_point_guard)。周六休市: live 源无新快照,
    以 11-06 收盘报告快照 20 冰点为判定口径"""
    from aana_afternoon_screen import check_ice_point_guard
    live = None
    try:
        live = check_ice_point_guard()
    except Exception as e:
        print(f"  live 情绪源异常(周六休市): {e}")
    snap = check_ice_point_guard(sent={"score": SNAP["score"], "label": SNAP["label"],
                                       "zt_count": SNAP["zt_count"], "dt_count": SNAP["dt_count"]})
    return live, snap


def load_sector_stats():
    with open(os.path.expanduser("~/code/AAna/data/rec_tuning.json")) as f:
        rt = json.load(f)
    return rt.get("sector_stats", {}), rt.get("overall_win_rate"), rt.get("total_records")


def load_nds():
    with open(os.path.expanduser("~/code/AAna/data/next_day_strategy.json")) as f:
        return json.load(f)


def review_pool(pool, title, mk_avg):
    """T+1 复核: 11-06 收盘快照验证「当日胜出(>大盘平均)+正盈利」"""
    q = tencent_quotes([r["code"] for r in pool])
    review = []
    for r in pool:
        px, chg, ts, prev = q.get(r["code"], (None, None, "", None))
        review.append({**r, "close": px, "prev_close": prev, "chg_pct": chg, "quote_ts": ts,
                       "beat_mkt": (chg is not None and chg > mk_avg),
                       "pos": (chg is not None and chg > 0),
                       "pnl_vs_entry": (round((px / r["entry"] - 1) * 100, 2) if px else None)})
    review.sort(key=lambda x: (x["chg_pct"] if x["chg_pct"] is not None else -99), reverse=True)
    print(f"\n=== {title} (11-06 收盘, 腾讯快照口径; 基准=大盘平均 {mk_avg:+.2f}%) ===")
    for i, r in enumerate(review, 1):
        ts = r['quote_ts'][:8]
        print(f"{i}. {r['code']} {r['name']} 深度{r['total']}{r['rating']}"
              f"{' [昨最值得购买→' + r['group'] + ']' if r['code'] == YDAY_RECOMMEND else ''}"
              f" | 11-06 实收 {r['chg_pct']:+.2f}% "
              f"({'✅胜大盘(' + format(mk_avg, '+.2f') + '%)' if r['beat_mkt'] else '❌弱于大盘'})"
              f"{' ✅正盈利' if r['pos'] else ' ❌负'} | vs 建仓参考 {r['entry']} → {r['pnl_vs_entry']:+.2f}%"
              f" | 快照日 {ts}"
              f"{' 🔴破软止损' + str(r['stop']) if (r['stop'] and (r['close'] or 0) < r['stop']) else ''}")
    n_beat = sum(1 for r in review if r["beat_mkt"])
    n_pos = sum(1 for r in review if r["pos"])
    print(f"胜大盘({mk_avg:+.2f}%): {n_beat}/{len(review)} | 正盈利: {n_pos}/{len(review)}")
    return review


def main():
    print("=" * 78)
    print(f"AAna 深度分析 — {TODAY} (周六休市日, 数据基准 {BASE_DATE} 收盘)")
    print(f"Run: autopilot ca411dd3 深度分析 {RUN_ID}")
    print("=" * 78)

    # ---- 报告确认 (autopilot 强制: 打印报告名称防错) ----
    sz = os.path.getsize(TODAY_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(TODAY_REPORT)))
    print(f"📄 当日报告: {TODAY_REPORT}")
    print(f"   → 存在 | 大小: {sz} 字节 | 修改: {mt}")
    print("   (周六休市无新报告 → 当日报告 = 11-06 周五 17:03 盘后版, '涨跌幅'=11-06 收盘口径)")
    text = open(TODAY_REPORT).read()
    pool = parse_top10_full(text)
    m = re.search(r'重点关注 Top 10(.*?)(?=\n###|\Z)', text, re.S)
    raw_rows = [l for l in (m.group(1) if m else "").split("\n")
                if l.strip().startswith("|") and re.search(r'\d{6}', l)
                and not l.strip().startswith("|:")]
    pm_text = open(os.path.join(REPORT_DIR, "2026-11-06-尾盘选股.md")).read()
    pm_zero = "今日无符合条件的尾盘买入机会" in pm_text
    snap_sent = (f"情绪{SNAP['score']}({SNAP['label']}) 仓位{SNAP['position']*100:.0f}% "
                 f"大盘平均{MK_AVG:+.2f}% 涨停{SNAP['zt_count']}/跌停{SNAP['dt_count']} "
                 f"上证{SH_CLOSE:+.2f}% 收3649.18 交易建议⚠️停止交易")
    print(f"   当日 Top10 表: {len(pool)} 只 (原始数据行 {len(raw_rows)} 行)")
    print(f"   尾盘腿交叉验证: 11-06 尾盘选股 (14:46) 同为 0 推荐"
          f"{' (『今日无符合条件的尾盘买入机会』)' if pm_zero else ' ⚠️表述异常'}")
    print(f"   报告快照 (= 11-06 周五收盘口径): {snap_sent}")
    print("   链路状态: 11-04 亢奋 85 → 11-05 降温回暖 73 → 11-06 冰点 20 (隔日塌方兑现); "
          "昨日追高风险披露应验: 昨全池 11-05 +4.5~4.8% → 11-06 全数回吐转负")

    sector_stats, overall_wr, n_rec = load_sector_stats()
    print(f"📊 板块胜率库 (rec_optimizer 口径, 11-06 晚间反馈闭环更新): {len(sector_stats)} 板块 | "
          f"整体胜率 {overall_wr:.1f}% ({n_rec} 笔) [昨日 98 键/394 笔 50.8% — 周五回撤回填拖低]")
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
              f"is_ice_point={live['is_ice_point']} (周六休市, 披露用)")
    ice = snap["is_ice_point"]

    # ---- 昨日 (11-06) 深度池 T+1 复核 (11-06 收盘, 腾讯快照) ----
    am_rev = review_pool(YDAY_AM_POOL, "昨早盘深度池 3 只复核 (11-06 选股报告盘前版 Top10)", MK_AVG)
    a = next(r for r in am_rev if r["code"] == YDAY_RECOMMEND)
    print(f"🏁 昨最值得购买 600633 浙数文化 铁律 T+1 复核: 11-06 实收 {a['chg_pct']:+.2f}% "
          f"vs 大盘 {MK_AVG:+.2f}% → 超额 {a['chg_pct']-MK_AVG:+.2f}pp "
          f"{'✅ 当日胜出' if a['beat_mkt'] else '❌ 未胜出'}"
          f"{' + 正盈利 ✅' if a['pos'] else ' 但 ❌负盈利 (极冰点系统性回撤, 全池无幸免)'} "
          f"(vs 入场参考 {a['entry']} → {a['pnl_vs_entry']:+.2f}%; 软止损 {a['stop']} "
          f"{'🔴已破' if (a['close'] or 0) < a['stop'] else '未破'})")

    # 板块胜率关联 (昨日推荐股板块键, 回填前后对比)
    print(f"\n=== 板块胜率关联 (昨日池板块键, 11-06 晚间回填后) ===")
    for r in am_rev:
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
    print("   ↳ 移动互联网服务键 75%(3/4)→50%(3/6): 周五电魂/统一(邻近链)回撤样本回填; "
          "板块≠个股, 冰点日系统性贝塔压倒板块阿尔法")

    # ---- 铁律合成 ----
    recommend = None
    eligible = []
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
                   "sector_count": len(sector_stats),
                   "nds_tuning": {"score_threshold": nds.get("score_threshold"),
                                  "cold_sectors": nds.get("cold_sectors"),
                                  "weak_sectors": nds.get("weak_sectors")},
                   "yesterday_review": {"am_pool": {"source": "11-06 早盘深度池 (选股报告盘前版 Top10 3 只)",
                                                    "verified_on": BASE_DATE,
                                                    "recommend": YDAY_RECOMMEND,
                                                    "n_beat_mkt": sum(1 for r in am_rev if r["beat_mkt"]),
                                                    "n_positive": sum(1 for r in am_rev if r["pos"]),
                                                    "results": am_rev}},
                   "recommend": None, "eligible_pool": [], "results": results}, f,
                  ensure_ascii=False, indent=1)

    print(f"\n=== 深度排名 (技术50%+基本面30%+估值20%) ===")
    print(f"   候选池 0 只 — 无可评分标的 (报告 Top10 空表 + 尾盘 0 推荐 + 冰点守卫短路)")
    print(f"\n🏁 0 推荐 → 不创建东财组合 {TODAY.replace('-','')}ZZ "
          f"(双重短路: ① 当日报告 0 推荐 (情绪 20 冰点/仓位 10%/⚠️停止交易) "
          f"② P0 冰点守卫 is_ice_point={ice}; 0推荐铁律, 先例 11-06 盘前 gid=1896 空占位组退役不重建)")
    print(f"   东财组现状: 20261106ZZ (gid=1901, 昨日建, 1 只 600633) 保持不动; "
          f"裸日期 20261106 (gid=1896 已退役) / 20261105 (gid=1891) 严禁触碰")
    print(f"   下一交易日: 周一 2026-11-09 — 观察冰点 20 后是否复制 11-04 V 型修复 (85); "
          f"周末消息面未明, 不抢跑")
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()

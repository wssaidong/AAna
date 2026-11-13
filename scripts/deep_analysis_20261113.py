#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-11-13 (周五交易日盘前 08:3x) — 情绪 30 冰点 · 建议仓位 10% · 停止交易 · 池 0 只 · 守卫短路日
当日报告 = reports/2026-11-13-选股报告.md (11-13 08:02 盘前版, 涨跌幅=昨收 11-12 周四收盘口径)
候选池 = 当日报告 Top10 表 → **0 只** (表体空, 原始数据行 0; 情绪 30 冰点/仓位 10%/交易建议 ⚠️停止交易,
         报告自带"今日无明显回调机会"; 另披露: 热点板块栏"数据获取中"= 08:02 生成链数据缺失迹象,
         agents/premarket_agent.py 缺失致盘前 agent cron 持续报错 — 双因素均指向 0 池)
铁律: 最值得购买者需基准交易日 11-12 当日胜出 (强于大盘) + 正盈利 + 深度评级 ≥增持(65) + 未破止损
      + 守卫放行 → 今日池 0 只 + 冰点守卫双口径短路 (快照 30 冰点 + live ths 11-12 收盘口径冰点)
      → **0 推荐 → 不创建东财 20261113ZZ 组合** (先例: 守卫短路日不建组, 与尾盘腿 11-14:45 拦截口径一致)
链路语境: 11-12 盘前 80 亢奋被开盘证伪 (09:31 冰点急跌) → 候选池⑩-j 局部崩盘 2/10 胜大盘 均值 -4.44%
      → 14:45:02 冰点守卫首次实战拦截 (不建仓不写推荐池) → 双腿一致空仓, positions=0 隔夜
      → 今晨 08:02 报告情绪 30 冰点延续, Top10 空 → 本 run 盘前深度分析 = 守卫短路披露 + 昨日池 T+1 复核
昨日复核基准 (11-12 收盘, 盘后战报 16:24 口径): 上证 -0.67% 3655.83 / 深成 -1.68% / 创业板 -2.44% /
      科创50 +0.73% → 四大核心指数均值 -1.02% (主基准) ; 报告快照"大盘平均 -1.39%"系 11-12 09:31 早盘读数,
      非收盘口径, 复核以收盘口径为准
Kimi: 本机无 kimi CLI / moonshot key (连续第 29 日, 11-12 复核维持) — 由 AAna 深度评分引擎 + LLM 定性层执行
东财: 0 推荐日不同步; groups.json 只读预检 20261113* 占用 (预期无; 昨日 ZZ=1981/20261112=1986 不动)
"""
import sys, os, json, re, time
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, '/Users/cai/code/AAna/scripts')

TODAY = "2026-11-13"
BASE_DATE = "2026-11-12"   # K 线末日 / 昨收基准 (11-12 周四收盘)
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
TODAY_REPORT = os.path.join(REPORT_DIR, f"{TODAY}-选股报告.md")  # 今日 08:02 盘前版
OUT_JSON = os.path.expanduser(f"~/code/AAna/data/deep_analysis_{TODAY.replace('-', '')}.json")
YDAY_AM_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_20261112.json")
YDAY_PM_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_pm_20261112.json")  # 预期不存在 (11-12 守卫拦截)
MK_AVG_CLOSE = -1.02       # 11-12 收盘四均 (复盘/盘后战报口径, 主基准)
SH_CLOSE = -0.67           # 上证 11-12 收盘 (辅助基准)
SNAP = {"score": 30, "label": "冰点", "zt_count": 37, "dt_count": 4, "position": 0.10}
RUN_ID = "01a1d250-3fc2-724f-93d5-f0c300b428b1"
GROUPS_FILE = os.path.expanduser(
    "~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json")


def parse_top10_full(text):
    """解析 '🏆 重点关注 Top 10' 表格 (口径同 deep_analysis_20261112)。"""
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
    """P0 冰点守卫 (单一真源 check_ice_point_guard)。盘前未开盘: live 源 (ths) = 11-12 收盘口径,
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
    """腾讯实时快照: 盘前=昨收(11-12 收盘)口径。返回 {code: (现价, 涨跌幅%, 快照时间戳, 昨收)}"""
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


def load_yday_pool(path, group_map):
    """昨日深度池动态加载: entry=分析时点价, stop=止损, total/rating=当日深度分"""
    if not os.path.exists(path):
        return None
    with open(path) as f:
        d = json.load(f)
    out = []
    for r in d.get("results", []):
        out.append({"code": r["code"], "name": r["name"], "total": r.get("total"),
                    "rating": r.get("rating"), "stop": r.get("stop"), "entry": r.get("price"),
                    "group": group_map.get(r["code"], "")})
    out.sort(key=lambda x: -(x["total"] or 0))
    return out


def review_pool(pool, title, mk_avg):
    """T+1 复核: 11-12 收盘快照验证「当日胜出(>大盘平均)+正盈利」"""
    q = tencent_quotes([r["code"] for r in pool])
    review = []
    for r in pool:
        px, chg, ts, prev = q.get(r["code"], (None, None, "", None))
        review.append({**r, "close": px, "prev_close": prev, "chg_pct": chg, "quote_ts": ts,
                       "beat_mkt": (chg is not None and chg > mk_avg),
                       "beat_sh": (chg is not None and chg > SH_CLOSE),
                       "pos": (chg is not None and chg > 0),
                       "pnl_vs_entry": (round((px / r["entry"] - 1) * 100, 2) if px else None)})
    review.sort(key=lambda x: (x["chg_pct"] if x["chg_pct"] is not None else -99), reverse=True)
    print(f"\n=== {title} (11-12 收盘, 腾讯快照口径; 基准=四均 {mk_avg:+.2f}% / 上证 {SH_CLOSE:+.2f}%) ===")
    for i, r in enumerate(review, 1):
        ts = r['quote_ts'][:8]
        print(f"{i}. {r['code']} {r['name']} 深度{r['total']}{r['rating']}"
              f"{' [' + r['group'] + ']' if r.get('group') else ''}"
              f" | 11-12 实收 {r['chg_pct']:+.2f}% ({'✅胜四均(' + format(mk_avg, '+.2f') + '%)' if r['beat_mkt'] else '❌弱于四均'})"
              f"{' ✅正盈利' if r['pos'] else ' ❌负'} | vs 建仓参考价 {r['entry']} → {r['pnl_vs_entry']:+.2f}%"
              f" | 快照日 {ts}"
              f"{' 🔴破软止损' + str(r['stop']) if (r['stop'] and (r['close'] or 0) < r['stop']) else ''}")
    n_beat = sum(1 for r in review if r["beat_mkt"])
    n_pos = sum(1 for r in review if r["pos"])
    print(f"胜四均({mk_avg:+.2f}%): {n_beat}/{len(review)} | 胜上证({SH_CLOSE:+.2f}%): "
          f"{sum(1 for r in review if r['beat_sh'])}/{len(review)} | 正盈利: {n_pos}/{len(review)}")
    return review


def groups_occupancy():
    """东财 groups.json 只读预检: 20261113* 占用 (预期无 — 0 推荐日不建组)。"""
    try:
        with open(GROUPS_FILE) as f:
            hist = json.load(f)
        hits = {k: v.get("gid") for k, v in hist.items() if k.startswith("20261113")}
        latest = max((int(v.get("gid", 0)) for v in hist.values()
                      if str(v.get("gid", "")).isdigit()), default=None)
        return hits, latest, len(hist)
    except Exception as e:
        return {"error": str(e)[:60]}, None, 0


def main():
    print("=" * 78)
    print(f"AAna 深度分析 — {TODAY} (周五交易日盘前, 数据基准 {BASE_DATE} 收盘)")
    print(f"Run: autopilot ca411dd3 深度分析 {RUN_ID}")
    print("=" * 78)

    # ---- 报告确认 (autopilot 强制: 打印报告名称防错) ----
    sz = os.path.getsize(TODAY_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(TODAY_REPORT)))
    print(f"📄 当日报告: {TODAY_REPORT}")
    print(f"   → 存在 | 大小: {sz} 字节 | 修改: {mt} (今日 08:02 盘前版, '涨跌幅'=昨收=11-12 收盘口径)")
    text = open(TODAY_REPORT).read()
    pool = parse_top10_full(text)
    raws = raw_row_count(text)
    print(f"   当日 Top10 表: {len(pool)} 只 (原始数据行 {len(raws)} 行) → 候选池 = {len(pool)} 只")
    print(f"   报告快照 (= 11-12 周四收盘/早盘档口径): 情绪{SNAP['score']}({SNAP['label']}) "
          f"仓位{SNAP['position']*100:.0f}% 涨停{SNAP['zt_count']}/跌停{SNAP['dt_count']} "
          f"上证{SH_CLOSE:+.2f}% 收3655.83 交易建议⚠️停止交易")
    print("   ⚠️ 报告异常披露: ① '热点板块: 数据获取中' = 08:02 生成链数据缺失迹象; "
          "② 快照'大盘平均涨跌 -1.39%'系 11-12 09:31 早盘档读数非收盘口径 (收盘四均 -1.02%); "
          "③ agents/premarket_agent.py 缺失, 盘前 agent cron 持续报错 (盘前/premarket.log 全为 No such file)")
    print("   链路状态: 11-12 盘前 80 亢奋被开盘证伪 (09:31 冰点急跌) → 候选池⑩-j 局部崩盘 (2/10 胜大盘, "
          "均值 -4.44%, 10/10 负延续) → 14:45:02 冰点守卫首次实战拦截 (不建仓不写推荐池, positions=0 空仓隔夜) "
          "→ 今晨情绪 30 冰点延续, Top10 空表 — 守卫语境一致, 非孤立信号")

    # ---- 胜率库 / 调参披露 ----
    with open(os.path.expanduser("~/code/AAna/data/rec_tuning.json")) as f:
        rt = json.load(f)
    sector_stats = rt.get("sector_stats", {})
    print(f"\n📊 板块胜率库 (rec_optimizer 口径, generated_at {rt.get('generated_at')}): "
          f"{len(sector_stats)} 板块 | 整体胜率 {rt.get('overall_win_rate'):.1f}% ({rt.get('total_records')} 笔)")
    with open(os.path.expanduser("~/code/AAna/data/next_day_strategy.json")) as f:
        nds = json.load(f)
    weak_l = nds.get("weak_sectors", [])
    print(f"   调参披露 (next_day_strategy 11-12 20:00): v24 阈值 {nds.get('score_threshold')} | "
          f"cold_sectors {len(nds.get('cold_sectors', []))} 个 | weak_sectors {len(weak_l)} 个 "
          f"({'/'.join(weak_l)})")

    # ---- 冰点守卫 (双口径) ----
    live, snap = guard_check()
    print(f"\n🛡 P0 冰点守卫: 快照口径 情绪{snap['sentiment_score']}({snap['sentiment_label']}) "
          f"仓位{snap['position_ratio']*100:.0f}% is_ice_point={snap['is_ice_point']}")
    if snap.get("reason"):
        print(f"   短路原因: {snap['reason']}")
    if live:
        print(f"   live 口径 情绪{live['sentiment_score']}({live['sentiment_label']}) "
              f"is_ice_point={live['is_ice_point']} (ths 源盘前=11-12 收盘口径)")
    ice = snap["is_ice_point"] and (live["is_ice_point"] if live else True)

    # ---- 昨日 (11-12) 池 T+1 复核 ----
    am_pool = load_yday_pool(YDAY_AM_JSON, {"001283": "20261112ZZ(gid=1981)"})
    pm_pool = load_yday_pool(YDAY_PM_JSON, {})
    am_rev = pm_rev = None
    if am_pool:
        print(f"\n=== 昨日复核范围 ===\n   早盘腿: 盘前深度池 10 只 (Top1 豪鹏科技 001283 → 20261112ZZ gid=1981)")
        am_rev = review_pool(am_pool, "昨盘前深度池 10 只复核 (11-12 收盘口径)", MK_AVG_CLOSE)
        a1 = next(r for r in am_rev if r["code"] == "001283")
        print(f"🏁 昨 Top1 001283 豪鹏科技 铁律复核: 11-12 实收 {a1['chg_pct']:+.2f}% "
              f"vs 四均 {MK_AVG_CLOSE:+.2f}% → 超额 {a1['chg_pct']-MK_AVG_CLOSE:+.2f}pp "
              f"{'✅ 当日胜出+正盈利' if (a1['beat_mkt'] and a1['pos']) else '❌ 未同时满足 (⑩-j 局部崩盘最伤之二, 20261112ZZ 组保留供跟踪)'} "
              f"(vs 入场参考 {a1['entry']} → {a1['pnl_vs_entry']:+.2f}%; 软止损 {a1['stop']} "
              f"{'🔴已破' if (a1['close'] or 0) < a1['stop'] else '未破'})")
    if pm_pool:
        pm_rev = review_pool(pm_pool, "昨尾盘深度池复核 (11-12 收盘口径)", MK_AVG_CLOSE)
    else:
        print("\n   尾盘腿: 11-12 14:45:02 冰点守卫拦截 → 无推荐池无深度分析 (deep_analysis_pm_20261112.json 不存在, N/A)")

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
          f"20261113* 占用: {occ if occ else '无 (0 推荐日不建组, 与守卫口径一致)'}")

    with open(OUT_JSON, "w") as f:
        json.dump({"date": TODAY, "base_date": BASE_DATE, "report": TODAY_REPORT,
                   "report_size": sz, "report_mtime": mt,
                   "trading_day": True, "session": "pre_market",
                   "generated": time.strftime("%H:%M:%S"),
                   "sentiment_snap": SNAP, "mk_avg_close": MK_AVG_CLOSE, "sh_close_pct": SH_CLOSE,
                   "pool_size": len(pool), "guard_ice": ice,
                   "guard_reason": snap.get("reason"), "run_id": RUN_ID,
                   "report_anomalies": ["热点板块=数据获取中 (08:02 生成链数据缺失迹象)",
                                        "大盘平均涨跌 -1.39% 为 11-12 09:31 早盘读数非收盘口径",
                                        "agents/premarket_agent.py 缺失, 盘前 agent cron 报错"],
                   "overall_win_rate": rt.get("overall_win_rate"),
                   "total_records": rt.get("total_records"),
                   "sector_count": len(sector_stats),
                   "rec_tuning_generated_at": rt.get("generated_at"),
                   "nds_tuning": {"score_threshold": nds.get("score_threshold"),
                                  "cold_sectors": nds.get("cold_sectors", []),
                                  "weak_sectors": weak_l},
                   "yesterday_review": {
                       "am_top10": ({"source": "11-12 盘前深度池 10 只 (deep_analysis_20261112.json)",
                                     "verified_on": BASE_DATE,
                                     "baseline_mk_avg": MK_AVG_CLOSE, "baseline_sh": SH_CLOSE,
                                     "n_beat_mkt": sum(1 for r in am_rev if r["beat_mkt"]),
                                     "n_beat_sh": sum(1 for r in am_rev if r["beat_sh"]),
                                     "n_positive": sum(1 for r in am_rev if r["pos"]),
                                     "mean_chg": round(sum(r["chg_pct"] for r in am_rev) / len(am_rev), 2),
                                     "results": am_rev} if am_rev else None),
                       "am_top1": ({"code": a1["code"], "name": a1["name"],
                                    "group": "20261112ZZ(gid=1981)",
                                    "verified_on": BASE_DATE,
                                    "chg_pct": a1["chg_pct"], "beat_mkt": a1["beat_mkt"],
                                    "pos": a1["pos"], "pnl_vs_entry": a1["pnl_vs_entry"],
                                    "stop": a1["stop"],
                                    "stop_broken": (a1["close"] or 0) < a1["stop"]} if am_rev else None),
                       "pm_leg": "N/A — 11-12 14:45:02 冰点守卫拦截, 无推荐池"},
                   "recommend": None, "eligible_pool": [], "results": results,
                   "eastmoney_sync": {"action": "skip",
                                      "reason": "0 推荐 (池 0 只 + 冰点守卫双口径短路) → 不创建 20261113ZZ",
                                      "groups_20261113_occupied": occ}}, f, ensure_ascii=False, indent=1)

    print(f"\n=== 深度排名: 池 0 只, 无排名 ===")
    print(f"正盈利: {len(positive)}/{len(results)} | 强于大盘({MK_AVG_CLOSE:+.2f}%): 0/0")
    print(f"铁律合格池 (≥增持65+正盈利+胜出+未破止损+守卫放行): []")
    if ice:
        print(f"\n🏁 0 推荐 → 不创建东财组合 {TODAY.replace('-', '')}ZZ "
              f"(P0 冰点守卫短路: 情绪{snap['sentiment_score']}{snap['sentiment_label']}/"
              f"仓位{snap['position_ratio']*100:.0f}%/{snap.get('reason') or '⚠️停止交易'}; "
              f"且当日报告 Top10 表 0 只, 无可分析标的 — 双重独立归因)")
    else:
        print(f"\n🏁 0 推荐 → 不创建东财组合 (当日报告 Top10 表 0 只, 无标的满足铁律)")
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()

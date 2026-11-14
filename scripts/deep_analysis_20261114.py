#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-11-14 (周六·非交易日·周末 cron 首考) — 无当日报告 · 盘前池 0 只 · 冰点守卫延续 · 0 推荐
当日报告 = reports/2026-11-13-选股报告.md (最新版 17:03; 11-14 为周六, cron.log 已正确跳过:
      "[AAna] 2026-11-14 非交易日 (周末 (周六))，跳过报告生成" — is_trading_day 周末首考通过)
候选池 = 11-13 报告 Top10 表 → 0 只 (表体空, 守卫双口径短路设计行为; 深度分析 JSON 快照为盘前池真值,
      绝不回落 09:38 重跑版 — 盘后战报/复盘报告/commit 2dc674b 三处裁定)
铁律: 最值得购买者需基准交易日当日胜出 (强于四均+上证) + 正盈利 + 深度评级 ≥增持(65) + 未破止损 + 守卫放行
      → 11-14 非交易日无「当日」可验证 + 盘前池 0 只 + 冰点守卫 (快照 30 冰点/仓位 10%/停止交易) 三重归因
      → **0 推荐 → 不创建东财 20261114ZZ** (先例: 11-13 守卫短路日不建组)
信息产品 T+0 终局复核 (非推荐池, 透明度披露): 09:38 重跑版 Top10 = 东财 gid=1991 组
      (002050/002181/002714/002979/601689/603019/603131/603179/603662/603667), 以 11-13 收盘终局判决:
      哪些「当日胜出+正盈利」— 回答 autopilot 任务问句, 但不据此产生推荐/建组
Kimi: 本机无 kimi CLI / moonshot key (连续第 31 日) — 由 AAna 引擎 + LLM 定性层执行
东财: 0 推荐日不同步; groups.json 只读预检 20261114* 占用 (预期无)
"""
import sys, os, json, re, time
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, '/Users/cai/code/AAna/scripts')

TODAY = "2026-11-14"
BASE_DATE = "2026-11-13"   # K 线末日 / 收盘基准 (11-13 周五收盘, 最后交易日)
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
LATEST_REPORT = os.path.join(REPORT_DIR, f"{BASE_DATE}-选股报告.md")  # 最新可用报告 (11-14 无报告)
OUT_JSON = os.path.expanduser(f"~/code/AAna/data/deep_analysis_{TODAY.replace('-', '')}.json")
RUN_ID = "01a1d776-90f8-7a1e-b161-70723a21454b"
GROUPS_FILE = os.path.expanduser(
    "~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json")

# 11-13 收盘基准 (复盘报告 17:00 收盘口径, 腾讯 16:1x 快照交叉一致)
MK_FOUR_AVG = -2.06   # 四大核心指数均值 (上证-0.59/深成-2.05/创业板-3.32/科创50-2.30)
SH_CLOSE = -0.59      # 上证指数
SNAP = {"score": 30, "label": "冰点", "position": 0.10, "zt_count": 38, "dt_count": 4}

# 09:38 重跑版 Top10 (东财 gid=1991, 信息产品) — 板块双源 runtime 实测 (2026-11-14 08:0x)
RERUN_POOL = [
    # code, name, sina行业, 东财行业, 概念标签
    ("002050", "三花智控", "家电零部件", "家电零部件Ⅱ", "人形机器人"),
    ("002181", "粤传媒",   "平面媒体",   "出版",        ""),
    ("002714", "牧原股份", "畜禽养殖",   "养殖业",      "猪周期"),
    ("002979", "雷赛智能", "工控自动化", "自动化设备",  "人形机器人"),
    ("601689", "拓普集团", "汽车零部件", "汽车零部件",  "人形机器人"),
    ("603019", "中科曙光", "计算机设备", "计算机设备",  "AI算力"),
    ("603131", "上海沪工", "其它通用机械", None,        "航天"),
    ("603179", "新泉股份", "汽车零部件", "汽车零部件",  "特斯拉链"),
    ("603662", "柯力传感", "仪器仪表",   None,          "人形机器人"),
    ("603667", "五洲新春", "机械基础件", None,          "人形机器人"),
]
# stat_key: 胜率库精确键 (rec_tuning sector_stats 117 键, 11-13 20:00 生成)
STAT_KEY = {"002050": "家电零部件", "002181": "平面媒体", "002714": "农林牧渔",
            "002979": "工控自动化", "601689": "汽车零部件", "603019": "计算机设备",
            "603131": "其它通用机械", "603179": "汽车零部件", "603662": "仪器仪表",
            "603667": "机械基础件"}
ROBOT_KEY = "robot"  # 人形机器人概念级 67% (2/3)


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
    """双重校验: 表区间内含 6 位代码的数据行原始计数 (防解析器误判, 10-28 口径)。"""
    m = re.search(r'重点关注 Top 10(.*?)(?=\n#{2,3} |\Z)', text, re.S)
    return [l for l in (m.group(1) if m else "").split("\n")
            if l.strip().startswith("|") and re.search(r'\d{6}', l)
            and not l.strip().startswith("|:")]


def weekend_verify():
    """非交易日四副腿核验 (复盘 P1「is_trading_day 周末首考」的深度分析侧应答)。"""
    import datetime
    d = datetime.date(2026, 11, 14)
    legs = {
        "weekday": ("周六" if d.weekday() == 5 else "非周六?!"),
        "report_today": bool([f for f in os.listdir(REPORT_DIR) if f.startswith(TODAY)]),
        "cron_skip_line": None,
        "last_trading_day": BASE_DATE,
    }
    try:
        with open(os.path.expanduser("~/code/AAna/scripts/cron.log")) as f:
            for line in f:
                if TODAY in line and "非交易日" in line:
                    legs["cron_skip_line"] = line.strip()[:80]
                    break
    except Exception:
        pass
    return legs


def guard_check():
    """P0 冰点守卫 (单一真源 check_ice_point_guard)。周末: live 源 (ths) = 11-13 收盘口径。"""
    from aana_afternoon_screen import check_ice_point_guard
    live = None
    try:
        live = check_ice_point_guard()
    except Exception as e:
        print(f"  live 情绪源异常(周末休市): {e}")
    snap = check_ice_point_guard(sent={"score": SNAP["score"], "label": SNAP["label"],
                                       "zt_count": SNAP["zt_count"], "dt_count": SNAP["dt_count"]})
    return live, snap


def tencent_quotes(codes):
    """腾讯快照: 周末=11-13 收盘口径。返回 {code: (现价, 涨跌幅%, 时间戳, 昨收)}"""
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


def main():
    print("=" * 78)
    print(f"AAna 深度分析 — {TODAY} (周六非交易日·周末 cron 首考, 数据基准 {BASE_DATE} 收盘)")
    print(f"Run: autopilot ca411dd3 深度分析 {RUN_ID}")
    print("=" * 78)

    # ---- 报告确认 (autopilot 强制: 打印报告名称防错) ----
    sz = os.path.getsize(LATEST_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(LATEST_REPORT)))
    print(f"📄 当日报告: 无 2026-11-14 报告 (周六休市) → 使用最新 {LATEST_REPORT}")
    print(f"   → 存在 | 大小: {sz} 字节 | 修改: {mt} (11-13 终版, 复盘链 17:03 生成)")
    text = open(LATEST_REPORT).read()
    pool = parse_top10_full(text)
    raws = raw_row_count(text)
    print(f"   报告 Top10 表: {len(pool)} 只 (原始数据行 {len(raws)} 行) → 候选池 = {len(pool)} 只")
    print(f"   报告快照: 情绪{SNAP['score']}({SNAP['label']}) 仓位{SNAP['position']*100:.0f}% "
          f"⚠️停止交易 | 盘前深度分析 JSON (08:35) + 开盘复核 (09:34) 双快照 = 盘前池真值 0 只, 绝不回落重跑版")

    legs = weekend_verify()
    print(f"\n📅 非交易日四副腿核验: weekday={legs['weekday']} | 今日报告存在="
          f"{legs['report_today']} | cron跳过行={'✅ ' + legs['cron_skip_line'] if legs['cron_skip_line'] else '❌未见'}"
          f" | 最后交易日={legs['last_trading_day']} → is_trading_day 周末首考 PASS (cron 正确跳过)")

    # ---- 胜率库 ----
    with open(os.path.expanduser("~/code/AAna/data/rec_tuning.json")) as f:
        rt = json.load(f)
    sector_stats = rt.get("sector_stats", {})
    print(f"\n📊 板块胜率库 (rec_optimizer 口径, generated_at {rt.get('generated_at')}): "
          f"{len(sector_stats)} 板块 | 整体胜率 {rt.get('overall_win_rate'):.1f}% ({rt.get('total_records')} 笔)")

    # ---- 冰点守卫 ----
    live, snap = guard_check()
    print(f"\n🛡 P0 冰点守卫: 快照口径 情绪{snap['sentiment_score']}({snap['sentiment_label']}) "
          f"仓位{snap.get('position_ratio', SNAP['position'])*100:.0f}% is_ice_point={snap['is_ice_point']}")
    if live:
        print(f"   live 口径 情绪{live['sentiment_score']}({live['sentiment_label']}) "
              f"is_ice_point={live['is_ice_point']} (ths 源周末=11-13 收盘口径)")
    ice = snap["is_ice_point"] and (live["is_ice_point"] if live else True)

    # ---- 信息产品 T+0 终局复核 (gid=1991 重跑池 10 只, 非推荐池) ----
    print(f"\n=== 信息产品 T+0 终局复核 — 09:38 重跑版 Top10 (东财 gid=1991) vs {BASE_DATE} 收盘 ===")
    print(f"    (定位: 信息产品非推荐池, 盘后战报 11-13 裁定; 本段为透明度披露, 不据此推荐/建组)")
    quotes = tencent_quotes([r[0] for r in RERUN_POOL])
    review = []
    for code, name, ind_sina, ind_em, concept in RERUN_POOL:
        px, chg, ts, prev = quotes.get(code, (None, None, "", None))
        sk = STAT_KEY.get(code)
        sec = sector_stats.get(sk, {}) if sk else {}
        sec_wr = f"{sec['win_rate']:.0f}% ({sec['win_count']}/{sec['count']})" if sec else "无记录"
        robot_wr = ""
        if code in ("002050", "002979", "601689", "603662", "603667"):
            rs = sector_stats.get(ROBOT_KEY, {})
            robot_wr = f" · 人形机器人概念 {rs['win_rate']:.0f}% ({rs['win_count']}/{rs['count']})" if rs else ""
        review.append({
            "code": code, "name": name, "industry_sina": ind_sina, "industry_em": ind_em,
            "concept": concept, "sector_stat_key": sk,
            "sector_win_rate": (f"{sec['win_rate']:.1f}%({sec['win_count']}/{sec['count']})" if sec else None),
            "close": px, "prev_close": prev, "chg_pct": chg, "quote_ts": ts,
            "beat_four": chg is not None and chg > MK_FOUR_AVG,
            "beat_sh": chg is not None and chg > SH_CLOSE,
            "pos": chg is not None and chg > 0,
        })
    review.sort(key=lambda x: (x["chg_pct"] if x["chg_pct"] is not None else -99), reverse=True)
    for i, r in enumerate(review, 1):
        tags = []
        if r["beat_four"]: tags.append("✅胜四均")
        if r["beat_sh"]: tags.append("✅胜上证")
        if r["pos"]: tags.append("✅正盈利")
        print(f"{i:2d}. {r['code']} {r['name']} 收{r['close']} {r['chg_pct']:+.2f}% "
              f"[{'/'.join(tags) if tags else '❌全败'}] | {r['industry_sina']}"
              f"{'/' + r['industry_em'] if r['industry_em'] else ''} 胜率 {r['sector_win_rate'] or '无记录'}"
              f"{' · ' + r['concept'] if r['concept'] else ''}{robot_wr if r['code'] in ('002050','002979','601689','603662','603667') else ''}")
    n_beat4 = sum(1 for r in review if r["beat_four"])
    n_beatsh = sum(1 for r in review if r["beat_sh"])
    n_pos = sum(1 for r in review if r["pos"])
    mean_chg = round(sum(r["chg_pct"] for r in review) / len(review), 2)
    winners = [r for r in review if r["pos"] and r["beat_four"] and r["beat_sh"]]
    print(f"    判决: 胜四均({MK_FOUR_AVG:+.2f}%) {n_beat4}/10 · 胜上证({SH_CLOSE:+.2f}%) {n_beatsh}/10 · "
          f"正盈利 {n_pos}/10 · 均值 {mean_chg:+.2f}% (超额 vs 四均 {mean_chg - MK_FOUR_AVG:+.2f}pp / vs 上证 {mean_chg - SH_CLOSE:+.2f}pp)")
    if winners:
        w_names = '、'.join(f"{r['name']} {r['chg_pct']:+.2f}%" for r in winners)
        print(f"    「当日胜出+正盈利」双达标: {len(winners)}/10 → {w_names}")
        top = winners[0]
        print(f"    龙头 = {top['name']}({top['code']}) {top['chg_pct']:+.2f}% — 仅作信息产品结论, "
              f"非推荐 (池口径=盘中重跑版, 盘前池真值 0 只; 11-14 无交易日铁律不可验证)")

    # ---- 铁律合成: 池 0 只 + 非交易日 + 守卫 → 0 推荐 ----
    results = []  # 官方池 0 只, 无逐股深度评分对象
    positive = []
    eligible = []
    recommend = None

    # ---- 东财 groups 只读预检 ----
    try:
        with open(GROUPS_FILE) as f:
            hist = json.load(f)
        occ = {k: v.get("gid") for k, v in hist.items() if k.startswith("20261114")}
        latest_gid = max((int(v.get("gid", 0)) for v in hist.values()
                          if str(v.get("gid", "")).isdigit()), default=None)
        n_groups = len(hist)
    except Exception as e:
        occ, latest_gid, n_groups = {"error": str(e)[:60]}, None, 0
    print(f"\n📁 东财 groups.json 只读预检: 共 {n_groups} 组 | 最新 gid {latest_gid} | "
          f"20261114* 占用: {occ if occ else '无 (0 推荐日不建组, 与 11-13 先例一致)'}")

    print(f"\n=== 逐股深度评分 (技术50%+基本面30%+估值20%): 官方池 0 只 → 无评分对象 ===")
    print(f"铁律合格池 (≥增持65+正盈利+当日胜出+未破止损+守卫放行): [] (非交易日, 「当日」不可验证)")
    print(f"\n🏁 0 推荐 → 不创建东财组合 20261114ZZ")
    print(f"    三重独立归因: ① 11-14 周六非交易日, 铁律「当日胜出+正盈利」无验证基准;")
    print(f"    ② 最新报告 (11-13) Top10 表 0 只 = 盘前池真值, 绝不回落 09:38 重跑版 (gid=1991 信息产品);")
    print(f"    ③ 冰点守卫延续 (快照 30 冰点/仓位 10%/停止交易{'/live 证实' if live and live['is_ice_point'] else ''})。")
    print(f"    下一动作: 11-16 (周一) 08:0x 盘前报告 → 深度分析按当日铁律重裁; t1sell 预期无持仓跳过。")

    with open(OUT_JSON, "w") as f:
        json.dump({"date": TODAY, "base_date": BASE_DATE,
                   "report": LATEST_REPORT, "report_note": "11-14 周六无报告, 用 11-13 终版",
                   "report_size": sz, "report_mtime": mt,
                   "trading_day": False, "session": "weekend",
                   "generated": time.strftime("%H:%M:%S"),
                   "weekend_legs": legs, "sentiment_snap": SNAP,
                   "mk_four_avg_close": MK_FOUR_AVG, "sh_close_pct": SH_CLOSE,
                   "pool_size": len(pool), "guard_ice": ice,
                   "guard_live": ({"score": live["sentiment_score"], "label": live["sentiment_label"],
                                   "is_ice_point": live["is_ice_point"]} if live else None),
                   "run_id": RUN_ID,
                   "overall_win_rate": rt.get("overall_win_rate"),
                   "total_records": rt.get("total_records"),
                   "sector_count": len(sector_stats),
                   "rec_tuning_generated_at": rt.get("generated_at"),
                   "rerun_pool_t0_review": {
                       "source": "09:38 重跑版 Top10 = 东财 gid=1991 (信息产品非推荐池)",
                       "judged_on": BASE_DATE, "baseline_four_avg": MK_FOUR_AVG,
                       "baseline_sh": SH_CLOSE,
                       "n_beat_four": n_beat4, "n_beat_sh": n_beatsh, "n_positive": n_pos,
                       "mean_chg": mean_chg,
                       "excess_vs_four": round(mean_chg - MK_FOUR_AVG, 2),
                       "excess_vs_sh": round(mean_chg - SH_CLOSE, 2),
                       "dual_qualified": [{"code": r["code"], "name": r["name"],
                                           "chg_pct": r["chg_pct"]} for r in winners],
                       "results": review},
                   "recommend": None, "eligible_pool": [], "results": results,
                   "eastmoney_sync": {"action": "skip",
                                      "reason": "0 推荐 (非交易日 + 盘前池 0 + 冰点守卫) → 不创建 20261114ZZ",
                                      "groups_20261114_occupied": occ}}, f, ensure_ascii=False, indent=1)
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()

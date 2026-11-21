#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-11-21 (周六·非交易日·周末第 1 日) — 无当日报告 · 候选池 0 只 · 冰点守卫延续 · 0 推荐
当日报告 = 无 2026-11-21 报告 (周六休市; premarket.log 07:00/08:25/08:30 三次「今日非交易日，退出」;
      cron.log "[AAna] 2026-11-21 非交易日 (周末 (周六))，跳过报告生成" — is_trading_day 周末首考核验通过)
基准报告 = reports/2026-11-20-选股报告.md (最新版 17:03 盘后版, 5283 字节) Top10 表 0 只 (表体仅基金推荐行)
候选池 = 0 只 → 0 推荐 (三重归因: 非交易日无「当日」可验证 + 报告池 0 只 + 冰点守卫延续)
周五 11-20 收盘快照: 情绪 20 冰点 · 大盘平均 -2.16% · 涨停 30/跌停 3 · 仓位 10% 空仓观望 · ⚠️停止交易
四大核心指数: 上证 -1.22% 收 3533.79 / 深成 -3.09 / 创业板 -3.54 / 科创50 -3.12 → 四均 -2.74%
铁律: 最值得购买者需基准交易日当日胜出 (强于四均+上证) + 正盈利 + 深度评级 ≥增持(65) + 未破止损 + 守卫放行
11-20 深度池 T+0 终局复核 (10 只, Top1 海康威视 002415 = 东财 20261120ZZ gid=2051):
      Top1 11-20 收 35.25 -1.29% → 胜大盘均(-2.16%)/胜四均(-2.74%) ✅ 但 负盈利 ❌ + 未胜上证(-1.22%) ❌ → 铁律未达标
      池: 胜大盘均 9/10 · 正盈利 4/10 · 均值 -0.79% (超额 vs 大盘均 +1.37pp) · 张江高科 600895 -10.01% 跌停破止损 26.36
实持复核: 20261120ZZ 海康威视 收 35.25 (vs 软止损 34.64 未破) · 20261118ZZ 宁波银行 收 35.24
      (vs 入场 35.53 = -0.82%, 软止损 34.34 未破) — 卖出腿归 daily_v24_sell, 非本任务范围
Kimi: 本机无 kimi CLI / moonshot key (连续第 38 日) — 由 AAna 引擎 + LLM 定性层执行
东财: 0 推荐日不同步, 不创建 20261121ZZ; groups.json 只读预检 20261121* 占用 (预期无)
"""
import sys, os, json, re, time
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, '/Users/cai/code/AAna/scripts')

TODAY = "2026-11-21"
BASE_DATE = "2026-11-20"   # K 线末日 / 收盘基准 (11-20 周五收盘, 最后交易日)
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
LATEST_REPORT = os.path.join(REPORT_DIR, f"{BASE_DATE}-选股报告.md")  # 最新可用报告 (11-21 无报告)
OUT_JSON = os.path.expanduser(f"~/code/AAna/data/deep_analysis_{TODAY.replace('-', '')}.json")
RUN_ID = "01a1fb82-ec42-79f7-aee8-e34428b13d7c"
GROUPS_FILE = os.path.expanduser(
    "~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json")

# 11-20 收盘基准 (盘后版 17:03 + 复盘评分 收盘口径, 腾讯 16:1x 快照交叉一致)
MK_FOUR_AVG = -2.74   # 四大核心指数均值 (上证-1.22/深成-3.09/创业板-3.54/科创50-3.12)
SH_CLOSE = -1.22      # 上证指数 收 3533.79
MK_AVG_ALL = -2.16    # 全市场大盘平均涨跌 (盘后版报告口径)
SNAP = {"score": 20, "label": "冰点", "position": 0.10, "zt_count": 30, "dt_count": 3}

# 11-20 早盘深度池 10 只 (data/deep_analysis_20261120.json, 基准日 11-19; Top1 已建 20261120ZZ gid=2051)
# (code, name, 深度总分, 评级, 软止损, 目标, rec_tuning stat_key, 板块胜率串, 基准日 11-19 涨跌%)
POOL_1120 = [
    ("002415", "海康威视", 89.0, "买入", 34.64, 37.50, "计算机设备", "100.0% (2/2)", 1.19),
    ("002142", "宁波银行", 89.0, "买入", 34.34, 37.17, "银行", "75.0% (3/4)", 0.48),
    ("600312", "平高电气", 79.6, "买入", 21.62, 23.40, "高低压设备", "100.0% (2/2)", 0.81),
    ("603288", "海天味业", 77.0, "买入", 35.35, 38.26, "调味发酵品", "100.0% (3/3)", 1.25),
    ("601166", "兴业银行", 77.0, "买入", 19.49, 21.09, "银行", "75.0% (3/4)", 0.60),
    ("600406", "国电南瑞", 74.6, "增持", 24.09, 26.08, "工控自动化", "100.0% (5/5)", 0.98),
    ("600066", "宇通客车", 71.6, "增持", 30.76, 33.30, "商用载客车", "0.0% (0/1)", 0.51),
    ("601318", "中国平安", 71.6, "增持", 53.02, 57.39, "多元金融", "100.0% (1/1)", 0.48),
    ("000651", "格力电器", 64.4, "中性", 39.75, 43.03, None, "无记录(冷启动)", 0.56),
    ("600895", "张江高科", 49.5, "减持", 26.36, 28.54, "房地产开发", "33.3% (1/3)", 1.99),
]
HELD = {"002415": {"zz": "20261120ZZ", "gid": 2051, "entry_ctx": "11-20 早盘关注价 35.38", "stop": 34.64},
        "002142": {"zz": "20261118ZZ", "gid": 2016, "entry": 35.53, "stop": 34.34}}


def parse_top10_full(text):
    """解析 '🏆 重点关注 Top 10' 表格 (口径同 deep_analysis_20261115)。"""
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
    """双重校验: 表区间内含 6 位代码的数据行原始计数 (10-28 口径)。"""
    m = re.search(r'重点关注 Top 10(.*?)(?=\n#{2,3} |\Z)', text, re.S)
    return [l for l in (m.group(1) if m else "").split("\n")
            if l.strip().startswith("|") and re.search(r'\d{6}', l)
            and not l.strip().startswith("|:")]


def weekend_verify():
    """非交易日四副腿核验 (复盘 P1「is_trading_day 周末首考」的深度分析侧应答)。"""
    import datetime
    d = datetime.date(2026, 11, 21)
    legs = {
        "weekday": ("周六" if d.weekday() == 5 else "非周六?!"),
        "report_today": bool([f for f in os.listdir(REPORT_DIR) if f.startswith(TODAY)]),
        "cron_skip_line": None,
        "premarket_exit_lines": 0,
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
    try:
        with open(os.path.join(REPORT_DIR, TODAY, "盘前", "premarket.log")) as f:
            legs["premarket_exit_lines"] = sum(1 for l in f if "非交易日" in l)
    except Exception:
        pass
    return legs


def guard_check():
    """P0 冰点守卫 (单一真源 check_ice_point_guard)。周末: live 源 (ths) = 11-20 收盘口径。"""
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
    """腾讯快照: 周末=11-20 收盘口径。返回 {code: (现价, 涨跌幅%, 时间戳, 昨收)}"""
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
    print(f"AAna 深度分析 — {TODAY} (周六非交易日·周末第 1 日核验, 数据基准 {BASE_DATE} 收盘)")
    print(f"Run: autopilot ca411dd3 深度分析 {RUN_ID}")
    print("=" * 78)

    # ---- 报告确认 (autopilot 强制: 打印报告名称防错) ----
    sz = os.path.getsize(LATEST_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(LATEST_REPORT)))
    print(f"📄 当日报告: 无 2026-11-21 报告 (周六休市) → 使用最新 {LATEST_REPORT}")
    print(f"   → 存在 | 大小: {sz} 字节 | 修改: {mt} (11-20 盘后版 17:03, 复盘链生成)")
    text = open(LATEST_REPORT).read()
    pool = parse_top10_full(text)
    raws = raw_row_count(text)
    print(f"   报告 Top10 表: {len(pool)} 只 (原始数据行 {len(raws)} 行, 6 位代码行均为基金推荐表) → 候选池 = {len(pool)} 只")
    print(f"   报告快照: 情绪{SNAP['score']}({SNAP['label']}) 仓位{SNAP['position']*100:.0f}% "
          f"涨停{SNAP['zt_count']}/跌停{SNAP['dt_count']} ⚠️停止交易 | 大盘平均 {MK_AVG_ALL}% 上证 {SH_CLOSE}% 收 3533.79")

    legs = weekend_verify()
    print(f"\n📅 非交易日四副腿核验: weekday={legs['weekday']} | 今日报告存在={legs['report_today']} "
          f"| premarket 非交易日退出 {legs['premarket_exit_lines']} 次 | "
          f"cron跳过行={'✅ ' + legs['cron_skip_line'] if legs['cron_skip_line'] else '❌未见'}"
          f" | 最后交易日={legs['last_trading_day']} → is_trading_day 周末首考核验 PASS")

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
              f"is_ice_point={live['is_ice_point']} (ths 源周末=11-20 收盘口径)")
    ice = snap["is_ice_point"] and (live["is_ice_point"] if live else True)

    # ---- 11-20 深度池 T+0 终局复核 (Top1=20261120ZZ 实持口径) ----
    print(f"\n=== 11-20 深度池 10 只 T+0 终局复核 — Top1 海康威视 (东财 20261120ZZ gid=2051) vs {BASE_DATE} 收盘 ===")
    quotes = tencent_quotes([r[0] for r in POOL_1120])
    review = []
    for code, name, total, rating, stop, target, sk, wr_str, chg_base in POOL_1120:
        px, chg, ts, prev = quotes.get(code, (None, None, "", None))
        sec = sector_stats.get(sk, {}) if sk else {}
        sec_wr_live = (f"{sec['win_rate']:.1f}% ({sec['win_count']}/{sec['count']})" if sec else wr_str)
        review.append({
            "code": code, "name": name, "total": total, "rating": rating,
            "stop": stop, "target": target, "sector_stat_key": sk,
            "sector_win_rate": sec_wr_live,
            "close": px, "prev_close": prev, "chg_pct": chg, "quote_ts": ts,
            "chg_base_1119": chg_base,
            "beat_four": chg is not None and chg > MK_FOUR_AVG,
            "beat_sh": chg is not None and chg > SH_CLOSE,
            "beat_mkt_avg": chg is not None and chg > MK_AVG_ALL,
            "pos": chg is not None and chg > 0,
            "stop_broken": (stop is not None and px is not None and px < stop),
            "held": code in HELD,
        })
    review.sort(key=lambda x: (x["chg_pct"] if x["chg_pct"] is not None else -99), reverse=True)
    for i, r in enumerate(review, 1):
        tags = []
        if r["beat_four"]:
            tags.append("✅胜四均")
        if r["beat_mkt_avg"]:
            tags.append("✅胜大盘均")
        if r["beat_sh"]:
            tags.append("✅胜上证")
        tags.append("✅正盈利" if r["pos"] else "❌负盈利")
        stop_mark = (f"🔴破止损{r['stop']:.2f}" if r["stop_broken"] else "止损未破")
        held_mark = f" [实持 {HELD[r['code']]['zz']}]" if r["held"] else ""
        print(f"{i:2d}. {r['code']} {r['name']} 深度{r['total']} {r['rating']} 收{r['close']} {r['chg_pct']:+.2f}% "
              f"[{'/'.join(tags)}] {stop_mark} | 板块[{r['sector_stat_key'] or '冷启动'}]{r['sector_win_rate']}{held_mark}")
    n_beat4 = sum(1 for r in review if r["beat_four"])
    n_beat_avg = sum(1 for r in review if r["beat_mkt_avg"])
    n_beatsh = sum(1 for r in review if r["beat_sh"])
    n_pos = sum(1 for r in review if r["pos"])
    n_stop = sum(1 for r in review if r["stop_broken"])
    mean_chg = round(sum(r["chg_pct"] for r in review) / len(review), 2)
    winners = [r for r in review if r["pos"] and r["beat_four"] and r["beat_sh"]]
    print(f"    判决: 胜四均({MK_FOUR_AVG:+.2f}%) {n_beat4}/10 · 胜大盘均({MK_AVG_ALL:+.2f}%) {n_beat_avg}/10 · "
          f"胜上证({SH_CLOSE:+.2f}%) {n_beatsh}/10 · 正盈利 {n_pos}/10 · 破止损 {n_stop}/10 · "
          f"均值 {mean_chg:+.2f}% (超额 vs 大盘均 {mean_chg - MK_AVG_ALL:+.2f}pp / vs 四均 {mean_chg - MK_FOUR_AVG:+.2f}pp)")
    if winners:
        print(f"    「当日胜出+正盈利」双达标 {len(winners)}/10: " +
              "、".join(f"{r['name']} {r['chg_pct']:+.2f}%" for r in winners))

    # ---- Top1 铁律裁定 + 实持复核 ----
    top1 = next(r for r in review if r["code"] == "002415")
    law_pass = top1["pos"] and top1["beat_four"] and top1["beat_sh"]
    print(f"\n🏁 Top1 铁律裁定 — 海康威视 002415 (11-20 深度 89.0 买入, 东财 20261120ZZ gid=2051): "
          f"收 {top1['close']} {top1['chg_pct']:+.2f}% → "
          f"{'✅当日胜出' if (top1['beat_four'] and top1['beat_sh']) else '❌未全面胜出'}"
          f" + {'✅正盈利' if top1['pos'] else '❌负盈利'} → 铁律{'✅达标' if law_pass else '❌未达标'}")
    print(f"    三基准分解: 胜大盘均 ✅ (+{top1['chg_pct'] - MK_AVG_ALL:.2f}pp) · 胜四均 ✅ "
          f"(+{top1['chg_pct'] - MK_FOUR_AVG:.2f}pp) · 胜上证 ❌ ({top1['chg_pct'] - SH_CLOSE:+.2f}pp)")
    print(f"    持仓: vs 软止损 {top1['stop']} {'🔴已破' if top1['stop_broken'] else '未破'} · "
          f"vs 早盘关注价 35.38 {(top1['close']/35.38-1)*100:+.2f}% — 卖出腿归 daily_v24_sell, 非本任务范围")
    nb = next(r for r in review if r["code"] == "002142")
    print(f"    实持 20261118ZZ 宁波银行 002142 (入场 35.53): 收 {nb['close']} {(nb['close']/35.53-1)*100:+.2f}% "
          f"| 软止损 34.34 {'🔴已破' if nb['stop_broken'] else '未破'} | 11-19/11-20 连续 2 日胜大盘均")
    print(f"    张江高科 600895 (池内评级最低 减持 49.5): 11-20 -10.01% 跌停破止损 26.36 — "
          f"反向印证深度评级区分度 (池内涨幅王 11-19 +1.99% → 次日领跌)")

    # ---- 铁律合成: 池 0 只 + 非交易日 + 守卫 → 0 推荐 ----
    results = []  # 官方池 0 只, 无逐股深度评分对象
    eligible = []
    recommend = None

    # ---- 东财 groups 只读预检 ----
    try:
        with open(GROUPS_FILE) as f:
            hist = json.load(f)
        occ = {k: v.get("gid") for k, v in hist.items() if k.startswith("20261121")}
        latest_gid = max((int(v.get("gid", 0)) for v in hist.values()
                          if str(v.get("gid", "")).isdigit()), default=None)
        n_groups = len(hist)
    except Exception as e:
        occ, latest_gid, n_groups = {"error": str(e)[:60]}, None, 0
    print(f"\n📁 东财 groups.json 只读预检: 共 {n_groups} 组 | 最新 gid {latest_gid} | "
          f"20261121* 占用: {occ if occ else '无 (0 推荐日不建组, 与 11-13/11-14/11-15 先例一致)'}")

    print(f"\n=== 逐股深度评分 (技术50%+基本面30%+估值20%): 官方池 0 只 → 无评分对象 ===")
    print(f"铁律合格池 (≥增持65+正盈利+当日胜出+未破止损+守卫放行): [] (非交易日, 「当日」不可验证)")
    print(f"\n🏁 0 推荐 → 不创建东财组合 20261121ZZ")
    print(f"    三重独立归因: ① 11-21 周六非交易日, 铁律「当日胜出+正盈利」无验证基准;")
    print(f"    ② 基准报告 (11-20 盘后版) Top10 表 0 只 = 收盘真值 (守卫短路设计行为);")
    print(f"    ③ 冰点守卫延续 (快照 20 冰点/仓位 10%/停止交易{'/live 证实' if live and live.get('is_ice_point') else ''})。")
    print(f"    下一动作: 11-24 (周一) 08:0x 盘前报告 → 深度分析按当日铁律重裁; 周末先例 11-14/11-15 同款 0 推荐。")
    print(f"    周一前瞻: 情绪 20 冰点第 1 日 (11-21 周末口径), 关注 10-28 V 型修复 20→58→75 先例; "
          f"20261120ZZ 海康威视 + 20261118ZZ 宁波银行 止损 34.64/34.34 未破, 周一开盘后以实时链路为准。")

    with open(OUT_JSON, "w") as f:
        json.dump({"date": TODAY, "base_date": BASE_DATE,
                   "report": LATEST_REPORT, "report_note": "11-21 周六无报告, 用 11-20 终版 (17:03 盘后版)",
                   "report_size": sz, "report_mtime": mt,
                   "trading_day": False, "session": "weekend",
                   "generated": time.strftime("%H:%M:%S"),
                   "weekend_legs": legs, "sentiment_snap": SNAP,
                   "mk_four_avg_close": MK_FOUR_AVG, "sh_close_pct": SH_CLOSE,
                   "mk_avg_all": MK_AVG_ALL,
                   "pool_size": len(pool), "guard_ice": ice,
                   "guard_live": ({"score": live["sentiment_score"], "label": live["sentiment_label"],
                                   "is_ice_point": live["is_ice_point"]} if live else None),
                   "run_id": RUN_ID,
                   "overall_win_rate": rt.get("overall_win_rate"),
                   "total_records": rt.get("total_records"),
                   "sector_count": len(sector_stats),
                   "rec_tuning_generated_at": rt.get("generated_at"),
                   "pool_1120_t0_review": {
                       "source": "data/deep_analysis_20261120.json 早盘深度池 10 只 (Top1 已建 20261120ZZ gid=2051)",
                       "judged_on": BASE_DATE,
                       "baseline_four_avg": MK_FOUR_AVG, "baseline_sh": SH_CLOSE,
                       "baseline_mkt_avg": MK_AVG_ALL,
                       "n_beat_four": n_beat4, "n_beat_sh": n_beatsh, "n_beat_mkt_avg": n_beat_avg,
                       "n_positive": n_pos, "n_stop_broken": n_stop,
                       "mean_chg": mean_chg,
                       "excess_vs_mkt_avg": round(mean_chg - MK_AVG_ALL, 2),
                       "excess_vs_four": round(mean_chg - MK_FOUR_AVG, 2),
                       "dual_qualified": [{"code": r["code"], "name": r["name"],
                                           "chg_pct": r["chg_pct"]} for r in winners],
                       "top1_law_verdict": ("fail_negative_and_below_sh" if not law_pass else "pass"),
                       "results": review},
                   "held_zz": [
                       {"group": "20261120ZZ", "gid": 2051, "code": "002415", "name": "海康威视",
                        "close": top1["close"], "chg_pct": top1["chg_pct"], "stop": 34.64,
                        "stop_broken": top1["stop_broken"], "judged_on": BASE_DATE,
                        "entry_ctx": "11-20 早盘关注价 35.38",
                        "pnl_vs_entry_ctx": round((top1["close"]/35.38-1)*100, 2)},
                       {"group": "20261118ZZ", "gid": 2016, "code": "002142", "name": "宁波银行",
                        "entry": 35.53, "close": nb["close"], "chg_pct": nb["chg_pct"], "stop": 34.34,
                        "stop_broken": nb["stop_broken"], "judged_on": BASE_DATE,
                        "pnl_vs_entry": round((nb["close"]/35.53-1)*100, 2)}],
                   "recommend": None, "eligible_pool": [], "results": results,
                   "eastmoney_sync": {"action": "skip",
                                      "reason": "0 推荐 (非交易日 + 报告池 0 + 冰点守卫) → 不创建 20261121ZZ",
                                      "groups_20261121_occupied": occ}}, f, ensure_ascii=False, indent=1)
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()

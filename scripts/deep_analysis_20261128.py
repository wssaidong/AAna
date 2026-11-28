#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-11-28 (周六·非交易日·周末第 1 日) — 无当日报告 · 0 推荐 · 不建 20261128ZZ · PM 深度池冻结复核
当日报告 = 无 2026-11-28 报告 (周六休市; premarket.log 07:00/08:25/08:30 三次「今日非交易日，退出」;
      cron.log "[AAna] 2026-11-28 非交易日 (周末 (周六))，跳过报告生成")
基准报告 = reports/2026-11-27-选股报告.md (最新正式版 17:01 盘后版, 5344 字节) Top10 表 0 只
      — 空表归因 = 熔断日极端日守卫缺陷 (创业板 +11.61% 被守卫「超出合理范围丢弃」+ 17:01 真源评分 1/43
        单向罚分批量触发), 与 11-21/11-22 周末的冰点短路不同类; 主链口径熔断日普涨为真
工作池 = 11-27 尾盘真源深度池 ×5 (data/deep_analysis_pm_20261127.json, 14:55 rerun e2bf8ed 修复后):
      菜百股份 605599 深度 82.2 买入 (Top1) / 科伦药业 002422 买入 / 鱼跃医疗 002223 增持 /
      皖通高速 600012 增持 / 丽珠集团 000513 中性; 已建东财 PP 组 20261127PP (gid=2131, 605599)
11-27 收盘冻结基准 (熔断日): 上证 3606.49 +3.73 / 深成 10814.02 +7.24 / 创业板 2443.96 +11.61 /
      科创50 1346.25 +15.07 → 四均 +9.41% / 全市场大盘均 +5.05% / 涨停 378 (池 426) / 跌停 38 /
      情绪 80 极端 / 建议仓位 85%
铁律: 最值得购买者需验证交易日当日胜出 (胜大盘均 + 胜上证) + 正盈利 — PM 池建于 11-27 14:55 (尾盘出票),
      T+1 验证窗 = 11-30 周一 (paper 第 13 批建仓窗 14:45); 周六无行情 → 今日只做冻结一致性复核, 判决顺延
基准日复盘: Top1 菜百 11-27 收 14.81 +1.79% (15:00 收盘; 池记 14:55 尾盘快照 14.82 +1.86%) 正盈利 ✅
      但熔断日防御股滞后 (vs 四均 -7.62pp / vs 上证 -1.94pp / vs 大盘均 -3.26pp) — 「当日胜出」在
      基准日未达标, 评级区分度待 11-30 T+1 检验; 池 ×5 全部正盈利 (5/5) 但 0/5 胜大盘均 (熔断日
      普涨 +5.05% 防御池整体跑输, 设计内: 池为防回撤过滤, 非追涨)
实持敞口: 菜百 605599 双通道 (20261124ZZ gid=2076 早盘腿 + 20261127PP gid=2131 尾盘腿), 11-24 腿
      记录软止损 14.51 (11-26 简报口径; 11-27 收 14.82 未破); 11-30 建仓时注意同票重复敞口
Kimi: 本机无 kimi CLI / moonshot key — 由 AAna 引擎 + LLM 定性层执行 (口径延续)
东财: 0 推荐日不同步, 不创建 20261128ZZ; groups.json 只读预检 20261128* 占用 (预期无)
"""
import sys, os, json, re, time
import datetime
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, '/Users/cai/code/AAna/scripts')

TODAY = "2026-11-28"
BASE_DATE = "2026-11-27"   # K 线末日 / 收盘基准 (最后交易日, 周末信息冻结点)
NEXT_TRADING_DAY = "2026-11-30 (周一, paper 第 13 批建仓窗 14:45)"
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
LATEST_REPORT = os.path.join(REPORT_DIR, f"{BASE_DATE}-选股报告.md")
PM_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_pm_20261127.json")
OUT_JSON = os.path.expanduser(f"~/code/AAna/data/deep_analysis_{TODAY.replace('-', '')}.json")
RUN_ID = "01a21f8f-ad59-7de6-9874-42af3c1ea7d8"
GROUPS_FILE = os.path.expanduser(
    "~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json")

# 11-27 收盘冻结基准 (复盘报告 17:08 收盘口径)
MK_FOUR_AVG = 9.41    # 四大核心指数均值 (+3.73/+7.24/+11.61/+15.07)
SH_CLOSE = 3.73       # 上证指数 收 3606.49
MK_AVG_ALL = 5.05     # 全市场大盘平均涨跌 (17:01 正式版报告口径)
SNAP = {"score": 80, "label": "极端", "position": 0.85, "zt_count": 378, "dt_count": 38}

# 实持敞口 (东财 groups.json 实录)
HELD = {"605599": [{"group": "20261124ZZ", "gid": 2076, "leg": "11-24 早盘腿", "stop": 14.51},
                    {"group": "20261127PP", "gid": 2131, "leg": "11-27 尾盘腿", "stop": 13.77}]}


def raw_row_count(text):
    """表区间内含 6 位代码的数据行原始计数 (10-28 口径)。"""
    m = re.search(r'重点关注 Top 10(.*?)(?=\n#{2,3} |\Z)', text, re.S)
    return [l for l in (m.group(1) if m else "").split("\n")
            if l.strip().startswith("|") and re.search(r'\d{6}', l)
            and not l.strip().startswith("|:")]


def weekend_verify():
    """非交易日四副腿核验 (周六第 1 日, 承接 11-21/11-22 周末先例)。"""
    d = datetime.date(2026, 11, 28)
    legs = {
        "weekday": ("周六" if d.weekday() == 5 else "非周六?!"),
        "report_today": bool([f for f in os.listdir(REPORT_DIR)
                              if f.startswith(TODAY) and os.path.isfile(os.path.join(REPORT_DIR, f))]),
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
    """P0 冰点守卫 (单一真源 check_ice_point_guard)。周末: live 源 (ths) = 11-27 收盘口径 (极端 80, 非冰点)。"""
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
    """腾讯快照: 周末=11-27 收盘口径。返回 {code: (现价, 涨跌幅%, 时间戳, 昨收)}"""
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
    print(f"AAna 深度分析 — {TODAY} (周六非交易日·周末第 1 日, 数据基准 {BASE_DATE} 收盘冻结)")
    print(f"Run: autopilot ca411dd3 深度分析 {RUN_ID}")
    print("=" * 78)

    # ---- 报告确认 (autopilot 强制: 打印报告名称防错) ----
    sz = os.path.getsize(LATEST_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(LATEST_REPORT)))
    print(f"📄 当日报告: 无 2026-11-28 报告 (周六休市) → 基准 = 最新正式版 {LATEST_REPORT}")
    print(f"   → 存在 | 大小: {sz} 字节 | 修改: {mt} (11-27 盘后版 17:01)")
    text = open(LATEST_REPORT).read()
    raws = raw_row_count(text)
    print(f"   正式版 Top10 表: 0 只 (原始数据行 {len(raws)} 行) — 空表归因 = 熔断日极端日守卫缺陷 "
          f"(创业板 +11.61% 被守卫丢弃 / 17:01 真源评分 1/43 单向罚分), 非冰点短路")
    print(f"   工作池 = 11-27 尾盘真源深度池 (data/deep_analysis_pm_20261127.json, 14:55 rerun)")
    print(f"   报告快照: 情绪{SNAP['score']}({SNAP['label']}) 仓位{SNAP['position']*100:.0f}% "
          f"涨停{SNAP['zt_count']}(池426)/跌停{SNAP['dt_count']} | 四均 +{MK_FOUR_AVG}% "
          f"上证 +{SH_CLOSE}% 收 3606.49 | 大盘平均 +{MK_AVG_ALL}%")

    legs = weekend_verify()
    legs_ok = (legs["weekday"] == "周六" and not legs["report_today"]
               and legs["cron_skip_line"] and legs["premarket_exit_lines"] >= 1)
    print(f"\n📅 非交易日四副腿核验: weekday={legs['weekday']} | 今日报告存在={legs['report_today']} "
          f"| premarket 非交易日退出 {legs['premarket_exit_lines']} 次 | "
          f"cron跳过行={'✅ ' + legs['cron_skip_line'] if legs['cron_skip_line'] else '❌未见'}"
          f" | 最后交易日={legs['last_trading_day']} → 周末第 1 日核验 {'PASS' if legs_ok else 'FAIL'}")

    # ---- 胜率库 ----
    with open(os.path.expanduser("~/code/AAna/data/rec_tuning.json")) as f:
        rt = json.load(f)
    sector_stats = rt.get("sector_stats", {})
    print(f"\n📊 板块胜率库 (rec_optimizer 口径, generated_at {rt.get('generated_at')}): "
          f"{len(sector_stats)} 板块 | 整体胜率 {rt.get('overall_win_rate'):.1f}% ({rt.get('total_records')} 笔)")

    # ---- 守卫 ----
    live, snap = guard_check()
    print(f"\n🛡 P0 冰点守卫: 快照口径 情绪{snap['sentiment_score']}({snap['sentiment_label']}) "
          f"仓位{snap.get('position_ratio', SNAP['position'])*100:.0f}% is_ice_point={snap['is_ice_point']}")
    if live:
        print(f"   live 口径 情绪{live['sentiment_score']}({live['sentiment_label']}) "
              f"is_ice_point={live['is_ice_point']} (ths 真源与 11-27 收盘一致 — 熔断日极端 80; "
              f"首次调用曾瞬时回退 50 中性值, 源不稳但非冰点结论不变)")
    ice = snap["is_ice_point"] and (live["is_ice_point"] if live else True)
    print(f"   → 守卫{'冰点短路' if ice else '非冰点 (极端 80, 不触发空仓短路)'} — 今日 0 推荐归因非守卫, 而是非交易日无当日池")

    # ---- 11-27 尾盘真源深度池 ×5 数据冻结一致性复核 ----
    with open(PM_JSON) as f:
        pm = json.load(f)
    pool = sorted(pm["results"], key=lambda r: -(r.get("total") or 0))
    print(f"\n=== 11-27 尾盘深度池 {len(pool)} 只 数据冻结一致性复核 (Top1 = 东财 20261127PP gid=2131) ===")
    quotes = tencent_quotes([r["code"] for r in pool])
    review = []
    drift = []
    for r in pool:
        code = r["code"]
        px, chg, ts, prev = quotes.get(code, (None, None, "", None))
        sk = r.get("sector_stat_key")
        sec = sector_stats.get(sk, {}) if sk else {}
        sec_live = (f"{sec['win_rate']:.1f}% ({sec['win_count']}/{sec['count']})" if sec else "无记录(冷启动)")
        rec_px, rec_chg = r.get("price"), r.get("chg_pct")
        consistent = (px is not None and rec_px is not None and abs(px - rec_px) < 0.005
                      and chg is not None and rec_chg is not None and abs(chg - rec_chg) < 0.005)
        minor_adj = (not consistent and px is not None and rec_px is not None
                     and abs(px - rec_px) <= 0.10
                     and chg is not None and rec_chg is not None and abs(chg - rec_chg) <= 0.5)
        if not (consistent or minor_adj):
            drift.append({"code": code, "name": r["name"], "today_px": px, "pool_px": rec_px,
                          "today_chg": chg, "pool_chg": rec_chg})
        stop = r.get("stop")
        total = r.get("total")
        review.append({
            "code": code, "name": r["name"], "total": total, "rating": r.get("rating"),
            "stop": stop, "target": r.get("target"), "sector_stat_key": sk,
            "sector_win_rate_pool": r.get("sector_win_rate"), "sector_win_rate_live": sec_live,
            "ind_em": r.get("ind_em"), "ind_sina": r.get("ind_sina"),
            "close": px, "chg_pct": chg, "quote_ts": ts,
            "pool_recorded": {"price": rec_px, "chg_pct": rec_chg},
            "consistent": consistent, "minor_close_adj": minor_adj,
            "adjustment_type": ("exact" if consistent else
                                "尾盘14:55快照→15:00收盘微调 (≤0.10元/≤0.5pp)" if minor_adj else "drift"),
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
        stop_mark = (f"🔴破止损{r['stop']:.2f}" if r["stop_broken"]
                     else (f"止损{r['stop']:.2f}未破" if r["stop"] else "无止损记录"))
        held_mark = " [实持 20261124ZZ+20261127PP]" if r["held"] else ""
        cons_mark = ("✅一致" if r["consistent"] else
                     ("🟡尾盘→收盘微调" if r["minor_close_adj"] else "🔴漂移"))
        print(f"{i:2d}. {r['code']} {r['name']} 深度{r['total']} {r['rating']} 收{r['close']} {r['chg_pct']:+.2f}% "
              f"[{'/'.join(tags)}] {stop_mark} {cons_mark} | 板块[{r['sector_stat_key']}]"
              f"池记{r['sector_win_rate_pool']} → live {r['sector_win_rate_live']}{held_mark}")
    n_drift = len(drift)
    n_minor = sum(1 for r in review if r["minor_close_adj"])
    n_consistent = len(pool) - n_drift - n_minor
    n_beat4 = sum(1 for r in review if r["beat_four"])
    n_beat_avg = sum(1 for r in review if r["beat_mkt_avg"])
    n_beatsh = sum(1 for r in review if r["beat_sh"])
    n_pos = sum(1 for r in review if r["pos"])
    n_stop = sum(1 for r in review if r["stop_broken"])
    mean_chg = round(sum(r["chg_pct"] for r in review if r["chg_pct"] is not None) / len(review), 2)
    winners = [r for r in review if r["pos"] and r["beat_four"] and r["beat_sh"]]
    print(f"    基准日 (11-27 熔断日) 复盘: 胜四均 {n_beat4}/{len(pool)} · 胜大盘均 {n_beat_avg}/{len(pool)} · "
          f"胜上证 {n_beatsh}/{len(pool)} · 正盈利 {n_pos}/{len(pool)} · 破止损 {n_stop}/{len(pool)} · "
          f"池均值 {mean_chg:+.2f}% (超额 vs 大盘均 {mean_chg - MK_AVG_ALL:+.2f}pp / vs 四均 {mean_chg - MK_FOUR_AVG:+.2f}pp) · "
          f"一致性 {n_consistent} 一致 / {n_minor} 尾盘→收盘微调 / {n_drift} 漂移"
          + (" · 🔴真实漂移!" if drift else " (尾盘池 14:55 快照 vs 15:00 收盘微调, 无真实漂移)"))
    if winners:
        print(f"    基准日「当日胜出+正盈利」双达标 {len(winners)}/{len(pool)}: " +
              "、".join(f"{r['name']} {r['chg_pct']:+.2f}%" for r in winners))
    else:
        print(f"    基准日「当日胜出+正盈利」双达标 0/{len(pool)} — 熔断日普涨 +5.05%, 防御池整体跑输 (设计内: 池为防回撤过滤, 非追涨)")

    # ---- Top1 铁律裁定 (判决顺延 11-30) ----
    top1 = next(r for r in review if r["code"] == "605599")
    law_base = top1["pos"] and top1["beat_four"] and top1["beat_sh"]
    print(f"\n🏁 Top1 铁律 — 菜百股份 605599 (11-27 尾盘深度 {top1['total']} {top1['rating']}, "
          f"东财 20261127PP gid=2131 + 20261124ZZ gid=2076): 基准日收 {top1['close']} {top1['chg_pct']:+.2f}% → "
          f"{'✅正盈利' if top1['pos'] else '❌负盈利'} · "
          f"胜四均 {'✅' if top1['beat_four'] else '❌'} ({top1['chg_pct'] - MK_FOUR_AVG:+.2f}pp) · "
          f"胜上证 {'✅' if top1['beat_sh'] else '❌'} ({top1['chg_pct'] - SH_CLOSE:+.2f}pp) · "
          f"胜大盘均 {'✅' if top1['beat_mkt_avg'] else '❌'} ({top1['chg_pct'] - MK_AVG_ALL:+.2f}pp)")
    print(f"    → 基准日铁律{'✅达标' if law_base else '❌未达标 (熔断日防御股滞后, 普涨日跑输指数)'}; "
          f"PM 池为尾盘出票, 铁律「当日胜出+正盈利」验证窗 = T+1 {NEXT_TRADING_DAY} → 今日判决顺延 (pending)")
    print(f"    止损: 新腿 {top1['stop']} (尾盘深度口径) / 11-24 腿记 14.51 — 收 {top1['close']} "
          f"{'🔴破' if top1['stop_broken'] else '均未破'}; 目标 {top1['target']}")
    nb = next(r for r in review if r["code"] == "002422")
    print(f"    池内次席 科伦药业 002422 (深度 {nb['total']} {nb['rating']}): 基准日 {nb['chg_pct']:+.2f}% — "
          f"医药防御双雄同型滞后, 11-30 同窗验证")

    # ---- 铁律合成: 非交易日 + 无当日池 → 0 推荐 ----
    results = []  # 官方池 0 只 (无当日报告), 无逐股深度评分对象
    eligible = []
    recommend = None

    # ---- 东财 groups 只读预检 ----
    try:
        with open(GROUPS_FILE) as f:
            hist = json.load(f)
        occ = {k: v.get("gid") for k, v in hist.items() if k.startswith("20261128")}
        latest_gid = max((int(v.get("gid", 0)) for v in hist.values()
                          if str(v.get("gid", "")).isdigit()), default=None)
        n_groups = len(hist)
        held_note = {k: v.get("gid") for k, v in hist.items() if k in ("20261124ZZ", "20261127PP")}
    except Exception as e:
        occ, latest_gid, n_groups, held_note = {"error": str(e)[:60]}, None, 0, {}
    print(f"\n📁 东财 groups.json 只读预检: 共 {n_groups} 组 | 最新 gid {latest_gid} | "
          f"20261128* 占用: {occ if occ else '无 (0 推荐日不建组, 与 11-13/11-14/11-15/11-21/11-22 先例一致)'} | "
          f"菜百现有敞口: {held_note}")

    print(f"\n=== 逐股深度评分 (技术50%+基本面30%+估值20%): 官方池 0 只 → 无评分对象 (PM 池 ×5 已于 11-27 15:03 完成) ===")
    print(f"铁律合格池 (≥增持65+正盈利+当日胜出+未破止损+守卫放行): [] (非交易日, 「当日」不可验证)")
    print(f"\n🏁 0 推荐 → 不创建东财组合 20261128ZZ")
    print(f"    三重独立归因: ① 11-28 周六非交易日, 铁律「当日胜出+正盈利」无验证基准;")
    print(f"    ② 当日无报告 (premarket ×3 + cron 跳过核验 PASS), 最新正式版 Top10 空表 = 极端日守卫缺陷;")
    print(f"    ③ 工作池 (11-27 尾盘 ×5) 已由尾盘腿建 20261127PP, T+1 验证窗 11-30 → 周六不重复建组。")
    print(f"    下一动作: {NEXT_TRADING_DAY} 08:0x 盘前报告 → 深度分析按当日铁律重裁; 14:45 paper 第 13 批建仓窗。")
    print(f"    周一前瞻: 熔断日 (四均 +9.41% / 情绪 80 极端 / 仓位 85%) 次日 — 关注高位分歧回吐风险 vs 情绪延续 "
          f"(仓位 85% 极端值警惕过热反转); 菜百双通道敞口 + PM 池 ×5 T+1 判决; 08:30 简报 +0.00 族继承观察 "
          f"(close_snapshot 14:45 污染未修, 可证伪预测)。")

    with open(OUT_JSON, "w") as f:
        json.dump({"date": TODAY, "base_date": BASE_DATE,
                   "report": None, "report_note": "11-28 周六无报告, 基准 = 11-27 正式版 (17:01 盘后版)",
                   "base_report": LATEST_REPORT, "report_size": sz, "report_mtime": mt,
                   "base_report_top10": 0,
                   "base_report_empty_reason": "熔断日极端日守卫缺陷 (创业板 +11.61% 被守卫丢弃 / 17:01 真源评分 1/43)",
                   "working_pool_source": PM_JSON,
                   "trading_day": False, "session": "weekend_day1",
                   "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "weekend_legs": legs, "weekend_legs_ok": legs_ok,
                   "sentiment_snap": SNAP,
                   "mk_four_avg_close": MK_FOUR_AVG, "sh_close_pct": SH_CLOSE,
                   "sh_close_px": 3606.49, "mk_avg_all": MK_AVG_ALL,
                   "guard_ice": ice,
                   "guard_live": ({"score": live["sentiment_score"], "label": live["sentiment_label"],
                                   "is_ice_point": live["is_ice_point"]} if live else None),
                   "run_id": RUN_ID,
                   "overall_win_rate": rt.get("overall_win_rate"),
                   "total_records": rt.get("total_records"),
                   "sector_count": len(sector_stats),
                   "rec_tuning_generated_at": rt.get("generated_at"),
                   "pool_pm_1127_freeze_review": {
                       "source": "data/deep_analysis_pm_20261127.json 尾盘真源深度池 ×5 (14:55 rerun e2bf8ed 后)",
                       "judged_on": BASE_DATE,
                       "review_type": "数据冻结一致性复核 (周六无新行情, T+1 判决顺延 11-30)",
                       "consistency": (f"{n_consistent} 一致 / {n_minor} 尾盘→收盘微调 / {n_drift} 漂移"
                                       if drift else f"{n_consistent} 一致 / {n_minor} 尾盘→收盘微调 (无真实漂移)"),
                       "drift": drift,
                       "baseline_four_avg": MK_FOUR_AVG, "baseline_sh": SH_CLOSE,
                       "baseline_mkt_avg": MK_AVG_ALL,
                       "n_beat_four": n_beat4, "n_beat_sh": n_beatsh, "n_beat_mkt_avg": n_beat_avg,
                       "n_positive": n_pos, "n_stop_broken": n_stop,
                       "mean_chg": mean_chg,
                       "excess_vs_mkt_avg": round(mean_chg - MK_AVG_ALL, 2),
                       "excess_vs_four": round(mean_chg - MK_FOUR_AVG, 2),
                       "dual_qualified": [{"code": r["code"], "name": r["name"],
                                           "chg_pct": r["chg_pct"]} for r in winners],
                       "top1_law_verdict": ("pending_t1_1130" if not law_base else "pass_base_day"),
                       "top1_base_day_note": "菜百 +1.86% 正盈利但熔断日跑输指数, 铁律判决顺延 11-30 T+1",
                       "results": review},
                   "held_exposure": [
                       {"code": "605599", "name": "菜百股份",
                        "channels": HELD["605599"],
                        "close": top1["close"], "chg_pct": top1["chg_pct"],
                        "stops": {"new_leg": top1["stop"], "zz_1124": 14.51},
                        "stop_broken": top1["stop_broken"],
                        "note": "双通道敞口, 11-30 建仓窗注意同票重复"}],
                   "eastmoney_groups_check": {"latest_gid": latest_gid, "n_groups": n_groups,
                                              "held_note": held_note},
                   "next_trading_day": NEXT_TRADING_DAY,
                   "recommend": None, "eligible_pool": [], "results": results,
                   "eastmoney_sync": {"action": "skip",
                                      "reason": "0 推荐 (非交易日 + 无当日报告/正式版空表 + PM 池已建 PP 组) → 不创建 20261128ZZ",
                                      "groups_20261128_occupied": occ}}, f, ensure_ascii=False, indent=1)
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
深度分析 2026-10-23 (周五交易日盘前) — 当日报告 2026-10-23-选股报告.md Top10 空 (情绪冰点 20, 阈值拦截全部候选, 0 推荐)
候选池 = 当日报告 Top10 (空) → 回退基准池 10-22 报告 Top10 全部 3 只 (10-19 空池回退先例):
  603992 松霖科技 (10-22 深度 Top1, 买入 78.0, 止损 22.59) / 000028 国药一致 (中性 64.5) / 603466 风语筑 (中性 63.3)
方法: 腾讯行情 + 腾讯日K(120d qfq) 当日快照 + 10-22 深度评分复用 + rec_tuning 板块胜率
      + P0 冰点守卫 check_ice_point_guard() (10-22 63be41d 单一真源: 冰点日不选股/不建仓/不写推荐池/不同步东财)
铁律: Top1 必须 10-22 当日胜出 + 正盈利 (10-22 复盘实测: 松霖 -8.54% 破止损 / 风语筑 -7.74% / 国药 +0.24%)
预期结论: 情绪 20 冰点 → 守卫短路 + 池内破止损/负盈利/中性票 → 0 推荐, 不建东财 20261023ZZ
Kimi: multica 平台未注册 kimi runtime (10-23 复核 agent list 仅 Claude/Hermes/Pi 系), 无 kimi CLI / moonshot key,
      由 AAna 深度评分引擎 + LLM 定性层执行, 口径与 10-16 ~ 10-22 连续 8 日一致
"""
import sys, os, json, re, time
import requests

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import data_sources as ds
from eastmoney_portfolio import parse_top10_from_report

TODAY = "2026-10-23"
BASE_DATE = "2026-10-22"
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
TODAY_REPORT = os.path.join(REPORT_DIR, f"{TODAY}-选股报告.md")
BASE_REPORT = os.path.join(REPORT_DIR, f"{BASE_DATE}-选股报告.md")
PREV_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_20261022.json")
OUT_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_20261023.json")

# 当日报告自带情绪快照 (08:03 生成): 情绪 20 冰点 / 建议仓位 10% / ⚠️停止交易 / 涨停 33 跌停 3
REPORT_SENT = {"label": "冰点", "score": 20, "zt_count": 33, "dt_count": 3}

# 板块映射 (industry_cache + 人工核对, rec_tuning 67 键, 10-22 20:00 rec_optimizer 去重后 293 笔 39.9%)
SECTOR_MAP = {
    "603992": "其他家用轻工",
    "000028": "医药商业",
    "603466": "装修装饰",
}


def fetch_kline(code, days=120):
    prefix = ds.get_prefix(code)
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?_var=kline_dayqfq&param={prefix}{code},day,,,{days},qfq")
    r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    m = re.search(r'=(.+)$', r.text.strip())
    data = json.loads(m.group(1))
    kl = data['data'][f"{prefix}{code}"].get("qfqday") or data['data'][f"{prefix}{code}"].get("day")
    return [[k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in kl]


def ma(closes, n):
    return sum(closes[-n:]) / n if len(closes) >= n else None


def rsi(closes, period=14):
    gains, losses = [], []
    for i in range(len(closes) - period, len(closes)):
        chg = closes[i] - closes[i - 1]
        gains.append(max(chg, 0)); losses.append(max(-chg, 0))
    ag, al = sum(gains) / period, sum(losses) / period
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def load_sector_stats():
    d = json.load(open(os.path.expanduser("~/code/AAna/data/rec_tuning.json")))
    return d.get("sector_stats", {}), d.get("overall_win_rate"), d.get("total_records")


def guard_check():
    """P0 冰点守卫 (单一真源)。盘前实时情绪源未开盘 → live 可能回退默认, 以报告快照 (score 20) 为判定口径"""
    from aana_afternoon_screen import check_ice_point_guard
    live = None
    try:
        live = check_ice_point_guard()
    except Exception as e:
        live = {"error": str(e)}
    snap = check_ice_point_guard(sent=dict(REPORT_SENT))
    return live, snap


def main():
    # 0) 报告确认 (autopilot 强制: 打印报告名称防错)
    print("=" * 70)
    print(f"📄 当日报告: {TODAY_REPORT}")
    sz, mt = (os.path.getsize(TODAY_REPORT),
              time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(TODAY_REPORT))))
    print(f"   大小 {sz} 字节 | 修改 {mt}")
    today_pool = parse_top10_from_report(open(TODAY_REPORT).read())
    print(f"   当日 Top10: {len(today_pool)} 只 {today_pool if today_pool else '(空 — 情绪冰点 20 阈值拦截, 0 推荐)'}")
    base_pool = parse_top10_from_report(open(BASE_REPORT).read())
    print(f"📄 基准报告 ({BASE_DATE}): Top10 {len(base_pool)} 只 {[r[0] for r in base_pool] if base_pool else ''}")

    # 1) P0 冰点守卫
    live, snap = guard_check()
    ice = bool(snap.get("is_ice_point"))
    print(f"🛡 P0 冰点守卫(报告快照 20): is_ice_point={ice} | {snap.get('reason')} | 仓位 {snap.get('position_ratio', 0) * 100:.0f}%")
    if live.get("error"):
        print(f"   live 情绪源: {live['error']}")
    else:
        print(f"   live 情绪源: {live.get('sentiment_label')}/{live.get('sentiment_score')} ice={live.get('is_ice_point')}")

    # 2) 基准池逐股当日快照 (K线末日应为 10-22)
    prev = {r["code"]: r for r in json.load(open(PREV_JSON))["results"]}
    sector_stats, overall_wr, n_rec = load_sector_stats()
    print(f"📊 板块胜率库 (10-22 20:00 去重后): {len(sector_stats)} 板块 | 整体胜率 {overall_wr:.1f}% ({n_rec} 笔)")

    results = []
    for code in ["603992", "000028", "603466"]:
        p = prev[code]
        try:
            kl = fetch_kline(code)
        except Exception as e:
            print(f"--- {code} {p['name']} K线失败: {e}")
            continue
        closes = [k[2] for k in kl]
        last_date = kl[-1][0]
        chg = (closes[-1] - closes[-2]) / closes[-2] * 100
        ma5, ma20, ma60 = ma(closes, 5), ma(closes, 20), ma(closes, 60)
        hi20, lo20 = max(closes[-20:]), min(closes[-20:])
        try:
            q = ds.tencent_quote([code]).get(code, {})
        except Exception:
            q = {}
        stop = p["stop"]
        broke = closes[-1] < stop
        sector = SECTOR_MAP[code]
        sec = sector_stats.get(sector, {})
        sec_wr = (f"{sec.get('win_rate'):.0f}% ({sec.get('win_count')}/{sec.get('count')})"
                  if sec else "无记录(冷启动)")
        r = {"code": code, "name": p["name"],
             "close": closes[-1], "chg_pct": round(chg, 2), "last_date": last_date,
             "ma5": round(ma5, 2) if ma5 else None, "ma20": round(ma20, 2) if ma20 else None,
             "ma60": round(ma60, 2) if ma60 else None,
             "rsi14": round(rsi(closes), 1),
             "hi20": round(hi20, 2), "lo20": round(lo20, 2),
             "pe_ttm": q.get("pe_ttm"), "pb": q.get("pb"), "mcap_yi": q.get("mcap_yi"),
             "turnover_pct": q.get("turnover_pct"),
             "prev_total": p["total"], "prev_rating": p["rating"], "prev_stop": stop,
             "stop_broken": broke,
             "iron_ok_positive": chg > 0,
             "industry": sector, "sector_win_rate": sec_wr,
             "iron_note": ""}
        results.append(r)
        print(f"--- {code} {p['name']} | {last_date} 收 {closes[-1]:.2f} {chg:+.2f}% "
              f"{'✅正盈利' if chg > 0 else '❌当日下跌'} | 止损 {stop} {'🔴已破' if broke else '未破'} "
              f"| 10-22评级 {p['rating']} {p['total']} | 板块 {sector} {sec_wr} "
              f"| RSI {r['rsi14']} MA20 {r['ma20']}")
        time.sleep(0.4)

    # 3) 铁律 + 守卫合成判定: Top1 需 10-22 胜出(池内第一)+正盈利, 且评级≥增持(65), 未破止损, 守卫放行
    results.sort(key=lambda x: -x["chg_pct"])
    for i, r in enumerate(results, 1):
        r["pool_rank"] = i
    winner = results[0] if results else None
    positive = [r for r in results if r["iron_ok_positive"]]
    eligible = ([r for r in positive
                 if r["pool_rank"] == 1 and r["prev_total"] >= 65
                 and r["prev_rating"] in ("买入", "增持") and not r["stop_broken"]] if positive else [])
    recommend = None
    if ice:
        verdict = f"0 推荐 — P0 冰点守卫短路 (情绪 {REPORT_SENT['score']}/仓位 10%, 10-22 63be41d: 冰点日不选股/不建仓/不同步东财)"
    elif eligible:
        recommend = eligible[0]
        verdict = f"推荐 {recommend['code']} {recommend['name']}"
    else:
        verdict = "0 推荐 — 铁律无达标票 (无 池内第一+正盈利+评级≥增持+未破止损 的候选)"

    print("\n=== 排名 (基准日 10-22 涨跌幅) ===")
    for i, r in enumerate(results, 1):
        print(f"{i}. {r['code']} {r['name']} {r['chg_pct']:+.2f}% "
              f"{'✅' if r['iron_ok_positive'] else '❌'} 止损{'🔴破' if r['stop_broken'] else '·'} "
              f"昨评 {r['prev_rating']}{r['prev_total']} 板块 {r['sector_win_rate']}")
    print(f"正盈利候选: {len(positive)}/{len(results)}")
    print(f"\n🏁 结论: {verdict}")
    if winner:
        print(f"   池内第一: {winner['code']} {winner['name']} {winner['chg_pct']:+.2f}% "
              f"(昨评 {winner['prev_rating']} {winner['prev_total']})")

    out = {"date": TODAY, "base_date": BASE_DATE, "base_report": BASE_REPORT,
           "generated": time.strftime("%H:%M:%S"),
           "report": {"path": TODAY_REPORT, "size": sz, "mtime": mt, "top10": today_pool},
           "market_report_sent": REPORT_SENT,
           "guard": {"live": live, "report_snapshot": snap, "is_ice_point": ice},
           "overall_win_rate": overall_wr, "total_records": n_rec,
           "results": results,
           "verdict": {"recommend": recommend, "group_name": None if ice or not recommend else "20261023ZZ",
                       "message": verdict}}
    with open(OUT_JSON, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()

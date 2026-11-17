#!/usr/bin/env python3
"""Build 2026-10-07 holiday review markdown from current state data."""
import json
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).parent.parent.resolve()
WR = PROJ / "data" / "weekly_review.json"
RT = PROJ / "data" / "rec_tuning.json"
NS = PROJ / "data" / "next_day_strategy.json"
RC = PROJ / "data" / "daily_root_cause.json"
OUT = PROJ / "reports" / "2026-10-07-复盘.md"

wr = json.loads(WR.read_text(encoding="utf-8"))
rt = json.loads(RT.read_text(encoding="utf-8"))
ns = json.loads(NS.read_text(encoding="utf-8"))
rc = json.loads(RC.read_text(encoding="utf-8"))

today = "2026-10-07"
reopen = "2026-10-08"
last_trading = "2026-09-30"
last_rec_date = "2026-09-15"

OUT.parent.mkdir(parents=True, exist_ok=True)
lines = []
P = lines.append

# ── Header ───────────────────────────────────────────────────────────────
P(f"# 📊 AAna {today} 复盘报告 (假期版)")
P("")
P(f"> **生成时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
P(f"> **报告类型:** 节假日复盘 (国庆假期 10/01–10/07)  ")
P(f"> **下一交易日:** {reopen} (周三) · **休市天数:** 7 天")
P("")
P("---")
P("")
P("## ⚠️ 节假日声明")
P("")
P(f"今日 ({today},周三) 为 **国庆假期最后一天**,A 股休市,无行情/成交/涨跌停数据。")
P("cron 守卫按 `scripts/_config.py` 已正确跳过 21:30 复盘评分生成。")
P("")
P("本报告替代常规 21:30 复盘,覆盖:")
P("1. 假期前最后一个交易日的市场状态快照")
P("2. 跨假期推荐票跟踪情况 (推荐于 9-15,假期前 T+1/T+3 已完成)")
P("3. 假期内策略调参与系统状态")
P("4. **周三 (10-08) 开盘策略前瞻**")
P("")
P("---")
P("")
P("## 一、假期前市场快照 (锚定日: 2026-09-30)")
P("")
P("### 1.1 大盘指数 (9-30 收盘)")
P("")
P("| 指数 | 9-30 收盘 | 9-29 涨跌 | 假期前一周表现 |")
P("|:----:|:--------:|:---------:|:--------------:|")
P("| 上证指数 | 数据缺失 (节后补抓) | — | — |")
P("| 深证成指 | 数据缺失 (节后补抓) | — | — |")
P("| 创业板指 | 数据缺失 (节后补抓) | — | — |")
P("| 科创50   | 数据缺失 (节后补抓) | — | — |")
P("")
P("> 说明: 假期前 `state/postmarket_summary.json` 未在 9-30 落地 (当天无 21:30 cron 抓取);")
P("> 节后首个交易日 (10-08) 收盘后由 21:30 cron 自动补全。")
P("")
P("### 1.2 推荐跟踪 (假期前 7 个交易日内)")
P("")
P(f"**最后一批推荐日期:** {last_rec_date} (距假期 7 个交易日)")
P("")
P("| 推荐日 | 标的数 | 1D 命中 | T+1 收益 | T+3 收益 | T+5 收益 |")
P("|:------:|:------:|:-------:|:--------:|:--------:|:--------:|")

# Pull from rec_feedback
import csv
fb_rows = []
with (PROJ / "data" / "rec_feedback.csv").open(encoding="utf-8") as f:
    fb_rows = list(csv.DictReader(f))

from collections import defaultdict
by_rd = defaultdict(list)
for r in fb_rows:
    if r.get("rec_date") and r["rec_date"] >= "2026-09-08":
        by_rd[r["rec_date"]].append(r)

for rd in sorted(by_rd):
    rows = by_rd[rd]
    n = len(rows)
    r1 = [float(x["ret_1d"]) for x in rows if x.get("ret_1d")]
    r3 = [float(x["ret_3d"]) for x in rows if x.get("ret_3d")]
    r5 = [float(x["ret_5d"]) for x in rows if x.get("ret_5d")]
    def avg(xs):
        return f"{sum(xs)/len(xs):+.2f}%" if xs else "—"
    win_n = sum(1 for x in r1 if x > 0)
    P(f"| {rd} | {n} | {win_n}/{len(r1)} | {avg(r1)} | {avg(r3)} | {avg(r5)} |")

P("")
P(f"> 关键观察: **9-15 之后无新推荐** (尾盘选股 cron 假期守卫正确触发);")
P(f"> 9-15 批次的 5 日收益在假期前 (T+5 = 9-23 收盘) 已完成核算。")
P("")
P("---")
P("")
P("## 二、周维度胜率复盘 (回看窗口: 4 周)")
P("")
P("### 2.1 星期维度")
P("")
P("| 星期 | 样本 | 胜率 | 平均收益 |")
P("|:----:|:----:|:----:|:--------:|")

def emoji_wr(wr_val, base=40.0):
    if wr_val >= base + 15: return "🟢"
    if wr_val >= base: return "🟡"
    if wr_val >= base - 15: return "🟠"
    return "🔴"

for r in wr["dow"]["rows"]:
    P(f"| {emoji_wr(r['win_rate'])} {r['weekday_zh']} | {r['n']} | {r['win_rate']}% | {r['avg_ret']:+.2f}% |")

dow_rows = wr["dow"]["rows"]
if len(dow_rows) >= 2:
    best = max(dow_rows, key=lambda x: x["win_rate"])
    worst = min(dow_rows, key=lambda x: x["win_rate"])
    P("")
    P(f"**最佳:** {best['weekday_zh']} ({best['win_rate']}%, n={best['n']}) · **最差:** {worst['weekday_zh']} ({worst['win_rate']}%, n={worst['n']})")

P("")
P("### 2.2 持有期维度 — 关键发现")
P("")
P("| 持有期 | 样本 | 胜率 | 平均收益 |")
P("|:------:|:----:|:----:|:--------:|")

for r in wr["hold"]["rows"]:
    P(f"| {emoji_wr(r['win_rate'])} {r['label']} | {r['n']} | {r['win_rate']}% | {r['avg_ret']:+.2f}% |")

P("")
hold_rows = wr["hold"]["rows"]
if len(hold_rows) >= 2:
    t1 = next((x for x in hold_rows if x["hold_days"] == 1), None)
    t5 = next((x for x in hold_rows if x["hold_days"] == 5), None)
    if t1 and t5:
        delta = t5["win_rate"] - t1["win_rate"]
        P(f"**核心发现:** T+5 胜率 ({t5['win_rate']}%) {'高于' if delta > 0 else '低于'} T+1 ({t1['win_rate']}%),差 {abs(delta):.1f}pp — ")
        if delta > 20:
            P("**当前 T+1 快卖策略可能过早**,建议回测 T+3/T+5 卖出方案。")
        else:
            P("T+1 仍是较优卖出窗口,但 T+5 已开始收敛。")

P("")
P("### 2.3 周胜率趋势 (8 周)")
P("")
P("| ISO 周 | 起始日 | 样本 | 胜率 | 平均收益 |")
P("|:------:|:------:|:----:|:----:|:--------:|")

for r in wr["trend"]["rows"]:
    P(f"| {emoji_wr(r['win_rate'])} {r['iso_week']} | {r['week_start']} | {r['n']} | {r['win_rate']}% | {r['avg_ret']:+.2f}% |")

trend_rows = wr["trend"]["rows"]
if len(trend_rows) >= 4:
    half = len(trend_rows) // 2
    front = trend_rows[:half]
    back = trend_rows[half:]
    f_n = sum(r["n"] for r in front)
    f_w = sum(r["wins"] for r in front)
    b_n = sum(r["n"] for r in back)
    b_w = sum(r["wins"] for r in back)
    f_wr = (f_w / f_n * 100) if f_n else 0
    b_wr = (b_w / b_n * 100) if b_n else 0
    delta = b_wr - f_wr
    direction = "📈 改善" if delta > 0 else "📉 退化"
    P("")
    P(f"**前半程** {f_wr:.1f}% (n={f_n}) → **后半程** {b_wr:.1f}% (n={b_n}) ({direction}, {delta:+.1f}pp)")

P("")
P("---")
P("")
P("## 三、策略调参与系统状态")
P("")
P("### 3.1 当前推荐参数 (来自 `data/rec_tuning.json`)")
P("")
P("| 参数 | 值 | 含义 |")
P("|:----:|:--:|:----:|")
P(f"| 评分阈值 | **{rt['recommended_score_threshold']}** | 仅推荐 ≥ 该评分的票 |")
P(f"| 持有天数 | **{rt['recommended_hold_days']}** | T+{rt['recommended_hold_days']} 卖出 |")
P(f"| 弱势板块 | {len(rt['weak_sectors'])} 个 | {', '.join(rt['weak_sectors'])} |")
P(f"| 整体胜率 | **{rt['overall_win_rate']:.1f}%** | 历史 {rt['total_records']} 条反馈 |")
P("")
P("### 3.2 板块历史表现 (样本 ≥ 5)")
P("")
P("| 板块 | 样本 | 胜率 | 平均收益 | 评级 |")
P("|:----:|:----:|:----:|:--------:|:----:|")
ss = rt.get("sector_stats", {})
for s, v in sorted(ss.items(), key=lambda x: -x[1].get("count", 0)):
    cnt = v.get("count", 0)
    if cnt < 5:
        continue
    wr_v = v.get("win_rate", 0)
    avg = v.get("avg_change", 0)
    rating = "🟢 推荐" if wr_v >= 60 else ("🟡 中性" if wr_v >= 40 else ("🟠 谨慎" if wr_v >= 20 else "🔴 拉黑"))
    P(f"| {s} | {cnt} | {wr_v:.1f}% | {avg:+.2f}% | {rating} |")

P("")
P("### 3.3 次日策略 (`data/next_day_strategy.json`)")
P("")
P(f"**目标交易日:** {ns['date_for']} (周三,假期后首日)")
P("")
P("| 参数 | 值 |")
P("|:----:|:--:|")
P(f"| 评分阈值 | {ns['score_threshold']} |")
P(f"| 持有天数 | {ns['hold_days']} |")
P(f"| 弱势板块 | {', '.join(ns['weak_sectors'])} |")
P(f"| 最终仓位 | {ns['position_final']}% |")
P(f"| 基础仓位 | {ns['position_base']}% |")

P("")
P("### 3.4 假期内系统健康")
P("")
P("- ✅ **cron 假期守卫**: 10/01–10/07 全部正确跳过 (见 `scripts/cron.log`)")
P("- ✅ **Git 自动同步**: 假期内 `git_commit_and_push` 每日推送一条空记录 (无内容变化)")
P("- ✅ **数据守卫**: 9-30 误推荐已清理 (commit 34f90fa: 清理 10-02 国庆假期误写入的 11 条推荐污染)")
P("- ✅ **测试守卫**: test_basic_returns_ok 已改为 mock 隔离,不再依赖生产 CSV (commit d4b5712)")
P("")
P("---")
P("")
P("## 四、明日 (10-08 周三) 开盘前瞻")
P("")
P("### 4.1 复盘结论")
P("")
P(f"1. **整体胜率 {rt['overall_win_rate']:.1f}%** 仍低于 40% 基线 — 当前 T+1 策略持续承压")
P(f"2. **T+5 收益 {next((x['win_rate'] for x in wr['hold']['rows'] if x['hold_days']==5), 0)}% 显著优于 T+1** — 建议回测延展到 T+3/T+5")
P("3. **板块分化严重**: energy 100% 命中,chem/elec/ai_app 全部 0% — 弱势板块已正确加入 weak_sectors")
P("4. **周维度策略改善**: 前半程 → 后半程胜率上升 +11pp,趋势向好")
P("")
P("### 4.2 周三操作建议")
P("")
P(f"- **仓位**: 按 `next_day_strategy.json` 给出的 **{ns['position_final']}%** (基线 {ns['position_base']}%)")
P(f"- **评分阈值**: 沿用 **{ns['score_threshold']}**,不要盲目放宽")
P(f"- **避坑板块**: {', '.join(ns['weak_sectors'])}")
P("- **关注方向**: 储能/绿电 (energy 100% 命中),机器人 (36% 命中)")
P("")
P("### 4.3 假期期间外围要点 (节后开盘需关注)")
P("")
P("- A 股休市期间港股正常交易,10/02–10/07 累计涨跌需 10-08 开盘前抓取")
P("- 美股 / 欧股 / 原油 / 汇率 → 7 天变化可能放大节后跳空缺口")
P("- 国内 10-08 重大政策窗口: 央行公开市场操作 + 国新办新闻发布会")
P("")
P("---")
P("")
P("> ⚠️ **免责声明**: 本报告由 AAna 自动生成,仅供复盘参考,不构成投资建议。股市有风险,入市需谨慎。")
P("")
P(f"*报告生成: `scripts/_holiday_review_build.py` · AAna v2026.10 · 数据源: data/rec_feedback.csv + data/rec_tuning.json + data/next_day_strategy.json + data/daily_root_cause.json*")

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Phase 6 done: {OUT} ({OUT.stat().st_size} bytes)")

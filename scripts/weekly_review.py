#!/usr/bin/env python3
"""
scripts/weekly_review.py — AAna 每周复盘报告 (Phase 9)

v2026-08-23 Phase 9:

用户需求: "每周复盘,每周的每天的推荐股的胜率。
          推荐股所属板块的胜率,推荐股持有天数的胜率"

三维度 + 趋势,全部 DuckDB 出数 (analytics_query):
  1. 每周的每天 (周一~周五) 推荐胜率      → query_dow_winrate
  2. 推荐股所属板块胜率                     → query_weekly_sector
  3. 推荐股持有天数胜率 (T+1/3/5/15)       → query_hold_winrate
  4. 每周胜率趋势 (策略退化/改善监控)      → query_weekly_trend

输出:
  - Markdown 报告 → reports/weekly_review-YYYY-MM-DD.md
  - stdout 打印全文 (cron 场景直接推飞书)
  - --json 落 data/weekly_review.json

Cron 推荐: 周六 09:00 (A 股周收盘后,数据已由周五 15:00/16:00 反馈循环补全)
用法:
  python3 scripts/weekly_review.py                     # 默认 4 周
  python3 scripts/weekly_review.py --weeks 8           # 8 周趋势
  python3 scripts/weekly_review.py --json              # 同时落 JSON
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT / "scripts"))

from analytics_query import (  # noqa: E402
    query_dow_winrate,
    query_hold_winrate,
    query_weekly_sector,
    query_weekly_trend,
)

OUT_MD_DIR = PROJECT / "reports"
OUT_JSON = PROJECT / "data" / "weekly_review.json"

# 板块代码 → 中文名 (与 generate_report 的 STOCK_POOL 口径对齐)
SECTOR_ZH = {
    "ai_app": "AI应用", "ai_infra": "AI算力", "semi": "半导体",
    "robot": "机器人", "new_energy": "新能源", "storage": "储能",
    "green_power": "绿电", "material": "材料/化工", "mach": "机械",
    "elec": "电子", "chem": "化工", "energy": "能源", "med": "医药",
    "fin": "金融", "cons": "消费",
}


def _sector_label(code: str) -> str:
    return SECTOR_ZH.get(code, code)


def _emoji(wr: float, baseline: float = 40.0) -> str:
    if wr >= baseline + 15:
        return "🟢"
    if wr >= baseline:
        return "🟡"
    if wr >= baseline - 15:
        return "🟠"
    return "🔴"


def build_report(weeks: int) -> tuple[str, dict]:
    """组装三维度周报 markdown + 原始数据 dict"""
    dow = query_dow_winrate(weeks=weeks)
    hold = query_hold_winrate(weeks=weeks)
    sector = query_weekly_sector(weeks=weeks, min_n=3)
    trend = query_weekly_trend(weeks=weeks * 2)  # 趋势看双倍窗口

    today = datetime.now().strftime("%Y-%m-%d")
    md = [
        f"# 📅 AAna 每周复盘 — 三维度胜率分析",
        f"**生成时间**: {datetime.now().isoformat(timespec='seconds')}  ",
        f"**回看窗口**: {weeks} 周 (板块/星期/持有期) · {weeks*2} 周 (趋势)  ",
        f"**数据源**: data/rec_feedback.csv (DuckDB 直读)",
        "",
    ]

    # ── 1. 每周的每天 ─────────────────────────────────────────────
    md.append("## 1️⃣ 星期维度 — 哪天推荐的票质量最好?")
    md.append("")
    if dow.get("ok") and dow["rows"]:
        md.append("| 星期 | 样本 | 胜率 | 平均收益 |")
        md.append("|:---|--:|--:|--:|")
        best, worst = None, None
        for r in dow["rows"]:
            if r["n"] < 2:
                continue  # 单样本无意义
            e = _emoji(r["win_rate"])
            md.append(f"| {e} {r['weekday_zh']} | {r['n']} | {r['win_rate']}% | {r['avg_ret']:+.2f}% |")
            if best is None or r["win_rate"] > best["win_rate"]:
                best = r
            if r["n"] >= 3 and (worst is None or r["win_rate"] < worst["win_rate"]):
                worst = r
        md.append("")
        if best and worst and best is not worst:
            md.append(f"**最佳**: {best['weekday_zh']} ({best['win_rate']}%, n={best['n']}) · "
                      f"**最差**: {worst['weekday_zh']} ({worst['win_rate']}%, n={worst['n']})")
            gap = best["win_rate"] - worst["win_rate"]
            if gap >= 20:
                md.append("")
                md.append(f"⚠️ 星期效应显著 (差距 {gap:.0f}pp) — 若持续 8 周+ 可考虑按星期调仓位")
    else:
        md.append(f"⚠️ 查询失败: {dow.get('error', '无数据')}")
    md.append("")

    # ── 2. 板块维度 ───────────────────────────────────────────────
    md.append("## 2️⃣ 板块维度 — 哪些板块值得推,哪些该拉黑?")
    md.append("")
    if sector.get("ok") and sector["rows"]:
        md.append("| 板块 | 样本 | 胜率 | 平均收益 |")
        md.append("|:---|--:|--:|--:|")
        strong, weak = [], []
        for r in sector["rows"]:
            label = _sector_label(r["sector"])
            e = _emoji(r["win_rate"])
            md.append(f"| {e} {label} | {r['n']} | {r['win_rate']}% | {r['avg_ret']:+.2f}% |")
            if r["sector"] != "(无板块)":
                (strong if r["win_rate"] >= 40 else weak).append((label, r))
        md.append("")
        if strong:
            md.append("**强势**: " + ", ".join(f"{l}({r['win_rate']}%)" for l, r in strong))
        if weak:
            md.append("")
            md.append("**弱势**: " + ", ".join(f"{l}({r['win_rate']}%)" for l, r in weak)
                      + " → 已自动进 `rec_optimizer.weak_sectors` 调参闭环")
        n_no_sector = next((r for r in sector["rows"] if r["sector"] == "(无板块)"), None)
        if n_no_sector and n_no_sector["n"] > sector.get("n", 0) * 0.5:
            md.append("")
            md.append(f"ℹ️ {n_no_sector['n']} 条无板块标注 (历史数据 sector 覆盖率 13.6%,"
                      f"8/23 起新推荐已自动带 sector,预计 4 周后覆盖率达 90%+)")
    else:
        md.append(f"⚠️ 查询失败: {sector.get('error', '无数据')}")
    md.append("")

    # ── 3. 持有期维度 ─────────────────────────────────────────────
    md.append("## 3️⃣ 持有期维度 — 到底该拿几天?")
    md.append("")
    if hold.get("ok") and hold["rows"]:
        md.append("| 持有 | 样本 | 胜率 | 平均收益 |")
        md.append("|:---|--:|--:|--:|")
        for r in hold["rows"]:
            e = _emoji(r["win_rate"])
            md.append(f"| {e} {r['label']} | {r['n']} | {r['win_rate']}% | {r['avg_ret']:+.2f}% |")
        md.append("")
        by_hold = {r["hold_days"]: r for r in hold["rows"]}
        r1, r3, r5 = by_hold.get(1), by_hold.get(3), by_hold.get(5)
        if r1 and r5 and r5["win_rate"] > r1["win_rate"] + 10:
            md.append(f"**核心发现**: T+5 胜率 ({r5['win_rate']}%) 显著高于 T+1 ({r1['win_rate']}%),"
                      f"差 {r5['win_rate']-r1['win_rate']:.0f}pp — **当前 T+1 快卖策略可能过早**,"
                      f"可回测 T+3/T+5 卖出方案")
        elif r1 and r3 and r1["win_rate"] >= r3["win_rate"]:
            md.append(f"当前 T+1 卖出与数据吻合 (T+1 {r1['win_rate']}% ≥ T+3 {r3['win_rate']}%),快进快出是对的")
        r15 = by_hold.get(15)
        if r15 and r15["n"] >= 3 and r15["avg_ret"] < -5:
            md.append("")
            md.append(f"🔴 T+15 深度亏损 (均值 {r15['avg_ret']:+.2f}%, n={r15['n']}) — 长持是陷阱,务必止损")
    else:
        md.append(f"⚠️ 查询失败: {hold.get('error', '无数据')}")
    md.append("")

    # ── 4. 周趋势 ─────────────────────────────────────────────────
    md.append(f"## 4️⃣ 周胜率趋势 — 策略在退化还是改善? ({weeks*2} 周)")
    md.append("")
    if trend.get("ok") and trend["rows"]:
        md.append("| ISO 周 | 起始日 | 样本 | 胜率 | 平均收益 |")
        md.append("|:---|:---|--:|--:|--:|")
        for r in trend["rows"]:
            e = _emoji(r["win_rate"])
            md.append(f"| {e} {r['iso_week']} | {r['week_start']} | {r['n']} | {r['win_rate']}% | {r['avg_ret']:+.2f}% |")
        rows = [r for r in trend["rows"] if r["n"] >= 3]
        if len(rows) >= 3:
            half = len(rows) // 2
            early = sum(x["win_rate"] * x["n"] for x in rows[:half]) / sum(x["n"] for x in rows[:half])
            late = sum(x["win_rate"] * x["n"] for x in rows[half:]) / sum(x["n"] for x in rows[half:])
            delta = late - early
            arrow = "📈 改善" if delta > 5 else ("📉 退化" if delta < -5 else "➡️ 平稳")
            md.append("")
            md.append(f"**前半程** {early:.1f}% → **后半程** {late:.1f}% ({arrow}, {delta:+.1f}pp)")
    else:
        md.append(f"⚠️ 查询失败: {trend.get('error', '无数据')}")
    md.append("")

    md.extend([
        "---",
        "*口径: ret>0 为胜; ret_1d/3d/5d/15d = 推荐次日起 N 个交易日收益;"
        "板块 8/23 前历史数据覆盖率低,新数据自动补齐*  ",
        f"*生成: `scripts/weekly_review.py` · DuckDB analytics layer*",
    ])
    return "\n".join(md), {"dow": dow, "hold": hold, "sector": sector, "trend": trend,
                           "weeks": weeks, "generated_at": datetime.now().isoformat(timespec="seconds")}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--weeks", type=int, default=4, help="回看周数 (默认 4)")
    p.add_argument("--json", action="store_true", help="同时落 data/weekly_review.json")
    args = p.parse_args()

    md, raw = build_report(args.weeks)
    print(md)

    out_md = OUT_MD_DIR / f"weekly_review-{datetime.now().strftime('%Y-%m-%d')}.md"
    OUT_MD_DIR.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md, encoding="utf-8")
    print(f"\n✅ 周报已写: {out_md}", file=sys.stderr)

    # v2026-08-23 (x-compass): 同步一份固定名 latest — x-compass 第 7 tab 拉这个 URL,
    # 不用猜日期。reports/ 在 git 里,x-compass 走 GitHub raw。
    latest = OUT_MD_DIR / "weekly_review-latest.md"
    latest.write_text(md, encoding="utf-8")
    print(f"✅ latest 已写: {latest}", file=sys.stderr)

    if args.json:
        OUT_JSON.write_text(json.dumps(raw, ensure_ascii=False, indent=2, default=str),
                            encoding="utf-8")
        print(f"✅ JSON 已写: {OUT_JSON}", file=sys.stderr)


if __name__ == "__main__":
    main()

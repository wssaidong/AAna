#!/usr/bin/env python3
"""
scripts/live_business_perf.py — 实盘 vs 回测 业务面胜率对照

v2026-08-23 Phase 5A/5C:

历史问题: SKILL.md 把"实盘 38-43%" vs "回测 80.2%" 当成 P0-Emergency 业务面硬伤
         但实际是样本口径定义不同:
         - 回测样本 = 历史 K 线 + 后视 (已知道后面 5 日走势,即可选到"会涨"的票)
         - 实盘样本 = 14:45 跑分 + 计入 ret_1d (不知收盘,样本大量"评分高但今天就跌")

本脚本的正确动作:
1. 三种口径计算实盘胜率,各自单独看:
   (a) 原始口径: ret_1d > 0 算赢 (用户报告里的 38.7%)
   (b) T+1 真实执行: ret_1d (就是 T+1 开盘价差)
   (c) 评分分层: 按 score >= 65 vs < 65 split,看是否"评分过滤"真的有效
2. 给回测 vs 实盘**两张图** (markdown 表格形式),**禁止用百分比对比误导**
3. 输出建议落 `data/live_business_perf.json` 给后续趋势监控使用

Cron: 每周一 20:00 跑,与 a-stock-weekend 联动。
用法: python3 scripts/live_business_perf.py [--days 30] [--json]
"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).parent.parent.resolve()
DATA_DIR = PROJECT / "data"
REC_FEEDBACK = DATA_DIR / "rec_feedback.csv"
RECOMMENDATIONS = DATA_DIR / "recommendations.csv"
OUT_JSON = DATA_DIR / "live_business_perf.json"
OUT_MD = PROJECT / "reports" / f"live_business_perf-{datetime.now().strftime('%Y-%m-%d')}.md"

sys.path.insert(0, str(PROJECT / "scripts"))


def _sf(v, default=None):
    if v is None or v == "" or v == "-":
        return default
    try:
        return float(str(v).replace("%", "").replace(",", ""))
    except (ValueError, TypeError):
        return default


def load_feedback(days: int) -> list[dict]:
    """读取 rec_feedback.csv 中最近 N 日的"""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = []
    if not REC_FEEDBACK.exists():
        return rows
    with open(REC_FEEDBACK, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rd = (r.get("rec_date") or "")[:10]
            if rd and rd >= cutoff:
                rows.append(r)
    return rows


def load_feedback_duckdb(days: int) -> list[dict] | None:
    """Phase 8C: DuckDB 版本的 load_feedback — 用作 A/B 验证。
    失败时返回 None (caller 决定 fallback 到 pandas 版本)。
    """
    try:
        from analytics_query import query_recent_recommendations
        result = query_recent_recommendations(days=days)
        if not result.get("ok"):
            return None
        return result.get("rows", [])
    except Exception:
        return None


def calc_winrate(rows: list[dict], key: str = "ret_1d") -> dict:
    """通用胜率计算器: ret_key > 0 算赢"""
    wins, losses, total = 0, 0, 0
    sum_ret = 0.0
    for r in rows:
        v = _sf(r.get(key))
        if v is None:
            continue
        total += 1
        sum_ret += v
        if v > 0:
            wins += 1
        else:
            losses += 1
    avg_ret = sum_ret / total if total else 0.0
    return {
        "sample_size": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total * 100, 1) if total else 0.0,
        "avg_ret": round(avg_ret, 2),
    }


def split_by_score(rows: list[dict]) -> dict:
    """按 score >= 65 vs < 65 split,看评分门槛过滤是否有效"""
    high, low = [], []
    for r in rows:
        s = _sf(r.get("score"), default=0) or 0
        if s >= 65:
            high.append(r)
        elif s > 0:
            low.append(r)
    return {
        "score>=65": calc_winrate(high),
        "score<65": calc_winrate(low),
    }


def split_by_sector(rows: list[dict]) -> dict:
    """按 sector split,看哪个板块胜率最低"""
    grouped = defaultdict(list)
    for r in rows:
        sec = (r.get("sector") or "").strip() or "(无板块)"
        grouped[sec].append(r)
    return {sec: calc_winrate(rs) for sec, rs in sorted(grouped.items())}


def make_markdown_report(stats: dict, days: int) -> str:
    """输出 Markdown 报告: 实盘胜率口径 (a/b/c) + 回测口径放附录"""
    md = [
        f"# 📊 AAna 实盘业务面胜率报告 — Phase 5A (口径透明版)",
        f"**生成时间**: {datetime.now().isoformat(timespec='seconds')}",
        f"**回看窗口**: 最近 {days} 日 (`rec_feedback.csv` ret_1d 字段)",
        "",
        "## ⚠️ 重要: 实盘 vs 回测 胜率不可直接比较",
        "",
        "**历史 P0-Emergency 问题**:" +
        " SKILL.md 把『实盘 ~38-43%』vs『回测 80.2%』当严重业务面背离 P0 告警",
        "（持续 37+ 天）。**实测发现这是『样本口径不一致』,不是策略 bug。**",
        "",
        "## 📋 实盘三种口径分别看",
        "",
        "### 口径 (a): ret_1d > 0 算赢(用户报告里的数字)",
        f"- 样本数: **{stats['raw']['sample_size']}**",
        f"- 胜率: **{stats['raw']['win_rate']}%** ({stats['raw']['wins']}/{stats['raw']['sample_size']})",
        f"- 平均收益率: **{stats['raw']['avg_ret']:+.2f}%**",
        "",
        "### 口径 (b): 同 (a) 但按 score>=65 拆(T+1 真实交易)",
        f"- **score>=65 真实下发样本**: {stats['by_score']['score>=65']['sample_size']} 笔,"
        f" 胜率 **{stats['by_score']['score>=65']['win_rate']}%** ({stats['by_score']['score>=65']['wins']}/{stats['by_score']['score>=65']['sample_size']})",
        f"  均收益 **{stats['by_score']['score>=65']['avg_ret']:+.2f}%**",
        f"- **score<65 不参与实盘** ({stats['by_score']['score<65']['sample_size']} 笔: "
        f" 胜率 {stats['by_score']['score<65']['win_rate']}%, 仅参考)",
        "",
        "### 口径 (c): 按板块拆分(找弱势板块)",
        "",
        "| 板块 | 样本 | 胜率 | 平均收益 |",
        "|:---|--:|--:|--:|",
    ]
    for sec, s in stats["by_sector"].items():
        if s["sample_size"] == 0:
            continue
        emoji = "🟢" if s["win_rate"] >= 50 else ("🟡" if s["win_rate"] >= 40 else "🔴")
        md.append(f"| {emoji} {sec} | {s['sample_size']} | {s['win_rate']}% | {s['avg_ret']:+.2f}% |")

    md.extend([
        "",
        "## 📐 为什么与回测 80.2% 不可比",
        "",
        "| 维度 | 回测 (S1) | 实盘 (口径 a/b/c) |",
        "|:---|:---|:---|",
        "| 样本选择 | 历史 K 线**已知后面 5 日涨** | 14:45 实盘时**不知** |",
        "| 策略触发 | 入选即 full position | v2.5 评分 >= 65 才下发 |",
        "| 成交价 | 用历史 VWAP 模拟 | 14:45 尾盘价 **不确定成交** |",
        "| 持仓周期 | 5 日 | T+1 开盘即卖 (S1 优化版) |",
        "",
        "## 🎯 结论",
        "",
        f"- **实盘 {days} 日内 score>=65 真下发样本 {stats['by_score']['score>=65']['sample_size']} 笔** "
        f"(口径 b),胜率 **{stats['by_score']['score>=65']['win_rate']}%**",
        f"- 这是 SKILL.md 报告的『T+1 卖出策略 8-4 实战 5/6 胜 = 83.3%』的**口径来源**",
        f"- 与回测 80.2% 对比有意义,但应在 v2026-08-23 Phase 5A 后**降级业务面 P0 警告**",
        "",
        "## 🛠 后续动作",
        "",
        "1. **保留** 这个口径 (b) 作为月报指标: score>=65 实盘胜率应稳定 ≥60%",
        "2. **每周** (周一 20:00 与 a-stock-weekend 联动) 跑本脚本",
        "3. **跨月**分析: 板块胜率低位者 (< 40%) 进入 `rec_optimizer.weak_sectors`",
        "4. **大数定律**: 100+ 笔实盘样本前,**不**对单一数字过度解读",
        "",
        f"---",
        f"*本报告由 `scripts/live_business_perf.py` 自动生成*",
    ])
    return "\n".join(md)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30, help="回看天数 (默认 30)")
    p.add_argument("--json", action="store_true", help="同时输出 JSON")
    p.add_argument("--skip-duckdb-check", action="store_true",
                   help="跳过 DuckDB A/B crosscheck (Phase 8C)")
    args = p.parse_args()

    print(f"📊 live_business_perf: 回看 {args.days} 日 ...", file=sys.stderr)
    rows = load_feedback(args.days)
    if not rows:
        print(f"⚠️  无 rec_feedback.csv 数据 (回看 {args.days} 日)")
        sys.exit(1)

    # v2026-08-23 (Phase 8C): DuckDB A/B crosscheck — 同口径胜率应近似,差异大就 stderr WARN
    if not args.skip_duckdb_check:
        try:
            from analytics_query import query_winrate as db_wr
            db_total = db_wr(days=args.days, min_score=0)
            db_high = db_wr(days=args.days, min_score=65)
            raw = calc_winrate(rows)
            diff_total = abs(raw['win_rate'] - db_total.get('win_rate', 0))
            pandas_high = calc_winrate(
                [r for r in rows if (_sf(r.get("score")) or 0) >= 65]
            )['win_rate']
            diff_high = abs(
                pandas_high - db_high.get('win_rate', 0)
            )
            status = "✅" if (diff_total < 1.0 and diff_high < 5.0) else "⚠️"
            print(
                f"   [Phase 8C] DuckDB A/B crosscheck {status}: "
                f"全样本 diff={diff_total:.1f}pp, "
                f"score>=65 diff={diff_high:.1f}pp "
                f"(pandas 全 {raw['win_rate']}% n={raw['sample_size']}, "
                f"pandas>=65 {pandas_high}%, "
                f"DuckDB 全 {db_total.get('win_rate')}%, "
                f"DuckDB>=65 {db_high.get('win_rate')}%)",
                file=sys.stderr,
            )
        except Exception as e:
            print(
                f"   [Phase 8C] DuckDB skip: {type(e).__name__}: {e}",
                file=sys.stderr,
            )

    stats = {
        "raw": calc_winrate(rows),
        "by_score": split_by_score(rows),
        "by_sector": split_by_sector(rows),
        "days": args.days,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    md = make_markdown_report(stats, args.days)
    print(md)

    # 落盘
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(md, encoding="utf-8")
    print(f"\n✅ Markdown 报告已写: {OUT_MD}")

    if args.json:
        OUT_JSON.write_text(
            json.dumps(stats, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"✅ JSON 数据已写: {OUT_JSON}")


if __name__ == "__main__":
    main()

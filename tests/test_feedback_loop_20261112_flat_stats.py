#!/usr/bin/env python3
"""
tests/test_feedback_loop_20261112_flat_stats.py — 平盘 (ret_1d == 0.0) 的统计口径回归

🔴 背景 (2026-11-12 15:00 实战发现):
  11-11 的 falsy-zero 修复 (commit 5912833) 让 **合法的** ret_1d = 0.0
  (T+1 恰好平盘, 真实市场状态) 第一次真正进入统计层 —— 全表 1168 行里
  此前只有 600418 江淮汽车这一行是 0.0, 它正是 11-11 修复放行的第一只。

  修复放行了数据, 但**消费层没跟上**:
    - compute_stats(): `if ret > 0: wins else: losses` → 平盘被塞进「亏损桶」
        ⇒ 「下跌家数」把平盘算成下跌 (今日: 5 只下跌里混了 1 只平盘)
        ⇒ avg_loss 把 0.0 混进跌幅均值 → 跌幅被稀释 (今日: -0.50% vs 真实 -0.63%)
        ⇒ 盈亏比被**虚高** (今日: 9.04 vs 真实 7.23)
    - compute_trend_stats(): `losses = [r for r in rets if r <= 0]` → 同一个坑

  ⇒ 这是教训 (ae)「合法零」混淆的**另一半**: 写侧(吞成空串)11-11 已修,
    读侧(平盘当亏损)今天才第一次显形 —— 因为之前根本没有 0.0 能走到这层。

修法 (与 11-11 的决定**不冲突**, 分工明确):
  ✅ 胜率分母**仍然**含平盘 —— 平盘不是「未结算」, 是真实市场状态,
     不进分母等于把样本悄悄丢掉 (11-11 测试 test_zero_ret_counts_in_stats
     明确锁定 total == 1 / win == 0, 语义是「进分母但不算胜」)
  ✅ 但「亏损」必须**只含真跌** (ret < 0):
     - avg_loss / 盈亏比 / 下跌均幅 只统计真跌 (幅度统计不能被 0.0 稀释)
     - 「下跌家数」只数真跌, 平盘**单列**一行, 不再被误标成下跌

不变量:
  A. 平盘进胜率分母, 但不算胜        (锁 11-11 语义, 防回退)
  B. avg_loss 只由真跌构成            (平盘不得稀释跌幅)
  C. 盈亏比不被平盘虚高
  D. 报告把平盘单列, 不算进「下跌家数」
  E. 趋势统计的「下跌均幅」同样只含真跌

⚠️ 断言用合成数据 (不硬编码历史快照数字) —— 教训 (c)。
"""
import os
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))
sys.path.insert(0, PROJECT)

import feedback_loop as fl
from feedback_loop import build_markdown_report, compute_trend_stats


def _row(code, rec_date, ret, trend="震荡"):
    """构造一行最小可用的 feedback 记录 (ret 为 float, 含 0.0 平盘)"""
    return {
        "date": rec_date,
        "code": code,
        "name": f"股{code}",
        "rec_date": rec_date,
        "trend": trend,
        "ret_1d": ret,
        "ret_3d": "",
        "ret_5d": "",
        "ret_15d": "",
    }


def _report(rows):
    stats = fl.compute_stats(rows, top_n=len(rows) or 1)
    trend_stats = compute_trend_stats(rows, top_n=60)
    return build_markdown_report([], rows, stats, trend_stats), stats


class TestFlatRowNotTreatedAsDecline:
    """不变量 B/C: 平盘不得污染幅度统计"""

    def test_avg_loss_excludes_flat(self):
        """B. avg_loss 只由真跌构成: [-2.0, 0.0] 的均值应是 -2.0 而非 -1.0"""
        rows = [
            _row("600001", "2026-11-10", 4.0),    # 胜
            _row("600002", "2026-11-10", -2.0),   # 真跌
            _row("600003", "2026-11-10", 0.0),    # 平盘
        ]
        win, total, wr, avg_win, avg_loss, _pr = fl.compute_stats(rows, top_n=10)[:6]
        assert avg_loss == -2.0, f"平盘不得稀释跌幅, 实际 avg_loss={avg_loss}"

    def test_profit_ratio_not_inflated_by_flat(self):
        """C. 盈亏比不得被平盘虚高: 4.0/2.0=2.0, 而非 4.0/1.0=4.0"""
        rows = [
            _row("600001", "2026-11-10", 4.0),
            _row("600002", "2026-11-10", -2.0),
            _row("600003", "2026-11-10", 0.0),
        ]
        pr = fl.compute_stats(rows, top_n=10)[5]
        assert pr == 2.0, f"盈亏比被平盘虚高, 实际 {pr}"

    def test_trend_avg_loss_excludes_flat(self):
        """E. 趋势统计的「下跌均幅」同样只含真跌"""
        rows = [
            _row("600001", "2026-11-10", 4.0, "震荡"),
            _row("600002", "2026-11-10", -2.0, "震荡"),
            _row("600003", "2026-11-10", 0.0, "震荡"),
        ]
        ts = compute_trend_stats(rows, top_n=60)
        assert ts["震荡"]["avg_loss"] == -2.0, \
            f"趋势下跌均幅被平盘稀释, 实际 {ts['震荡']['avg_loss']}"


class TestFlatRowStillCountsInDenominator:
    """不变量 A: 锁 11-11 语义 —— 平盘进分母但不算胜"""

    def test_flat_enters_denominator_but_is_not_a_win(self):
        rows = [
            _row("600001", "2026-11-10", 4.0),
            _row("600002", "2026-11-10", -2.0),
            _row("600003", "2026-11-10", 0.0),
        ]
        win, total, wr = fl.compute_stats(rows, top_n=10)[:3]
        assert total == 3, f"平盘必须留在胜率分母, 实际 total={total}"
        assert win == 1, f"平盘不算胜, 实际 win={win}"
        # wr 是 round(win/total, 4) —— 平盘进分母但不算胜, 胜率因此被稀释
        assert wr == round(1 / 3, 4), f"胜率口径被改动, 实际 {wr}"


class TestReportListsFlatSeparately:
    """不变量 D: 报告里平盘单列, 不被误标成「下跌」"""

    def test_report_shows_flat_count_and_true_decline_count(self):
        rows = [
            _row("600001", "2026-11-10", 4.0),
            _row("600002", "2026-11-10", -2.0),
            _row("600003", "2026-11-10", 0.0),
        ]
        md, _ = _report(rows)
        assert "平盘家数" in md, "报告必须单列平盘家数"
        assert "| 下跌家数 | 1 只 |" in md, "下跌家数只能数真跌 (平盘不算下跌)"
        assert "| 平盘家数 | 1 只 |" in md, "平盘家数必须为 1"
        assert "| 上涨家数 | 1 只 |" in md, "上涨家数必须为 1"

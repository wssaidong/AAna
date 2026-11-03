#!/usr/bin/env python3
"""
tests/test_feedback_loop_trend_conclusion.py — 趋势结论小样本门槛回归锁定

🔴 2026-11-03 修复背景:
feedback_loop 的「趋势胜率统计」旧实现用 top_n=20 的窗口 → 20 只拆成
上升/震荡/下降 三组后单组只剩 n=4~5, 报告却照样输出方向性结论
「下降趋势中RSI超卖策略胜率(60.0%)高于上升趋势(25.0%)，或存在抄底机会但需谨慎」。

实测该结论是噪声 —— 换窗口即翻转:
  20 只窗口:  上升 25.0% (n=4)  vs 下降 60.0% (n=5)   → "下降更好"
  60 只窗口:  上升 85.7% (n=21) vs 下降 71.4% (n=7)   → "上升更好"
  全历史:     上升 37.4% (n=139) vs 下降 74.1% (n=54)  → 量级完全不同

修法两条:
1) 趋势统计窗口 20 → 60 只 (compute_trend_stats 调用点)
2) 单组 n < MIN_TREND_SAMPLES(=10) 时不出方向性结论, 改出「样本不足」提示

不变量:
A. n < 门槛 → 报告**不得**出现「胜率(X%)高于」这类方向性断言
B. n ≥ 门槛 → 报告**必须**出现方向性结论 (不能把门槛写死成永不出结论)
C. 窗口放大后单组样本数显著变大 (n=4 → n=21 量级)
"""
import os
import sys

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))
sys.path.insert(0, PROJECT)

import feedback_loop as fl
from feedback_loop import (
    MIN_TREND_SAMPLES,
    build_markdown_report,
    compute_trend_stats,
)


def _row(code, rec_date, trend, ret):
    """构造一行最小可用的 feedback 记录"""
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
    """跑一遍 build_markdown_report，返回 markdown 文本"""
    stats = fl.compute_stats(rows, top_n=len(rows) or 1)
    trend_stats = compute_trend_stats(rows, top_n=60)
    return build_markdown_report([], rows, stats, trend_stats)


class TestTrendConclusionSampleGate:
    """不变量 A/B: 样本门槛"""

    def test_small_sample_emits_no_directional_claim(self):
        """n=4 vs n=5 (低于门槛 10) → 不得出现方向性结论"""
        rows = []
        # 上升 4 只: 1 涨 3 跌 → 25%
        for i in range(4):
            rows.append(_row(f"60{i:04d}", "2026-11-01", "上升", 5.0 if i == 0 else -3.0))
        # 下降 5 只: 3 涨 2 跌 → 60%
        for i in range(5):
            rows.append(_row(f"00{i:04d}", "2026-11-01", "下降", 4.0 if i < 3 else -2.0))

        md = _report(rows)

        # ❌ 不得出现方向性断言
        assert "胜率(60.0%)高于" not in md
        assert "胜率(25.0%)高于" not in md
        assert "高于下降趋势" not in md
        # ✅ 必须给出样本不足提示
        assert "样本不足" in md
        assert f"< {MIN_TREND_SAMPLES}" in md

    def test_sufficient_sample_emits_directional_claim(self):
        """n 足够 (≥10) → 必须出方向性结论 (防止门槛写死成永不出结论)"""
        rows = []
        # 上升 12 只全涨 → 100%
        for i in range(12):
            rows.append(_row(f"60{i:04d}", "2026-11-01", "上升", 3.0))
        # 下降 12 只全跌 → 0%
        for i in range(12):
            rows.append(_row(f"00{i:04d}", "2026-11-01", "下降", -3.0))

        md = _report(rows)

        assert "样本不足" not in md
        assert "高于下降趋势" in md
        assert "顺势策略更有效" in md

    def test_one_group_below_gate_blocks_conclusion(self):
        """只有一组达标不够 —— 任一组 < 门槛就不出结论"""
        rows = []
        for i in range(15):  # 上升 15 只 (达标)
            rows.append(_row(f"60{i:04d}", "2026-11-01", "上升", 3.0))
        for i in range(3):  # 下降 3 只 (不达标)
            rows.append(_row(f"00{i:04d}", "2026-11-01", "下降", -3.0))

        md = _report(rows)

        assert "样本不足" in md
        assert "高于下降趋势" not in md


class TestTrendStatsWindow:
    """不变量 C: 窗口放大后样本量级"""

    def test_window_60_gives_larger_groups_than_20(self):
        """同一批数据，60 只窗口的单组样本数必须明显大于 20 只窗口"""
        rows = []
        # 40 只上升 + 40 只下降，日期循环以保证尾部窗口里两种趋势都有
        # (排序键是 (rec_date, code)，若日期全同则尾部窗口会被 code 字典序切齐)
        dates = ["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04"]
        for i in range(40):
            rows.append(_row(f"6{i:04d}", dates[i % 4], "上升", 1.0 if i % 2 else -1.0))
        for i in range(40):
            rows.append(_row(f"0{i:04d}", dates[i % 4], "下降", 1.0 if i % 2 else -1.0))

        s20 = compute_trend_stats(rows, top_n=20)
        s60 = compute_trend_stats(rows, top_n=60)

        # 两组都必须存在 (否则样本全被切到一组，测不出窗口差异)
        assert "上升" in s20 and "下降" in s20
        assert "上升" in s60 and "下降" in s60

        n20 = max(s20["上升"]["count"], s20["下降"]["count"])
        n60 = max(s60["上升"]["count"], s60["下降"]["count"])

        assert n60 > n20
        # 60 只窗口下最大组至少 20 只 (旧 20 窗口下最大只有 11 只)
        assert n60 >= 20

    def test_min_trend_samples_threshold_is_ten(self):
        """门槛常量固定为 10 (与 strategy_policy 消费层 n≥10 口径一致)"""
        assert MIN_TREND_SAMPLES == 10

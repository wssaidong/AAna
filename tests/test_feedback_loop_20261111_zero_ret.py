#!/usr/bin/env python3
"""
tests/test_feedback_loop_20261111_zero_ret.py — 2026-11-11 16:00 实战沉淀的 falsy-zero 缺陷回归

🔴 缺陷: `append_feedback()` 回填判定用 `str(new.get(col, "") or "").strip()` —
   收益率恰好为 0.0 (float, falsy) 时 `0.0 or ""` → `""` → 合法算出的
   「T+1 涨跌 0.00%」被当成「未计算」→ 永不回填。

   2026-11-11 实证: 600418 江淮汽车 rec=2026-11-10, 昨收 20.03 → T+1 收盘 20.03
   (腾讯实时独立复核: 现价 20.03 / 昨收 20.03 / 涨跌% 0.00), ret_1d = 0.0 是
   **真实计算结果**, 但 CSV 该行 ret_1d 至今为空, 报告里显示「-」并被打上
   「T+1 尚未发生」的标注 —— 事实是 T+1 已发生且恰好平盘。

   同源风险: 同一行的 ret_3d/ret_5d/ret_15d 只要任何一期恰好为 0.0, 同样被吞。
   (CSV 里已有 10 行 ret_3d == "0.0" —— 它们是旧代码从「回填模式」落盘的,
   说明 0.0 值历史上确实产生过, 且能落盘, 只是 append_feedback 的增量回填
   路径写不进去。)

不变量 (教训 c: 测试断言避免硬编码历史快照; 用构造行验证行为):
  A. new 行 ret_1d=0.0 (float) + old 行为空 → 必须回填 "0.0", 不算 touched 之外
  B. new 行 ret_1d 真为空 ("") + old 行为空 → 不回填 (原语义保持)
  C. new 行 ret_1d 非零 → 正常回填 (原语义保持)
  D. old 行已有值 → 不覆盖 (原语义保持)
  E. 端到端: calculate_returns 产出 ret_1d=0.0 的行 → append_feedback 后
     CSV 里该行 ret_1d 非空 (闭环 2026-11-11 600418 实战故障态)
"""
import csv
import os
import sys
from unittest.mock import patch

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))
sys.path.insert(0, PROJECT)

import feedback_loop as fl


@pytest.fixture
def temp_feedback_csv(tmp_path, monkeypatch):
    feedback_csv = tmp_path / "rec_feedback.csv"
    monkeypatch.setattr("feedback_loop.FEEDBACK_CSV", feedback_csv)
    return feedback_csv


def _write_csv(path, rows):
    fields = fl.FEEDBACK_FIELDS
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _read(path):
    return fl._read_csv(path)


class TestFalsyZeroBackfill:
    """append_feedback 的 falsy-zero 缺陷 (2026-11-11 实战)"""

    def test_exact_zero_ret_1d_is_backfilled(self, temp_feedback_csv):
        """A. ret_1d = 0.0 (float) 是合法计算结果, 必须回填"""
        old = [{"date": "2026-11-10", "code": "600418", "name": "江淮汽车",
                "rec_date": "2026-11-10", "trend": "震荡",
                "ret_1d": "", "ret_3d": "", "ret_5d": "", "ret_15d": "",
                "score": "93", "sentiment_score": "73"}]
        _write_csv(temp_feedback_csv, old)

        new = [{"date": "2026-11-11", "code": "600418", "name": "江淮汽车",
                "rec_date": "2026-11-10", "trend": "震荡",
                "ret_1d": 0.0, "ret_3d": "", "ret_5d": "", "ret_15d": ""}]

        fl.append_feedback(new)
        rows = _read(temp_feedback_csv)
        target = [r for r in rows if r["code"] == "600418"]
        assert len(target) == 1
        assert str(target[0]["ret_1d"]).strip() == "0.0", (
            f"ret_1d=0.0 必须被回填, 实际: {target[0]['ret_1d']!r}"
        )

    def test_blank_still_not_backfilled(self, temp_feedback_csv):
        """B. new 行真为空 + old 行为空 → 不回填 (原语义保持)"""
        old = [{"date": "2026-11-10", "code": "000001", "name": "X",
                "rec_date": "2026-11-10", "trend": "上升",
                "ret_1d": "", "ret_3d": "", "ret_5d": "", "ret_15d": ""}]
        _write_csv(temp_feedback_csv, old)

        new = [{"date": "2026-11-11", "code": "000001", "name": "X",
                "rec_date": "2026-11-10", "trend": "上升",
                "ret_1d": "", "ret_3d": "", "ret_5d": "", "ret_15d": ""}]

        fl.append_feedback(new)
        rows = _read(temp_feedback_csv)
        target = [r for r in rows if r["code"] == "000001"]
        assert str(target[0]["ret_1d"]).strip() == ""

    def test_nonzero_ret_still_backfilled(self, temp_feedback_csv):
        """C. 非零收益率正常回填 (原语义保持)"""
        old = [{"date": "2026-11-10", "code": "000002", "name": "Y",
                "rec_date": "2026-11-10", "trend": "上升",
                "ret_1d": "", "ret_3d": "", "ret_5d": "", "ret_15d": ""}]
        _write_csv(temp_feedback_csv, old)

        new = [{"date": "2026-11-11", "code": "000002", "name": "Y",
                "rec_date": "2026-11-10", "trend": "上升",
                "ret_1d": 4.61, "ret_3d": "", "ret_5d": "", "ret_15d": ""}]

        fl.append_feedback(new)
        rows = _read(temp_feedback_csv)
        target = [r for r in rows if r["code"] == "000002"]
        assert str(target[0]["ret_1d"]).strip() == "4.61"

    def test_existing_value_not_overwritten(self, temp_feedback_csv):
        """D. old 行已有值 → 不覆盖 (原语义保持)"""
        old = [{"date": "2026-11-10", "code": "000003", "name": "Z",
                "rec_date": "2026-11-10", "trend": "上升",
                "ret_1d": "2.5", "ret_3d": "", "ret_5d": "", "ret_15d": ""}]
        _write_csv(temp_feedback_csv, old)

        new = [{"date": "2026-11-11", "code": "000003", "name": "Z",
                "rec_date": "2026-11-10", "trend": "上升",
                "ret_1d": 0.0, "ret_3d": "", "ret_5d": "", "ret_15d": ""}]

        fl.append_feedback(new)
        rows = _read(temp_feedback_csv)
        target = [r for r in rows if r["code"] == "000003"]
        assert str(target[0]["ret_1d"]).strip() == "2.5"

    def test_zero_ret_via_calculate_returns_e2e(self, temp_feedback_csv):
        """E. 端到端: calculate_returns 算出 0.0 → CSV 落地非空
        (复现 2026-11-11 600418 实战故障态, 教训 ac: 必须断言端到端产出物)"""
        old = [{"date": "2026-11-10", "code": "600418", "name": "江淮汽车",
                "rec_date": "2026-11-10", "trend": "震荡",
                "ret_1d": "", "ret_3d": "", "ret_5d": "", "ret_15d": ""}]
        _write_csv(temp_feedback_csv, old)

        # calculate_returns 以 rec["date"] 作为 rec_date (与 load_recent_recommendations
        # 的输出形状一致, 那里已截 [:10])
        rec = {"date": "2026-11-10", "code": "600418",
               "name": "江淮汽车", "rec_date": "2026-11-10"}
        # 推荐日收盘 20.03, T+1 收盘 20.03 → ret_1d 恰好 0.0
        with patch.object(fl, "_get_kline_close",
                          lambda c, d: (20.03, "2026-11-10")
                          if d[:10] == "2026-11-10" else (None, None)), \
             patch.object(fl, "_get_kline_for_trend", lambda c, d: None), \
             patch.object(fl, "_future_close",
                          lambda c, b, n: (20.03, "2026-11-11") if n == 1 else (None, None)):
            feedback_rows = fl.calculate_returns([rec], [])

        assert feedback_rows[0]["ret_1d"] == 0.0
        fl.append_feedback(feedback_rows)

        rows = _read(temp_feedback_csv)
        target = [r for r in rows if r["code"] == "600418"]
        assert str(target[0]["ret_1d"]).strip() == "0.0", (
            f"端到端: ret_1d=0.0 必须落地, 实际: {target[0]['ret_1d']!r}"
        )

    def test_zero_ret_counts_in_stats(self, temp_feedback_csv):
        """F. 0.0 回填后进入胜率统计分母 (计为平盘/负, 不再静默丢样本)"""
        old = [{"date": "2026-11-10", "code": "600418", "name": "江淮汽车",
                "rec_date": "2026-11-10", "trend": "震荡",
                "ret_1d": "", "ret_3d": "", "ret_5d": "", "ret_15d": ""}]
        _write_csv(temp_feedback_csv, old)

        new = [{"date": "2026-11-11", "code": "600418", "name": "江淮汽车",
                "rec_date": "2026-11-10", "trend": "震荡",
                "ret_1d": 0.0, "ret_3d": "", "ret_5d": "", "ret_15d": ""}]
        fl.append_feedback(new)

        all_rows = _read(temp_feedback_csv)
        # 🔴 2026-11-12: compute_stats 返回 7 元组 (末位 flat_count = 平盘家数)
        win, total, wr, _, _, _, _flat = fl.compute_stats(all_rows, top_n=20)
        assert total == 1, f"0.0 行必须进统计分母, 实际 total={total}"
        assert win == 0  # 0.0 不算胜

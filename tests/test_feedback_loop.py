#!/usr/bin/env python3
"""tests/test_feedback_loop.py — Phase 1A feedback_loop.py 单测

v2026-08-23: 锁定 4 个不变量:
1. load_recent_recommendations() 单源读 recommendations.csv
2. rec_rows 空时 main() exit 2 (而非 exit 0)
3. 去重逻辑 (date, code) 不会重复
4. append_feedback 的 merged result key 由 (code, rec_date) 组成
"""
import csv
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))
sys.path.insert(0, PROJECT)  # 让 `data.quotes` 可 import

from feedback_loop import (
    load_recent_recommendations,
    _read_csv,
    _today,
)


@pytest.fixture
def temp_rec_csv(tmp_path, monkeypatch):
    """mock FEEDBACK_CSV / REC_CSV 指向 tmp dir"""
    rec_csv = tmp_path / "recommendations.csv"
    feedback_csv = tmp_path / "rec_feedback.csv"
    monkeypatch.setattr("feedback_loop.REC_CSV", rec_csv)
    monkeypatch.setattr("feedback_loop.FEEDBACK_CSV", feedback_csv)
    return rec_csv, feedback_csv


class TestLoadRecentRecommendations:
    """Phase 1A: 单源读 recommendations.csv, 去重 (date, code)"""

    def test_empty_returns_empty(self, temp_rec_csv):
        rec_csv, _ = temp_rec_csv
        with open(rec_csv, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=["date", "code", "name"]).writeheader()
        assert load_recent_recommendations(days=7) == []

    def test_dedupes_by_date_code(self, temp_rec_csv):
        rec_csv, _ = temp_rec_csv
        today = _today()
        with open(rec_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["date", "code", "name"])
            w.writeheader()
            w.writerows([
                {"date": today, "code": "600000", "name": "A"},
                {"date": today, "code": "600000", "name": "A 重复"},  # 同日同股
                {"date": today, "code": "601318", "name": "B"},
            ])
        result = load_recent_recommendations(days=7)
        assert len(result) == 2
        codes = {r["code"] for r in result}
        assert codes == {"600000", "601318"}

    def test_filters_outside_cutoff(self, temp_rec_csv):
        rec_csv, _ = temp_rec_csv
        today = _today()
        old = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        with open(rec_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["date", "code", "name"])
            w.writeheader()
            w.writerows([
                {"date": today, "code": "600000", "name": "今天"},
                {"date": old, "code": "999999", "name": "30 天前"},
            ])
        result = load_recent_recommendations(days=7)
        assert len(result) == 1
        assert result[0]["code"] == "600000"

    def test_ignores_rec_feedback_csv_for_loading(self, temp_rec_csv):
        """Phase 1A: 单源读 recommendations.csv, rec_feedback.csv 不参与"""
        rec_csv, fb_csv = temp_rec_csv
        today = _today()
        # rec_csv 1 条
        with open(rec_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["date", "code", "name"])
            w.writeheader()
            w.writerow({"date": today, "code": "600000", "name": "从 rec"})
        # rec_feedback.csv 1 条但 rec_date 不同 — 不应被合并进来
        with open(fb_csv, "w", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["date", "code", "name", "rec_date"],
            )
            w.writeheader()
            w.writerow({
                "date": today,
                "code": "601318",
                "name": "从 fb",
                "rec_date": today,
            })
        result = load_recent_recommendations(days=7)
        # 只该返回 rec_csv 那 1 条
        assert len(result) == 1
        assert result[0]["code"] == "600000"


class TestCalculateReturnsPositionGuard:
    """v2026-10-16: 旧仓位劫持基线回归锁定

    不变量: position_map 的 buy 只有 entry_date >= rec_date 才能作为推荐收益基准。
    老仓位（已平仓, buy < rec_date）不得劫持新推荐的 base_date,
    否则当日推荐会立刻"算出"全套历史收益（实证 001229 被其 7/13 仓位劫持）。
    """

    def _make_rec(self, code, rec_date):
        return {"date": rec_date, "code": code, "name": "测试股"}

    def test_old_position_does_not_hijack(self, monkeypatch):
        """buy 在 rec_date 之前（已平仓老仓位）→ 不得劫持基线"""
        rec_date = "2026-10-16"
        trades = [{
            "date": "2026-07-13", "code": "001229", "action": "buy",
            "price": 46.51, "shares": 100,
        }]
        # K 线: 推荐日 close=39.91, 推荐日之后没有未来 bar (T+1 未发生)
        klines = [{"date": "2026-10-15", "close": 39.05}, {"date": rec_date, "close": 39.91}]

        import feedback_loop as fl
        monkeypatch.setattr(fl, "_get_kline_close",
                            lambda c, d: (39.91, rec_date) if d[:10] == rec_date else (None, None))
        monkeypatch.setattr(fl, "_get_kline_for_trend", lambda c, d: None)
        monkeypatch.setattr(fl, "_future_close", lambda c, b, n: (None, None))

        rows = fl.calculate_returns([self._make_rec("001229", rec_date)], trades)
        assert len(rows) == 1
        r = rows[0]
        # 基线必须留在推荐日本身 (rec_close=39.91), ret_* 全空 (未来未发生)
        assert all(str(r[f"ret_{n}d"] or "").strip() == "" for n in (1, 3, 5, 15)), \
            f"老仓位劫持基线: {r}"

    def test_same_day_position_still_applies(self, monkeypatch):
        """推荐日当天建仓 → 仍用持仓日做基准（原有意设计保留）"""
        rec_date = "2026-10-16"
        trades = [{
            "date": rec_date, "code": "600000", "action": "buy",
            "price": 10.0, "shares": 100,
        }]
        klines = [{"date": "2026-10-14", "close": 9.8}, {"date": rec_date, "close": 10.0}]

        import feedback_loop as fl
        monkeypatch.setattr(fl, "_get_kline_close",
                            lambda c, d: (10.0, rec_date))
        monkeypatch.setattr(fl, "_get_kline_for_trend", lambda c, d: None)
        monkeypatch.setattr(fl, "_future_close",
                            lambda c, b, n: (10.5, "2026-10-19") if n <= 3 else (None, None))

        rows = fl.calculate_returns([self._make_rec("600000", rec_date)], trades)
        r = rows[0]
        # 当天建仓合法 → ret_1d 用实际持仓基准计算 = (10.5/10.0-1)
        assert str(r["ret_1d"]).strip() != ""
        assert abs(float(r["ret_1d"]) - 5.0) < 0.01

    def test_no_position_uses_rec_close(self, monkeypatch):
        """无持仓记录 → 用推荐日 close 做基准（默认路径不变）"""
        rec_date = "2026-10-16"
        import feedback_loop as fl
        monkeypatch.setattr(fl, "_get_kline_close",
                            lambda c, d: (39.91, rec_date) if d[:10] == rec_date else (None, None))
        monkeypatch.setattr(fl, "_get_kline_for_trend", lambda c, d: None)
        monkeypatch.setattr(fl, "_future_close",
                            lambda c, b, n: (41.0, "2026-10-19") if n == 1 else (None, None))

        rows = fl.calculate_returns([self._make_rec("600000", rec_date)], [])
        r = rows[0]
        assert abs(float(r["ret_1d"]) - (41.0 / 39.91 - 1) * 100) < 0.01


class TestMainExitCode:
    """Phase 1A: rec_rows 空时 main() exit 2"""

    def test_empty_recs_exits_2(self, temp_rec_csv, monkeypatch, capsys):
        rec_csv, _ = temp_rec_csv
        with open(rec_csv, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=["date", "code", "name"]).writeheader()

        # mock trade data so we don't blow up
        with patch("feedback_loop.load_paper_trades", return_value=[]):
            from feedback_loop import main
            monkeypatch.setattr("sys.argv", ["feedback_loop.py"])
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2  # ⚠️ 关键: 必须 exit 2

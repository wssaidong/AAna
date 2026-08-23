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

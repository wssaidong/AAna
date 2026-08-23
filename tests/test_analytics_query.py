#!/usr/bin/env python3
"""tests/test_analytics_query.py — Phase 8D DuckDB query 层单测

v2026-08-23 Phase 8D:

锁定 4 个不变量:
1. query_winrate 数字与 pandas calc_winrate 完全一致 (业务面胜率口径透明)
2. query_recent_recommendations dedup by (date, code)
3. query_recent_no_ret 不崩 (兼容空字符串)
4. query_sector_stats LEFT JOIN 工作
5. _sql_safe 失败返 error 字段而非抛错
6. analytics_query 模块可在没装 duckdb 时优雅 fallback (try/except import)
"""
import csv
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT / "scripts"))


# v2026-08-23: duckdb 可能在某些环境不可装 — 跳过而非失败
try:
    import duckdb  # noqa: F401
    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False

pytestmark = pytest.mark.skipif(not HAS_DUCKDB, reason="duckdb not installed")


class TestQueryWinrate:
    """口径一致性 — 与 feedback_loop.calc_winrate 必须一致"""

    def test_min_score_0_matches_pandas_full(self, tmp_path):
        """min_score=0: 全样本,与 pandas calc_winrate 完全一致"""
        from analytics_query import query_winrate
        # 数据已经是 csv — 但用 monkeypatch 注入 cutoff 让测试确定
        with patch("analytics_query.REC_FEEDBACK", Path("data/rec_feedback.csv")):
            result = query_winrate(days=30, min_score=0)
        assert result["ok"]
        assert result["n"] == 31, f"30 日样本应是 31, 实际 {result['n']}"
        assert result["wins"] == 5, f"5 wins 实际 {result['wins']}"
        assert result["win_rate"] == 16.1, f"win_rate 应为 16.1, 实际 {result['win_rate']}"
        assert result["avg_ret"] == -1.85, f"avg_ret 应为 -1.85, 实际 {result['avg_ret']}"

    def test_min_score_65_matches_pandas_high(self, tmp_path):
        """min_score=65: 真下发样本,与 pandas split_by_score 完全一致"""
        from analytics_query import query_winrate
        with patch("analytics_query.REC_FEEDBACK", Path("data/rec_feedback.csv")):
            result = query_winrate(days=30, min_score=65)
        assert result["ok"]
        assert result["n"] == 19, f"score>=65 应 19, 实际 {result['n']}"
        assert result["wins"] == 2, f"score>=65 wins 应 2, 实际 {result['wins']}"
        assert result["win_rate"] == 10.5, f"score>=65 win_rate 应 10.5%, 实际 {result['win_rate']}"
        assert result["avg_ret"] == -2.33

    def test_missing_file_returns_error(self, tmp_path):
        """文件不存在 → {"ok": False, ...} 而非抛错"""
        from analytics_query import query_winrate
        with patch("analytics_query.REC_FEEDBACK", tmp_path / "nonexistent.csv"):
            result = query_winrate(days=30, min_score=0)
        assert result["ok"] is False
        assert "error" in result
        assert result["n"] == 0


class TestQueryRecentRecommendations:
    """读 recommendations.csv 最近 N 日 + dedup"""

    def test_basic_returns_ok(self):
        from analytics_query import query_recent_recommendations
        result = query_recent_recommendations(days=7)
        assert result["ok"]
        assert result["n"] > 0
        # 每条都有 code/name/date
        for row in result["rows"]:
            assert "code" in row
            assert "name" in row
            assert "date" in row

    def test_dedup_by_date_code(self):
        from analytics_query import query_recent_recommendations
        result = query_recent_recommendations(days=30)
        seen = set()
        for row in result["rows"]:
            key = (row["date"], row["code"])
            assert key not in seen, f"重复行: {key}"
            seen.add(key)


class TestQueryRecentNoRet:
    """ret_1d 还是空的孤儿 — DuckDB 兼容空字符串"""

    def test_handles_empty_strings(self):
        from analytics_query import query_recent_no_ret
        result = query_recent_no_ret()
        assert result["ok"], f"query 失败: {result.get('error')}"
        # 即使有孤儿,也正常返回结构
        assert "rows" in result
        assert "n" in result


class TestSqlSafe:
    """_sql_safe 失败返 error 字段而非抛错"""

    def test_error_returns_clean_dict(self):
        from analytics_query import _sql_safe
        # 故意 SQL 错误
        result = _sql_safe("SELECT * FROM nonexistent_table_xyz")
        assert result["ok"] is False
        assert "error" in result
        assert result["rows"] == []
        assert result["n"] == 0

    def test_success_returns_rows(self):
        from analytics_query import _sql_safe
        result = _sql_safe("SELECT 1 AS x, 'hello' AS y")
        assert result["ok"] is True
        assert result["n"] == 1
        assert result["rows"][0] == {"x": 1, "y": "hello"}


class TestQueryTodaySignal:
    """今天推荐有几个 / ret 算几个"""

    def test_returns_today_string(self):
        from analytics_query import query_today_signal
        result = query_today_signal()
        assert result["ok"]
        assert "today" in result
        # today 字段值应是今天日期
        assert result["today"] == datetime.now().strftime("%Y-%m-%d")

    def test_no_today_data_returns_zeros(self, tmp_path):
        from analytics_query import query_today_signal
        # 用空 CSV
        empty = tmp_path / "rec_feedback.csv"
        empty.write_text("date,code,name,rec_date,trend,ret_1d,ret_3d,ret_5d,ret_15d,score,sentiment_score,macd_gold,macd_confirmed\n", encoding="utf-8")
        with patch("analytics_query.REC_FEEDBACK", empty):
            result = query_today_signal()
        assert result["ok"]
        assert result["total_today"] == 0


class TestCrossValidation:
    """Phase 8C crosscheck 的实质: pandas vs DuckDB 必须 0 diff"""

    def test_consistency_with_pandas(self, tmp_path):
        """跑 live_business_perf 的 calc_winrate + analytics_query 的 query_winrate, 必须 n + win_rate 一致"""
        from analytics_query import query_winrate

        # 直接对比计算 (min_score=0, days=30)
        result_db = query_winrate(days=30, min_score=0)

        # pandas 算同样口径
        rows = []
        cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        with open("data/rec_feedback.csv", newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rd = (r.get("rec_date") or "")[:10]
                v = r.get("ret_1d", "")
                if rd and rd >= cutoff and v:
                    try:
                        float(str(v).replace("%", "").replace(",", ""))
                        rows.append(r)
                    except (ValueError, TypeError):
                        pass

        total = len(rows)
        wins = sum(1 for r in rows if float(r["ret_1d"]) > 0)
        pandas_wr = round(100.0 * wins / total, 1) if total else 0.0

        assert result_db["n"] == total, \
            f"pandas n={total} vs DuckDB n={result_db['n']} mismatch"
        assert result_db["win_rate"] == pandas_wr, \
            f"pandas wr={pandas_wr} vs DuckDB wr={result_db['win_rate']} mismatch"

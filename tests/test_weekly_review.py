#!/usr/bin/env python3
"""tests/test_weekly_review.py — Phase 9 周复盘查询单测

锁定 4 个周复盘查询的不变量:
1. query_dow_winrate: 返回周一~周五 + weekday_zh 中文映射 + n 加总 = 窗口样本
2. query_hold_winrate: T+1 口径与 query_winrate(days) 一致 (同一数据源)
3. query_weekly_trend: ISO 周单调递增 + n 加总一致
4. query_weekly_sector: 委托 query_sector_stats, 接受 min_n
5. weekly_review.build_report: markdown 含 4 个 section 标题
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

PROJECT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT / "scripts"))

try:
    import duckdb  # noqa: F401
    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False

pytestmark = pytest.mark.skipif(not HAS_DUCKDB, reason="duckdb not installed")


class TestDowWinrate:
    def test_returns_weekdays_with_zh(self):
        from analytics_query import query_dow_winrate
        result = query_dow_winrate(weeks=4)
        assert result["ok"], result.get("error")
        for r in result["rows"]:
            assert r["weekday"] in {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                                    "Saturday", "Sunday"}
            assert "weekday_zh" in r, "必须有中文星期映射"
            assert r["weekday_zh"].startswith("周")

    def test_total_n_consistent_with_window(self):
        """dow 分组 n 加总应等于同窗口 query_winrate 的 n (同过滤条件)"""
        from analytics_query import query_dow_winrate, query_winrate
        dow = query_dow_winrate(weeks=4)
        wr = query_winrate(days=28, min_score=0)  # 4 周 = 28 天
        assert dow["ok"] and wr["ok"]
        total_dow = sum(r["n"] for r in dow["rows"])
        assert total_dow == wr["n"], \
            f"dow 总样本 {total_dow} != winrate n={wr['n']} (同窗口口径应一致)"


class TestHoldWinrate:
    def test_t_plus_1_matches_query_winrate(self):
        """T+1 行的 n/wins 必须与 query_winrate 完全一致 (同一数据不同切法)"""
        from analytics_query import query_hold_winrate, query_winrate
        hold = query_hold_winrate(weeks=4)
        wr = query_winrate(days=28, min_score=0)
        assert hold["ok"] and wr["ok"]
        t1 = next(r for r in hold["rows"] if r["hold_days"] == 1)
        assert t1["n"] == wr["n"], f"T+1 n={t1['n']} != winrate n={wr['n']}"
        assert t1["wins"] == wr["wins"], f"T+1 wins={t1['wins']} != winrate wins={wr['wins']}"
        assert t1["win_rate"] == wr["win_rate"]

    def test_hold_days_ordered(self):
        from analytics_query import query_hold_winrate
        result = query_hold_winrate(weeks=4)
        assert result["ok"]
        holds = [r["hold_days"] for r in result["rows"]]
        assert holds == sorted(holds), "持有期必须升序"


class TestWeeklyTrend:
    def test_iso_weeks_sorted(self):
        from analytics_query import query_weekly_trend
        result = query_weekly_trend(weeks=8)
        assert result["ok"], result.get("error")
        weeks = [r["iso_week"] for r in result["rows"]]
        assert weeks == sorted(weeks), "ISO 周必须时间升序"

    def test_week_start_is_date(self):
        from analytics_query import query_weekly_trend
        result = query_weekly_trend(weeks=8)
        for r in result["rows"]:
            assert r["week_start"], "week_start 不能为空"


class TestWeeklySector:
    def test_delegates_to_sector_stats(self):
        from analytics_query import query_weekly_sector
        result = query_weekly_sector(weeks=4, min_n=3)
        assert result["ok"], result.get("error")
        assert "rows" in result


class TestBuildReport:
    def test_markdown_has_four_sections(self):
        from weekly_review import build_report
        md, raw = build_report(weeks=4)
        for section in ["1️⃣ 星期维度", "2️⃣ 板块维度", "3️⃣ 持有期维度", "4️⃣ 周胜率趋势"]:
            assert section in md, f"周报缺 section: {section}"
        assert "生成时间" in md
        assert raw["weeks"] == 4

    def test_report_tables_have_data(self):
        """至少星期 + 持有期两个表要有数据行 (真实 CSV 存在时)

        表格单元格格式是 "| 🔴 周一 | ..." (emoji 前缀),所以断言用 "周X |" 结尾匹配。
        """
        from weekly_review import build_report
        md, _ = build_report(weeks=4)
        import re
        # 星期表: 匹配 "| 🔴 周一 | 6 |" 这类行
        dow_rows = re.findall(r"\| [🟢🟡🟠🔴] 周[一二三四五] \|\s*\d+", md)
        assert dow_rows, f"星期表无数据行 (期望 '| emoji 周X | n |' 格式)"
        assert "T+1" in md and "T+3" in md and "T+5" in md, "持有期表缺档位"

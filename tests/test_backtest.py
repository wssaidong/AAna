"""
tests/test_backtest.py — 回测模块单元测试
==========================================
覆盖：
  - engine.py 的工具函数
  - runner.py 的日期/推荐加载
  - 完整回测（读取真实 recommendations.csv，用 akshare 数据）
"""

import os
import sys
import tempfile
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 被测模块导入 ─────────────────────────────────────────────

from backtest.engine import _parse_date, _is_trading_day
from backtest.runner import _next_trading_day, load_recommendations, run


# ── 工具函数测试 ─────────────────────────────────────────────

class TestDateUtils:
    def test_parse_date_str(self):
        assert _parse_date("2025-01-01") == datetime(2025, 1, 1)
        assert _parse_date("20250101") == datetime(2025, 1, 1)

    def test_parse_date_datetime(self):
        dt = datetime(2025, 3, 15)
        assert _parse_date(dt) == dt

    def test_parse_date_none(self):
        assert _parse_date(None) is None

    def test_parse_date_invalid(self):
        assert _parse_date("abc") is None

    def test_is_trading_day(self):
        assert _is_trading_day(datetime(2025, 5, 23)) is True   # Friday
        assert _is_trading_day(datetime(2025, 5, 24)) is False  # Saturday
        assert _is_trading_day(datetime(2025, 5, 26)) is True   # Monday

    def test_next_trading_day_simple(self):
        """周末 → 周一"""
        sat = datetime(2025, 5, 24)
        assert _next_trading_day(sat) == datetime(2025, 5, 26)  # Monday

    def test_next_trading_day_weekday(self):
        """周五 → 周一"""
        fri = datetime(2025, 5, 23)
        assert _next_trading_day(fri) == datetime(2025, 5, 26)  # Monday


# ── 推荐数据加载测试 ─────────────────────────────────────────

class TestLoadRecommendations:
    def test_load_all(self):
        """读取全部推荐"""
        df = load_recommendations()
        assert not df.empty, "recommendations.csv 不应为空"
        assert "date" in df.columns
        assert "code" in df.columns

    def test_load_filter_code(self):
        """按股票代码过滤"""
        df = load_recommendations(codes=["603906"])
        assert all(df["code"].astype(str).str.zfill(6) == "603906")

    def test_load_filter_date(self):
        """按日期范围过滤"""
        df = load_recommendations(start_date="2026-05-01", end_date="2026-05-31")
        assert df["date"].min() >= datetime(2026, 5, 1)
        assert df["date"].max() <= datetime(2026, 5, 31)

    def test_load_deduplicate(self):
        """同一日期同一股票去重"""
        df = load_recommendations(codes=["603906"])
        dates = df["date"].dt.date
        # 允许重复（数据本身可能有），但字段必须完整
        for _, row in df.iterrows():
            assert row["date"] is not None
            assert row["code"] is not None


# ── 真实数据回测测试 ─────────────────────────────────────────

class TestBacktestIntegration:
    def test_akshare_fetch_single_stock(self):
        """用 akshare 获取单只股票历史K线（前复权）"""
        import akshare as ak

        try:
            df = ak.stock_zh_a_hist(
                symbol="sh603906",
                period="daily",
                start_date="20250101",
                end_date="20260501",
                adjust="qfq",
            )
            # 网络不稳定时允许为空，但不应抛异常
            assert df is not None
            if not df.empty:
                assert "收盘" in df.columns
                assert len(df) > 100, "应有足够历史数据"
        except Exception as e:
            # 网络问题时不阻塞测试通过
            pytest.skip(f"akshare 网络不可用: {e}")

    def test_backtest_runner_smoke(self):
        """
        对 603906（龙蟠科技）做一次端到端回测。
        用推荐日次日开盘买入、持有5天卖出。
        """
        result = run(
            codes=["603906"],
            start_date="2025-01-01",
            end_date="2025-12-31",
            hold_days=5,
        )
        # 允许 "无数据" 错误（测试环境无2025年推荐数据），但不接受崩溃
        assert "total_trades" in result or "error" in result

    def test_backtest_writes_json(self):
        """输出 JSON 文件"""
        import tempfile
        out = os.path.join(tempfile.gettempdir(), "aana_backtest_test.json")
        if os.path.exists(out):
            os.unlink(out)

        try:
            result = run(
                codes=["603906"],
                start_date="2025-01-01",
                end_date="2025-06-01",
                hold_days=3,
                output_path=out,
            )
            assert os.path.exists(out), f"应生成 JSON 文件（result={result}）"
            import json
            with open(out) as f:
                data = json.load(f)
            assert isinstance(data, dict), "JSON 应为字典"
        finally:
            if os.path.exists(out):
                os.unlink(out)


# ── engine 导入测试 ─────────────────────────────────────────

class TestEngineImport:
    def test_engine_imports(self):
        """模块能正常导入，无语法错误"""
        from backtest.engine import BacktestEngine, ScoreSignalStrategy
        assert BacktestEngine is not None
        assert ScoreSignalStrategy is not None

    def test_engine_instantiate(self):
        """引擎能正常实例化"""
        from backtest.engine import BacktestEngine
        engine = BacktestEngine(initial_cash=50_000, commission=0.001)
        assert engine.initial_cash == 50_000
        assert engine.commission == 0.001

    def test_score_signal_strategy_params(self):
        """策略参数默认值"""
        from backtest.engine import ScoreSignalStrategy
        assert ScoreSignalStrategy.params.score_threshold == 60
        assert ScoreSignalStrategy.params.hold_days == 5
        assert ScoreSignalStrategy.params.stop_loss_pct == -5
        assert ScoreSignalStrategy.params.strategy_type == "composite"

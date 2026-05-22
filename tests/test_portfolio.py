"""
tests/test_portfolio.py — PortfolioTracker 测试套件
"""

import pytest
import tempfile
import pathlib
import json
from data.portfolio import PortfolioTracker, Position, Trade, PortfolioState


class TestBuySell:
    def test_buy_sell(self):
        """买入一只股票，次日卖出，验证资金变化和收益"""
        pt = PortfolioTracker(initial_cash=100000.0)
        pt.buy("000001", price=10.0, date="2024-01-01", shares=1000)
        assert pt.cash == 90000.0
        assert pt.positions["000001"].shares == 1000
        assert pt.positions["000001"].entry_price == 10.0

        trade = pt.sell("000001", price=11.0, date="2024-01-02")
        assert pt.cash == 101000.0
        assert trade.pnl == 1000.0
        assert trade.pnl_pct == 10.0
        assert "000001" not in pt.positions
        assert pt.realized_pnl == 1000.0


class TestMarkToMarket:
    def test_mark_to_market(self):
        """买入后盯市，验证浮亏浮盈计算"""
        pt = PortfolioTracker(initial_cash=100000.0)
        pt.buy("000001", price=10.0, date="2024-01-01", shares=1000)

        state = pt.mark_to_market("2024-01-02", quotes={"000001": 9.0})
        pos = state.positions["000001"]
        assert pos.unrealized_pnl == -1000.0
        assert abs(pos.unrealized_pnl_pct - (-10.0)) < 1e-9
        assert state.daily_pnl == -1000.0  # 从100000初始跌到99000

    def test_mark_to_market_multiple_days(self):
        """连续两日盯市，验证daily_pnl累积"""
        pt = PortfolioTracker(initial_cash=100000.0)
        pt.buy("000001", price=10.0, date="2024-01-01", shares=1000)

        state1 = pt.mark_to_market("2024-01-02", quotes={"000001": 10.0})
        assert state1.daily_pnl == 0.0  # 成本价，无盈亏

        state2 = pt.mark_to_market("2024-01-03", quotes={"000001": 11.0})
        assert state2.daily_pnl == 1000.0  # 10->11，1000股赚1000


class TestPersistence:
    def test_persistence(self):
        """save + load，验证数据一致"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(pathlib.Path(tmpdir) / "portfolio.json")

            pt1 = PortfolioTracker(initial_cash=50000.0)
            pt1.buy("000001", price=10.0, date="2024-01-01", shares=100)
            # 50000 - 10*100 = 49000
            assert pt1.cash == 49000.0
            pt1.save(path)

            pt2 = PortfolioTracker.load(path)
            assert pt2.initial_cash == 50000.0
            assert pt2.cash == 49000.0
            assert "000001" in pt2.positions
            assert pt2.positions["000001"].shares == 100
            assert len(pt2.trades) == 1


class TestCompareBacktest:
    def test_compare_backtest(self):
        """构造假的回测结果，对比是否正确"""
        pt = PortfolioTracker(initial_cash=100000.0)
        pt.buy("000001", price=10.0, date="2024-01-01", shares=1000)
        pt.mark_to_market("2024-01-02", quotes={"000001": 11.0})

        backtest_result = {
            "total_return": 5.0,
            "total_trades": 20,
            "win_rate": 60.0,
            "overlap_codes": ["000001", "000002"],
            "daily_navs": [],
        }

        result = pt.compare_backtest(backtest_result)
        assert result["realized_return"] == 0.0  # 未卖出
        # 浮盈1000元，收益率 = 1000/100000*100 = 1.0%
        assert result["total_return"] == 1.0
        assert result["backtest_return"] == 5.0
        assert result["excess_return"] == -4.0  # 跑输回测 4%
        assert result["overlap_codes"] == ["000001", "000002"]
        assert result["overlap_count"] == 2

    def test_compare_backtest_sold(self):
        """卖出后对比"""
        pt = PortfolioTracker(initial_cash=100000.0)
        pt.buy("000001", price=10.0, date="2024-01-01", shares=1000)
        pt.sell("000001", price=12.0, date="2024-01-02")
        # 已实现收益 = (12-10)*1000 = 2000, 收益率 = 2000/100000*100 = 2.0%
        result = pt.compare_backtest({"total_return": 8.0, "overlap_codes": []})
        assert result["realized_return"] == 2.0
        assert result["total_return"] == 2.0


class TestEquityCurve:
    def test_equity_curve(self):
        """连续两日盯市，验证daily_pnl"""
        pt = PortfolioTracker(initial_cash=100000.0)
        pt.buy("000001", price=10.0, date="2024-01-01", shares=1000)

        pt.mark_to_market("2024-01-02", quotes={"000001": 9.0})
        pt.mark_to_market("2024-01-03", quotes={"000001": 11.0})

        curve = pt.equity_curve()
        assert len(curve) == 2
        assert curve[0]["daily_pnl"] == -1000.0
        assert curve[1]["daily_pnl"] == 2000.0
        assert curve[0]["nav"] == 0.99
        assert curve[1]["nav"] == 1.01


class TestOverlapStocks:
    def test_overlap_stocks(self):
        """验证compare_backtest的overlap_codes"""
        pt = PortfolioTracker(initial_cash=100000.0)
        pt.buy("000001", price=10.0, date="2024-01-01", shares=100)
        pt.buy("000002", price=20.0, date="2024-01-01", shares=100)

        backtest_result = {
            "total_return": 10.0,
            "total_trades": 5,
            "win_rate": 50.0,
            "overlap_codes": ["000001", "000003"],
            "daily_navs": [],
        }

        result = pt.compare_backtest(backtest_result)
        assert result["overlap_codes"] == ["000001", "000003"]
        assert result["overlap_count"] == 2


class TestPositionAddition:
    def test_buy_multiple_times_same_stock(self):
        """同一股票分批买入，成本加权平均"""
        pt = PortfolioTracker(initial_cash=100000.0)
        pt.buy("000001", price=10.0, date="2024-01-01", shares=1000)
        pt.buy("000001", price=12.0, date="2024-01-02", shares=1000)

        pos = pt.positions["000001"]
        assert pos.shares == 2000
        assert pos.entry_price == 11.0  # (10*1000 + 12*1000) / 2000

        pt.mark_to_market("2024-01-03", quotes={"000001": 13.0})
        assert pos.unrealized_pnl == 4000.0  # (13-11)*2000


class TestErrors:
    def test_buy_insufficient_cash(self):
        pt = PortfolioTracker(initial_cash=1000.0)
        with pytest.raises(ValueError, match="资金不足"):
            pt.buy("000001", price=10.0, date="2024-01-01", shares=200)

    def test_sell_no_position(self):
        pt = PortfolioTracker(initial_cash=100000.0)
        with pytest.raises(ValueError, match="持仓中没有"):
            pt.sell("000001", price=10.0, date="2024-01-01")

    def test_load_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            PortfolioTracker.load("/nonexistent/path/portfolio.json")

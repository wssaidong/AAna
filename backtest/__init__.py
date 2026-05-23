"""
backtest/ — AAna 回测引擎
===================================
基于 backtrader 的事件驱动回测，封装 strategies/ 评分信号为买卖事件。

目录结构：
  backtest/
  ├── __init__.py      # 本模块
  ├── engine.py        # BacktestEngine + ScoreSignalStrategy
  └── runner.py        # 命令行回测入口

使用方法：
  # 快速回测最近 N 条推荐
  from backtest.runner import run
  result = run(codes=["603906", "605566"], start="2025-01-01",
               entry_type="next_close", hold_days=5, stop_loss=-3)

  # 用 engine 定制
  from backtest.engine import BacktestEngine
  engine = BacktestEngine(initial_cash=100_000)
  engine.load_data("603906", start="20250101", end="20260501")
  engine.add_strategy(ScoreSignalStrategy, score_threshold=60, hold_days=5)
  result = engine.run()
"""

from .engine import BacktestEngine, ScoreSignalStrategy
from .runner import run, load_recommendations
from .optimizer import HoldDaysScanner, StopLossComparator

__all__ = [
    "BacktestEngine",
    "ScoreSignalStrategy",
    "run",
    "load_recommendations",
    "HoldDaysScanner",
    "StopLossComparator",
]

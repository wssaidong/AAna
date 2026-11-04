"""strategies/composite.py — 复合策略（XWI-81 P0-2 拆分自原 strategies/__init__.py）"""
from typing import Any, Optional

from strategies.base import BaseStrategy
from strategies.value import ValueStrategy


class CompositeStrategy:
    """
    复合策略：加权组合多个子策略（组合器，不进 STRATEGY_REGISTRY——
    它没有无参构造，按名实例化走 quick_score 的专用分支）
    """

    def __init__(self, strategies: list[BaseStrategy],
                 weights: Optional[list[float]] = None):
        self.strategies = strategies
        n = len(strategies)
        self.weights = weights or [1.0 / n] * n

    def score(self, code: str, klines: list[dict[str, Any]],
              tech: Optional[dict[str, Any]] = None,
              financials: Optional[dict[str, float]] = None) -> dict[str, float]:
        """返回 {strategy_name: score, composite: weighted_score}"""
        scores = {}
        total = 0
        for strat, w in zip(self.strategies, self.weights):
            # ValueStrategy 需要 financials，其他不需要
            if isinstance(strat, ValueStrategy):
                s = strat.score(code, klines, tech, financials)
            else:
                s = strat.score(code, klines, tech)
            scores[strat.name] = s
            total += s * w
        scores['composite'] = round(min(100, total), 1)
        return scores

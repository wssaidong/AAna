"""strategies/momentum.py — 动量策略（XWI-81 P0-2 拆分自原 strategies/__init__.py）"""
from typing import Any, Optional

from strategies.base import BaseStrategy, _get_qs, register_strategy


@register_strategy("momentum")
class MomentumStrategy(BaseStrategy):
    """
    动量策略
    因子：RSI（40-65 区间佳）、近5日累计涨幅（适度为正，不追高）、
         今日涨幅（0~+5%，不追高也不宜跌）
    """

    name = "动量策略"

    def score(self, code: str, klines: list[dict[str, Any]],
              tech: Optional[dict[str, Any]] = None) -> float:
        tech = tech or _get_qs().technical(code)
        rsi = tech.get('rsi')
        change_pct = tech.get('change_pct', 0)
        ma5 = tech.get('ma5') or 0
        price = tech.get('price') or 0

        # RSI 评分：40-65 最佳
        rsi_score = self._check_range(rsi, 30, 70) * 40  # 权重 40

        # 涨幅评分：0~+5% 为佳（不追高、不抄底）
        if change_pct is not None:
            gain_score = self._check_range(change_pct, -3, 8) * 30  # 权重 30
        else:
            gain_score = 15

        # 均线多头排列（价格在 MA5 上方 = 好）
        ma_score = 30 if (ma5 and price > ma5) else 0

        return round(min(100, rsi_score + gain_score + ma_score), 1)

"""strategies/technical.py — 技术面策略（XWI-81 P0-2 拆分自原 strategies/__init__.py）

XWI-81 P1-4：本策略不再用 Python 列表推导抽收盘价序列，指标计算统一走
data/indicators.py 的向量化路径（rolling/shift，禁 iterrows）。
"""
from typing import Any, Optional

from strategies.base import BaseStrategy, _get_qs, register_strategy


@register_strategy("technical")
class TechnicalStrategy(BaseStrategy):
    """
    技术面策略
    因子：均线多头、MACD 金叉（近5日内）、量比 > 1.2、
         今日阳线（close > open）
    """

    name = "技术面策略"

    def score(self, code: str, klines: list[dict[str, Any]],
              tech: Optional[dict[str, Any]] = None) -> float:
        tech = tech or _get_qs().technical(code)
        if not klines:
            return 0

        ma5 = tech.get('ma5')
        ma10 = tech.get('ma10')
        ma20 = tech.get('ma20')
        close_p = tech.get('close') or klines[-1]['close']
        macd_hist = tech.get('macd_hist')
        vol_ratio = tech.get('vol_ratio')
        open_p = tech.get('open') or klines[-1].get('open')

        # 均线多头（MA5 > MA10 > MA20）
        if all([ma5, ma10, ma20]) and ma5 > ma10 > ma20:
            ma_score = 35
        elif all([ma5, ma10]) and ma5 > ma10:
            ma_score = 20
        else:
            ma_score = 0

        # MACD 金叉（柱由负转正）
        macd_score = 25 if (macd_hist is not None and macd_hist > 0) else 0

        # 量比适中（>1.2 说明有资金关注，但不过度放量）
        if vol_ratio and vol_ratio > 1.2:
            vol_score = 20
        elif vol_ratio and vol_ratio > 0.8:
            vol_score = 12
        else:
            vol_score = 0

        # 阳线（收盘 > 开盘）
        yang_score = 20 if (close_p and open_p and close_p > open_p) else 0

        return round(min(100, ma_score + macd_score + vol_score + yang_score), 1)

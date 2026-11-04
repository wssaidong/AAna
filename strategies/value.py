"""strategies/value.py — 价值策略（XWI-81 P0-2 拆分自原 strategies/__init__.py）"""
from typing import Any, Optional

from strategies.base import BaseStrategy, _get_qs, register_strategy


@register_strategy("value")
class ValueStrategy(BaseStrategy):
    """
    价值策略（基本面 + 技术面综合评分）
    基本面评分 0-40（PE/PB/ROE/增速），技术面评分 0-100
    综合评分 = 技术面 * 0.6 + 基本面 * 0.4
    """

    name = "价值策略"

    def score(self, code: str, klines: list[dict[str, Any]],
              tech: Optional[dict[str, Any]] = None,
              financials: Optional[dict[str, float]] = None) -> float:
        tech = tech or _get_qs().technical(code)
        price = tech.get('price')

        # ── 基本面评分 0-40 ──────────────────────────
        from data.fundamentals import FundamentalService
        if financials and all(k in financials for k in ('pe', 'pb', 'roe')):
            pe = financials.get('pe')
            pb = financials.get('pb')
            roe = financials.get('roe')
            # 用 financials 中的增速（如果有）
            rev_g = financials.get('revenue_growth')
            prof_g = financials.get('profit_growth')
            best_g = max(rev_g, prof_g) if (rev_g is not None and prof_g is not None) \
                else (rev_g or prof_g)
            fs = FundamentalService()
            fund_score = (
                fs._pe_score(pe)
                + fs._pb_score(pb)
                + fs._roe_score(roe)
                + fs._growth_score(best_g)
            )
        else:
            # 未传入 financials，从 tushare 实时获取
            fs = FundamentalService()
            fund_score = fs.get_score(code)
            if fund_score is None:  # 无token或网络失败，使用中性基准
                fund_score = 20.0

        # ── 技术面评分 0-100 ──────────────────────────
        pe = (financials or {}).get('pe')
        pb = (financials or {}).get('pb')
        pe_score = self._check_range(pe, 5, 60) * 40 if pe and pe > 0 else 20  # 权重 40
        pb_score = self._check_range(pb, 1, 10) * 30 if pb else 15  # 权重 30
        price_score = self._check_range(price, 5, 100) * 30 if price else 15
        tech_score = min(100, pe_score + pb_score + price_score)

        # ── 综合评分 0-100 ────────────────────────────
        return round(min(100, tech_score * 0.6 + fund_score * 0.4), 1)

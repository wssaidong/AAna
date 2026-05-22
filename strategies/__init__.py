"""
strategies/ — AAna 可插拔选股策略层
=====================================
所有策略实现 BaseStrategy 接口，通过 score() 方法输出 0-100 评分。

目录结构：
  strategies/
  ├── __init__.py      # 导出 + BaseStrategy
  ├── momentum.py       # 动量策略（RSI + 涨幅）
  ├── technical.py      # 技术面策略（均线多头 + MACD + 量价）
  ├── value.py         # 价值策略（PE/PB/ROE）
  └── composite.py      # 复合策略（加权组合多个策略）

使用示例：
  from strategies import CompositeStrategy, MomentumStrategy, TechnicalStrategy
  strat = CompositeStrategy([MomentumStrategy(), TechnicalStrategy()], weights=[0.4, 0.6])
  qt = QuoteService()
  klines = qt.kline(code, count=60)
  score = strat.score(code, klines)
"""

import os, sys
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 延迟实例化，避免模块加载时立即发起网络请求
_qs = None

def _get_qs():
    global _qs
    if _qs is None:
        from data.quotes import QuoteService
        _qs = QuoteService()
    return _qs


class BaseStrategy(ABC):
    """策略基类，所有策略必须实现 score() 方法"""

    name: str = "BaseStrategy"
    weight: float = 1.0  # 复合策略中的权重

    @abstractmethod
    def score(self, code: str, klines: List[Dict[str, Any]],
              tech: Dict[str, Any] = None) -> float:
        """
        对个股打分，返回 0-100
        code:  股票代码
        klines: K线数据（来自 QuoteService.kline）
        tech:  技术指标（来自 QuoteService.technical），可选
        """
        ...

    def _check_range(self, value: Optional[float],
                     low: float, high: float) -> float:
        """将 value 线性映射到 [0, 1]，越接近中间越好"""
        if value is None:
            return 0.5
        if value < low:
            return max(0, (value / low) * 0.5)
        if value > high:
            return max(0, 1 - (value - high) / high * 0.5)
        mid = (low + high) / 2
        return 0.5 + (value - mid) / (high - low) * 0.5


class MomentumStrategy(BaseStrategy):
    """
    动量策略
    因子：RSI（40-65 区间佳）、近5日累计涨幅（适度为正，不追高）、
         今日涨幅（0~+5%，不追高也不宜跌）
    """

    name = "动量策略"

    def score(self, code: str, klines: List[Dict[str, Any]],
              tech: Dict[str, Any] = None) -> float:
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


class TechnicalStrategy(BaseStrategy):
    """
    技术面策略
    因子：均线多头、MACD 金叉（近5日内）、量比 > 1.2、
         今日阳线（close > open）
    """

    name = "技术面策略"

    def score(self, code: str, klines: List[Dict[str, Any]],
              tech: Dict[str, Any] = None) -> float:
        tech = tech or _get_qs().technical(code)
        closes = [k['close'] for k in klines]
        if not closes:
            return 0

        ma5 = tech.get('ma5')
        ma10 = tech.get('ma10')
        ma20 = tech.get('ma20')
        close_p = tech.get('close') or closes[-1]
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


class ValueStrategy(BaseStrategy):
    """
    价值策略（基本面 + 技术面综合评分）
    基本面评分 0-40（PE/PB/ROE/增速），技术面评分 0-100
    综合评分 = 技术面 * 0.6 + 基本面 * 0.4
    """

    name = "价值策略"

    def score(self, code: str, klines: List[Dict[str, Any]],
              tech: Dict[str, Any] = None,
              financials: Dict[str, float] = None) -> float:
        tech = tech or _get_qs().technical(code)
        price = tech.get('price')

        # ── 基本面评分 0-40 ──────────────────────────
        if financials and all(k in financials for k in ('pe', 'pb', 'roe')):
            pe = financials.get('pe')
            pb = financials.get('pb')
            roe = financials.get('roe')
            # 用 financials 中的增速（如果有）
            rev_g = financials.get('revenue_growth')
            prof_g = financials.get('profit_growth')
            best_g = max(rev_g, prof_g) if (rev_g is not None and prof_g is not None) else (rev_g or prof_g)
            from data.fundamentals import FundamentalService
            fs = FundamentalService()
            fund_score = (
                fs._pe_score(pe)
                + fs._pb_score(pb)
                + fs._roe_score(roe)
                + fs._growth_score(best_g)
            )
        else:
            # 未传入 financials，从 tushare 实时获取
            from data.fundamentals import FundamentalService
            fs = FundamentalService()
            fund_score = fs.get_score(code)
            if fund_score is None:  # 无token或网络失败，使用中性基准
                fund_score = 20.0

        # ── 技术面评分 0-100 ──────────────────────────
        pe = (financials or {}).get('pe')
        pb = (financials or {}).get('pb')
        pe_score = self._check_range(pe, 5, 60) * 40 if pe else 20  # 权重 40
        pb_score = self._check_range(pb, 1, 10) * 30 if pb else 15  # 权重 30
        price_score = self._check_range(price, 5, 100) * 30 if price else 15
        tech_score = min(100, pe_score + pb_score + price_score)

        # ── 综合评分 ─────────────────────────────────
        return round(min(100, tech_score * 0.6 + fund_score * 0.4), 1)


class CompositeStrategy:
    """
    复合策略：加权组合多个子策略
    """

    def __init__(self, strategies: List[BaseStrategy],
                 weights: List[float] = None):
        self.strategies = strategies
        n = len(strategies)
        self.weights = weights or [1.0 / n] * n

    def score(self, code: str, klines: List[Dict[str, Any]],
              tech: Dict[str, Any] = None,
              financials: Dict[str, float] = None) -> Dict[str, float]:
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


# ── 快捷调用 ───────────────────────────────────────────────
def quick_score(code: str,
                strategy: str = "composite") -> Dict[str, Any]:
    """
    快速评分：获取K线+技术指标，统一打分
    strategy: 'momentum' | 'technical' | 'value' | 'composite'
    """
    klines = _get_qs().kline(code, count=60)
    if not klines:
        return {'code': code, 'error': '无法获取K线数据'}
    tech = _get_qs().technical(code)

    strat_map = {
        'momentum': MomentumStrategy(),
        'technical': TechnicalStrategy(),
        'value': ValueStrategy(),
        'composite': CompositeStrategy(
            [MomentumStrategy(), TechnicalStrategy(), ValueStrategy()],
            weights=[0.35, 0.45, 0.20]
        ),
    }
    strat = strat_map.get(strategy, strat_map['composite'])

    if isinstance(strat, CompositeStrategy):
        result = strat.score(code, klines, tech)
        result['code'] = code
        result['name'] = tech.get('name', code)
        result['price'] = tech.get('price')
        result['change_pct'] = tech.get('change_pct')
        return result
    else:
        s = strat.score(code, klines, tech)
        return {
            'code': code, 'name': tech.get('name', code),
            'price': tech.get('price'),
            'change_pct': tech.get('change_pct'),
            'strategy': strat.name,
            'score': s,
        }

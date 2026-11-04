"""
strategies/base.py — 策略契约层（XWI-81 P0-2 拆分自原 strategies/__init__.py）

两层契约（借鉴 Sequoia-X strategy/base.py 的 ABC 契约设计，未复制代码）：
  BaseStrategy.score()   AAna 评分制契约（0-100，评分制是 AAna 优势，不退回二值）
  ShapeFilter.run()      形态筛选层契约（Sequoia-X run() -> list[str] 的「返回选中
                         代码列表」形态），与评分层组合：先筛形态，再对筛出的票打分

插件注册：@register_strategy / @register_filter + STRATEGY_REGISTRY / FILTER_REGISTRY，
新增策略只加新文件，不改旧文件（见 strategies/__init__.py 的自动发现）。
"""
from abc import ABC, abstractmethod
from typing import Any, Optional

# 延迟实例化，避免模块加载时立即发起网络请求
_qs = None


def _get_qs():
    global _qs
    if _qs is None:
        from data.quotes import QuoteService
        _qs = QuoteService()
    return _qs


class BaseStrategy(ABC):
    """策略基类，所有评分制策略必须实现 score() 方法"""

    name: str = "BaseStrategy"
    weight: float = 1.0  # 复合策略中的权重

    @abstractmethod
    def score(self, code: str, klines: list[dict[str, Any]],
              tech: Optional[dict[str, Any]] = None) -> float:
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


class ShapeFilter(ABC):
    """形态筛选层：对候选列表做形态过滤，返回满足形态的代码列表。

    借鉴 Sequoia-X BaseStrategy.run() -> list[str] 的「返回选中代码」契约，
    但在 AAna 中它是评分层之前的**前置筛选层**，不替代 score() 评分制。
    实现见 strategies/filters.py，组合方式见 filter_and_score()。
    """

    name: str = "ShapeFilter"

    @abstractmethod
    def run(self, codes: list[str],
            klines_map: dict[str, list[dict[str, Any]]]) -> list[str]:
        """
        codes:      候选代码列表
        klines_map: {code: klines}，数据由调用方注入（通常来自本地日线库）
        返回: 满足形态条件的代码子集（保持输入顺序）
        """
        ...


# ── 插件注册表 ───────────────────────────────────────────────
STRATEGY_REGISTRY: dict[str, type] = {}
FILTER_REGISTRY: dict[str, type] = {}


def register_strategy(key: str):
    """类装饰器：把策略类注册进 STRATEGY_REGISTRY，供按名实例化/发现式测试。"""
    def deco(cls):
        STRATEGY_REGISTRY[key] = cls
        return cls
    return deco


def register_filter(key: str):
    """类装饰器：把形态过滤器注册进 FILTER_REGISTRY。"""
    def deco(cls):
        FILTER_REGISTRY[key] = cls
        return cls
    return deco


def filter_and_score(codes: list[str],
                     klines_map: dict[str, list[dict[str, Any]]],
                     flt: ShapeFilter,
                     strategy: BaseStrategy) -> list[dict[str, float]]:
    """形态筛选层 × 评分层组合：flt.run() 先筛形态，strategy.score() 再打分排名。

    返回 [{code, score}] 按分数降序；未提供K线的代码不参与（宁缺毋滥）。
    """
    picked = flt.run(codes, klines_map)
    rows = [
        {"code": c, "score": strategy.score(c, klines_map.get(c, []))}
        for c in picked
    ]
    return sorted(rows, key=lambda r: r["score"], reverse=True)

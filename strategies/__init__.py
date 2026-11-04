"""
strategies/ — AAna 可插拔选股策略层
=====================================
一策略一文件 + 自动发现注册（XWI-81 P0-2 拆分）：strategies/ 下任意模块
import 时通过 @register_strategy / @register_filter 自注册，新增策略只需
新增文件，不改任何旧文件（包括本 __init__ 和 tests/test_strategies.py）。

目录结构（与旧 docstring 声称的终于一致了）：
  strategies/
  ├── __init__.py     # 导出 + 自动发现注册（本文件）
  ├── base.py         # 契约层：BaseStrategy.score() 评分制 + ShapeFilter.run() 形态筛选层
  ├── momentum.py     # 动量策略（RSI + 涨幅）
  ├── technical.py    # 技术面策略（均线多头 + MACD + 量价）
  ├── value.py        # 价值策略（PE/PB/ROE）
  ├── composite.py    # 复合策略（加权组合多个策略）
  └── filters.py      # 形态筛选层实现（ShapeFilter.run() -> list[str] 落点）

使用示例：
  from strategies import CompositeStrategy, MomentumStrategy, TechnicalStrategy
  strat = CompositeStrategy([MomentumStrategy(), TechnicalStrategy()], weights=[0.4, 0.6])
  qt = QuoteService()
  klines = qt.kline(code, count=60)
  score = strat.score(code, klines)
"""

import importlib
import pkgutil
from typing import Any

from strategies.base import (
    FILTER_REGISTRY,
    STRATEGY_REGISTRY,
    BaseStrategy,
    ShapeFilter,
    _get_qs,
    filter_and_score,
    register_filter,
    register_strategy,
)
from strategies.composite import CompositeStrategy
from strategies.momentum import MomentumStrategy
from strategies.technical import TechnicalStrategy
from strategies.value import ValueStrategy

__all__ = [
    "BaseStrategy", "ShapeFilter", "MomentumStrategy", "TechnicalStrategy",
    "ValueStrategy", "CompositeStrategy",
    "STRATEGY_REGISTRY", "FILTER_REGISTRY",
    "register_strategy", "register_filter", "filter_and_score",
    "_get_qs", "quick_score", "list_strategies",
]


def _discover_plugins() -> None:
    """扫描 strategies/*.py 并 import 触发装饰器注册。

    未来的策略文件不需要在本 __init__ 里显式 import——放进目录即注册。
    单个模块加载失败不拖垮整个策略层（行情红线：缺数据宁可留空）。
    """
    for mod_info in pkgutil.iter_modules(__path__):
        if mod_info.name.startswith("_"):
            continue
        try:
            importlib.import_module(f"strategies.{mod_info.name}")
        except Exception:
            continue


_discover_plugins()


def list_strategies() -> list[str]:
    """当前已注册的策略 key 列表（发现式，供调用方枚举）。"""
    return sorted(STRATEGY_REGISTRY)


# ── 快捷调用 ───────────────────────────────────────────────
def quick_score(code: str,
                strategy: str = "composite") -> dict[str, Any]:
    """
    快速评分：获取K线+技术指标，统一打分
    strategy: 'momentum' | 'technical' | 'value' | 'composite'（XWI-81 起走注册表，
    未知 key 与 'composite' 一致回退复合策略）
    """
    klines = _get_qs().kline(code, count=60)
    if not klines:
        return {'code': code, 'error': '无法获取K线数据'}
    tech = _get_qs().technical(code)

    if strategy in STRATEGY_REGISTRY:
        strat = STRATEGY_REGISTRY[strategy]()
    else:
        strat = CompositeStrategy(
            [MomentumStrategy(), TechnicalStrategy(), ValueStrategy()],
            weights=[0.35, 0.45, 0.20]
        )

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

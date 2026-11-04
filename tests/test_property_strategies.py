"""
tests/test_property_strategies.py — 策略插件层属性测试（XWI-82 P1-5）

借鉴 Sequoia-X tests/test_strategy.py 的 @given + settings(max_examples=30,
deadline=None) 写法（只借鉴思路，未复制代码）。断言「输入任意合法行情 →
输出必合法」类不变量，且按注册表发现式覆盖——S2 之后新增的策略文件自动
被本文件覆盖，无需改测试：

  1. 评分层：STRATEGY_REGISTRY 里所有可无参构造的策略，任意 (code,
     klines, tech[, financials]) → score() ∈ [0,100] 且永不抛异常
  2. 形态筛选层：FILTER_REGISTRY 里所有过滤器，任意 (codes, klines_map)
     → 返回 list，⊆ codes 且保持输入顺序，永不抛异常
  3. 组合层：CompositeStrategy 任意输入 → 每个子分与 composite ∈ [0,100]
  4. filter_and_score：输出按 score 降序、分数 ∈ [0,100]

输入域 = 「合法行情形状 + 任意数值」：bar 必含 date/open/high/low/close/vol
（indicators.snapshot 的形状契约），数值任意（None / 0 / 负 / 极端值），
K线列表可为空。tech 字段全键存在（避开 score 内部的网络回退分支）。
"""
import inspect
from datetime import date

from hypothesis import given, settings
from hypothesis import strategies as st

import strategies  # noqa: F401  触发插件自动发现注册
from strategies import (
    FILTER_REGISTRY,
    STRATEGY_REGISTRY,
    CompositeStrategy,
    MomentumStrategy,
    TechnicalStrategy,
    ValueStrategy,
    filter_and_score,
)

_PRICE = st.floats(min_value=0.0, max_value=1e7, allow_nan=False)
_OPT_NUM = st.one_of(st.none(), st.floats(min_value=-1e4, max_value=1e4,
                                         allow_nan=False))
_CODE = st.text(min_size=0, max_size=12)

_BAR = st.fixed_dictionaries({
    "date": st.dates(min_value=date(2020, 1, 1),
                     max_value=date(2026, 12, 31)).map(lambda d: d.isoformat()),
    "open": _PRICE, "high": _PRICE, "low": _PRICE, "close": _PRICE,
    "vol": st.floats(min_value=0.0, max_value=1e10, allow_nan=False),
})

_KLINES = st.lists(_BAR, min_size=0, max_size=80)

_TECH = st.fixed_dictionaries({
    "price": _OPT_NUM, "open": _OPT_NUM, "close": _OPT_NUM,
    "ma5": _OPT_NUM, "ma10": _OPT_NUM, "ma20": _OPT_NUM,
    "rsi": _OPT_NUM, "change_pct": _OPT_NUM,
    "macd_hist": _OPT_NUM, "vol_ratio": _OPT_NUM,
})

_FIN = st.fixed_dictionaries({
    "pe": _OPT_NUM, "pb": _OPT_NUM, "roe": _OPT_NUM,
    "revenue_growth": _OPT_NUM, "profit_growth": _OPT_NUM,
})

_DEFAULT_FIN = {"pe": 10.0, "pb": 1.0, "roe": 8.0,
                "revenue_growth": 12.0, "profit_growth": 15.0}


def _call_score(strat, code, klines, tech):
    """按 score() 真实签名调用：需要 financials 的策略喂全量字典（离线）。"""
    params = inspect.signature(strat.score).parameters
    kw = {"financials": _DEFAULT_FIN} if "financials" in params else {}
    return strat.score(code, klines, tech, **kw)


def _instantiable(cls):
    try:
        return cls()
    except TypeError:  # 需要构造参数的组合器等，不属于无参契约
        return None


@given(code=_CODE, klines=_KLINES, tech=_TECH)
@settings(max_examples=30, deadline=None)
def test_property_registry_scores_in_bounds(code, klines, tech):
    """属性：注册表内所有策略，任意合法输入 → score ∈ [0,100]，不抛异常。"""
    assert STRATEGY_REGISTRY, "注册表不应为空（插件发现失效）"
    for key in sorted(STRATEGY_REGISTRY):
        strat = _instantiable(STRATEGY_REGISTRY[key])
        if strat is None:
            continue
        s = _call_score(strat, code, klines, tech)
        assert isinstance(s, (int, float)), f"{key} 返回非数值: {type(s)}"
        assert 0 <= s <= 100, f"{key} 越界: {s}"


@given(code=_CODE, klines=_KLINES, tech=_TECH, fin=_FIN)
@settings(max_examples=30, deadline=None)
def test_property_value_score_any_financials(code, klines, tech, fin):
    """属性：价值策略对任意 financials（None/负 PE/缺失增速）→ 分数 ∈ [0,100]。"""
    s = ValueStrategy().score(code, klines, tech, financials=fin)
    assert isinstance(s, (int, float)) and 0 <= s <= 100


@given(code=_CODE, klines=_KLINES, tech=_TECH, fin=_FIN)
@settings(max_examples=30, deadline=None)
def test_property_composite_all_scores_in_bounds(code, klines, tech, fin):
    """属性：复合策略每个子分与 composite 均 ∈ [0,100]。"""
    comp = CompositeStrategy(
        [MomentumStrategy(), TechnicalStrategy(), ValueStrategy()],
        weights=[0.35, 0.45, 0.20])
    res = comp.score(code, klines, tech, fin)
    assert 0 <= res["composite"] <= 100
    for k, v in res.items():
        assert isinstance(v, (int, float)) and 0 <= v <= 100, f"{k}={v}"


@given(codes=st.lists(st.text(alphabet="0123456789", min_size=6, max_size=6),
                      min_size=0, max_size=10, unique=True),
       klines_map=st.dictionaries(
           st.text(alphabet="0123456789", min_size=6, max_size=6),
           _KLINES, max_size=10))
@settings(max_examples=30, deadline=None)
def test_property_filters_subset_and_order_preserved(codes, klines_map):
    """属性：注册表内所有形态过滤器 → 返回 codes 子集、保序、不抛异常。"""
    assert FILTER_REGISTRY, "过滤器注册表不应为空"
    for key in sorted(FILTER_REGISTRY):
        flt = _instantiable(FILTER_REGISTRY[key])
        if flt is None:
            continue
        out = flt.run(codes, klines_map)
        assert isinstance(out, list), f"{key} 返回非 list"
        out_set = set(out)
        assert out_set <= set(codes), f"{key} 返回了候选外的代码"
        assert out == [c for c in codes if c in out_set], f"{key} 破坏了输入顺序"


@given(codes=st.lists(st.text(alphabet="0123456789", min_size=6, max_size=6),
                      min_size=0, max_size=10, unique=True),
       klines_map=st.dictionaries(
           st.text(alphabet="0123456789", min_size=6, max_size=6),
           _KLINES, max_size=10))
@settings(max_examples=30, deadline=None)
def test_property_filter_and_score_sorted_desc(codes, klines_map):
    """属性：filter_and_score 输出降序且分数 ∈ [0,100]。"""
    flt = _instantiable(FILTER_REGISTRY["ma_bull"])
    assert flt is not None
    rows = filter_and_score(codes, klines_map, flt, MomentumStrategy())
    scores = [r["score"] for r in rows]
    assert scores == sorted(scores, reverse=True)
    assert all(0 <= s <= 100 for s in scores)

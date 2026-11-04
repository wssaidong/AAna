"""
tests/test_strategies.py — 策略层测试（XWI-81 P0-2 起按文件发现式）

扫描 strategies/ 包自动发现已注册的策略并逐个生成用例：
新增策略只需在 strategies/ 下加新文件并用 @register_strategy 注册，
无需修改本文件，也不需要改任何旧文件。数据全部合成，零网络。
"""
import pkgutil
import random
import sys

import pytest

import strategies
from strategies import (
    FILTER_REGISTRY,
    STRATEGY_REGISTRY,
    BaseStrategy,
    CompositeStrategy,
    ShapeFilter,
    filter_and_score,
    quick_score,
)


# ── 合成数据（确定性，零网络） ─────────────────────────────
def synth_klines(seed: int = 7, n: int = 60, start: float = 10.0, drift: float = 0.02):
    """确定性合成K线：轻微上涨漂移 + 随机波动。drift<0 为下跌序列。"""
    rnd = random.Random(seed)
    bars = []
    px = start
    for i in range(n):
        px = max(1.0, px * (1 + rnd.uniform(drift * -0.75 - 0.015, drift + 0.005)))
        o = px * (1 + rnd.uniform(-0.005, 0.005))
        h = max(px, o) * 1.005
        low = min(px, o) * 0.995
        bars.append({
            "date": f"2026-{i // 28 + 1:02d}-{i % 28 + 1:02d}",
            "open": round(o, 2), "high": round(h, 2), "low": round(low, 2),
            "close": round(px, 2), "vol": round(rnd.uniform(1e5, 5e6), 0),
        })
    return bars


def synth_tech(klines):
    """合成 tech dict（评分层只读 rsi/change_pct/ma*/price 等字段）。"""
    closes = [k["close"] for k in klines]
    last = klines[-1]
    prev = closes[-2] if len(closes) >= 2 else closes[-1]
    return {
        "code": "TEST", "name": "合成",
        "price": last["close"], "open": last["open"],
        "high": last["high"], "low": last["low"], "close": last["close"],
        "vol": last["vol"],
        "change_pct": round((last["close"] - prev) / prev * 100, 2),
        "ma5": sum(closes[-5:]) / 5, "ma10": sum(closes[-10:]) / 10,
        "ma20": sum(closes[-20:]) / 20, "ma60": sum(closes) / len(closes),
        "rsi": 55.0, "macd_hist": 0.3, "vol_ratio": 1.5,
    }


class _FakeQS:
    def __init__(self, klines_map):
        self._kl = klines_map

    def kline(self, code, period="daily", count=30, adjust="qfq",
              allow_sina_fallback=True):
        return list(self._kl.get(code, []))[-count:]

    def technical(self, code):
        kl = self._kl.get(code, [])
        return synth_tech(kl) if kl else {}


class _FakeFS:
    def get_score(self, code):
        return None  # 与生产「无 token」路径一致 → 中性基准 20.0

    def _pe_score(self, pe):
        return 10.0

    def _pb_score(self, pb):
        return 8.0

    def _roe_score(self, roe):
        return 9.0

    def _growth_score(self, g):
        return 7.0


@pytest.fixture
def fake_market(monkeypatch):
    """把 strategies 各模块的 _get_qs 与基本面服务换成合成数据源：零网络。"""
    import data.fundamentals as fmod
    kl = {f"60{i:04d}": synth_klines(seed=i) for i in range(6)}
    kl["empty"] = []
    fake = _FakeQS(kl)
    for name, mod in list(sys.modules.items()):
        if name.startswith("strategies") and hasattr(mod, "_get_qs"):
            monkeypatch.setattr(mod, "_get_qs", lambda: fake)
    monkeypatch.setattr(fmod, "FundamentalService", _FakeFS)
    return fake


# ── 插件发现 / 注册表 ─────────────────────────────────────
def test_legacy_exports_alive():
    """向后兼容：旧入口名必须继续可用（backtest/engine.py 等依赖）。"""
    from strategies import MomentumStrategy, TechnicalStrategy, ValueStrategy
    for cls in (MomentumStrategy, TechnicalStrategy, ValueStrategy):
        assert issubclass(cls, BaseStrategy)


def test_registry_covers_legacy_strategies():
    assert {"momentum", "technical", "value"} <= set(STRATEGY_REGISTRY)


def test_every_strategy_file_registers_plugin():
    """发现式：strategies/ 下除基础层外每个模块至少注册一个插件。

    base=契约层、composite=组合器（非可插拔叶子策略）为基础模块；
    新增策略文件若漏注册，本用例立刻红。
    """
    infra = {"base", "composite"}
    files = {m.name for m in pkgutil.iter_modules(strategies.__path__)} - infra
    contributors = {
        cls.__module__.split(".")[-1] for cls in STRATEGY_REGISTRY.values()
    } | {
        cls.__module__.split(".")[-1] for cls in FILTER_REGISTRY.values()
    }
    assert files <= contributors, f"未注册的策略文件: {files - contributors}"


# ── 逐策略自动生成用例 ───────────────────────────────────
@pytest.mark.parametrize("key", sorted(STRATEGY_REGISTRY))
def test_registered_strategy_valid_score(key, fake_market):
    """不变量：任意注册策略对任意输入输出 0-100 且不崩溃。"""
    strat = STRATEGY_REGISTRY[key]()
    assert strat.name
    for code in ("600000", "600001"):
        kl = fake_market.kline(code, count=60)
        s = strat.score(code, kl, fake_market.technical(code))
        assert 0 <= s <= 100


@pytest.mark.parametrize("key", sorted(STRATEGY_REGISTRY))
def test_registered_strategy_empty_inputs(key, fake_market):
    """不变量：空K线 / 空 tech 不崩溃，输出仍在 0-100。"""
    strat = STRATEGY_REGISTRY[key]()
    s = strat.score("999999", [], {})
    assert 0 <= s <= 100


# ── 逐形态过滤器自动生成用例 ──────────────────────────────
@pytest.mark.parametrize("key", sorted(FILTER_REGISTRY))
def test_registered_filter_contract(key):
    """不变量：任意注册过滤器返回 list[str]、是输入子集、元素非空、空输入安全。"""
    flt = FILTER_REGISTRY[key]()
    assert flt.name
    codes = ["600000", "600001", "600002", "unknown"]
    klines_map = {c: synth_klines(seed=i) for i, c in enumerate(codes[:3])}
    out = flt.run(codes, klines_map)
    assert isinstance(out, list)
    assert all(isinstance(c, str) and c for c in out)
    assert set(out) <= set(codes)
    assert flt.run([], {}) == []


def test_ma_bull_filter_selects():
    """均线多头判定：严格上涨序列入选，严格下跌序列排除。"""
    from strategies.filters import MABullFilter

    def linear(n=60, step=0.5, start=10.0):
        return [
            {"date": f"d{i}", "open": start, "high": start + step, "low": start,
             "close": start + step * i, "vol": 1000.0 + i}
            for i in range(n)
        ]

    rising, falling = linear(step=0.5), linear(step=-0.3)
    out = MABullFilter().run(["up", "down"], {"up": rising, "down": falling})
    assert out == ["up"]


def test_filter_and_score_composition(fake_market):
    """形态筛选层 × 评分层组合：先筛后打分，输出按分数降序。"""
    from strategies.filters import MABullFilter

    codes = [f"60{i:04d}" for i in range(4)]
    klines_map = {c: synth_klines(seed=i) for i, c in enumerate(codes)}
    ranked = filter_and_score(
        codes, klines_map, MABullFilter(), STRATEGY_REGISTRY["momentum"]()
    )
    assert all(r["code"] in codes for r in ranked)
    scores = [r["score"] for r in ranked]
    assert scores == sorted(scores, reverse=True)


# ── 契约层 ──────────────────────────────────────────────
def test_base_contracts_abstract():
    with pytest.raises(TypeError):
        BaseStrategy()
    with pytest.raises(TypeError):
        ShapeFilter()


# ── 旧行为回归 ──────────────────────────────────────────
def test_composite_legacy_behavior(fake_market):
    from strategies import MomentumStrategy, TechnicalStrategy
    comp = CompositeStrategy(
        [MomentumStrategy(), TechnicalStrategy()], weights=[0.4, 0.6]
    )
    code = "600000"
    kl = fake_market.kline(code, count=60)
    res = comp.score(code, kl, fake_market.technical(code))
    assert "composite" in res and 0 <= res["composite"] <= 100
    assert "动量策略" in res and "技术面策略" in res


def test_quick_score_hermetic(fake_market):
    res = quick_score("600000", strategy="composite")
    assert res["code"] == "600000" and "composite" in res
    res2 = quick_score("600000", strategy="momentum")
    assert 0 <= res2["score"] <= 100
    err = quick_score("empty", strategy="composite")
    assert "error" in err

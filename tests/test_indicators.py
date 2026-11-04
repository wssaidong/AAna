"""
tests/test_indicators.py — 向量化指标层测试（XWI-81 P1-4）

oracle = 旧 QuoteService.technical() 的指标数学逐行拷贝（改造 quotes.py 前留档）。
「向后兼容」在这里就是规格：data/indicators.snapshot 必须与 oracle 逐字段一致。
新实现全 pandas rolling()/shift()/groupby()，严禁 iterrows / Python 循环算均线。
"""
import random

import pandas as pd
import pytest

from data import indicators


def synth_klines(seed: int, n: int, drift: float = 0.01) -> list[dict]:
    rnd = random.Random(seed)
    bars = []
    px = 10.0
    for i in range(n):
        px = max(1.0, px * (1 + rnd.uniform(-0.02, 0.02 + drift)))
        o = px * (1 + rnd.uniform(-0.008, 0.008))
        bars.append({
            "date": f"2026-{i // 28 + 1:02d}-{i % 28 + 1:02d}",
            "open": round(o, 2), "high": round(max(px, o) * 1.01, 2),
            "low": round(min(px, o) * 0.99, 2), "close": round(px, 2),
            "vol": round(rnd.uniform(1e5, 5e6), 0),
        })
    return bars


def flat_klines(n: int = 60, close: float = 10.0) -> list[dict]:
    return [
        {"date": f"d{i}", "open": close, "high": close, "low": close,
         "close": close, "vol": 1000.0}
        for i in range(n)
    ]


def linear_klines(n: int = 60, start: float = 10.0, step: float = 0.5) -> list[dict]:
    """严格单调序列（上涨 step>0 / 下跌 step<0），均线必然有序。"""
    return [
        {"date": f"d{i}", "open": start, "high": start + step, "low": start,
         "close": start + step * i, "vol": 1000.0 + i}
        for i in range(n)
    ]


# ── oracle：旧实现逐行拷贝（改动 quotes.py 前留档） ──────────
def _legacy_ema(d, p):
    k = 2 / (p + 1)
    e = d[0]
    for v in d[1:]:
        e = v * k + e * (1 - k)
    return e


def _legacy_technical(klines, code="TEST"):
    closes = [k["close"] for k in klines]
    prices = klines[-1]
    vol_list = [k["vol"] for k in klines]

    def ma(n):
        if len(closes) >= n:
            return sum(closes[-n:]) / n
        return sum(closes) / len(closes) if closes else None

    def calc_rsi(c, p=14):
        if len(c) < p + 1:
            return None
        gains, losses = [], []
        for i in range(1, len(c)):
            d = c[i] - c[i - 1]
            gains.append(max(d, 0))
            losses.append(max(-d, 0))
        ag = sum(gains[-p:]) / p
        al = sum(losses[-p:]) / p
        if al == 0:
            return 100.0
        return round(100 - 100 / (1 + ag / al), 2)

    dif_list, dea_list = [], []
    if len(closes) >= 26:
        for i in range(25, len(closes)):
            d = closes[: i + 1]
            dif = _legacy_ema(d, 12) - _legacy_ema(d, 26)
            dea = dif * 0.8 + (dif_list[-1] if dif_list else dif) * 0.2 if dif_list else dif
            dif_list.append(dif)
            dea_list.append(dea)

    macd_hist = [(dif_list[-1] - dea_list[-1]) * 2] if dif_list and dea_list else [0]

    vol_ratio = None
    if len(vol_list) >= 6:
        avg5 = sum(vol_list[-6:-1]) / 5
        vol_ratio = round(vol_list[-1] / avg5, 2) if avg5 else None

    yesterday_close = klines[-2]["close"] if len(klines) >= 2 else prices["close"]
    change_pct = (
        round((prices["close"] - yesterday_close) / yesterday_close * 100, 2)
        if yesterday_close
        else 0
    )

    return {
        "code": code,
        "name": prices.get("name", code),
        "price": prices.get("close") or prices.get("price"),
        "open": prices.get("open"),
        "high": prices.get("high"),
        "low": prices.get("low"),
        "close": prices.get("close") or prices.get("price"),
        "vol": prices.get("vol"),
        "change_pct": change_pct,
        "ma5": ma(5), "ma10": ma(10), "ma20": ma(20), "ma60": ma(60),
        "rsi": calc_rsi(closes),
        "macd_dif": round(dif_list[-1], 4) if dif_list else None,
        "macd_dea": round(dea_list[-1], 4) if dea_list else None,
        "macd_hist": round(macd_hist[-1], 4),
        "vol_ratio": vol_ratio,
    }


CASES = {
    "n1": synth_klines(1, 1),
    "n2": synth_klines(2, 2),
    "n5": synth_klines(5, 5),
    "n6": synth_klines(6, 6),
    "n14": synth_klines(14, 14),
    "n15": synth_klines(15, 15),
    "n16": synth_klines(16, 16),
    "n25": synth_klines(25, 25),
    "n26": synth_klines(26, 26),
    "n27": synth_klines(27, 27),
    "n30": synth_klines(30, 30),
    "n60": synth_klines(42, 60),
    "n250": synth_klines(99, 250),
    "flat": flat_klines(),
    "rising": linear_klines(),
    "falling": linear_klines(step=-0.3),
    "zero_vol": [
        {"date": f"d{i}", "open": 10, "high": 11, "low": 9,
         "close": 10 + (i % 3), "vol": 0.0}
        for i in range(30)
    ],
}


def _assert_parity(got: dict, expected: dict):
    assert set(got) == set(expected), f"字段集不一致: {set(got) ^ set(expected)}"
    for k, v in expected.items():
        g = got[k]
        if isinstance(v, float):
            assert g == pytest.approx(v, rel=1e-9, abs=1e-9), f"字段 {k}: {g} != {v}"
        else:
            assert g == v, f"字段 {k}: {g!r} != {v!r}"


@pytest.mark.parametrize("case", sorted(CASES))
def test_snapshot_parity_with_legacy(case):
    """snapshot() 与旧 technical() 指标数学逐字段一致（含 <n 根 MA 回退、RSI 100
    平盘 quirk、MACD 26/27 根边界、零成交量 → vol_ratio=None）。"""
    klines = CASES[case]
    _assert_parity(indicators.snapshot(klines, code="TEST"), _legacy_technical(klines))


def test_snapshot_empty():
    assert indicators.snapshot([]) == {}


def test_snapshot_many_parity_with_snapshot():
    """批量 groupby 路径与单只路径逐字段一致。"""
    m = {f"c{i}": kl for i, kl in enumerate(
        [CASES["n1"], CASES["n6"], CASES["n15"], CASES["n26"],
         CASES["n27"], CASES["n60"], CASES["flat"], CASES["rising"]],
    )}
    many = indicators.snapshot_many(m)
    assert set(many) == set(m)
    for c, kl in m.items():
        _assert_parity(many[c], indicators.snapshot(kl, code=c))
    assert indicators.snapshot_many({}) == {}
    assert indicators.snapshot_many({"e": []}) == {}


def test_quotes_technical_uses_indicators(monkeypatch):
    """QuoteService.technical 集成：kline 打桩后输出与 oracle 一致。"""
    from data.quotes import QuoteService

    kl = CASES["n60"]
    qs = QuoteService()
    monkeypatch.setattr(qs, "kline", lambda code, **kw: kl)
    _assert_parity(qs.technical("600000"), _legacy_technical(kl, code="600000"))


# ── 向量化函数的数学正确性（独立于 oracle 的已知值） ──────────
def test_ma_known_value():
    s = pd.Series(range(1, 11), dtype=float)  # 1..10
    out = indicators.ma(s, 3)
    assert out.iloc[-1] == 9.0  # mean(8,9,10)
    assert pd.isna(out.iloc[1])  # 不足窗口 → NaN
    assert indicators.ma(s, 3).iloc[-1] == indicators.ma(s, 3).iloc[-1]


def test_rsi_known_values():
    rising = pd.Series([10.0 + i for i in range(20)])
    assert indicators.rsi(rising).iloc[-1] == 100.0  # 只涨不跌 → 100
    falling = pd.Series([10.0 - i * 0.1 for i in range(20)])
    assert indicators.rsi(falling).iloc[-1] == pytest.approx(0.0, abs=1e-9)


def test_volatility_known_value():
    closes = pd.Series([100.0, 101.0, 102.0, 101.5])
    v = indicators.volatility(closes, n=2)
    import statistics
    # 最后窗口 = 两个日收益率 [102/101-1, 101.5/102-1] 的样本标准差
    r2, r3 = 1.0 / 101.0, -0.5 / 102.0
    assert v.iloc[-1] == pytest.approx(statistics.stdev([r2, r3]), rel=1e-9)
    assert pd.isna(v.iloc[0])


def test_macd_dea_keeps_legacy_quirk():
    """DEA 口径 = 0.8*dif[i] + 0.2*dif[i-1]（旧实现的 dif 一阶滞后，非教科书 EMA9）。
    修正与否留给 S5 评审，本阶段必须逐位复刻。"""
    closes = pd.Series([10.0 + (i % 5) * 0.3 + i * 0.01 for i in range(40)])
    m = indicators.macd(closes)
    dif = (closes.ewm(span=12, adjust=False).mean()
           - closes.ewm(span=26, adjust=False).mean())
    dea_last = 0.8 * dif.iloc[-1] + 0.2 * dif.iloc[-2]
    assert m["dif"].iloc[-1] == pytest.approx(dif.iloc[-1], rel=1e-12)
    assert m["dea"].iloc[-1] == pytest.approx(dea_last, rel=1e-12, abs=1e-12)
    assert m["hist"].iloc[-1] == pytest.approx((dif.iloc[-1] - dea_last) * 2, rel=1e-12)

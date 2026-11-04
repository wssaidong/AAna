"""
tests/test_property_rps.py — RPS 引擎属性测试（XWI-82 P1-5）

借鉴 Sequoia-X tests/test_strategy.py 的 @given + settings(max_examples=30,
deadline=None) 写法（只借鉴思路，未复制代码）。断言「输入任意合法行情 →
输出必合法」类不变量：

  1. 有界性：非 NaN 的 RPS 必在 [0, 100]
  2. 完备性：RPS 有值 ⇔ ret 有值；每日参与排名数 = 当日非 NaN ret 数
  3. 单调性：同一交易日内 ret 越高 RPS 不低（横截面排位的定义）
  4. 分布守恒：分桶计数之和 = 非 NaN 数
  5. Top-N 合法：至多 n 行、降序、全部来自同一（最新）交易日
  6. 纯函数：不改动输入 DataFrame
"""
import random
from datetime import date

import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from analysis_tools import rps as rps_mod

_SYMS = st.text(alphabet="0123456789", min_size=6, max_size=6)
_DATES = st.dates(min_value=date(2020, 1, 1), max_value=date(2026, 12, 31))


def _build_frame(symbols, dates, seed):
    """由基本量确定性构造行情表：每股取日期子序列（模拟停牌断档），
    close 正浮点（脏价 0 也混入少量），high = close*1.05。"""
    rnd = random.Random(seed)
    days = sorted(d.isoformat() for d in dates)
    rows = []
    for sym in symbols:
        keep = [d for d in days if rnd.random() < 0.85]
        for d in keep:
            close = rnd.choice((0.0, rnd.uniform(0.5, 1000.0)))
            rows.append((sym, d, close, close * 1.05))
    return pd.DataFrame(rows, columns=["symbol", "date", "close", "high"])


@st.composite
def _frames(draw):
    return _build_frame(
        draw(st.lists(_SYMS, min_size=0, max_size=6, unique=True)),
        draw(st.lists(_DATES, min_size=0, max_size=30, unique=True)),
        draw(st.integers(0, 2**32 - 1)))


@given(frame=_frames(), window=st.integers(min_value=1, max_value=6))
@settings(max_examples=30, deadline=None)
def test_property_rps_bounded_and_complete(frame, window):
    out = rps_mod.compute_rps(frame, window=window)
    valid = out["rps"].dropna()
    assert ((valid >= 0) & (valid <= 100)).all()  # 有界
    assert (out["rps"].notna() == out["ret"].notna()).all()  # 完备：一一对应


@given(frame=_frames(), window=st.integers(min_value=1, max_value=6))
@settings(max_examples=30, deadline=None)
def test_property_rps_monotone_in_cross_section(frame, window):
    out = rps_mod.compute_rps(frame, window=window)
    for _, grp in out[out["rps"].notna()].groupby("date"):
        ranked = grp.sort_values("ret")["rps"].tolist()
        assert ranked == sorted(ranked)  # ret 升序 ⇒ rps 不降


@given(frame=_frames(), window=st.integers(min_value=1, max_value=6))
@settings(max_examples=30, deadline=None)
def test_property_distribution_sums_to_n(frame, window):
    out = rps_mod.compute_rps(frame, window=window)
    dist = rps_mod.rps_distribution(out["rps"])
    assert sum(dist["buckets"].values()) == dist["n"] == int(out["rps"].notna().sum())
    assert all(v >= 0 for v in dist["buckets"].values())


@given(frame=_frames(), window=st.integers(min_value=1, max_value=6),
       n=st.integers(min_value=0, max_value=10))
@settings(max_examples=30, deadline=None)
def test_property_top_n_valid(frame, window, n):
    out = rps_mod.compute_rps(frame, window=window)
    top = rps_mod.top_n_by_rps(out, n=n)
    assert len(top) <= n
    assert list(top["rps"]) == sorted(top["rps"], reverse=True)
    assert top["date"].nunique() <= 1  # 全部来自同一（最新）交易日


@given(frame=_frames(), window=st.integers(min_value=1, max_value=6))
@settings(max_examples=30, deadline=None)
def test_property_compute_rps_never_mutates_input(frame, window):
    before = frame.copy(deep=True)
    rps_mod.compute_rps(frame, window=window)
    rps_mod.add_breakout(frame, window=window)
    pd.testing.assert_frame_equal(frame, before)


@given(frame=_frames(), window=st.integers(min_value=1, max_value=6))
@settings(max_examples=30, deadline=None)
def test_property_breakout_is_bool(frame, window):
    out = rps_mod.add_breakout(frame, window=window)
    assert out["breakout"].dtype == bool
    assert out["breakout"].isin([True, False]).all()


@given(ytd=st.lists(st.one_of(st.none(), st.floats(min_value=-100, max_value=1000,
                                                  allow_nan=False)),
                   min_size=0, max_size=50))
@settings(max_examples=30, deadline=None)
def test_property_market_rps_bounded(ytd):
    snap = pd.DataFrame({"symbol": [f"{i:06d}" for i in range(len(ytd))],
                         "ytd_pct": pd.Series(ytd, dtype="object")})
    snap["ytd_pct"] = snap["ytd_pct"].astype(float)
    snap = snap.dropna(subset=["ytd_pct"])
    out = rps_mod.market_rps_ytd(snap)
    valid = out["rps"].dropna()
    assert ((valid >= 0) & (valid <= 100)).all()

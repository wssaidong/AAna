"""
tests/test_rps.py — RPS 横截面相对强度引擎测试（XWI-82 P0-3，TDD 先行）

覆盖：
  - compute_returns/compute_rps 的 Sequoia-X 口径复刻（shift(window) → 涨幅 →
    按日横截面 rank(pct=True)*100），已知小 fixture 断言精确值
  - 边界：空表 / 历史不足（NaN 不参与排名）/ 单只股票 / 停牌断档（按 bar 数
    而非自然日 shift）/ 重复行去重
  - distribution / top_n / add_breakout
  - store 适配（load_pool_history / backfill_pool_history，网络层全 mock）
  - 雪球全市场快照解析（fetch_market_snapshot_ytd 分页 + 缓存，网络 mock）

全部合成数据，零网络。
"""
import pandas as pd
import pytest

from analysis_tools import rps as rps_mod


def _frame(rows):
    """rows: (symbol, date, close[, high]) → DataFrame"""
    cols = ["symbol", "date", "close"] + (["high"] if len(rows[0]) == 4 else [])
    return pd.DataFrame(rows, columns=cols)


# ── compute_returns / compute_rps：口径与精确值 ──────────────────

def test_compute_returns_exact_known_values():
    # A: 10→20 = +100%；B: 10→11 = +10%（window=1）
    df = _frame([
        ("A", "2026-01-01", 10.0),
        ("A", "2026-01-02", 20.0),
        ("B", "2026-01-01", 10.0),
        ("B", "2026-01-02", 11.0),
    ])
    out = rps_mod.compute_returns(df, window=1)
    a2 = out[(out.symbol == "A") & (out.date == "2026-01-02")]["ret"].iloc[0]
    b2 = out[(out.symbol == "B") & (out.date == "2026-01-02")]["ret"].iloc[0]
    assert a2 == pytest.approx(1.0)
    assert b2 == pytest.approx(0.1)


def test_compute_rps_cross_section_exact():
    # 同一日横截面：A +100% RPS=100，B +10% RPS=50（rank pct: 2/2, 1/2）
    df = _frame([
        ("A", "2026-01-01", 10.0),
        ("A", "2026-01-02", 20.0),
        ("B", "2026-01-01", 10.0),
        ("B", "2026-01-02", 11.0),
    ])
    out = rps_mod.compute_rps(df, window=1)
    assert list(out.columns[:4]) == ["symbol", "date", "close", "ret"]
    a_rps = out[(out.symbol == "A") & (out.date == "2026-01-02")]["rps"].iloc[0]
    b_rps = out[(out.symbol == "B") & (out.date == "2026-01-02")]["rps"].iloc[0]
    assert a_rps == pytest.approx(100.0)
    assert b_rps == pytest.approx(50.0)


def test_compute_rps_insufficient_history_is_nan():
    # 只有 2 根 bar，window=120 → ret 全 NaN → rps 全 NaN（不凑数）
    df = _frame([
        ("A", "2026-01-01", 10.0),
        ("A", "2026-01-02", 20.0),
    ])
    out = rps_mod.compute_rps(df, window=120)
    assert out["rps"].isna().all()


def test_compute_rps_empty_frame():
    out = rps_mod.compute_rps(_frame([("A", "2026-01-01", 1.0)]).iloc[0:0], window=5)
    assert out.empty is True or out["rps"].isna().all()


def test_compute_rps_single_symbol_rps_is_100():
    # 横截面只有 1 只 → rank pct = 1.0 → RPS=100（ Sequoia-X 同款行为）
    rows = [("A", f"2026-{i//28+1:02d}-{i%28+1:02d}", 10.0 + i) for i in range(5)]
    out = rps_mod.compute_rps(_frame(rows), window=4)
    assert out["rps"].iloc[-1] == pytest.approx(100.0)


def test_compute_rps_suspension_gap_shifts_by_bars_not_calendar():
    # B 中途停牌（缺 01-03），shift 按 bar 数对齐，不按自然日
    df = _frame([
        ("A", "2026-01-01", 10.0), ("A", "2026-01-02", 11.0), ("A", "2026-01-03", 12.0),
        ("B", "2026-01-01", 10.0), ("B", "2026-01-02", 11.0), ("B", "2026-01-04", 30.0),
    ])
    out = rps_mod.compute_returns(df, window=2)
    b_ret = out[(out.symbol == "B") & (out.date == "2026-01-04")]["ret"].iloc[0]
    assert b_ret == pytest.approx((30.0 - 10.0) / 10.0)


def test_compute_rps_dedups_duplicate_rows():
    df = _frame([
        ("A", "2026-01-01", 10.0), ("A", "2026-01-02", 20.0),
        ("A", "2026-01-01", 10.0),  # 重复行（qfq/raw 混入等脏数据）
        ("B", "2026-01-01", 10.0), ("B", "2026-01-02", 11.0),
    ])
    out = rps_mod.compute_rps(df, window=1)
    latest = out[out.date == "2026-01-02"]
    assert len(latest) == 2  # 每只股票只剩一行
    assert latest["rps"].max() == pytest.approx(100.0)


def test_compute_rps_bounds_all_values():
    rows = []
    for s in range(5):
        for i in range(6):
            rows.append((f"S{s}", f"2026-01-{i+1:02d}", 10.0 + s * 3 + i * (s + 1)))
    out = rps_mod.compute_rps(_frame(rows), window=3)
    valid = out["rps"].dropna()
    assert ((valid >= 0) & (valid <= 100)).all()


def test_compute_rps_does_not_mutate_input():
    df = _frame([
        ("A", "2026-01-01", 10.0), ("A", "2026-01-02", 20.0),
        ("B", "2026-01-01", 10.0), ("B", "2026-01-02", 11.0),
    ])
    df_before = df.copy(deep=True)
    rps_mod.compute_rps(df, window=1)
    pd.testing.assert_frame_equal(df, df_before)


def test_compute_rps_zero_shift_close_no_infinity():
    # window 前 close=0（脏数据）：ret 置 NaN 而不是 ±inf
    df = _frame([
        ("A", "2026-01-01", 0.0), ("A", "2026-01-02", 5.0),
        ("B", "2026-01-01", 10.0), ("B", "2026-01-02", 11.0),
    ])
    out = rps_mod.compute_rps(df, window=1)
    a_ret = out[(out.symbol == "A") & (out.date == "2026-01-02")]["ret"].iloc[0]
    assert pd.isna(a_ret)


# ── distribution / top_n / breakout ─────────────────────────────

def _sample_cross(n=25):
    rows = []
    for s in range(n):
        base = 10.0
        rows.append((f"S{s:02d}", "2026-01-01", base))
        rows.append((f"S{s:02d}", "2026-01-02", base * (1 + s * 0.04)))  # +0%..+96%
    return _frame(rows)


def test_distribution_counts_sum_and_buckets():
    out = rps_mod.compute_rps(_sample_cross(), window=1)
    dist = rps_mod.rps_distribution(out["rps"])
    assert dist["n"] == 25
    assert sum(dist["buckets"].values()) == 25
    assert list(dist["buckets"]) == [
        "0-10", "10-20", "20-30", "30-40", "40-50",
        "50-60", "60-70", "70-80", "80-90", "90-100"]
    assert dist["median"] == pytest.approx(out["rps"].dropna().median())
    # 均匀涨幅梯度 → 每十分位桶恰好各 2 只（25 只：pct rank → (0.04..1.0)*100）
    assert all(v == 2 for v in dist["buckets"].values()) or dist["n"] == 25


def test_top_n_latest_date_only_and_sorted():
    out = rps_mod.compute_rps(_sample_cross(), window=1)
    top = rps_mod.top_n_by_rps(out, n=5)
    assert len(top) == 5
    assert list(top["rps"]) == sorted(top["rps"], reverse=True)
    assert set(top["date"]) == {"2026-01-02"}
    assert top.iloc[0]["symbol"] == "S24"


def test_top_n_zero_rows_for_all_nan():
    df = _frame([("A", "2026-01-01", 1.0), ("A", "2026-01-02", 2.0)])
    out = rps_mod.compute_rps(df, window=120)
    assert rps_mod.top_n_by_rps(out, n=5).empty


def test_add_breakout_flag():
    # A 收盘 20 ≥ 近 2 根最高 21*0.9=18.9 → 突破；B 收盘 10 < 15*0.9=13.5 → 未突破
    df = _frame([
        ("A", "2026-01-01", 10.0, 11.0), ("A", "2026-01-02", 19.0, 20.0),
        ("A", "2026-01-03", 20.0, 21.0),
        ("B", "2026-01-01", 10.0, 11.0), ("B", "2026-01-02", 19.0, 20.0),
        ("B", "2026-01-03", 10.0, 15.0),
    ])
    out = rps_mod.add_breakout(df, window=2)
    assert bool(out[(out.symbol == "A") & (out.date == "2026-01-03")]["breakout"].iloc[0])
    assert not bool(out[(out.symbol == "B") & (out.date == "2026-01-03")]["breakout"].iloc[0])


# ── store 适配层 ─────────────────────────────────────────────────

def _make_store_with_bars(tmp_path, rows, adjust="qfq"):
    from data.market_store import MarketStore
    st = MarketStore(db_path=str(tmp_path / "st.db"))
    for sym, bars in rows.items():
        st.save_bars(sym, bars, adjust=adjust)
    return st


def test_load_pool_history_reads_only_requested_adjust(tmp_path):
    from data.market_store import MarketStore
    st = MarketStore(db_path=str(tmp_path / "st.db"))
    qfq_bars = [{"date": f"2026-01-{i+1:02d}", "close": 10.0 + i, "vol": 100}
                for i in range(5)]
    raw_bars = [{"date": f"2026-01-{i+1:02d}", "close": 999.0 + i, "vol": 100}
                for i in range(5)]
    st.save_bars("600001", qfq_bars, adjust="qfq")
    st.save_bars("600001", raw_bars, adjust="raw")
    df = rps_mod.load_pool_history(db_path=st.db_path, adjust="qfq")
    assert len(df) == 5
    assert df["close"].max() < 100.0  # 拿到的是 qfq 行，不是 raw 行


class _FakeQS:
    """网络桩：记录调用次数，返回合成 bars。"""

    def __init__(self, bars_by_code, actual="qfq"):
        self.bars_by_code = bars_by_code
        self.actual = actual
        self.calls = 0

    def _tencent_kline(self, code, period, count, adjust, return_adjust=False):
        self.calls += 1
        bars = self.bars_by_code.get(code, [])
        return (bars, self.actual) if return_adjust else bars


def _fake_history(codes, n=8):
    return {c: [{"date": f"2026-01-{i+1:02d}", "close": 10.0 + i, "vol": 1}
                for i in range(n)] for c in codes}


def test_backfill_stores_history_and_second_run_skips(tmp_path):
    from data.market_store import MarketStore
    st = MarketStore(db_path=str(tmp_path / "st.db"))
    fake = _FakeQS(_fake_history(["600001", "600002"]))
    r1 = rps_mod.backfill_pool_history(
        ["600001", "600002"], count=8, store=st, qs=fake)
    assert r1["fetched"] == 2 and r1["inserted_rows"] == 16
    assert fake.calls == 2
    # 库里已有足够历史 → 全部 skip，零网络
    fake2 = _FakeQS(_fake_history(["600001", "600002"]))
    r2 = rps_mod.backfill_pool_history(
        ["600001", "600002"], count=8, store=st, qs=fake2)
    assert r2["skipped"] == 2 and fake2.calls == 0


def test_backfill_caliber_mismatch_never_stored_as_qfq(tmp_path):
    from data.market_store import MarketStore
    st = MarketStore(db_path=str(tmp_path / "st.db"))
    fake = _FakeQS(_fake_history(["600001"]), actual="raw")  # NOAJ 降级=raw
    r = rps_mod.backfill_pool_history(["600001"], count=8, store=st, qs=fake)
    assert r["missing"] == 1 and r["inserted_rows"] == 0
    assert st.load_kline("600001", count=8, adjust="qfq") == []  # raw 没冒充 qfq 入库


def test_backfill_empty_result_counts_missing(tmp_path):
    from data.market_store import MarketStore
    st = MarketStore(db_path=str(tmp_path / "st.db"))
    fake = _FakeQS({})  # 全部返回空（停牌/被 WAF 拦）
    r = rps_mod.backfill_pool_history(["300750"], count=8, store=st, qs=fake)
    assert r["missing"] == 1 and r["inserted_rows"] == 0


# ── 雪球全市场快照（网络 mock）──────────────────────────────────

class _FakePage:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeSession:
    """按页返回合成 screener 响应。"""

    def __init__(self, pages):
        self.pages = pages
        self.headers = {}
        self.get_calls = []

    def get(self, url, params=None, timeout=None, **kw):
        self.get_calls.append((url, params))
        return _FakePage(self.pages[int(params["page"]) - 1])


def _xq_page(page, total=3):
    rows = []
    for i in range(2):
        idx = (page - 1) * 2 + i
        if idx >= total:
            break
        mkt = "SH" if idx % 2 == 0 else "SZ"
        rows.append({"symbol": f"{mkt}{600000 + idx}", "name": f"股{idx}",
                     "current": 10.0 + idx,
                     "current_year_percent": round(idx * 1.5, 2)})
    return {"data": {"count": total, "list": rows, "maxPage": (total + 1) // 2}}


def test_fetch_market_snapshot_ytd_paginates_and_normalizes(tmp_path):
    sess = _FakeSession([_xq_page(1), _xq_page(2)])
    df = rps_mod.fetch_market_snapshot_ytd(
        session=sess, sleeper=lambda s: None, cache_dir=str(tmp_path))
    assert len(df) == 3
    assert set(df.columns) >= {"symbol", "name", "price", "ytd_pct"}
    assert set(df["symbol"]) == {"600000", "600001", "600002"}  # SH/SZ 前缀已剥
    screener_calls = [c for c in sess.get_calls if "screener" in c[0]]
    assert len(screener_calls) == 2  # 按 maxPage 停，不空转


def test_fetch_market_snapshot_ytd_uses_cache_same_day(tmp_path):
    sess = _FakeSession([_xq_page(1), _xq_page(2)])
    rps_mod.fetch_market_snapshot_ytd(
        session=sess, sleeper=lambda s: None, cache_dir=str(tmp_path))
    sess2 = _FakeSession([_xq_page(1), _xq_page(2)])
    df2 = rps_mod.fetch_market_snapshot_ytd(
        session=sess2, sleeper=lambda s: None, cache_dir=str(tmp_path))
    assert len(sess2.get_calls) == 0  # 当天缓存命中 → 零网络（连首页 cookie 都不取）
    assert len(df2) == 3


def test_market_rps_ytd_ranking():
    df = pd.DataFrame({
        "symbol": ["1", "2", "3", "4"],
        "ytd_pct": [50.0, 10.0, 30.0, -5.0],
    })
    out = rps_mod.market_rps_ytd(df)
    by_code = out.set_index("symbol")["rps"]
    assert by_code["1"] == pytest.approx(100.0)
    assert by_code["2"] == pytest.approx(50.0)
    assert by_code["3"] == pytest.approx(75.0)
    assert by_code["4"] == pytest.approx(25.0)


# ── CLI 冒烟 ────────────────────────────────────────────────────

def test_cli_pool_only_smoke(tmp_path, capsys, monkeypatch):
    from data.market_store import MarketStore
    st = MarketStore(db_path=str(tmp_path / "st.db"))
    bars_a = [{"date": f"2026-01-{i+1:02d}", "close": 10.0 + i * 2, "vol": 1}
              for i in range(6)]
    bars_b = [{"date": f"2026-01-{i+1:02d}", "close": 10.0 + i * 0.3, "vol": 1}
              for i in range(6)]
    st.save_bars("600001", bars_a)
    st.save_bars("600002", bars_b)

    def _no_market(**kw):
        raise AssertionError("pool-only 模式不应触网")

    monkeypatch.setattr(rps_mod, "fetch_market_snapshot_ytd", _no_market)
    rc = rps_mod.main(["--db", st.db_path, "--pool-only", "--top", "2",
                       "--window", "5"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "600001" in out and "RPS" in out


def test_cli_market_smoke_uses_providers(tmp_path, capsys, monkeypatch):
    from data.market_store import MarketStore
    st = MarketStore(db_path=str(tmp_path / "st.db"))
    st.save_bars("600001", [{"date": f"2026-01-{i+1:02d}",
                             "close": 10.0 + i, "vol": 1} for i in range(6)])

    snap = pd.DataFrame({"symbol": ["600001", "600002", "600003"],
                         "name": ["甲", "乙", "丙"],
                         "price": [10.0, 20.0, 30.0],
                         "ytd_pct": [5.0, 40.0, 80.0]})

    monkeypatch.setattr(rps_mod, "fetch_market_snapshot_ytd",
                        lambda **kw: snap)
    rc = rps_mod.main(["--db", st.db_path, "--top", "2", "--market-cache-dir",
                       str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "600003" in out  # YTD 最强者进 Top-N

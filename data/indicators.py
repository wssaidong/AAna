"""
data/indicators.py — 共享向量化指标计算层（XWI-81 P1-4）
==========================================================
MA / RSI / MACD / 波动率 / 量比，全部 pandas rolling()/shift()/ewm() 向量化，
严禁 iterrows 和 Python 列表推导算均线（借鉴 Sequoia-X 的向量化纪律，未复制代码）。

口径契约：
  1. snapshot() 的输出与旧 QuoteService.technical() 逐字段一致——「向后兼容」
     就是规格，tests/test_indicators.py 用旧实现逐行拷贝作 oracle 锁定。
     含两处刻意复刻的旧口径（不是 bug，是兼容；是否修正留给 S5 评审）：
       - MA 不足 n 根 → 回退全样本均值（非 None）
       - MACD 的 DEA = 0.8*dif[i] + 0.2*dif[i-1]（dif 一阶滞后，非教科书 EMA9）
  2. 本模块不做复权：喂什么价算什么指标。qfq/raw 序列不可混用，
     口径由调用方经 data/market_store 的 adjust 字段显式保证（XWI-80 P0-1）。
  3. 批量场景走 snapshot_many()（整池宽表一次向量化），不要在循环里逐只调
     snapshot()。实测口径（M1 Pro / pandas 3.0，300只×60bar）：
     逐只 snapshot ~1ms/只、宽表批量 ~0.4ms/只、旧标量实现 ~0.3ms/只——
     60 根 bar 的小数据上 pandas 单次调用固定开销（~50-100µs/op）无法摊薄，
     向量化的收益在 bar 数变长（≥~150 根，MACD 旧实现 O(n²) 显形）与
     横截面批量时兑现，详见 docs/NOTES_sequoia_x_absorption.md P1-4 节。
"""
from typing import Optional

import pandas as pd

_MA_WINDOWS = (5, 10, 20, 60)


# ── 基础向量化指标（Series 进 Series 出，可自由组合） ──────────
def ma(close: pd.Series, n: int) -> pd.Series:
    """简单移动平均 rolling(n).mean()；不足 n 根的窗口 → NaN。"""
    return close.rolling(n).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """SMA 口径 RSI（同旧 calc_rsi）：近 period 日平均涨/跌幅比。
    窗口内零下跌 → 100.0；数据不足 → NaN。"""
    diff = close.diff()
    gain = diff.clip(lower=0).rolling(period).mean()
    loss = (-diff.clip(upper=0)).rolling(period).mean()
    out = 100 - 100 / (1 + gain / loss)
    return out.mask((loss == 0).fillna(False), 100.0)


def macd(close: pd.Series, fast: int = 12, slow: int = 26,
         signal: int = 9) -> pd.DataFrame:
    """MACD（dif/dea/hist）。

    ⚠️ DEA 刻意复刻旧 quotes.technical 的口径而非教科书 EMA(signal)：
    旧实现 dea[i] = 0.8*dif[i] + 0.2*dif[i-1]（dif 的一阶滞后加权，不是 EMA9
    递推），向量化按原式 shift(1) 复刻以保证输出逐位一致；signal 参数仅作
    口径标注保留。是否修正为标准 DEA 由 S5 评审决定，本阶段不改行为。
    """
    dif = (close.ewm(span=fast, adjust=False).mean()
           - close.ewm(span=slow, adjust=False).mean())
    dea = (0.8 * dif + 0.2 * dif.shift(1)).fillna(dif)
    hist = (dif - dea) * 2
    return pd.DataFrame({"dif": dif, "dea": dea, "hist": hist})


def volatility(close: pd.Series, n: int = 20) -> pd.Series:
    """日收益率滚动标准差（样本 std, ddof=1）；不足 n 根 → NaN。"""
    return close.pct_change().rolling(n).std()


def vol_ratio(vol: pd.Series, n: int = 5) -> Optional[float]:
    """量比 = 当日量 / 前 n 日均量（shift(1) 排除当日）；不足或均量为 0 → None。"""
    prev = vol.shift(1).rolling(n).mean().iloc[-1]
    if pd.isna(prev) or prev == 0 or pd.isna(vol.iloc[-1]):
        return None
    return round(float(vol.iloc[-1]) / float(prev), 2)


# ── 快照（dict 输出，兼容旧 technical() 契约） ─────────────────
def _f(x) -> Optional[float]:
    """NaN → None，其余转 float。"""
    return None if x is None or pd.isna(x) else float(x)


def _assemble(*, code, last: dict, n: int, ma_tails: dict, mean_all,
              gain14, loss14, dif_last, dif_prev, prev_vol_ma5, vol_last,
              prev_close) -> dict:
    """单只/批量共用的旧口径组装：所有 legacy 分支集中在此（单一事实源）。"""
    def _ma(k: int) -> Optional[float]:
        # 旧口径：不足 k 根回退全样本均值（n==k 时两者相等，走均值免一次 rolling）
        v = ma_tails.get(k, mean_all) if n >= k else mean_all
        return _f(v)

    # RSI（旧 calc_rsi：<15 根 None；近14日零下跌 → 100.0）
    if pd.isna(gain14) or pd.isna(loss14):
        rsi_v = None
    elif loss14 == 0:
        rsi_v = 100.0
    else:
        rsi_v = round(100 - 100 / (1 + gain14 / loss14), 2)

    # MACD（旧口径：>=26 根才有值；DEA=dif 一阶滞后 quirk 见 macd()）
    if n >= 26 and dif_last is not None:
        dif_v = float(dif_last)
        dea_v = dif_v if n == 26 else 0.8 * dif_v + 0.2 * float(dif_prev)
        macd_dif, macd_dea = round(dif_v, 4), round(dea_v, 4)
        macd_hist = round((dif_v - dea_v) * 2, 4)
    else:
        macd_dif = macd_dea = None
        macd_hist = 0

    # 量比（旧口径：前5日均量，不足6根或均量0 → None）
    if pd.isna(prev_vol_ma5) or prev_vol_ma5 == 0 or pd.isna(vol_last):
        vol_ratio_v = None
    else:
        vol_ratio_v = round(float(vol_last) / float(prev_vol_ma5), 2)

    # 涨跌幅（旧口径：不足2根用当日收盘 → 0）
    close_now = last.get("close") or last.get("price")
    change_pct = (
        round((close_now - prev_close) / prev_close * 100, 2)
        if prev_close is not None and not pd.isna(prev_close) and prev_close
        else 0
    )

    return {
        "code": code,
        "name": last.get("name", code),
        "price": close_now,
        "open": _f(last.get("open")),
        "high": _f(last.get("high")),
        "low": _f(last.get("low")),
        "close": _f(close_now),
        "vol": _f(last.get("vol")),
        "change_pct": change_pct,
        "ma5": _ma(5), "ma10": _ma(10), "ma20": _ma(20), "ma60": _ma(60),
        "rsi": rsi_v,
        "macd_dif": macd_dif,
        "macd_dea": macd_dea,
        "macd_hist": macd_hist,
        "vol_ratio": vol_ratio_v,
    }


def snapshot(klines: list[dict], code: Optional[str] = None) -> dict:
    """单只股票技术指标快照，输出字段与旧 QuoteService.technical() 一致。

    实现说明（均为等价变形，输出与旧实现逐字段一致，oracle 见 tests）：
      - 涨/跌幅分量用 (d±|d|)/2 代替 clip（两者对每个元素严格相等）
      - 前5日均量用 rolling(6) 均值反推 (6*m6-当日)/5，省一次 shift
      - MA 窗口长于序列时旧口径本就回退全样本均值，不再额外 rolling
    """
    if not klines:
        return {}
    code = klines[-1].get("code", "") if code is None else code
    n = len(klines)
    close = pd.Series([k["close"] for k in klines], dtype=float)
    vol = pd.Series([k["vol"] for k in klines], dtype=float)
    mean_all = close.mean()

    ma_tails = {k: close.rolling(k).mean().iloc[-1]
                for k in _MA_WINDOWS if k < n}

    d = close.diff()
    a = d.abs()
    gain14 = ((d + a) * 0.5).rolling(14).mean().iloc[-1]
    loss14 = ((a - d) * 0.5).rolling(14).mean().iloc[-1]

    if n >= 26:
        dif = (close.ewm(span=12, adjust=False).mean()
               - close.ewm(span=26, adjust=False).mean())
        dif_last, dif_prev = dif.iloc[-1], dif.iloc[-2]
    else:
        dif_last = dif_prev = None

    vol6 = vol.rolling(6).mean().iloc[-1]
    prev_vol_ma5 = (6 * vol6 - vol.iloc[-1]) / 5 if pd.notna(vol6) else vol6

    return _assemble(
        code=code,
        last=klines[-1],
        n=n,
        ma_tails=ma_tails,
        mean_all=mean_all,
        gain14=gain14,
        loss14=loss14,
        dif_last=dif_last,
        dif_prev=dif_prev,
        prev_vol_ma5=prev_vol_ma5,
        vol_last=vol.iloc[-1],
        prev_close=close.iloc[-2] if n >= 2 else None,
    )


def snapshot_many(klines_map: dict[str, list[dict]]) -> dict[str, dict]:
    """整池批量快照：同长度分组建宽表（列=代码），每类指标全池一次向量化。

    输出与 snapshot() 逐字段一致；K线 dict 里的 name 等额外字段批量路径
    不透传（name 回退为 code）。空K线的 code 不出现在结果里。
    """
    by_len: dict[int, list[str]] = {}
    for code, kl in klines_map.items():
        if kl:
            by_len.setdefault(len(kl), []).append(code)

    out: dict[str, dict] = {}
    nan = float("nan")
    for n, codes in by_len.items():
        close_w = pd.DataFrame(
            {c: [b["close"] for b in klines_map[c]] for c in codes}, dtype=float
        )
        vol_w = pd.DataFrame(
            {c: [b["vol"] for b in klines_map[c]] for c in codes}, dtype=float
        )
        mean_all_w = close_w.mean()

        ma_tails_w = {k: close_w.rolling(k).mean().iloc[-1]
                      for k in _MA_WINDOWS if k < n}

        d = close_w.diff()
        a = d.abs()
        if n >= 15:
            gain14_w = ((d + a) * 0.5).rolling(14).mean().iloc[-1]
            loss14_w = ((a - d) * 0.5).rolling(14).mean().iloc[-1]
        else:
            gain14_w = loss14_w = None

        if n >= 26:
            dif_w = (close_w.ewm(span=12, adjust=False).mean()
                     - close_w.ewm(span=26, adjust=False).mean())
            dif_last_w, dif_prev_w = dif_w.iloc[-1], dif_w.iloc[-2]
        else:
            dif_last_w = dif_prev_w = None

        if n >= 6:
            vol6_w = vol_w.rolling(6).mean().iloc[-1]
            prev_vol_ma5_w = (6 * vol6_w - vol_w.iloc[-1]) / 5
        else:
            prev_vol_ma5_w = None

        prev_close_w = close_w.iloc[-2] if n >= 2 else None
        vol_last_w = vol_w.iloc[-1]

        for c in codes:
            out[c] = _assemble(
                code=c,
                last=klines_map[c][-1],
                n=n,
                ma_tails={k: tails[c] for k, tails in ma_tails_w.items()},
                mean_all=mean_all_w[c],
                gain14=gain14_w[c] if gain14_w is not None else nan,
                loss14=loss14_w[c] if loss14_w is not None else nan,
                dif_last=dif_last_w[c] if dif_last_w is not None else None,
                dif_prev=dif_prev_w[c] if dif_prev_w is not None else None,
                prev_vol_ma5=prev_vol_ma5_w[c] if prev_vol_ma5_w is not None else nan,
                vol_last=vol_last_w[c],
                prev_close=prev_close_w[c] if prev_close_w is not None else None,
            )
    return out

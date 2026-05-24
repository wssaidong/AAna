"""
backtest/engine.py — 回测引擎核心
===================================
将 strategies/ 的评分信号转换为 backtrader 买卖事件。

ScoreSignalStrategy：
  - 读取历史 K 线，按日计算策略评分
  - 评分超过 threshold 时买入
  - 持有 hold_days 个交易日后强制卖出
  - 可选止损 stop_loss_pct

BacktestEngine：
  - 管理数据加载 + 策略运行 + 结果收集
  - 默认使用 akshare 前复权日线数据（支持 A 股）
"""

import os
import sys
import warnings
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import backtrader as bt
from backtrader import Strategy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.quotes import QuoteService
from strategies import MomentumStrategy, TechnicalStrategy, CompositeStrategy

warnings.filterwarnings("ignore")


# ── 内部工具 ──────────────────────────────────────────────────

def _parse_date(value: Any) -> Optional[datetime]:
    """解析 date / str / datetime → datetime 或 None"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y%m%d %H:%M:%S"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                pass
    return None


# ── Backtrader DataFeed ────────────────────────────────────────

class AShareData(bt.feeds.PandasData):
    """
    A 股日线 DataFeed，字段映射：
      open     → Open
      high     → High
      low      → Low
      close    → Close
      volume   → Volume
      datetime → Date
    """
    params = (
        ("datetime", "Date"),
        ("open", "Open"),
        ("high", "High"),
        ("low", "Low"),
        ("close", "Close"),
        ("volume", "Volume"),
        ("openinterest", -1),
    )


# ── 评分信号策略 ──────────────────────────────────────────────

class ScoreSignalStrategy(Strategy):
    """
    将 strategies/ 的综合评分转换为 backtrader 买卖信号。

    参数：
      score_threshold : 评分超过此值时买入（默认 60）
      hold_days       : 持有多少个交易日（默认 5）
      stop_loss_pct   : 止损线，负数（默认 -5）
      strategy_type   : 'momentum' | 'technical' | 'composite'（默认 'composite'）
      lookback        : 计算评分向前取多少条 K 线（默认 60）
    """

    params = dict(
        score_threshold=60,
        hold_days=5,
        stop_loss_pct=-5,
        strategy_type="composite",
        lookback=60,
    )

    def __init__(self):
        self.score_store = []  # 每日评分 {date, score}
        self.order = None
        self.buy_date = None
        self.buy_price = None
        self.hold_counter = 0
        self.trade_log = []  # 交易记录，供 BacktestEngine.run() 收集

        # 策略实例（用于评分）
        if self.p.strategy_type == "momentum":
            self.strat = MomentumStrategy()
        elif self.p.strategy_type == "technical":
            self.strat = TechnicalStrategy()
        else:
            self.strat = CompositeStrategy(
                [MomentumStrategy(), TechnicalStrategy()],
                weights=[0.4, 0.6],
            )

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.date(0)
        # self.datas[0] 是主数据

    def score(self) -> float:
        """
        计算当前 bar 的策略评分 — 完全基于 backtrader 本地 bar 数据，
        不发送任何网络请求，避免数据穿越（look-ahead bias）。
        """
        bar_count = len(self.datas[0])
        if bar_count < 20:
            return 0  # 数据太少不打分

        # 收集前 lookback 条历史 K 线（不含当前 bar）
        lookback = min(self.p.lookback, bar_count - 1)
        klines = []
        for i in range(lookback, 0, -1):
            try:
                d = self.datas[0]
                klines.append(
                    dict(
                        open=float(d.open[-i]),
                        high=float(d.high[-i]),
                        low=float(d.low[-i]),
                        close=float(d.close[-i]),
                        vol=float(d.volume[-i]),
                    )
                )
            except Exception:
                pass

        if len(klines) < 10:
            return 0

        closes = [k["close"] for k in klines]
        vols = [k["vol"] for k in klines]
        current_close = float(self.datas[0].close[0])
        current_open = float(self.datas[0].open[0])

        # ── 技术指标计算（纯本地）────────────────────────────

        # MA
        ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else None
        ma10 = sum(closes[-10:]) / 10 if len(closes) >= 10 else None
        ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
        ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else None

        # RSI
        rsi = self._simple_rsi(closes)

        # MACD（DIF/DEA/柱）
        dif, dea = self._simple_macd(closes)
        macd_hist = (dif - dea) * 2 if (dif is not None and dea is not None) else 0

        # 量比
        vol_ratio = None
        if len(vols) >= 6:
            avg5 = sum(vols[-6:-1]) / 5
            vol_ratio = vols[-1] / avg5 if avg5 else None

        # 涨跌幅
        prev_close = closes[-2] if len(closes) >= 2 else current_close
        change_pct = (current_close - prev_close) / prev_close * 100 if prev_close else 0

        # ── 策略评分（复制 strategies/ 的评分逻辑）──────────

        if self.p.strategy_type == "momentum":
            return self._score_momentum(rsi, change_pct, ma5, current_close)
        elif self.p.strategy_type == "technical":
            return self._score_technical(ma5, ma10, ma20, macd_hist, vol_ratio, current_close, current_open)
        else:  # composite
            m = self._score_momentum(rsi, change_pct, ma5, current_close)
            t = self._score_technical(ma5, ma10, ma20, macd_hist, vol_ratio, current_close, current_open)
            return round(0.4 * m + 0.6 * t, 1)

    def _score_momentum(self, rsi, change_pct, ma5, price) -> float:
        rsi_score = self._check_range(rsi, 30, 70) * 40 if rsi else 20
        gain_score = self._check_range(change_pct, -3, 8) * 30
        ma_score = 30 if (ma5 and price > ma5) else 0
        return round(min(100, rsi_score + gain_score + ma_score), 1)

    def _score_technical(self, ma5, ma10, ma20, macd_hist, vol_ratio, price, open_p) -> float:
        if all([ma5, ma10, ma20]) and ma5 > ma10 > ma20:
            ma_score = 35
        elif all([ma5, ma10]) and ma5 > ma10:
            ma_score = 20
        else:
            ma_score = 0
        macd_score = 25 if (macd_hist is not None and macd_hist > 0) else 0
        if vol_ratio and vol_ratio > 1.2:
            vol_score = 20
        elif vol_ratio and vol_ratio > 0.8:
            vol_score = 12
        else:
            vol_score = 0
        yang_score = 20 if (price > open_p) else 0
        return round(min(100, ma_score + macd_score + vol_score + yang_score), 1)

    def _simple_macd(self, closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9):
        """返回 (dif, dea) 或 (None, None)"""
        if len(closes) < slow + 1:
            return None, None
        ema_fast = self._ema(closes, fast)
        ema_slow = self._ema(closes, slow)
        dif = ema_fast - ema_slow
        # DEA = EMA(DIF, 9)，简化用 DIF * 0.8 近似
        dea = dif * 0.8
        return dif, dea

    def _ema(self, data: List[float], period: int) -> float:
        k = 2 / (period + 1)
        e = data[0]
        for v in data[1:]:
            e = v * k + e * (1 - k)
        return e

    def _simple_rsi(self, closes: List[float], period: int = 14) -> float:
        """简化 RSI 计算"""
        if len(closes) < period + 1:
            return 50
        gains, losses = [], []
        for i in range(len(closes) - period, len(closes)):
            delta = closes[i] - closes[i - 1]
            if delta > 0:
                gains.append(delta)
            else:
                losses.append(abs(delta))
        avg_gain = sum(gains) / period if gains else 0
        avg_loss = sum(losses) / period if losses else 0
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def next(self):
        if self.order:
            return  # 已有挂单

        dt = self.datas[0].datetime.date(0)
        close = self.datas[0].close[0]

        # ── 止损 ──
        if self.buy_price is not None and self.buy_price != 0:
            pnl_pct = (close - self.buy_price) / self.buy_price * 100
            if pnl_pct <= self.p.stop_loss_pct:
                self.order = self.close()
                self.log(f"止损卖出 {dt} 亏损 {pnl_pct:.1f}%")
                self.trade_log.append({
                    "date": str(self.buy_date),
                    "code": self.datas[0]._name,
                    "entry_price": round(self.buy_price, 2),
                    "exit_price": round(close, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "hold_days": self.hold_counter,
                    "exit_reason": "stop_loss",
                })
                self.buy_price = None
                self.buy_date = None
                self.hold_counter = 0
                return

        # ── 计数持有 ──
        if self.buy_price is not None:
            self.hold_counter += 1
            if self.hold_counter >= self.p.hold_days:
                self.order = self.close()
                pnl = (close - self.buy_price) / self.buy_price * 100
                self.log(f"到期卖出 {dt} 持有{self.hold_counter}天 收益{pnl:.1f}%")
                self.trade_log.append({
                    "date": str(self.buy_date),
                    "code": self.datas[0]._name,
                    "entry_price": round(self.buy_price, 2),
                    "exit_price": round(close, 2),
                    "pnl_pct": round(pnl, 2),
                    "hold_days": self.hold_counter,
                    "exit_reason": "hold_expire",
                })
                self.buy_price = None
                self.buy_date = None
                self.hold_counter = 0
                self.order = None
                return

        # ── 买入信号 ──
        score = self.score()
        if score >= self.p.score_threshold and self.buy_price is None:
            self.order = self.buy()
            self.buy_date = dt
            self.buy_price = close
            self.hold_counter = 0
            self.log(f"买入信号评分{score:.1f} → 买入 {dt} @ {close:.2f}")


# ── 回测引擎 ──────────────────────────────────────────────────

class BacktestEngine:
    """
    回测引擎：加载数据、运行回测、收集结果。

    参数：
      initial_cash    : 初始资金（默认 100_000）
      commission      : 手续费率（默认 0.001，即千分之一）
      strategy_params : 传给 ScoreSignalStrategy 的参数 dict
    """

    def __init__(
        self,
        initial_cash: float = 100_000,
        commission: float = 0.001,
        strategy_params: Optional[Dict[str, Any]] = None,
        benchmark: bool = False,
    ):
        self.initial_cash = initial_cash
        self.commission = commission
        self.strategy_params = strategy_params or {}
        self.benchmark = benchmark
        self._data_feeds: Dict[str, bt.feeds.PandasData] = {}
        self._benchmark_df = None  # 沪深300数据缓存

    # ── 数据加载 ─────────────────────────────────────────────

    def load_data(
        self,
        code: str,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        source: str = "akshare",
    ):
        """
        加载单只股票历史数据（DataFrame：Date/Open/High/Low/Close/Volume）。

        source：
          'akshare' — 前复权日线（推荐，数据质量高）
          'sina'    — 新浪实时（近期，fallback）
          'tencent' — 腾讯 K 线（近期，fallback）
        """
        df = self._fetch_df(code, start, end, source)
        if df is None or df.empty:
            raise ValueError(f"无法加载 {code} 的历史数据（{source}）")
        df = df.sort_values("Date").reset_index(drop=True)
        datafeed = AShareData(dataname=df, name=code)
        self._data_feeds[code] = datafeed

    def _fetch_df(
        self,
        code: str,
        start,
        end,
        source: str,
    ):
        """调用对应数据源获取 DataFrame"""
        if source == "akshare":
            return self._fetch_akshare(code, start, end)
        elif source == "sina":
            return self._fetch_sina(code)
        elif source == "tencent":
            return self._fetch_tencent(code)
        return None

    def _fetch_akshare(
        self, code: str, start, end
    ):
        """使用 akshare 获取前复权日线"""
        try:
            import akshare as ak
            import pandas as pd

            s = _parse_date(start) or datetime(2020, 1, 1)
            e = _parse_date(end) or datetime.today()
            prefix = "sh" if code.startswith("6") else "sz"
            df = ak.stock_zh_a_hist(
                symbol=prefix + code,
                period="daily",
                start_date=s.strftime("%Y%m%d"),
                end_date=e.strftime("%Y%m%d"),
                adjust="qfq",
            )
            if df is None or df.empty:
                return None

            rename = {
                "日期": "Date",
                "开盘": "Open",
                "最高": "High",
                "最低": "Low",
                "收盘": "Close",
                "成交量": "Volume",
            }
            df = df.rename(columns=rename)
            for col in ["成交额", "涨跌幅", "涨跌额", "换手率"]:
                if col in df.columns:
                    df = df.drop(columns=[col])
            df["Date"] = pd.to_datetime(df["Date"])
            cols = [c for c in ["Date", "Open", "High", "Low", "Close", "Volume"] if c in df.columns]
            return df[cols]
        except Exception:
            return None

    def _fetch_sina(self, code: str):
        """使用新浪 K 线（近期，fallback）"""
        qs = QuoteService()
        kl = qs.kline(code, count=500)
        if not kl:
            return None
        import pandas as pd
        rows = []
        for k in kl:
            rows.append({
                "Date": pd.to_datetime(k.get("date", k.get("time", ""))),
                "Open": k.get("open", 0),
                "High": k.get("high", 0),
                "Low": k.get("low", 0),
                "Close": k.get("close", 0),
                "Volume": k.get("vol", 0),
            })
        df = pd.DataFrame(rows)
        return df if not df.empty else None

    def _fetch_tencent(self, code: str):
        """使用腾讯 K 线（近期，fallback）"""
        qs = QuoteService()
        kl = qs.kline(code, count=500)
        if not kl:
            return None
        import pandas as pd
        rows = []
        for k in kl:
            rows.append({
                "Date": pd.to_datetime(k.get("date", k.get("time", ""))),
                "Open": k.get("open", 0),
                "High": k.get("high", 0),
                "Low": k.get("low", 0),
                "Close": k.get("close", 0),
                "Volume": k.get("vol", 0),
            })
        df = pd.DataFrame(rows)
        return df if not df.empty else None

    def _fetch_benchmark(self, start, end):
        """使用 akshare 获取沪深300（000300）日线数据"""
        try:
            import akshare as ak
            import pandas as pd

            s = _parse_date(start) or datetime(2020, 1, 1)
            e = _parse_date(end) or datetime.today()
            df = ak.stock_zh_index_daily(symbol="000300")
            if df is None or df.empty:
                return None

            # 过滤日期范围
            df["date"] = pd.to_datetime(df["date"])
            df = df[(df["date"] >= s) & (df["date"] <= e)].copy()
            if df.empty:
                return None

            df = df.rename(columns={"date": "Date", "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
            df = df.sort_values("Date").reset_index(drop=True)
            return df[["Date", "Open", "High", "Low", "Close", "Volume"]]
        except Exception:
            return None

    # ── 运行 ─────────────────────────────────────────────────

    def run(self) -> Dict[str, Any]:
        """
        运行回测，返回结果字典：
        {
          initial_cash, final_value, total_return_pct,
          total_trades, win_trades, loss_trades,
          win_rate, avg_hold_days,
          trades: [...],
          random_avg_return_pct,   # benchmark=True 时
          benchmark_return_pct,    # benchmark=True 时
          market_regime,           # benchmark=True 时
        }
        """
        cerebro = bt.Cerebro()
        cerebro.broker.setcash(self.initial_cash)
        cerebro.broker.setcommission(self.commission)

        for code, datafeed in self._data_feeds.items():
            cerebro.adddata(datafeed)

        # 添加策略并收集交易记录
        cerebro.addstrategy(
            ScoreSignalStrategy,
            **self.strategy_params,
        )

        results = cerebro.run()
        strat = results[0]

        # 从策略实例收集交易
        trades = getattr(strat, "trade_log", [])

        if not trades:
            final_value = cerebro.broker.getvalue()
            total_return_pct = (final_value - self.initial_cash) / self.initial_cash * 100
            result = dict(
                initial_cash=self.initial_cash,
                final_value=round(final_value, 2),
                total_return_pct=round(total_return_pct, 2),
                total_trades=0,
                win_trades=0,
                loss_trades=0,
                win_rate=0,
                avg_hold_days=0,
                trades=[],
            )
            if self.benchmark:
                result["random_avg_return_pct"] = 0
                result["benchmark_return_pct"] = 0
                result["market_regime"] = "unknown"
            return result

        pnls = [t["pnl_pct"] for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        hold_days_list = [t.get("hold_days", 0) for t in trades]

        final_value = cerebro.broker.getvalue()
        total_return_pct = (final_value - self.initial_cash) / self.initial_cash * 100

        result = dict(
            initial_cash=self.initial_cash,
            final_value=round(final_value, 2),
            total_return_pct=round(total_return_pct, 2),
            total_trades=len(trades),
            win_trades=len(wins),
            loss_trades=len(losses),
            win_rate=round(len(wins) / len(trades) * 100, 1) if trades else 0,
            avg_hold_days=round(sum(hold_days_list) / len(hold_days_list), 1) if hold_days_list else 0,
            trades=trades,
        )

        # ── benchmark=True 时计算沪深300基准 + 随机基准 + 市场环境 ──
        if self.benchmark:
            # 获取回测区间（从已加载数据的日期范围）
            dates = []
            for code, df in [(code, self._data_feeds[code].dataname) for code in self._data_feeds]:
                if "Date" in df.columns:
                    dates.extend(df["Date"].tolist())
            if dates:
                start_date = min(dates)
                end_date = max(dates)
            else:
                start_date = end_date = None

            # 沪深300基准收益率
            benchmark_return_pct = 0.0
            if start_date and end_date:
                bm_df = self._fetch_benchmark(start_date, end_date)
                if bm_df is not None and len(bm_df) >= 2:
                    first_close = bm_df.iloc[0]["Close"]
                    last_close = bm_df.iloc[-1]["Close"]
                    benchmark_return_pct = (last_close - first_close) / first_close * 100

            # 随机基准：多次模拟求均值
            random_avg_return_pct = self._run_random()

            # 市场环境判断
            if benchmark_return_pct > 15:
                market_regime = "bull"
            elif benchmark_return_pct < -15:
                market_regime = "bear"
            else:
                market_regime = "sideways"

            result["random_avg_return_pct"] = round(random_avg_return_pct, 2)
            result["benchmark_return_pct"] = round(benchmark_return_pct, 2)
            result["market_regime"] = market_regime

        return result

    def _run_random(self, simulations: int = 50) -> float:
        """
        随机策略基准：每次随机选一只股票，5%概率买入，持有5天后卖出。
        返回多次模拟的平均收益率。
        """
        if not self._data_feeds:
            return 0.0

        codes = list(self._data_feeds.keys())
        total_return = 0.0

        for _ in range(simulations):
            cerebro = bt.Cerebro()
            cerebro.broker.setcash(self.initial_cash)
            cerebro.broker.setcommission(self.commission)

            for code, datafeed in self._data_feeds.items():
                cerebro.adddata(datafeed)

            cerebro.addstrategy(RandomStrategy)
            cerebro.run(runonce=False)

            final_value = cerebro.broker.getvalue()
            ret = (final_value - self.initial_cash) / self.initial_cash * 100
            total_return += ret

        return total_return / simulations


# ── 随机基准策略 ──────────────────────────────────────────────

class RandomStrategy(Strategy):
    """
    随机买入策略（用于基准对比）：
    - 每次只持有 1 只股票
    - 每天有 5% 概率随机买入（若当前空仓）
    - 持有 5 天后强制卖出
    """
    params = dict(buy_prob=0.05, hold_days=5)

    def __init__(self):
        self.order = None
        self.hold_counter = 0
        self.trade_log = []

    def next(self):
        if self.order:
            return

        dt = self.datas[0].datetime.date(0)
        close = self.datas[0].close[0]

        # 计数持有
        if self.position.size > 0:
            self.hold_counter += 1
            if self.hold_counter >= self.p.hold_days:
                self.order = self.close()
                pnl = (close - self.position.price) / self.position.price * 100
                self.trade_log.append({
                    "date": str(dt),
                    "pnl_pct": round(pnl, 2),
                    "hold_days": self.hold_counter,
                })
                self.hold_counter = 0
                return

        # 5% 概率随机买入（仅在空仓时）
        if self.position.size == 0:
            import random
            if random.random() < self.p.buy_prob:
                self.order = self.buy()
                self.hold_counter = 0


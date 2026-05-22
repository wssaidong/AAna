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
from typing import List, Dict, Any, Optional, Type

import backtrader as bt
from backtrader import Strategy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.quotes import QuoteService
from strategies import (
    MomentumStrategy,
    TechnicalStrategy,
    CompositeStrategy,
    quick_score,
)

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


def _is_trading_day(dt: datetime) -> bool:
    """简单判断是否为 A 股交易日（周一~五，排除少量节假日）"""
    return dt.weekday() < 5


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
        计算当前 bar 的策略评分（调用 strategies/）。
        使用前 N 条 K 线计算技术指标。
        """
        # backtrader 的 self.datas[0] 是当前数据
        # 我们取 lookback 条历史 K 线（不含当前，以后者为准避免 lookahead）
        bar_count = len(self.datas[0])
        if bar_count < 20:
            return 0  # 数据太少不打分

        # 收集前 lookback 条 K 线数据（open/high/low/close/vol）
        lookback = min(self.p.lookback, bar_count - 1)
        klines = []
        for i in range(lookback, 0, -1):
            try:
                d = self.datas[0]
                date_i = bt.date2num(d.datetime[-i]) if hasattr(d, "datetime") else None
                klines.append(
                    dict(
                        date=date_i,
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

        # 用 strategies/ 的 quick_score 评分（内部会调用 QuoteService）
        # 但 backtrader 已经在循环中，我们需要直接调用策略
        code = self.datas[0]._name or ""

        try:
            result = quick_score(code, strategy=self.p.strategy_type)
            return result.get("composite", result.get("score", 0))
        except Exception:
            # 兜底：用简单动量
            closes = [k["close"] for k in klines]
            if len(closes) < 5:
                return 0
            gain = (closes[-1] - closes[-5]) / closes[-5] * 100 if closes[-5] else 0
            rsi = self._simple_rsi(closes)
            return min(100, max(0, 50 + gain + rsi * 0.3))

    def _simple_rsi(self, closes: List[float], period: int = 14) -> float:
        """简化 RSI 计算"""
        if len(closes) < period + 1:
            return 50
        gains = []
        losses = []
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
        if self.buy_price is not None:
            pnl_pct = (close - self.buy_price) / self.buy_price * 100
            if pnl_pct <= self.p.stop_loss_pct:
                self.order = self.close()
                self.log(f"止损卖出 {dt} 亏損 {pnl_pct:.1f}%")
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
    ):
        self.initial_cash = initial_cash
        self.commission = commission
        self.strategy_params = strategy_params or {}
        self._data_feeds: Dict[str, bt.feeds.PandasData] = {}
        self._results: Dict[str, Any] = {}

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
          'sina'    — 新浪实时（仅适合单次/近期）
          'tencent' — 腾讯 K 线（仅适合单次/近期）
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
        start: str | datetime | None,
        end: str | datetime | None,
        source: str,
    ):
        """调用对应数据源获取 DataFrame"""
        if source == "akshare":
            return self._fetch_akshare(code, start, end)
        elif source == "sina":
            return self._fetch_sina(code, end)
        elif source == "tencent":
            return self._fetch_tencent(code, end)
        return None

    def _fetch_akshare(
        self, code: str, start, end
    ):
        """使用 akshare 获取前复权日线"""
        try:
            import akshare as ak
            import pandas as pd

            symbol = code if code.startswith("6") else f"{code}.SZ"
            s = _parse_date(start) or datetime(2020, 1, 1)
            e = _parse_date(end) or datetime.today()

            df = ak.stock_zh_a_hist(
                symbol=("sh" + code if code.startswith("6") else "sz" + code),
                period="daily",
                start_date=s.strftime("%Y%m%d"),
                end_date=e.strftime("%Y%m%d"),
                adjust="qfq",  # 前复权
            )
            if df is None or df.empty:
                return None

            # 字段映射
            rename = {
                "日期": "Date",
                "开盘": "Open",
                "最高": "High",
                "最低": "Low",
                "收盘": "Close",
                "成交量": "Volume",
            }
            df = df.rename(columns=rename)
            # 过滤不需要的列
            for col in ["成交额", "涨跌幅", "涨跌额", "换手率"]:
                if col in df.columns:
                    df = df.drop(columns=[col])
            df["Date"] = pd.to_datetime(df["Date"])
            # 只保留标准列
            cols = [c for c in ["Date", "Open", "High", "Low", "Close", "Volume"] if c in df.columns]
            return df[cols]
        except Exception as e:
            return None

    def _fetch_sina(self, code: str, end):
        """使用新浪 K 线（近期，fallback）"""
        qs = QuoteService()
        kl = qs.kline(code, count=500, end=end)
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

    def _fetch_tencent(self, code: str, end):
        """使用腾讯 K 线（近期，fallback）"""
        qs = QuoteService()
        kl = qs.kline(code, count=500, end=end)
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

    # ── 运行 ─────────────────────────────────────────────────

    def run(self) -> Dict[str, Any]:
        """
        运行回测，返回结果字典：
        {
          initial_cash, final_value, total_return_pct,
          total_trades, win_trades, loss_trades,
          win_rate, avg_hold_days,
          trades: [{date, code, entry_price, exit_price, pnl_pct, hold_days}, ...]
        }
        """
        cerebro = bt.Cerebro()
        cerebro.broker.setcash(self.initial_cash)
        cerebro.broker.setcommission(self.commission)

        for code, datafeed in self._data_feeds.items():
            cerebro.adddata(datafeed)

        # 收集交易记录
        trades = []

        class TradeCollector(Strategy):
            def __init__(self):
                self.trades = []
                self.buy_price = None
                self.buy_date = None
                self.hold_days = 0

            def next(self):
                for d in self.datas:
                    pos = self.getposition(d)
                    if not pos.size and self.buy_price is not None:
                        # 已卖出，记录
                        exit_price = d.close[0]
                        pnl = (exit_price - self.buy_price) / self.buy_price * 100
                        self.trades.append(
                            dict(
                                date=self.buy_date,
                                code=d._name,
                                entry_price=self.buy_price,
                                exit_price=exit_price,
                                pnl_pct=round(pnl, 2),
                                hold_days=self.hold_days,
                            )
                        )
                        self.buy_price = None
                        self.buy_date = None
                        self.hold_days = 0

                    elif pos.size > 0:
                        self.hold_days += 1

        # 用 ScoreSignalStrategy 运行
        cerebro.addstrategy(
            ScoreSignalStrategy,
            **self.strategy_params,
        )

        results = cerebro.run()
        strat = results[0]

        final_value = cerebro.broker.getvalue()
        total_return_pct = (final_value - self.initial_cash) / self.initial_cash * 100

        return dict(
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

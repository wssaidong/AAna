"""
backtest/runner.py — 回测命令行入口
=====================================
从 recommendations.csv 读取历史推荐，按「推荐日次日开盘买入、持有 N 天后卖出」
模拟回测，输出收益率、胜率、夏普比率等统计。

使用方法：
  python -m backtest.runner

  # 或在代码中调用
  from backtest.runner import run, load_recommendations
  result = run(codes=["603906", "605566"], hold_days=5)
"""

import os
import sys
import json
import warnings
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import pandas as pd
import backtrader as bt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.quotes import QuoteService

warnings.filterwarnings("ignore")


# ── 内部工具 ──────────────────────────────────────────────────

def _parse_date(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                pass
    return None


def _is_trading_day(dt: datetime) -> bool:
    """A 股简单日历（排除周末，不处理节假日）"""
    return dt.weekday() < 5


def _next_trading_day(dt: datetime, calendar: List[datetime] = None) -> datetime:
    """返回 dt 之后的下一个交易日（不含 dt）"""
    if calendar:
        for d in calendar:
            if d > dt:
                return d
    d = dt + timedelta(days=1)
    while not _is_trading_day(d):
        d += timedelta(days=1)
    return d


# ── 推荐数据加载 ─────────────────────────────────────────────

def load_recommendations(
    csv_path: str = None,
    codes: List[str] = None,
    start_date: str = None,
    end_date: str = None,
) -> pd.DataFrame:
    """
    读取 recommendations.csv，可按股票代码、日期范围过滤。

    返回 DataFrame，字段：date, code, name, sector, reason,
                             expected_high, expected_low, actual_change, hit
    """
    if csv_path is None:
        csv_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "recommendations.csv",
        )

    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"推荐数据文件不存在: {csv_path}")

    df = pd.read_csv(csv_path, parse_dates=["date"])

    if codes:
        df = df[df["code"].astype(str).isin([str(c) for c in codes])]
    if start_date:
        df = df[df["date"] >= pd.to_datetime(start_date)]
    if end_date:
        df = df[df["date"] <= pd.to_datetime(end_date)]

    return df.reset_index(drop=True)


# ── 单只股票回测 ─────────────────────────────────────────────

def _fetch_history(code: str, start: datetime, end: datetime) -> Optional[pd.DataFrame]:
    """获取 A 股日线历史（前复权，akshare）"""
    try:
        import akshare as ak

        symbol = "sh" + code if code.startswith("6") else "sz" + code
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
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
        return df[cols].sort_values("Date").reset_index(drop=True)
    except Exception:
        return None


def _bt_run(
    df: pd.DataFrame,
    code: str,
    entry_dt: datetime,
    hold_days: int,
    initial_cash: float = 100_000,
    stop_loss_pct: float = -8,
) -> Optional[Dict[str, Any]]:
    """
    用 backtrader 对单只股票做一次回测：
    entry_dt 当日收盘价买入，持有 hold_days 个交易日 后卖出。
    返回交易结果 dict，失败返回 None。
    """
    if df is None or df.empty:
        return None

    df = df.sort_values("Date").reset_index(drop=True)
    date_set = set(df["Date"].dt.normalize())

    # 找 entry_dt 之后的第一个交易日
    entry_row = None
    for _, row in df.iterrows():
        if row["Date"].normalize() >= entry_dt.normalize():
            entry_row = row
            break

    if entry_row is None:
        return None

    entry_price = float(entry_row["Close"])
    entry_date = entry_row["Date"].normalize()

    # 收集持有期内的所有交易日后，选取第 hold_days 个
    trading_days_after = [d for d in sorted(date_set) if d > entry_date]
    if len(trading_days_after) < hold_days:
        return None
    exit_date = trading_days_after[hold_days - 1]

    exit_row = df[df["Date"].dt.normalize() == exit_date]
    if exit_row.empty:
        return None
    exit_price = float(exit_row.iloc[0]["Close"])

    pnl_pct = (exit_price - entry_price) / entry_price * 100
    stop_triggered = pnl_pct <= stop_loss_pct

    return dict(
        code=code,
        entry_date=entry_date.strftime("%Y-%m-%d"),
        exit_date=exit_date.strftime("%Y-%m-%d"),
        entry_price=round(entry_price, 2),
        exit_price=round(exit_price, 2),
        hold_days=hold_days,
        pnl_pct=round(pnl_pct, 2),
        stop_loss=stop_triggered,
    )


# ── 主回测函数 ─────────────────────────────────────────────

def run(
    codes: List[str] = None,
    start_date: str = None,
    end_date: str = None,
    hold_days: int = 5,
    initial_cash: float = 100_000,
    stop_loss_pct: float = -8,
    output_path: str = None,
) -> Dict[str, Any]:
    """
    主回测入口。

    参数：
      codes        : 只回测这些股票（None = 全部）
      start_date   : 最早推荐日期（None = 不限）
      end_date     : 最晚推荐日期（None = 不限）
      hold_days    : 持有多少个交易日（默认 5）
      initial_cash : 初始资金（默认 10 万，用于计算收益率）
      stop_loss_pct: 止损线，默认 -8%（但目前简化版暂未强制触发）
      output_path  : 可选，输出 JSON 结果到文件

    返回：
      {
        hold_days, initial_cash,
        total_trades, win_trades, loss_trades, pending_trades,
        win_rate, avg_return_pct, total_return_pct,
        sharpe_ratio（简化版）,
        best_trade, worst_trade,
        trades: [单笔记录列表]
      }
    """
    # 1. 读取推荐
    df_rec = load_recommendations(codes=codes, start_date=start_date, end_date=end_date)

    if df_rec.empty:
        result = {"error": "没有找到符合条件的推荐记录", "trades": []}
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        return result

    # 2. 按股票去重（同一股票同一日期只取第一条）
    df_rec = df_rec.drop_duplicates(subset=["date", "code"])

    trades = []
    errors = []

    for _, row in df_rec.iterrows():
        code = str(row["code"]).zfill(6)
        rec_date = row["date"]
        name = row.get("name", code)

        # 推荐日 + 2 天作为买入日期（次交易日开盘买入）
        entry_dt = _next_trading_day(rec_date + timedelta(days=1))

        # 数据截止：持有期 + 20 天缓冲
        data_end = entry_dt + timedelta(days=hold_days + 30)

        df_hist = _fetch_history(code, rec_date - timedelta(days=90), data_end)
        result = _bt_run(df_hist, code, entry_dt, hold_days, initial_cash, stop_loss_pct)

        if result:
            result["name"] = name
            result["reason"] = row.get("reason", "")
            trades.append(result)
        else:
            errors.append({"code": code, "name": name, "date": str(rec_date.date())})

    # 3. 统计
    if not trades:
        result = {"error": "所有股票都无法获取历史数据", "errors": errors[:10], "trades": []}
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        return result

    pnls = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    total_return_pct = sum(pnls)  # 简化：等权累计收益
    avg_return_pct = sum(pnls) / len(pnls) if pnls else 0

    # 简化夏普：无风险利率 2.5%，年化 252 交易日
    if len(pnls) >= 2:
        import statistics
        std_dev = statistics.stdev(pnls) if len(pnls) > 1 else 0
        if std_dev > 0:
            sharpe = (avg_return_pct / std_dev) * (252 ** 0.5 / (hold_days ** 0.5)) - 0.025
        else:
            sharpe = 0.0
    else:
        sharpe = 0.0

    result = {
        "hold_days": hold_days,
        "initial_cash": initial_cash,
        "start_date": str(df_rec["date"].min().date()) if len(df_rec) else None,
        "end_date": str(df_rec["date"].max().date()) if len(df_rec) else None,
        "total_trades": len(trades),
        "win_trades": len(wins),
        "loss_trades": len(losses),
        "pending_trades": len(errors),
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
        "avg_return_pct": round(avg_return_pct, 2),
        "total_return_pct": round(total_return_pct, 2),
        "sharpe_ratio": round(sharpe, 2),
        "best_trade": max(trades, key=lambda t: t["pnl_pct"]) if trades else None,
        "worst_trade": min(trades, key=lambda t: t["pnl_pct"]) if trades else None,
        "trades": trades,
        "errors": errors[:10],
    }

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    return result


# ── 打印报告 ─────────────────────────────────────────────

def print_report(r: Dict[str, Any]):
    """格式化打印回测报告"""
    print("\n" + "=" * 60)
    print("  AAna 回测报告")
    print("=" * 60)
    if "error" in r:
        print(f"  ❌ {r['error']}")
        return

    print(f"  持有周期   : {r['hold_days']} 个交易日")
    print(f"  回测区间   : {r['start_date']} ~ {r['end_date']}")
    print(f"  总交易次数 : {r['total_trades']} 笔")
    print(f"  胜率       : {r['win_rate']}%")
    print(f"  平均收益率 : {r['avg_return_pct']}%")
    print(f"  累计收益率 : {r['total_return_pct']}%（等权合计）")
    print(f"  夏普比率   : {r['sharpe_ratio']}")
    print(f"  盈利交易   : {r['win_trades']} 笔")
    print(f"  亏损交易   : {r['loss_trades']} 笔")
    print(f"  待确认     : {r['pending_trades']} 笔（数据缺失）")

    if r.get("best_trade"):
        bt_ = r["best_trade"]
        print(f"\n  🏆 最佳交易 : {bt_['code']} {bt_['name']}")
        print(f"     买入 {bt_['entry_date']} @{bt_['entry_price']} → "
              f"卖出 {bt_['exit_date']} @{bt_['exit_price']} "
              f"收益率 {bt_['pnl_pct']}%")

    if r.get("worst_trade"):
        wt = r["worst_trade"]
        print(f"\n  💔 最差交易 : {wt['code']} {wt['name']}")
        print(f"     买入 {wt['entry_date']} @{wt['entry_price']} → "
              f"卖出 {wt['exit_date']} @{wt['exit_price']} "
              f"收益率 {wt['pnl_pct']}%")

    print(f"\n  最近 10 笔交易：")
    for t in r["trades"][-10:]:
        emoji = "✅" if t["pnl_pct"] > 0 else "❌"
        print(f"    {emoji} {t['date']} {t['code']} {t['name']} "
              f"买入@{t['entry_price']} → {t['pnl_pct']}% "
              f"持有{t['hold_days']}天")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AAna 回测")
    parser.add_argument("--codes", nargs="+", help="只回测这些股票")
    parser.add_argument("--start", help="最早日期 YYYY-MM-DD")
    parser.add_argument("--end", help="最晚日期 YYYY-MM-DD")
    parser.add_argument("--hold", type=int, default=5, help="持有天数（默认5）")
    parser.add_argument("--cash", type=float, default=100_000, help="初始资金")
    parser.add_argument("--output", help="输出 JSON 路径")
    args = parser.parse_args()

    result = run(
        codes=args.codes,
        start_date=args.start,
        end_date=args.end,
        hold_days=args.hold,
        initial_cash=args.cash,
        output_path=args.output,
    )
    print_report(result)

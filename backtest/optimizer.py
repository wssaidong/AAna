"""
backtest/optimizer.py — 回测优化器
====================================
两个实用工具：

1. HoldDaysScanner  — 「最优持有天数」扫描
   对同一只股票 / 同一批股票，遍历 hold_days∈{5,10,15,20,30}，
   找出总收益率最高的持有天数，输出对比表。

2. StopLossComparator — 「止损条件」回测对比
   同一参数下，分别跑带止损（stop_loss_pct=-5）和不带止损（stop_loss_pct=0）
   两组回测，输出对比表（收益率、胜率、最大回撤）。

用法示例：
  from backtest.optimizer import HoldDaysScanner, StopLossComparator

  # 最优持有天数扫描
  scanner = HoldDaysScanner(codes=["603906", "605566"], start="20250101")
  result = scanner.scan()
  scanner.print_summary()

  # 止损对比
  comparator = StopLossComparator(codes=["603906"], start="20250101", hold_days=5)
  result = comparator.compare()
  comparator.print_summary()
"""

import os
import sys
from datetime import datetime
from typing import List, Dict, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.engine import BacktestEngine, ScoreSignalStrategy

# ── 通用辅助 ──────────────────────────────────────────────────────────────


def _max_drawdown(pnl_list: List[float]) -> float:
    """根据单笔 pnl 列表计算近似的最大回撤比例（负数）。"""
    if not pnl_list:
        return 0.0
    cumulative = []
    total = 0.0
    for p in pnl_list:
        total += p
        cumulative.append(total)
    peak = cumulative[0]
    max_dd = 0.0
    for c in cumulative:
        if c > peak:
            peak = c
        dd = peak - c
        if dd > max_dd:
            max_dd = dd
    return -round(max_dd, 2)


def _run_single(
    code: str,
    start,
    end,
    hold_days: int,
    stop_loss_pct: float,
    initial_cash: float = 100_000,
) -> Optional[Dict[str, Any]]:
    """用 BacktestEngine 跑单只股票，回测结束后返回结果 dict。"""
    try:
        engine = BacktestEngine(
            initial_cash=initial_cash,
            strategy_params=dict(
                hold_days=hold_days,
                stop_loss_pct=stop_loss_pct,
                score_threshold=60,
                strategy_type="composite",
                lookback=60,
            ),
        )
        engine.load_data(code, start=start, end=end, source="akshare")
        result = engine.run()
        result["code"] = code
        return result
    except Exception:
        return None


# ── 1. 最优持有天数扫描 ───────────────────────────────────────────────────


class HoldDaysScanner:
    """
    扫描 hold_days ∈ {5, 10, 15, 20, 30}，对每只股票找出收益率最高的持有天数。

    参数：
      codes        : 股票代码列表，如 ["603906"]
      start / end : 回测区间
      initial_cash : 初始资金（默认 100_000）
    """

    HOLD_DAYS_OPTIONS = [5, 10, 15, 20, 30]

    def __init__(
        self,
        codes: List[str],
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        initial_cash: float = 100_000,
    ):
        self.codes = codes
        self.start = start or "2020-01-01"
        self.end = end or datetime.today().strftime("%Y-%m-%d")
        self.initial_cash = initial_cash
        self._results: Dict[int, Dict[str, Any]] = {}

    def scan(self) -> Dict[int, Dict[str, Any]]:
        """
        对每个 hold_days 选项运行回测，返回结构：
        { hold_days: { "total_return_pct", "total_trades", "win_rate", "avg_hold_days", "max_drawdown", "per_stock_results" } }
        """
        for hd in self.HOLD_DAYS_OPTIONS:
            all_trades = []
            per_stock = []

            for code in self.codes:
                res = _run_single(
                    code, self.start, self.end,
                    hold_days=hd, stop_loss_pct=-5,
                    initial_cash=self.initial_cash,
                )
                if res:
                    all_trades.extend(res.get("trades", []))
                    per_stock.append({
                        "code": code,
                        "total_return_pct": res.get("total_return_pct", 0),
                        "total_trades": res.get("total_trades", 0),
                        "win_rate": res.get("win_rate", 0),
                    })

            pnls = [t["pnl_pct"] for t in all_trades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]
            hold_days_list = [t.get("hold_days", 0) for t in all_trades]

            self._results[hd] = {
                "total_return_pct": round(sum(pnls), 2) if pnls else 0.0,
                "total_trades": len(all_trades),
                "win_rate": round(len(wins) / len(all_trades) * 100, 1) if all_trades else 0.0,
                "avg_hold_days": round(sum(hold_days_list) / len(hold_days_list), 1) if hold_days_list else 0.0,
                "max_drawdown": _max_drawdown(pnls),
                "per_stock_results": per_stock,
            }

        return self._results

    def best_hold_days(self) -> int:
        """返回收益率最高的 hold_days。必须在 scan() 之后调用。"""
        if not self._results:
            raise RuntimeError("请先调用 scan()")
        return max(self._results, key=lambda k: self._results[k]["total_return_pct"])

    def print_summary(self) -> None:
        """打印 Markdown 格式的对比表。"""
        if not self._results:
            print("⚠️ 尚未调用 scan()")
            return

        header = "| hold_days | 总收益率(%) | 交易次数 | 胜率(%) | 平均持仓天 | 最大回撤(%) |"
        sep    = "|------------|------------|----------|---------|------------|------------|"
        print(f"\n### 📊 最优持有天数扫描结果（代码: {self.codes}，区间: {self.start}~{self.end}）\n")
        print(header)
        print(sep)

        for hd in self.HOLD_DAYS_OPTIONS:
            r = self._results.get(hd, {})
            print(
                f"| {hd:>9} | "
                f"{r.get('total_return_pct', 0):>10.2f}  | "
                f"{r.get('total_trades', 0):>8}  | "
                f"{r.get('win_rate', 0):>6.1f}  | "
                f"{r.get('avg_hold_days', 0):>10.1f}  | "
                f"{r.get('max_drawdown', 0):>10.2f}  |"
            )

        best = self.best_hold_days()
        print(f"\n✅ 最优持有天数：**{best} 天**（总收益率 {self._results[best]['total_return_pct']:.2f}%）")


# ── 2. 止损条件回测对比 ───────────────────────────────────────────────────


class StopLossComparator:
    """
    对比「带止损（-5%）」vs「不带止损（stop_loss_pct=0）」两种策略表现。

    参数：
      codes        : 股票代码列表
      start / end  : 回测区间
      hold_days    : 持有天数（默认 5）
      initial_cash : 初始资金（默认 100_000）
    """

    def __init__(
        self,
        codes: List[str],
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        hold_days: int = 5,
        initial_cash: float = 100_000,
    ):
        self.codes = codes
        self.start = start or "2020-01-01"
        self.end = end or datetime.today().strftime("%Y-%m-%d")
        self.hold_days = hold_days
        self.initial_cash = initial_cash
        self._result: Optional[Dict[str, Any]] = None

    def compare(self) -> Dict[str, Any]:
        """
        执行两组回测（带止损 vs 不带止损），返回结果 dict：
        {
          "with_stop_loss":  { total_return_pct, total_trades, win_rate, avg_hold_days, max_drawdown },
          "without_stop_loss": { ... },
          "codes": [...],
          "hold_days": int,
        }
        """
        scenarios = {
            "with_stop_loss": -5.0,
            "without_stop_loss": 0.0,
        }

        out = {}

        for label, stop_loss_pct in scenarios.items():
            all_trades = []
            per_stock = []

            for code in self.codes:
                res = _run_single(
                    code, self.start, self.end,
                    hold_days=self.hold_days,
                    stop_loss_pct=stop_loss_pct,
                    initial_cash=self.initial_cash,
                )
                if res:
                    all_trades.extend(res.get("trades", []))
                    per_stock.append({
                        "code": code,
                        "total_return_pct": res.get("total_return_pct", 0),
                        "total_trades": res.get("total_trades", 0),
                        "win_rate": res.get("win_rate", 0),
                    })

            pnls = [t["pnl_pct"] for t in all_trades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]
            hold_days_list = [t.get("hold_days", 0) for t in all_trades]

            out[label] = {
                "total_return_pct": round(sum(pnls), 2) if pnls else 0.0,
                "total_trades": len(all_trades),
                "win_rate": round(len(wins) / len(all_trades) * 100, 1) if all_trades else 0.0,
                "avg_hold_days": round(sum(hold_days_list) / len(hold_days_list), 1) if hold_days_list else 0.0,
                "max_drawdown": _max_drawdown(pnls),
                "per_stock_results": per_stock,
            }

        out["codes"] = self.codes
        out["hold_days"] = self.hold_days
        self._result = out
        return out

    def print_summary(self) -> None:
        """打印 Markdown 格式的对比表。"""
        if not self._result:
            print("⚠️ 尚未调用 compare()")
            return

        r_with = self._result.get("with_stop_loss", {})
        r_no = self._result.get("without_stop_loss", {})

        print(
            f"\n### 🔍 止损条件回测对比（代码: {self.codes}，"
            f"持仓: {self.hold_days}天，区间: {self.start}~{self.end}）\n"
        )
        print("| 指标         | 带止损(-5%)  | 不带止损     |")
        print("|--------------|-------------|-------------|")
        print(f"| 总收益率(%)  | {r_with.get('total_return_pct', 0):>11.2f}  | {r_no.get('total_return_pct', 0):>11.2f}  |")
        print(f"| 交易次数     | {r_with.get('total_trades', 0):>11}  | {r_no.get('total_trades', 0):>11}  |")
        print(f"| 胜率(%)      | {r_with.get('win_rate', 0):>11.1f}  | {r_no.get('win_rate', 0):>11.1f}  |")
        print(f"| 平均持仓天   | {r_with.get('avg_hold_days', 0):>11.1f}  | {r_no.get('avg_hold_days', 0):>11.1f}  |")
        print(f"| 最大回撤(%)  | {r_with.get('max_drawdown', 0):>11.2f}  | {r_no.get('max_drawdown', 0):>11.2f}  |")

        delta = r_with.get("total_return_pct", 0) - r_no.get("total_return_pct", 0)
        if delta > 0:
            print(f"\n✅ 带止损总收益率更高，领先 {delta:.2f} 个百分点")
        elif delta < 0:
            print(f"\n⚠️ 不带止损总收益率更高，差距 {abs(delta):.2f} 个百分点")
        else:
            print(f"\n➖ 两者总收益率相同")
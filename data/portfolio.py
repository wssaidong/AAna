"""
data/portfolio.py — AAna 实盘模拟层
=====================================
持仓追踪 + 盯市（Mark-to-Market）+ 对比回测

dataclass:
  Position     — 单只股票持仓
  Trade        — 交易记录
  PortfolioState — 每日组合快照

PortfolioTracker:
  buy(code, price, date, shares)       — 买入
  sell(code, price, date)               — 卖出（计算实现收益）
  mark_to_market(date, quotes)          — 每日盯市 quotes={code: price}
  save() / load()                       — 持久化到 data/portfolio.json
  compare_backtest(backtest_result)     — 与回测结果对比
  equity_curve()                        — 每日净值曲线
  summary()                             — 打印报告
"""

import json
import pathlib
from dataclasses import dataclass, asdict, field
from datetime import datetime, date
from typing import Optional, Dict, List, Any

PROJECT = pathlib.Path(__file__).parent.parent.resolve()
DATA = pathlib.Path(__file__).parent.resolve()


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class Position:
    code: str
    shares: int                      # 持股数量（正数）
    entry_price: float               # 持仓成本
    entry_date: str                  # 建仓日期 YYYY-MM-DD
    current_price: float = 0.0       # 最新行情价
    unrealized_pnl: float = 0.0      # 浮动盈亏金额
    unrealized_pnl_pct: float = 0.0  # 浮动盈亏百分比


@dataclass
class Trade:
    date: str                        # 交易日期 YYYY-MM-DD
    code: str
    action: str                      # "buy" | "sell"
    price: float
    shares: int
    pnl: float = 0.0                 # 实现收益（仅 sell 有值）
    pnl_pct: float = 0.0             # 实现收益率（仅 sell 有值）


@dataclass
class PortfolioState:
    date: str                        # 快照日期 YYYY-MM-DD
    cash: float                      # 可用资金
    positions: Dict[str, Position]   # code -> Position
    total_value: float              # 总资产 = cash + 持仓市值
    total_pnl: float                # 累计收益（含已实现）
    total_pnl_pct: float            # 累计收益率
    daily_pnl: float                # 当日盈亏


# ── PortfolioTracker ───────────────────────────────────────────────────────────

class PortfolioTracker:
    """
    实盘模拟组合管理器

    用法示例：
        pt = PortfolioTracker(initial_cash=100000)
        pt.buy("000001", price=10.0, date="2024-01-01", shares=1000)
        pt.mark_to_market("2024-01-02", quotes={"000001": 10.5})
        pt.sell("000001", price=10.5, date="2024-01-02")
        print(pt.summary())
    """

    def __init__(self, initial_cash: float = 0.0, portfolio_file: str = None):
        self.initial_cash = float(initial_cash)
        self.cash = float(initial_cash)
        self.positions: Dict[str, Position] = {}   # code -> Position
        self.trades: List[Trade] = []              # 历史交易记录
        self.states: List[PortfolioState] = []     # 每日快照
        self.realized_pnl: float = 0.0             # 累计已实现收益
        self._portfolio_file = portfolio_file or str(DATA / "portfolio.json")

    # ── 核心操作 ───────────────────────────────────────────────────────────────

    def buy(self, code: str, price: float, date: str, shares: int) -> None:
        """买入股票"""
        cost = price * shares
        if cost > self.cash:
            raise ValueError(f"资金不足：需要 {cost:.2f}，可用 {self.cash:.2f}")

        self.cash -= cost

        if code in self.positions:
            pos = self.positions[code]
            # 加权平均成本
            total_shares = pos.shares + shares
            pos.entry_price = (pos.entry_price * pos.shares + price * shares) / total_shares
            pos.shares = total_shares
            pos.entry_date = min(pos.entry_date, date)
        else:
            self.positions[code] = Position(
                code=code,
                shares=shares,
                entry_price=price,
                entry_date=date,
                current_price=price,
                unrealized_pnl=0.0,
                unrealized_pnl_pct=0.0,
            )

        self.trades.append(Trade(
            date=date, code=code, action="buy",
            price=price, shares=shares, pnl=0.0, pnl_pct=0.0
        ))

    def sell(self, code: str, price: float, date: str) -> Trade:
        """卖出股票，计算实现收益"""
        if code not in self.positions:
            raise ValueError(f"持仓中没有 {code}")

        pos = self.positions[code]
        if pos.shares <= 0:
            raise ValueError(f"{code} 持仓为 0，无法卖出")

        sell_value = price * pos.shares
        cost_basis = pos.entry_price * pos.shares
        pnl = sell_value - cost_basis
        pnl_pct = (price / pos.entry_price - 1) * 100

        self.cash += sell_value
        self.realized_pnl += pnl

        trade = Trade(
            date=date, code=code, action="sell",
            price=price, shares=pos.shares,
            pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 2)
        )
        self.trades.append(trade)

        del self.positions[code]
        return trade

    def mark_to_market(self, date: str, quotes: Dict[str, float]) -> PortfolioState:
        """
        每日盯市，更新持仓浮动盈亏，生成快照
        quotes = {code: price}
        """
        # 更新持仓价格
        for code, price in quotes.items():
            if code in self.positions:
                pos = self.positions[code]
                pos.current_price = price
                pos.unrealized_pnl = (price - pos.entry_price) * pos.shares
                pos.unrealized_pnl_pct = (price / pos.entry_price - 1) * 100

        # 计算当日盈亏（对比昨日收盘）
        prev_value = self.states[-1].total_value if self.states else self.initial_cash
        positions_value = sum(p.current_price * p.shares for p in self.positions.values())
        total_value = self.cash + positions_value
        daily_pnl = total_value - prev_value

        # 累计总收益（含已实现）
        total_pnl = self.realized_pnl + sum(p.unrealized_pnl for p in self.positions.values())
        total_pnl_pct = (total_pnl / self.initial_cash * 100) if self.initial_cash else 0.0

        state = PortfolioState(
            date=date,
            cash=round(self.cash, 2),
            positions={code: Position(**asdict(p)) for code, p in self.positions.items()},
            total_value=round(total_value, 2),
            total_pnl=round(total_pnl, 2),
            total_pnl_pct=round(total_pnl_pct, 2),
            daily_pnl=round(daily_pnl, 2),
        )
        self.states.append(state)
        return state

    # ── 持久化 ─────────────────────────────────────────────────────────────────

    def _serialize(self) -> dict:
        return {
            "initial_cash": self.initial_cash,
            "cash": self.cash,
            "realized_pnl": self.realized_pnl,
            "positions": {code: asdict(p) for code, p in self.positions.items()},
            "trades": [asdict(t) for t in self.trades],
            "states": [
                {
                    **asdict(s),
                    "positions": {code: asdict(p) for code, p in s.positions.items()},
                }
                for s in self.states
            ],
        }

    @classmethod
    def _deserialize(cls, d: dict, portfolio_file: str) -> "PortfolioTracker":
        pt = cls(initial_cash=d["initial_cash"], portfolio_file=portfolio_file)
        pt.cash = d["cash"]
        pt.realized_pnl = d.get("realized_pnl", 0.0)
        pt.positions = {code: Position(**p) for code, p in d.get("positions", {}).items()}
        pt.trades = [Trade(**t) for t in d.get("trades", [])]
        pt.states = [
            PortfolioState(
                **{k: v for k, v in asdict(s).items() if k != "positions"},
                positions={code: Position(**p) for code, p in s["positions"].items()},
            )
            for s in d.get("states", [])
        ]
        return pt

    def save(self, path: str = None) -> None:
        """保存到 JSON 文件"""
        path = path or self._portfolio_file
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._serialize(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str = None) -> "PortfolioTracker":
        """从 JSON 文件加载"""
        path = path or str(DATA / "portfolio.json")
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return cls._deserialize(d, portfolio_file=path)

    # ── 分析工具 ───────────────────────────────────────────────────────────────

    def equity_curve(self) -> List[Dict[str, Any]]:
        """
        返回每日净值曲线
        [{date, total_value, total_pnl, total_pnl_pct, daily_pnl, cash}, ...]
        """
        result = []
        base_value = self.initial_cash
        for s in self.states:
            result.append({
                "date": s.date,
                "total_value": s.total_value,
                "total_pnl": s.total_pnl,
                "total_pnl_pct": s.total_pnl_pct,
                "daily_pnl": s.daily_pnl,
                "cash": s.cash,
                "nav": round(s.total_value / base_value, 4) if base_value else 1.0,
            })
        return result

    def compare_backtest(self, backtest_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        与回测结果对比

        backtest_result 格式：
        {
            "total_return": float,       # 回测总收益率 %
            "total_trades": int,          # 回测交易次数
            "win_rate": float,            # 胜率 %
            "overlap_codes": List[str],   # 与实盘重叠的股票代码
            "daily_navs": List[Dict]      # 每日净值 [{date, nav}, ...]
        }

        返回：
        {
            "realized_return": float,     # 实盘已实现收益率 %
            "total_return": float,        # 实盘总收益率（含浮盈）%
            "backtest_return": float,     # 回测收益率
            "overlap_codes": List[str],   # 重叠股票
            "overlap_count": int,
            "excess_return": float,        # 跑赢/跑输回测 %
        }
        """
        # 计算实盘收益率（基于 realied_pnl，始终准确）
        realized_return = (self.realized_pnl / self.initial_cash * 100) if self.initial_cash else 0.0

        # 总收益率：优先用最新快照的 total_pnl_pct（含浮盈），否则用已实现收益
        if self.states:
            total_return = self.states[-1].total_pnl_pct
        else:
            total_return = realized_return

        backtest_return = backtest_result.get("total_return", 0.0)
        overlap_codes = backtest_result.get("overlap_codes", [])
        overlap_count = len(overlap_codes)

        return {
            "realized_return": round(realized_return, 2),
            "total_return": round(total_return, 2),
            "backtest_return": round(backtest_return, 2),
            "overlap_codes": overlap_codes,
            "overlap_count": overlap_count,
            "excess_return": round(total_return - backtest_return, 2),
        }

    def summary(self) -> str:
        """生成组合报告"""
        lines = ["=" * 50, "实盘组合报告", "=" * 50]
        lines.append(f"初始资金：{self.initial_cash:,.2f}")
        lines.append(f"当前现金：{self.cash:,.2f}")
        lines.append(f"累计已实现收益：{self.realized_pnl:,.2f}")

        if self.states:
            latest = self.states[-1]
            lines.append(f"总资产：{latest.total_value:,.2f}")
            lines.append(f"累计收益：{latest.total_pnl:,.2f} ({latest.total_pnl_pct:+.2f}%)")
            lines.append(f"持仓市值：{latest.total_value - self.cash:,.2f}")

        lines.append(f"\n持仓明细（共 {len(self.positions)} 只）：")
        if not self.positions:
            lines.append("  （空仓）")
        else:
            for code, pos in sorted(self.positions.items(), key=lambda x: x[1].unrealized_pnl, reverse=True):
                lines.append(
                    f"  {code}  数量:{pos.shares}  成本:{pos.entry_price:.2f}  "
                    f"现价:{pos.current_price:.2f}  浮盈:{pos.unrealized_pnl:+.2f} ({pos.unrealized_pnl_pct:+.2f}%)"
                )

        lines.append(f"\n交易记录（共 {len(self.trades)} 笔）：")
        for t in self.trades[-10:]:  # 显示最近10笔
            if t.action == "sell":
                lines.append(f"  {t.date}  {t.action.upper()}  {t.code}  {t.price} x {t.shares}  收益:{t.pnl:+.2f} ({t.pnl_pct:+.2f}%)")
            else:
                lines.append(f"  {t.date}  {t.action.upper()}  {t.code}  {t.price} x {t.shares}")

        if self.states:
            lines.append(f"\n最近盯市：{latest.date}")
            lines.append(f"  当日盈亏：{latest.daily_pnl:+.2f}")
            nav = round(latest.total_value / self.initial_cash, 4) if self.initial_cash else 1.0
            lines.append(f"  净值（NAV）：{nav:.4f}")

        lines.append("=" * 50)
        return "\n".join(lines)

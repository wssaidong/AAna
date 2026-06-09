"""
scripts/sell_strategy_v24.py — AAna v2.4 卖出策略（极简版：T+1 开盘即卖）
========================================================================

【v2.4 核心发现】（2026-06-09 完整 90 天回测 + V24 vs S1 对比验证）:

  90 天 / 1508 笔 / 29 只候选股 / v2.3 评分（已删 MACD 二次确认）:

  ┌──────────────────────────┬──────┬──────┬────────┬──────────┐
  │ 策略                     │ 胜率 │ 平均 │ 总收益 │ 盈亏比   │
  ├──────────────────────────┼──────┼──────┼────────┼──────────┤
  │ S0 5日持有（v2.2基线）  │ 29.9%│-1.84%│-2775%  │ 0.35     │
  │ V24 完整组合（含T+3止损）│ 66.2%│+0.45%│ +684%  │ 1.50     │
  │ S1 T+1开盘即卖（v2.4）  │80.2% │+1.17%│+1766%  │ 11.83 ⭐ │
  └──────────────────────────┴──────┴──────┴────────┴──────────┘

  V24 输给 S1 原因（504 笔 S1 更优，285 笔 V24 更优）:
    T+1 跳空 0~0.5% 笔（336 笔）:
      S1 卖在 T+1 开盘 +0.05% 平均
      V24 走到 T+3 钝化止损 → -1.41% 平均
      差异 -1.46%

  T+1 跳空 0.5~1% 笔（292 笔）:
      S1 卖在 T+1 开盘 +0.54% 平均
      V24 走到 T+3 钝化止损 → -0.93% 平均
      差异 -1.47%

  T+1 跳空 -2~0% 笔（162 笔）:
      S1 卖在 T+1 开盘 -0.73%
      V24 走到 T+3 钝化止损 → -1.72%
      差异 -1.00%

  **结论**: T+1 开盘即卖 = 90 天最优极简策略。S1 = V25（无观察/止损/截止版本）100% 等价。

【接口保留】（兼容早期 V24 设计）:
  - SellStrategyV24 / PositionState / SellDecision 三个类
  - make_sell_decision() 单行调用函数
  - on_day() / on_t1_open() 方法（保持 V24 API 兼容）

【实盘集成位置】:
  data/paper_trading.py → auto_sell_v24(date_str, quotes_ohlc)
  每日 15:30 收盘后调用，传入当日 K 线。

【硬止损保留】:
  T+1 跳空 < -5% 视为硬止损（90 天 0 笔，但代码保留作为风险底线）

【为什么不直接用 S1 = 卖在 T+1 开盘价?】
  1. T+1 开盘价仅在"开盘集合竞价"形成（09:30），可用
  2. 但 14:45 选股 → 次日 09:25 集合竞价下单 → 09:30 开盘成交
  3. 实盘可以接入券商 API（华泰/东财）自动开盘卖出
  4. paper trading 模式：每日 09:30 模拟开盘价卖
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime
import json
import os


# ── 配置常量（v2.4 极简版） ──
# 主策略: T+1 开盘即卖（90 天回测最稳胜率 80.2% / 盈亏比 11.83）
HARD_STOP_PCT = -5.0  # 极保守底线：T+1 开盘跌幅 >5% 视为硬止损


@dataclass
class SellDecision:
    """卖出决策"""
    action: str  # 'sell' | 'hold'
    reason: str
    price: float
    pnl_pct: float
    days_held: int
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            'action': self.action,
            'reason': self.reason,
            'price': round(self.price, 3),
            'pnl_pct': round(self.pnl_pct, 3),
            'days_held': self.days_held,
            'notes': self.notes,
        }


@dataclass
class PositionState:
    """持仓状态"""
    code: str
    name: str
    entry_date: str
    entry_price: float
    shares: int
    cost_rate: float = 0.002  # 双边 0.2%
    highest_price: float = 0.0
    t1_open_price: Optional[float] = None
    t1_open_gap_pct: float = 0.0

    def __post_init__(self):
        if self.highest_price == 0.0:
            self.highest_price = self.entry_price

    def days_held(self, today: str) -> int:
        d1 = datetime.strptime(self.entry_date, '%Y-%m-%d')
        d2 = datetime.strptime(today, '%Y-%m-%d')
        return (d2 - d1).days

    def pnl_pct_now(self, price: float) -> float:
        """扣成本后的收益率"""
        gross_ret = (price / self.entry_price - 1) * 100
        return gross_ret - self.cost_rate * 100


class SellStrategyV24:
    """
    v2.4 卖出策略（极简版：T+1 开盘即卖）

    决策规则（90 天回测 1508 笔验证）:
      1. T+1 开盘价相对成本价 < -5% → 硬止损（90 天 0 笔触发，保留作为风险底线）
      2. 其他情况 → 全部 T+1 开盘即卖

    历史兼容（保留 V24 早期设计接口，行为已统一为 T+1 开盘即卖）:
      - on_t1_open(): 旧版 API
      - on_day(): 旧版 API（统一行为：T+1 卖在开盘价）
    """

    def __init__(self, position: PositionState):
        self.position = position
        self._t1_recorded = False
        self._decision_log: List[SellDecision] = []

    def on_t1_open(self, t1_open_price: float) -> SellDecision:
        """
        T+1 开盘时调用（仅一次）
        v2.4 极简版: 全部 T+1 开盘即卖
        """
        pos = self.position
        self._t1_recorded = True
        pos.t1_open_price = t1_open_price
        gap_pct = (t1_open_price / pos.entry_price - 1) * 100
        pos.t1_open_gap_pct = gap_pct
        pnl = pos.pnl_pct_now(t1_open_price)

        if gap_pct <= HARD_STOP_PCT:
            decision = SellDecision(
                action='sell', reason='T1_hard_stop',
                price=t1_open_price, pnl_pct=pnl, days_held=1,
                notes=f'硬止损：T+1 跳空 {gap_pct:.2f}% ≤ {HARD_STOP_PCT}%（90 天 0 笔触发）'
            )
        else:
            decision = SellDecision(
                action='sell', reason='T1_open_sell',
                price=t1_open_price, pnl_pct=pnl, days_held=1,
                notes=f'T+1 开盘即卖（v2.4 主策略，跳空 {gap_pct:+.2f}%）'
            )
        self._decision_log.append(decision)
        return decision

    def on_day(self, today: str, open_price: float, high_price: float,
               low_price: float, close_price: float) -> SellDecision:
        """
        每日决策调用（T+1 ~ T+5）
        v2.4 极简版: 任何时候调用都返回 T+1 开盘即卖决策（如果 T+1 已过则返回 hold）
        """
        pos = self.position
        days = pos.days_held(today)

        # T+1: 触发 T+1 开盘即卖决策
        if days == 1 and not self._t1_recorded:
            return self.on_t1_open(open_price)

        # T+1 已过: 返回历史决策（不重复决策）
        if self._t1_recorded and self._decision_log:
            last = self._decision_log[-1]
            if last.action == 'sell':
                return SellDecision(
                    action='hold', reason='already_sold_at_t1',
                    price=last.price, pnl_pct=last.pnl_pct,
                    days_held=days,
                    notes=f'已在 T+1 卖 @{last.price:.2f}，不重复决策'
                )

        # T+2+: 不再决策（已过 T+1，应已卖）
        pnl = pos.pnl_pct_now(close_price)
        decision = SellDecision(
            action='hold', reason='past_t1',
            price=close_price, pnl_pct=pnl, days_held=days,
            notes=f'T+{days} 已过 T+1 决策窗口（实盘应已在 T+1 卖）'
        )
        self._decision_log.append(decision)
        return decision

    @property
    def decision_log(self) -> List[Dict]:
        return [d.to_dict() for d in self._decision_log]


# ── 集成 helper：供 paper_trading.py 调用 ──
def make_sell_decision(code: str, name: str, entry_date: str,
                        entry_price: float, shares: int,
                        today: str, open_price: float, high_price: float,
                        low_price: float, close_price: float,
                        cost_rate: float = 0.002) -> SellDecision:
    """
    单行调用：传入当前行情，返回卖出决策

    v2.4 极简版：T+1 开盘即卖（90 天回测最稳）
    实盘: 每日 09:30 集合竞价后取开盘价调用此函数，决策通常为 sell

    用法:
        # 每日 09:30 (T+1) 集合竞价后
        ohlc = fetch_ohlc(code)  # {'open': 24.10, ...}
        decision = make_sell_decision(
            '000951', '中国重汽', '2026-06-09', 23.45, 100,
            '2026-06-10', ohlc['open'], ohlc['high'], ohlc['low'], ohlc['close']
        )
        if decision.action == 'sell':
            execute_sell(code, decision.price, today)
    """
    pos = PositionState(
        code=code, name=name, entry_date=entry_date,
        entry_price=entry_price, shares=shares, cost_rate=cost_rate
    )
    strategy = SellStrategyV24(pos)
    return strategy.on_day(today, open_price, high_price, low_price, close_price)


# ── CLI: 单只股票回放验证 ──
if __name__ == '__main__':
    print("=" * 60)
    print("v2.4 卖出策略 (极简版: T+1 开盘即卖) - 验证")
    print("=" * 60)

    # 场景 1: T+1 跳空高开 +2.77%
    pos = PositionState(
        code='000951', name='中国重汽',
        entry_date='2026-06-09', entry_price=23.45, shares=100
    )
    strategy = SellStrategyV24(pos)
    d = strategy.on_day('2026-06-10', 24.10, 24.30, 24.00, 24.05)
    print(f"\n[T+1 高开 +2.77%]")
    print(f"  → {d.to_dict()}")

    # 场景 2: T+1 跳空低开 -0.5% (90 天此类 162 笔，S1 卖 -0.73%)
    pos2 = PositionState(
        code='002472', name='双环传动',
        entry_date='2026-06-09', entry_price=30.00, shares=100
    )
    s2 = SellStrategyV24(pos2)
    d2 = s2.on_day('2026-06-10', 29.85, 30.10, 29.70, 29.95)
    print(f"\n[T+1 低开 -0.5%]")
    print(f"  → {d2.to_dict()}")

    # 场景 3: 硬止损 (-6% 跳空)
    pos3 = PositionState(
        code='603662', name='柯力传感',
        entry_date='2026-06-09', entry_price=40.00, shares=100
    )
    s3 = SellStrategyV24(pos3)
    d3 = s3.on_day('2026-06-10', 37.60, 37.80, 37.50, 37.65)
    print(f"\n[T+1 跳空 -6% 硬止损]")
    print(f"  → {d3.to_dict()}")

    # 场景 4: 同一只股, T+2 再次调用 (应返回 hold)
    d4 = s2.on_day('2026-06-11', 29.95, 30.20, 29.80, 30.10)
    print(f"\n[同一只股 T+2 再次调用]")
    print(f"  → {d4.to_dict()}")

"""
data/paper_trading.py — AAna 模拟交易模块
===========================================
每日记录"理论买入/卖出"，追踪模拟持仓收益，与推荐复盘联动

数据文件: data/paper_trades.json
结构:
{
  "init_cash": 100000,
  "trades": [
    {"date", "code", "name", "action": "buy"|"sell",
     "price", "shares", "reason", "pnl", "pnl_pct"}
  ],
  "positions": {
    "code": {"date", "name", "shares", "entry_price",
             "highest_price", "entry_date"}
  },
  "daily_snapshots": [
    {"date", "cash", "position_value", "total_value",
     "daily_pnl", "total_pnl_pct", "positions"}
  ]
}
"""

import json, pathlib, os
from datetime import datetime, date
from typing import Optional

PROJECT = pathlib.Path(__file__).parent.parent.resolve()
TRADE_FILE = PROJECT / "data" / "paper_trades.json"
os.makedirs(PROJECT / "data", exist_ok=True)


def _load() -> dict:
    if not TRADE_FILE.exists():
        return {"init_cash": 100000.0, "trades": [], "positions": {}, "daily_snapshots": []}
    with open(TRADE_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save(d: dict) -> None:
    with open(TRADE_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def record_buy(code: str, name: str, price: float, shares: int,
               date_str: str, reason: str = "") -> dict:
    """
    记录理论买入（不校验资金，只记录）
    返回买入记录
    """
    d = _load()
    if code in d["positions"]:
        # 已有持仓，增持
        pos = d["positions"][code]
        total_shares = pos["shares"] + shares
        pos["entry_price"] = (pos["entry_price"] * pos["shares"] + price * shares) / total_shares
        pos["shares"] = total_shares
        pos["highest_price"] = max(pos.get("highest_price", price), price)
    else:
        d["positions"][code] = {
            "date": date_str,
            "name": name,
            "shares": shares,
            "entry_price": price,
            "highest_price": price,
            "entry_date": date_str,
        }
    trade = {
        "date": date_str, "code": code, "name": name,
        "action": "buy", "price": round(price, 2),
        "shares": shares, "reason": reason, "pnl": 0.0, "pnl_pct": 0.0,
    }
    d["trades"].append(trade)
    _save(d)
    return trade


def record_sell(code: str, price: float, date_str: str) -> dict:
    """
    记录理论卖出（计算收益，从持仓中移除）
    返回卖出记录（含 pnl）
    """
    d = _load()
    if code not in d["positions"]:
        return {}
    pos = d["positions"].pop(code)
    pnl = (price - pos["entry_price"]) * pos["shares"]
    pnl_pct = (price / pos["entry_price"] - 1) * 100
    trade = {
        "date": date_str, "code": code, "name": pos["name"],
        "action": "sell", "price": round(price, 2),
        "shares": pos["shares"], "reason": "止损/止盈/到期",
        "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
    }
    d["trades"].append(trade)
    _save(d)
    return trade


def mark_to_market(date_str: str, quotes: dict) -> dict:
    """
    每日盯市：更新持仓浮动盈亏，生成快照
    quotes = {code: price}
    """
    d = _load()
    cash = d.get("init_cash", 100000) - sum(
        t["price"] * t["shares"] for t in d["trades"]
        if t["action"] == "buy"
    ) + sum(
        t["price"] * t["shares"] for t in d["trades"]
        if t["action"] == "sell"
    )

    total_value = cash
    positions_snapshot = []
    for code, pos in list(d["positions"].items()):
        current_price = quotes.get(code, pos["highest_price"])
        # 更新最高价
        if current_price > pos.get("highest_price", 0):
            d["positions"][code]["highest_price"] = current_price
        pos_val = current_price * pos["shares"]
        unreal_pnl = (current_price - pos["entry_price"]) * pos["shares"]
        unreal_pct = (current_price / pos["entry_price"] - 1) * 100
        total_value += pos_val
        positions_snapshot.append({
            "code": code, "name": pos["name"],
            "shares": pos["shares"], "entry_price": pos["entry_price"],
            "current_price": current_price,
            "highest_price": d["positions"][code]["highest_price"],
            "unreal_pnl": round(unreal_pnl, 2), "unreal_pct": round(unreal_pct, 2),
            "days_held": (datetime.strptime(date_str, "%Y-%m-%d") -
                          datetime.strptime(pos["entry_date"], "%Y-%m-%d")).days,
        })

    # 累计已实现
    realized_pnl = sum(t["pnl"] for t in d["trades"] if t["action"] == "sell")
    unrealized_pnl = sum(
        (quotes.get(code, pos["entry_price"]) - pos["entry_price"]) * pos["shares"]
        for code, pos in d["positions"].items()
    )
    total_pnl = realized_pnl + unrealized_pnl
    total_pnl_pct = total_pnl / d.get("init_cash", 100000) * 100

    prev_total = d["daily_snapshots"][-1]["total_value"] if d["daily_snapshots"] else d.get("init_cash", 100000)
    daily_pnl = total_value - prev_total

    snapshot = {
        "date": date_str, "cash": round(cash, 2),
        "position_value": round(total_value - cash, 2),
        "total_value": round(total_value, 2),
        "daily_pnl": round(daily_pnl, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "realized_pnl": round(realized_pnl, 2),
        "positions": positions_snapshot,
    }
    d["daily_snapshots"].append(snapshot)
    _save(d)
    return snapshot


def auto_stop_loss(date_str: str, quotes: dict,
                   soft_pct: float = -0.03,
                   hard_pct: float = -0.05) -> list:
    """
    自动止损扫描：触发止损则记录卖出
    返回触发止损的股票列表
    """
    d = _load()
    triggered = []
    for code in list(d["positions"].keys()):
        price = quotes.get(code)
        if not price:
            continue
        pos = d["positions"][code]
        entry = pos["entry_price"]
        loss_pct = (price - entry) / entry
        if loss_pct <= hard_pct:
            trade = record_sell(code, price, date_str)
            trade["stop_reason"] = f"硬止损{loss_pct*100:.1f}%"
            triggered.append(trade)
        elif loss_pct <= soft_pct:
            trade = record_sell(code, price, date_str)
            trade["stop_reason"] = f"软止损{loss_pct*100:.1f}%"
            triggered.append(trade)
    return triggered


def auto_take_profit_trail(date_str: str, quotes: dict,
                           trail_pct: float = 0.06) -> list:
    """
    移动止盈扫描：从最高点回落 trail_pct 触发
    """
    d = _load()
    triggered = []
    for code in list(d["positions"].keys()):
        price = quotes.get(code)
        if not price:
            continue
        pos = d["positions"][code]
        highest = pos.get("highest_price", price)
        if price < highest and (highest - price) / highest >= trail_pct:
            pnl_pct = (price - pos["entry_price"]) / pos["entry_price"] * 100
            trade = record_sell(code, price, date_str)
            trade["stop_reason"] = f"移动止盈({trail_pct*100:.0f}%)盈利{pnl_pct:.1f}%"
            triggered.append(trade)
    return triggered


def summary() -> str:
    """生成模拟交易报告"""
    d = _load()
    lines = ["=" * 50, "模拟交易报告", "=" * 50]
    lines.append(f"初始资金：{d.get('init_cash', 100000):,.2f}")
    total_trades = len(d["trades"])
    buy_cnt = sum(1 for t in d["trades"] if t["action"] == "buy")
    sell_cnt = sum(1 for t in d["trades"] if t["action"] == "sell")
    lines.append(f"总交易笔数：{total_trades}（买入{buy_cnt} 卖出{sell_cnt}）")
    realized = sum(t["pnl"] for t in d["trades"] if t["action"] == "sell")
    lines.append(f"已实现收益：{realized:,.2f}")
    if d["daily_snapshots"]:
        latest = d["daily_snapshots"][-1]
        lines.append(f"当前总资产：{latest['total_value']:,.2f}")
        lines.append(f"累计收益率：{latest['total_pnl_pct']:+.2f}%")
    lines.append(f"当前持仓：{len(d['positions'])} 只")
    for code, pos in d["positions"].items():
        if d["daily_snapshots"]:
            snap = d["daily_snapshots"][-1]
            ps = next((p for p in snap["positions"] if p["code"] == code), None)
            if ps:
                lines.append(
                    f"  {code} {pos['name']} "
                    f"数量:{pos['shares']} 成本:{pos['entry_price']:.2f} "
                    f"现价:{ps['current_price']:.2f} "
                    f"浮盈:{ps['unreal_pnl']:+.2f}({ps['unreal_pct']:+.2f}%)"
                )
    lines.append("=" * 50)
    return "\n".join(lines)


# ── 联动推荐复盘：自动建仓/清仓 ────────────────────────────────

def sync_from_recommendations(date_str: str = None) -> dict:
    """
    从 data/recommendations.csv 读取今日推荐，
    对每只推荐股票自动模拟建仓（尾盘收盘价买入）
    用于每日收盘后自动运行
    """
    from data import get_recommendations_by_date
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    recs = get_recommendations_by_date(date_str)
    bought = []
    for rec in recs:
        code = rec.get("code", "").zfill(6)
        if code in (d["positions"] for d in [_load()]):
            continue  # 已有持仓
        price = float(rec.get("price") or 0)
        if price <= 0:
            continue
        try:
            record_buy(code, rec.get("name", ""), price,
                      100, date_str, rec.get("reason", ""))
            bought.append(code)
        except Exception as e:
            print(f"[Paper] 建仓失败 {code}: {e}")
    return {"date": date_str, "bought": bought, "total_recommendations": len(recs)}


if __name__ == '__main__':
    print(summary())

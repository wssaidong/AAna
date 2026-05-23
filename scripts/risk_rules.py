#!/usr/bin/env python3
"""
AAna v2.5 风控规则硬化模块
所有硬规则集中在此，便于维护和回溯：
  - 仓位规则（根据情绪档位决定总仓位）
  - 止损规则（固定止损 + 移动止盈）
  - 过滤规则（排除高风险标的）
  - 评分加权（资金流向因子加入综合评分）
"""

from datetime import datetime
from typing import Optional
import csv, pathlib

# ── 硬规则常量 ──────────────────────────────────────────────────

# 仓位（按情绪分档）
POSITION_RULES = {
    "空仓观望": 0,     # 冰点/极端
    "极低仓": 0.10,   # score < 35
    "轻仓": 0.20,     # 35 <= score < 45
    "半仓": 0.50,     # 45 <= score < 60
    "正常仓": 0.70,   # 60 <= score < 75
    "高仓": 0.85,     # score >= 75
}

# 单股最大仓位（总资金的%）
MAX_SINGLE_POSITION_PCT = 0.20   # 不超过20%

# 大盘情绪联动仓位（冰点/分歧/亢奋）
SENTIMENT_POSITION_RULES = {
    "冰点": 1.00,    # 情绪极低，满仓进场
    "分歧": 0.60,    # 情绪分化，半仓以下
    "亢奋": 0.30,    # 情绪高涨，轻仓试单
    "回暖": 0.70,    # 正常回暖，正常仓
    "空仓": 0.00,    # 建议空仓
}

# 止损规则
STOP_LOSS_PCT = 0.03            # 买入后 -3% 强制止损
STOP_LOSS_HARD_PCT = 0.05      # -5% 必须清仓（不允许幻想）
TAKE_PROFIT_TRAIL_PCT = 0.06   # 从最高点回落 6% 止盈

# 过滤规则
PRICE_MIN = 20.0
PRICE_MAX = 80.0
TURNOVER_MIN = 1e7             # 成交额下限 1000万
TURNOVER_RATE_MAX = 30.0       # 换手率上限 30%（筹码太散）
FLOAT_MARKET_CAP_MIN = 30e8   # 流通市值下限 30亿

# 科创板/创业板过滤（用户要求）
BOARD_EXCLUDE = ('688', '8', '300', '301')

# 评分权重（调整后）
WEIGHT_TECH = 0.50
WEIGHT_FUND = 0.20
WEIGHT_MONEYFLOW = 0.30       # 资金流向占30%


# ── 工具函数 ───────────────────────────────────────────────────

def get_position_ratio(sentiment_score: int) -> float:
    """根据情绪分返回建议仓位比例"""
    if sentiment_score >= 75:
        return POSITION_RULES["高仓"]
    elif sentiment_score >= 60:
        return POSITION_RULES["正常仓"]
    elif sentiment_score >= 45:
        return POSITION_RULES["半仓"]
    elif sentiment_score >= 35:
        return POSITION_RULES["轻仓"]
    elif sentiment_score >= 20:
        return POSITION_RULES["极低仓"]
    else:
        return POSITION_RULES["空仓观望"]


def get_sentiment_position_ratio(sentiment_label: str) -> float:
    """
    根据大盘情绪标签返回仓位比例（冰点100%/分歧60%/亢奋30%）
    向后兼容：若标签不在字典中，使用默认值 0.50
    """
    return SENTIMENT_POSITION_RULES.get(sentiment_label, 0.50)


def check_concentration_risk(positions: dict, total_capital: float) -> list:
    """
    检查持仓集中度风险
    positions: {code: {'shares': int, 'current_price': float}}
    total_capital: 总资金
    返回触发集中的股票列表 [{'code': str, 'ratio': float, 'reason': str}]
    """
    triggered = []
    for code, pos in positions.items():
        value = pos['current_price'] * pos['shares']
        ratio = value / total_capital
        if ratio > MAX_SINGLE_POSITION_PCT:
            triggered.append({
                'code': code,
                'ratio': round(ratio * 100, 2),
                'reason': f"持仓集中度{ratio*100:.1f}%>20%"
            })
    return triggered


_STOP_LOSS_LOG = pathlib.Path(__file__).parent.parent / "data" / "stop_loss_log.csv"
_STOP_LOSS_LOG_FIELDS = ["datetime", "code", "entry_price", "exit_price", "loss_pct", "action", "reason"]


def log_stop_loss(code: str, entry_price: float, exit_price: float,
                  loss_pct: float, action: str, reason: str) -> None:
    """
    追加止损日志到 data/stop_loss_log.csv
    """
    _STOP_LOSS_LOG.parent.mkdir(parents=True, exist_ok=True)
    file_exists = _STOP_LOSS_LOG.exists()
    with open(_STOP_LOSS_LOG, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_STOP_LOSS_LOG_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "code": code,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "loss_pct": round(loss_pct * 100, 2),
            "action": action,
            "reason": reason,
        })


def filter_stock_basic(code: str, name: str, price: float,
                       amount: float, turnover_rate: float = None,
                       float_market_cap: float = None) -> tuple:
    """
    基础过滤，返回 (通过: bool, 原因: str)
    """
    # 股票板过滤
    for prefix in BOARD_EXCLUDE:
        if code.startswith(prefix):
            return False, f"排除{prefix}板块（高波动）"

    # 价格过滤
    if price < PRICE_MIN:
        return False, f"股价{price}<{PRICE_MIN}元"
    if price > PRICE_MAX:
        return False, f"股价{price}>{PRICE_MAX}元"

    # 成交额过滤
    if amount < TURNOVER_MIN:
        return False, f"成交额不足{amount/1e6:.0f}万"

    # 换手率过滤
    if turnover_rate is not None and turnover_rate > TURNOVER_RATE_MAX:
        return False, f"换手率{turnover_rate:.1f}%过高"

    # 流通市值过滤
    if float_market_cap is not None and float_market_cap < FLOAT_MARKET_CAP_MIN:
        return False, f"流通市值{float_market_cap/1e8:.0f}亿<30亿"

    return True, "通过"


def calc_stop_loss(entry_price: float) -> dict:
    """计算止损价位"""
    return {
        "entry_price": entry_price,
        "stop_soft": round(entry_price * (1 - STOP_LOSS_PCT), 2),   # -3% 软止损
        "stop_hard": round(entry_price * (1 - STOP_LOSS_HARD_PCT), 2),  # -5% 硬止损
        "take_profit": round(entry_price * (1 + STOP_LOSS_PCT * 2), 2),   # +6% 初步目标
    }


def calc_take_profit_trail(entry_price: float, highest_price: float) -> float:
    """
    移动止盈：从最高点回落 TAKE_PROFIT_TRAIL_PCT 触发
    """
    if highest_price <= entry_price:
        return round(entry_price * 1.03, 2)  # 保本微利
    return round(highest_price * (1 - TAKE_PROFIT_TRAIL_PCT), 2)


def apply_moneyflow_score(base_score: int, net_in_wan: float,
                           change_pct: float) -> int:
    """
    根据资金流向调整评分
    net_in_wan: 超大单净流入（万元），正=流入，负=流出
    核心逻辑：
      - 超大单净流入 + 涨幅合理(<5%) → 主力在建仓，还没走 → 加分
      - 超大单净流入 + 涨幅过大(>7%) → 可能是拉高出货 → 减分
      - 超大单净流出 + 股价却涨 → 主力诱多 → 大幅减分
    """
    score = base_score
    abs_net = abs(net_in_wan)

    # 大额净流入（>5000万）
    if net_in_wan > 5000:
        if change_pct < 5:
            score += 20  # 吸筹，尚未拉升
        elif change_pct < 8:
            score += 10  # 边拉边吸
        else:
            score -= 10  # 拉高出货嫌疑
    elif net_in_wan > 1000:
        if change_pct < 5:
            score += 10
        elif change_pct < 8:
            score += 3
        else:
            score -= 5
    # 大额净流出
    elif net_in_wan < -5000:
        if change_pct > 0:
            score -= 25  # 主力在跑，诱多
        else:
            score -= 15  # 砸盘
    elif net_in_wan < -1000:
        if change_pct > 0:
            score -= 10
        else:
            score -= 5

    return max(0, min(100, score))


def apply_sentiment_adjustment(score: int, sentiment_score: int) -> int:
    """
    根据大盘情绪调整个股评分
    冰点时降低评分（避免逆势）；亢奋时提升（顺势而为）
    """
    if sentiment_score >= 75:  # 亢奋
        return min(100, score + 5)
    elif sentiment_score <= 30:  # 冰点
        return max(0, score - 10)
    return score


def composite_score(tech_score: int, fund_score: int,
                     net_in_wan: float, change_pct: float,
                     sentiment_score: int) -> dict:
    """
    综合评分 = 技术(50%) + 基本面(20%) + 资金流(30%)
    加入情绪修正
    """
    # 资金流评分转换（0-100）
    money_score = 50 + (net_in_wan / 10000) * 0.5  # 简单线性映射
    money_score = max(0, min(100, money_score))

    composite = (
        tech_score * WEIGHT_TECH +
        fund_score * WEIGHT_FUND +
        money_score * WEIGHT_MONEYFLOW
    )

    # 情绪修正
    composite = apply_sentiment_adjustment(composite, sentiment_score)
    composite = int(max(0, min(100, composite)))

    return {
        "composite": composite,
        "tech_score": tech_score,
        "fund_score": fund_score,
        "money_score": int(money_score),
        "sentiment_adjustment": True,
        "weights": f"技术{WEIGHT_TECH:.0%}/基本面{WEIGHT_FUND:.0%}/资金流{WEIGHT_MONEYFLOW:.0%}",
    }


# ── 模拟交易信号生成 ───────────────────────────────────────────

class RiskManager:
    """
    风控管理器：生成交易信号（买/持有/卖）
    用于模拟交易和实盘辅助决策
    """

    def __init__(self, sentiment: dict = None):
        self.sentiment = sentiment or {}
        self.sentiment_score = self.sentiment.get('score', 50)
        self.position_ratio = get_position_ratio(self.sentiment_score)
        self.avoid_trading = self.sentiment.get('avoid_trading', False)

    def should_buy(self, code: str, info: dict) -> tuple:
        """
        判断是否应买入
        返回 (should: bool, reason: str, signal: str)
        """
        if self.avoid_trading:
            return False, "大盘冰点/极端，建议空仓", "空仓信号"

        if self.position_ratio == 0:
            return False, f"情绪{sentiment_score}分，建议{get_position_ratio(self.sentiment_score)*100:.0f}仓", "降仓信号"

        price = info.get('price', 0)
        change_pct = info.get('change_pct', 0)
        amount = info.get('amount', 0)
        passed, reason = filter_stock_basic(
            code, info.get('name', ''), price, amount
        )
        if not passed:
            return False, reason, "过滤"

        # 尾盘：涨幅 -3%~2% 是最佳买点区间（不追高）
        if not (-3 <= change_pct <= 2):
            return False, f"涨幅{change_pct:+.2f}%不在最佳区间(-3%~2%)", "观望"

        return True, "符合买入条件", "买入信号"

    def get_position_size(self, total_capital: float, price: float) -> int:
        """
        计算买入股数（100股整数倍）
        按单股最大仓位限制
        """
        max_amount = total_capital * min(MAX_SINGLE_POSITION_PCT, self.position_ratio)
        shares = int(max_amount / price / 100) * 100
        return max(100, shares)

    def should_stop_loss(self, entry_price: float, current_price: float,
                         highest_since_entry: float) -> tuple:
        """
        判断是否触发止损/止盈
        返回 (action: str, reason: str, price: float)
        action: "持有" | "止损" | "止盈" | "清仓"
        """
        if entry_price <= 0 or current_price <= 0:
            return "持有", "数据异常", current_price

        loss_pct = (current_price - entry_price) / entry_price

        # 硬止损 -5%
        if loss_pct <= -STOP_LOSS_HARD_PCT:
            log_stop_loss(code="", entry_price=entry_price, exit_price=current_price,
                          loss_pct=loss_pct, action="清仓", reason=f"硬止损{loss_pct*100:.1f}%")
            return "清仓", f"跌幅{loss_pct*100:.1f}%触发硬止损-5%", round(current_price * 0.995, 2)

        # 软止损 -3%
        if loss_pct <= -STOP_LOSS_PCT:
            log_stop_loss(code="", entry_price=entry_price, exit_price=current_price,
                          loss_pct=loss_pct, action="止损", reason=f"软止损{loss_pct*100:.1f}%")
            return "止损", f"跌幅{loss_pct*100:.1f}%触发软止损-3%", round(current_price * 0.99, 2)

        # 移动止盈
        if highest_since_entry > entry_price:
            trail_price = calc_take_profit_trail(entry_price, highest_since_entry)
            if current_price <= trail_price:
                profit_pct = (current_price - entry_price) / entry_price
                return "止盈", f"从高点回落至触发线({trail_price})，盈利{profit_pct*100:.1f}%", round(current_price * 0.99, 2)

        return "持有", f"现价{current_price}在成本价{entry_price:.2f}上方", current_price

    def check_risk(self, positions: dict, total_capital: float) -> dict:
        """
        综合性风控检查（向后兼容）
        返回 {'pass': bool, 'alerts': list, 'actions': list}
        alerts: 警告信息列表
        actions: 需要执行的止损/降仓动作
        """
        alerts = []
        actions = []

        # 1) 持仓集中度检查
        concentration = check_concentration_risk(positions, total_capital)
        for item in concentration:
            alerts.append(f"[集中度警告] {item['code']} 持仓{item['ratio']}% > 20%")

        # 2) 大盘情绪联动仓位（基于当前 sentiment label）
        sentiment_label = self.sentiment.get('label', '正常')
        sentiment_pos = get_sentiment_position_ratio(sentiment_label)
        if sentiment_pos == 0.0:
            alerts.append(f"[仓位警告] 大盘情绪「{sentiment_label}」建议空仓")
        elif sentiment_pos <= 0.30:
            alerts.append(f"[仓位警告] 大盘情绪「{sentiment_label}」建议轻仓{sentiment_pos*100:.0f}%")

        return {
            'pass': len(concentration) == 0 and sentiment_pos > 0,
            'alerts': alerts,
            'actions': actions,
            'concentration_risk': concentration,
            'sentiment_position_ratio': sentiment_pos,
            'sentiment_label': sentiment_label,
        }


# ── 报告辅助 ───────────────────────────────────────────────────

def format_risk_report(stock: dict, risk_info: dict) -> str:
    """生成单只股票的风控说明"""
    sl = calc_stop_loss(stock.get('price', 0))
    msg = (
        f"建仓:{stock.get('price')} | "
        f"软止损:{sl['stop_soft']} | "
        f"硬止损:{sl['stop_hard']} | "
        f"目标:{sl['take_profit']} | "
        f"建议仓位:{risk_info.get('position_ratio', 0)*100:.0f}%"
    )
    return msg


# ── 入口测试 ───────────────────────────────────────────────────

if __name__ == '__main__':
    print("=== 风控规则测试 ===")
    print(f"仓位规则: {POSITION_RULES}")
    print(f"止损规则: -{STOP_LOSS_PCT*100:.0f}%软止损 / -{STOP_LOSS_HARD_PCT*100:.0f}%硬止损 / 移动止盈-{TAKE_PROFIT_TRAIL_PCT*100:.0f}%")
    print(f"过滤规则: 价格{PRICE_MIN}-{PRICE_MAX}元 | 成交额>{TURNOVER_MIN/1e6:.0f}万 | 换手率<{TURNOVER_RATE_MAX}% | 流通市值>{FLOAT_MARKET_CAP_MIN/1e8:.0f}亿")
    print(f"评分权重: 技术{WEIGHT_TECH}/基本面{WEIGHT_FUND}/资金流{WEIGHT_MONEYFLOW}")

    rm = RiskManager({'score': 65, 'avoid_trading': False, 'label': '回暖'})
    print(f"\n当前仓位: {rm.position_ratio*100:.0f}%")

    info = {'price': 45.0, 'change_pct': -1.5, 'amount': 5e7, 'name': '测试'}
    ok, reason, signal = rm.should_buy('600000', info)
    print(f"买入判断: {ok} | {reason} | {signal}")

    action, reason2, price2 = rm.should_stop_loss(45.0, 43.0, 47.0)
    print(f"止损判断: {action} | {reason2} | {price2}")

    sc = composite_score(tech_score=70, fund_score=55, net_in_wan=8000, change_pct=2.5, sentiment_score=65)
    print(f"综合评分: {sc}")

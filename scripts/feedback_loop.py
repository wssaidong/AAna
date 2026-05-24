#!/usr/bin/env python3
"""
scripts/feedback_loop.py — 推荐反馈循环
=====================================
读取最近7日推荐 + 持仓记录，通过K线计算推荐后N日收益率，
追加写入 data/rec_feedback.csv，输出 Markdown 报告。

用法: python3 scripts/feedback_loop.py
"""

import csv
import json
import sys
import os
import warnings
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings('ignore')

# ── 项目路径 ────────────────────────────────────────────────────────────────
PROJECT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT))

from data.quotes import QuoteService

DATA_DIR = PROJECT / "data"
REC_CSV = DATA_DIR / "recommendations.csv"
TRADE_JSON = DATA_DIR / "paper_trades.json"
FEEDBACK_CSV = DATA_DIR / "rec_feedback.csv"

N_DAYS = [1, 3, 5, 15]
WINRATE_THRESHOLD = 0.50

# ── 内部工具 ────────────────────────────────────────────────────────────────

def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _read_csv(path):
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


FEEDBACK_FIELDS = ["date", "code", "name", "rec_date", "trend", "ret_1d", "ret_3d", "ret_5d", "ret_15d"]


def _detect_trend(klines):
    """
    从K线检测趋势状态：上升/震荡/下降
    基于MA排列 + 价格位置 + 近期涨跌
    """
    if not klines or len(klines) < 20:
        return "震荡"
    try:
        closes = []
        for kl in klines:
            c = _sf(kl.get("close"))
            if c:
                closes.append(c)
        if len(closes) < 20:
            return "震荡"
        ma5 = sum(closes[-5:]) / 5
        ma10 = sum(closes[-10:]) / 10
        ma20 = sum(closes[-20:]) / 20
        current = closes[-1]
        recent_change = (closes[-1] - closes[-5]) / closes[-5] * 100 if closes[-5] > 0 else 0
        if ma5 > ma10 > ma20 and current > ma5 and recent_change > 0:
            return "上升"
        elif ma5 < ma10 < ma20 and current < ma5 and recent_change < 0:
            return "下降"
        elif ma5 < ma10 < ma20:
            return "下降"
        elif ma5 > ma10 > ma20:
            return "上升"
        else:
            return "震荡"
    except Exception:
        return "震荡"


def _get_kline_for_trend(code: str, rec_date: str):
    """获取推荐日附近的K线用于趋势检测"""
    qs = QuoteService()
    klines = qs.kline(code, period="daily", count=60, adjust="qfq")
    if not klines:
        return None
    # 优先找推荐日附近的K线
    target = rec_date[:10]
    for kl in klines:
        if kl.get("date", "")[:10] == target:
            # 返回推荐日前后5天的K线
            idx = klines.index(kl)
            start = max(0, idx - 4)
            end = min(len(klines), idx + 5)
            return klines[start:end]
    # 回退：返回最近60天
    return klines[:30]

def _write_csv(path, fields, rows, mode="w"):
    with open(path, mode, newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _load_trades():
    if not TRADE_JSON.exists():
        return {"trades": [], "positions": {}}
    with open(TRADE_JSON, encoding="utf-8") as f:
        return json.load(f)


def _to_date(s):
    """解析 YYYY-MM-DD 格式"""
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _date_offset(date_str, offset):
    """返回 date_str 之后 offset 个交易日的日期字符串（字符串 naive 版）"""
    d = _to_date(date_str)
    if d is None:
        return None
    # 用 K 线数据判断是否交易日太复杂，这里直接用日历日近似
    # 实际应该用持仓记录中的 sell date 来确定实际持仓天数
    return (d + timedelta(days=offset)).strftime("%Y-%m-%d")


def _get_kline_close(code: str, target_date: str) -> tuple:
    """
    获取最近 close 价格，支持指定日期或最近交易日。
    返回 (price, date_str)，找不到返回 (None, None)
    """
    qs = QuoteService()
    # 腾讯 K 线最多返回 500 条，够用
    klines = qs.kline(code, period="daily", count=100, adjust="qfq")
    if not klines:
        return None, None

    # 尝试精确匹配 target_date
    for kl in klines:
        if kl.get("date", "")[:10] == target_date[:10]:
            p = _sf(kl.get("close"))
            if p:
                return p, kl.get("date", "")[:10]

    # 回退：找最近一条
    kl = klines[0]
    p = _sf(kl.get("close"))
    return p, kl.get("date", "")[:10] if p else (None, None)


def _sf(v, default=None):
    """安全转 float"""
    if v is None or v == '' or v == '--' or v == '-':
        return default
    try:
        return float(str(v).replace('%', '').replace(',', ''))
    except (ValueError, TypeError):
        return default


def _calc_ret(entry_price, exit_price):
    """计算收益率（%）"""
    if entry_price and exit_price and entry_price != 0:
        return round((exit_price - entry_price) / entry_price * 100, 2)
    return None


# ── 核心逻辑 ────────────────────────────────────────────────────────────────

def load_recent_recommendations(days=7):
    """加载最近 N 日的推荐"""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = _read_csv(REC_CSV)
    return [r for r in rows if r.get("date", "") >= cutoff]


def load_positions():
    """加载当前持仓（来自 paper_trades.json）"""
    data = _load_trades()
    return data.get("positions", {})


def load_paper_trades():
    """加载历史交易记录"""
    data = _load_trades()
    return data.get("trades", [])


def calculate_returns(rec_rows, trade_rows):
    """
    计算每条推荐的 N 日收益率。
    策略：
    - 如果有 paper_trade 记录，用实际持仓日和卖点计算
    - 否则用推荐日后 N 日的 K 线收盘价对比
    """
    results = []
    qs = QuoteService()

    # 按推荐日期分组，便于查找持仓信息
    # 构建 code→持仓信息 的映射
    position_map = {}  # code → {entry_date, entry_price, shares}
    for trade in trade_rows:
        if trade.get("action") == "buy":
            code = trade.get("code", "")
            position_map[code] = {
                "entry_date": trade.get("date", ""),
                "entry_price": _sf(trade.get("price")),
                "shares": trade.get("shares", 0),
            }

    for rec in rec_rows:
        code = rec.get("code", "")
        name = rec.get("name", "")
        rec_date = rec.get("date", "")

        # 找到推荐日的收盘价
        rec_close, rec_close_date = _get_kline_close(code, rec_date)
        if rec_close is None:
            # 尝试用推荐日附近的 K 线
            rec_close, rec_close_date = _get_kline_close(code, _date_offset(rec_date, 1))

        # 检测趋势状态
        trend_klines = _get_kline_for_trend(code, rec_date)
        trend = _detect_trend(trend_klines) if trend_klines else "震荡"

        row_out = {
            "date": _today(),
            "code": code,
            "name": name,
            "rec_date": rec_date,
            "trend": trend,
            "ret_1d": "",
            "ret_3d": "",
            "ret_5d": "",
            "ret_15d": "",
        }

        if rec_close is None:
            results.append(row_out)
            continue

        # 尝试从持仓记录获取实际持仓信息
        pos = position_map.get(code)

        for nd in N_DAYS:
            if pos:
                # 有实际持仓：用实际持仓价格
                hold_exit_date = _date_offset(pos["entry_date"], nd)
                if hold_exit_date:
                    exit_price, _ = _get_kline_close(code, hold_exit_date)
                    if exit_price is None:
                        exit_price, _ = _get_kline_close(code, _date_offset(pos["entry_date"], nd + 1))
                else:
                    exit_price = None
            else:
                # 无实际持仓：用推荐日后 N 日的 K 线
                target = _date_offset(rec_date, nd)
                exit_price, _ = _get_kline_close(code, target)
                if exit_price is None:
                    # 尝试往后找一天
                    exit_price, _ = _get_kline_close(code, _date_offset(rec_date, nd + 1))

            ret = _calc_ret(rec_close, exit_price)
            row_out[f"ret_{nd}d"] = ret if ret is not None else ""

        results.append(row_out)

    return results


def append_feedback(rows):
    """追加写入 feedback CSV"""
    existing = _read_csv(FEEDBACK_CSV)
    _write_csv(FEEDBACK_CSV, FEEDBACK_FIELDS, existing + rows, mode="w")


def compute_stats(rows, top_n=20):
    """
    计算最近 N 条推荐的统计数据。
    返回 (win_count, total, winrate, avg_win, avg_loss, profit_ratio)
    """
    # 过滤掉没有收益率的记录，取最近 top_n 条
    valid = [r for r in rows if r.get("ret_1d") != ""]
    valid = valid[-top_n:] if len(valid) > top_n else valid

    if not valid:
        return 0, 0, 0.0, 0.0, 0.0, None

    wins = []
    losses = []

    for r in valid:
        # 用 1 日收益率判断胜败
        ret = _sf(r.get("ret_1d"))
        if ret is None:
            continue
        if ret > 0:
            wins.append(ret)
        else:
            losses.append(ret)

    total = len(wins) + len(losses)
    if total == 0:
        return 0, 0, 0.0, 0.0, 0.0, None

    winrate = len(wins) / total

    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0

    # 盈亏比（avg_win / |avg_loss|）
    profit_ratio = round(avg_win / abs(avg_loss), 2) if avg_loss != 0 else None

    return len(wins), total, round(winrate, 4), round(avg_win, 2), round(avg_loss, 2), profit_ratio


def compute_trend_stats(rows, top_n=20):
    """
    按趋势分类统计RSI超卖策略的胜率差异
    区分：上升趋势中RSI超卖 vs 下降趋势中RSI超卖
    返回趋势统计数据字典
    """
    valid = [r for r in rows if r.get("ret_1d") != ""]
    valid = valid[-top_n:] if len(valid) > top_n else valid

    if not valid:
        return {}

    # 按趋势分组
    trend_groups = {"上升": [], "震荡": [], "下降": []}
    for r in valid:
        trend = r.get("trend", "震荡")
        ret = _sf(r.get("ret_1d"))
        if ret is not None and trend in trend_groups:
            trend_groups[trend].append(ret)

    trend_stats = {}
    for trend, rets in trend_groups.items():
        if not rets:
            continue
        wins = [r for r in rets if r > 0]
        losses = [r for r in rets if r <= 0]
        total = len(rets)
        winrate = len(wins) / total if total > 0 else 0
        avg_ret = sum(rets) / total if total > 0 else 0
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        trend_stats[trend] = {
            "count": total,
            "wins": len(wins),
            "losses": len(losses),
            "winrate": round(winrate * 100, 1),
            "avg_ret": round(avg_ret, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
        }
    return trend_stats


def build_markdown_report(rec_rows, feedback_rows, stats, trend_stats=None):
    """构建 Markdown 报告"""
    win_n, total, winrate, avg_win, avg_loss, profit_ratio = stats

    lines = [
        "# 📈 推荐反馈报告",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 📊 近期推荐统计（最近 20 只）",
        "",
        f"| 指标 | 值 |",
        f"|------|----|",
        f"| 统计样本 | {total} 只 |",
        f"| 上涨家数 | {win_n} 只 |",
        f"| 下跌家数 | {total - win_n} 只 |",
        f"| **胜率** | **{winrate*100:.1f}%** |",
        f"| 平均涨幅 | {avg_win:+.2f}% |" if avg_win else f"| 平均涨幅 | N/A |",
        f"| 平均跌幅 | {avg_loss:+.2f}% |" if avg_loss else f"| 平均跌幅 | N/A |",
        f"| 盈亏比 | {profit_ratio:.2f} |" if profit_ratio else f"| 盈亏比 | N/A |",
        "",
    ]

    # 趋势胜率统计（新增）
    if trend_stats:
        lines.extend([
            "",
            "## 📈 趋势胜率统计（RSI超卖视角）",
            "",
            f"| 趋势 | 样本 | 胜率 | 平均收益 | 上涨均幅 | 下跌均幅 |",
            f"|:----:|:----:|:----:|:--------:|:--------:|:--------:|",
        ])
        emoji_map = {"上升": "📈", "震荡": "➡️", "下降": "📉"}
        for trend in ["上升", "震荡", "下降"]:
            if trend in trend_stats:
                s = trend_stats[trend]
                emoji = emoji_map.get(trend, "")
                lines.append(
                    f"| {emoji} {trend} | {s['count']} | {s['winrate']:.1f}% | {s['avg_ret']:+.2f}% | "
                    f"{s['avg_win']:+.2f}% | {s['avg_loss']:+.2f}% |"
                )
        lines.append("")
        # 添加趋势分析结论
        if "上升" in trend_stats and "下降" in trend_stats:
            up_wr = trend_stats["上升"]["winrate"]
            down_wr = trend_stats["下降"]["winrate"]
            if up_wr > down_wr:
                lines.append(f"> 📊 **结论：** 上升趋势中RSI超卖策略胜率({up_wr:.1f}%)高于下降趋势({down_wr:.1f}%)，顺势策略更有效。")
            elif down_wr > up_wr:
                lines.append(f"> 📊 **结论：** 下降趋势中RSI超卖策略胜率({down_wr:.1f}%)高于上升趋势({up_wr:.1f}%)，或存在抄底机会但需谨慎。")
            else:
                lines.append("> 📊 **结论：** 不同趋势下RSI超卖策略胜率接近。")

    if winrate < WINRATE_THRESHOLD:
        lines.append("## ⚠️ 建议提高选股评分阈值")
        lines.append("")
        lines.append(f"> 当前胜率 **{winrate*100:.1f}%** 低于 **{WINRATE_THRESHOLD*100:.0f}%**，建议适当提高选股评分阈值以筛选更优质标的。")

    lines.extend([
        "",
        "## 📋 最新推荐详情",
        "",
        "| 日期 | 代码 | 名称 | 推荐日 | 趋势 | 1日收益 | 3日收益 | 5日收益 | 15日收益 |",
        "|------|------|------|--------|------|--------|--------|--------|--------|",
    ])

    for r in feedback_rows[-20:]:
        ret_1d = f"{r['ret_1d']:+.2f}%" if r.get("ret_1d") != "" else "-"
        ret_3d = f"{r['ret_3d']:+.2f}%" if r.get("ret_3d") != "" else "-"
        ret_5d = f"{r['ret_5d']:+.2f}%" if r.get("ret_5d") != "" else "-"
        ret_15d = f"{r['ret_15d']:+.2f}%" if r.get("ret_15d") != "" else "-"
        trend_emoji = "📈" if r.get("trend") == "上升" else "📉" if r.get("trend") == "下降" else "➡️"
        trend_str = r.get("trend", "震荡")
        lines.append(
            f"| {r['date']} | {r['code']} | {r['name']} | {r['rec_date']} | {trend_emoji}{trend_str} | {ret_1d} | {ret_3d} | {ret_5d} | {ret_15d} |"
        )

    lines.extend([
        "",
        "---",
        "*本报告由 `scripts/feedback_loop.py` 自动生成*",
    ])

    return "\n".join(lines)


# ── 主入口 ────────────────────────────────────────────────────────────────────

def main():
    print("🔄 加载数据...", file=sys.stderr)

    # 1. 读取最近7日推荐
    rec_rows = load_recent_recommendations(days=7)
    print(f"   最近7日推荐: {len(rec_rows)} 条", file=sys.stderr)

    # 2. 读取持仓记录
    trade_data = load_paper_trades()
    print(f"   历史交易记录: {len(trade_data)} 条", file=sys.stderr)

    if not rec_rows:
        print("⚠️  无最近推荐数据，退出。", file=sys.stderr)
        print("\n# 📈 推荐反馈报告\n\n> 暂无推荐数据。")
        return

    # 3. 计算 N 日收益率
    print("📐 计算收益率...", file=sys.stderr)
    feedback_rows = calculate_returns(rec_rows, trade_data)
    print(f"   计算完成: {len(feedback_rows)} 条", file=sys.stderr)

    # 4. 追加写入 CSV
    append_feedback(feedback_rows)
    print(f"   已追加写入: {FEEDBACK_CSV}", file=sys.stderr)

    # 5. 统计
    stats = compute_stats(feedback_rows, top_n=20)
    print(f"   统计样本: {stats[1]} 只, 胜率: {stats[2]*100:.1f}%, 盈亏比: {stats[5]}", file=sys.stderr)

    # 5b. 趋势胜率统计
    trend_stats = compute_trend_stats(feedback_rows, top_n=20)
    if trend_stats:
        print(f"   趋势分布: " + ", ".join(f"{k}({v['count']}只,{v['winrate']}%)" for k, v in trend_stats.items()), file=sys.stderr)

    # 6. 输出 Markdown 报告
    report = build_markdown_report(rec_rows, feedback_rows, stats, trend_stats)
    print(report)


if __name__ == "__main__":
    main()
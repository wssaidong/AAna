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
import shutil
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


def _sf(val):
    """安全转浮点数"""
    try:
        return float(val)
    except (TypeError, ValueError):
        return None

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
        # 严格上升：MA多头排列 + 价格在MA5之上 + 近期上涨
        if ma5 > ma10 > ma20 and current > ma5 and recent_change > 0:
            return "上升"
        # 严格下降：MA空头排列 + 价格在MA5之下 + 近期下跌
        elif ma5 < ma10 < ma20 and current < ma5 and recent_change < 0:
            return "下降"
        # 弱上升：MA多头排列（价格或近期条件不满足）
        elif ma5 > ma10 > ma20:
            return "上升"
        # 弱下降：MA空头排列
        elif ma5 < ma10 < ma20:
            return "下降"
        else:
            return "震荡"
    except Exception:
        return "震荡"


_KLINE_CACHE = {}


def _kline_cached(code: str, count: int = 260):
    """按 code 缓存日线，避免同一只股票被反复拉取（原版每只股票要拉 5+ 次）。"""
    if code in _KLINE_CACHE:
        return _KLINE_CACHE[code]
    try:
        qs = QuoteService()
        kl = qs.kline(code, period="daily", count=count, adjust="qfq") or []
    except Exception:
        kl = []
    # 统一按日期升序（旧 → 新）；QuoteService 已是升序，这里做一次防御性排序
    kl = sorted([k for k in kl if k.get("date")], key=lambda k: k.get("date", "")[:10])
    _KLINE_CACHE[code] = kl
    return kl


def _find_bar_index(klines, target_date):
    """
    返回 target_date 在 klines 中的下标。
    精确命中优先；否则取 <= target_date 的最后一根（推荐日停牌/非交易日的情况）。
    找不到返回 None —— 绝不回退到「最老的一根」。
    """
    if not klines or not target_date:
        return None
    t = target_date[:10]
    idx = None
    for i, kl in enumerate(klines):
        d = kl.get("date", "")[:10]
        if d == t:
            return i
        if d <= t:
            idx = i
        else:
            break
    return idx


def _get_kline_for_trend(code: str, rec_date: str):
    """获取推荐日附近的K线用于趋势检测（需要 >=20 根做均线，取推荐日前 20 根）"""
    klines = _kline_cached(code)
    if not klines:
        return None
    idx = _find_bar_index(klines, rec_date)
    if idx is None:
        return klines[-30:]
    start = max(0, idx - 29)
    return klines[start:idx + 1]

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
    获取 target_date 当日（或之前最近一个交易日）的收盘价。
    返回 (price, date_str)，找不到返回 (None, None)。

    ⚠️ 2026-08-13 修复：原实现在找不到 target_date 时回退到 klines[0]
    （升序数据里 = 最老的一根，可能是 3~5 个月前的价格）→ 静默算出完全错误的收益率。
    现在找不到就返回 (None, None)，宁可留空也不产生脏数据。
    """
    klines = _kline_cached(code)
    if not klines:
        return None, None
    idx = _find_bar_index(klines, target_date)
    if idx is None:
        return None, None
    kl = klines[idx]
    p = _sf(kl.get("close"))
    if p is None:
        return None, None
    return p, kl.get("date", "")[:10]


def _future_close(code: str, base_date: str, n_bars: int) -> tuple:
    """
    取 base_date 之后第 n_bars 个【交易日】的收盘价（按 K 线行数走，不是日历日）。
    未来还没走完 n_bars 根 → 返回 (None, None)，该周期留空。
    """
    klines = _kline_cached(code)
    if not klines:
        return None, None
    idx = _find_bar_index(klines, base_date)
    if idx is None:
        return None, None
    tgt = idx + n_bars
    if tgt >= len(klines):
        return None, None
    kl = klines[tgt]
    p = _sf(kl.get("close"))
    if p is None:
        return None, None
    return p, kl.get("date", "")[:10]


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
    """
    加载最近 N 日的推荐（单源：recommendations.csv）。

    v2026-08-23 修复（Phase 1A）:
    原实现双源（recommendations.csv + rec_feedback.csv）的 merge 实际上是为了兼容
    7/29 - 8/13 期间 cron 走 record_recommendation 而 main() 走 append_recommendations_batch
    的"split-brain"问题。现在 record_recommendation() 已经统一双写（见
    aana_afternoon_screen.record_recommendation 的 Phase 1A 改动），feedback_loop 可以
    安全地**只读 recommendations.csv**——更简单、更一致、更可调试。

    同时 rec_feedback.csv 仍保留作为"细粒度追踪层"（含 score/sentiment_score/macd_*），
    append_feedback() 继续负责把收益率/趋势补回 rec_feedback.csv。两份数据不冲突：
    - recommendations.csv = 单一写入点（推荐源 = 真值之源）
    - rec_feedback.csv = 反馈层（推荐 + 收益率 + 趋势 + 信号）
    """
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    rows = []
    for r in _read_csv(REC_CSV):
        d = (r.get("date") or "")[:10]
        code = r.get("code", "")
        if d and code and d >= cutoff:
            rows.append({"code": code, "name": r.get("name", ""), "date": d})

    # 按 (date, code) 去重（推荐 batch 写入可能产重复行）
    seen = set()
    deduped = []
    for r in rows:
        key = (r["date"], r["code"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    return sorted(deduped, key=lambda x: (x["date"], x["code"]))


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
        base_date = rec_close_date or rec_date
        base_price = rec_close

        # ⚠️ 2026-08-13 修复（复权基准混用）：
        # paper_trades.json 里的 entry_price 是**未复权**成交价（如 603269 = 23.47），
        # 而 K 线走的是 qfq **前复权**序列（同日 close = 15.847）。
        # 两者直接相除会算出 -34.61% 这种假暴跌（该笔实际是 +2.9%）。
        # 因此：持仓记录只用来对齐【建仓日期】，价格一律取同一条 qfq 序列，保证基准一致。
        if pos and pos.get("entry_date"):
            entry_close, entry_date = _get_kline_close(code, pos["entry_date"][:10])
            if entry_close is not None:
                base_price = entry_close
                base_date = entry_date

        for nd in N_DAYS:
            # ⚠️ 2026-08-13 修复：原实现用 _date_offset() 加【日历日】，
            # 周末/节假日直接落在非交易日上 → _get_kline_close 找不到 → 旧代码回退到
            # klines[0]（最老的一根）→ 算出天文数字般错误的收益率。
            # 现在按【交易日行数】前进，未来 bar 不够就留空。
            exit_price, _ = _future_close(code, base_date, nd)
            ret = _calc_ret(base_price, exit_price)
            row_out[f"ret_{nd}d"] = ret if ret is not None else ""

        results.append(row_out)

    return results


def append_feedback(rows):
    """
    合并写入 feedback CSV。

    ⚠️ 2026-08-13 修复两个严重缺陷：
    1) 列丢失：原实现用固定 FEEDBACK_FIELDS + extrasaction="ignore" 全量重写，
       会把实际文件里的 score / sentiment_score / macd_gold / macd_confirmed
       四列**整表抹掉**（这四列由 aana_afternoon_screen.record_recommendation 写入，
       且 rec_optimizer.py 依赖）。现在按「已有表头 ∪ 标准字段」写回。
    2) 永不回填：原实现按 (code, rec_date) 去重后直接丢弃新算的行，导致
       已存在但 ret_* 为空的记录**永远补不上收益率**（实测 106 行自 6/10 起一直空）。
       现在改为：已存在 → 用新算出的非空值补全空字段；不存在 → 追加。
    """
    existing = _read_csv(FEEDBACK_CSV)

    # 保留文件里已有的所有列（防止把 score 等列写没了）
    fields = list(FEEDBACK_FIELDS)
    if FEEDBACK_CSV.exists():
        with open(FEEDBACK_CSV, newline="", encoding="utf-8") as f:
            hdr = csv.DictReader(f).fieldnames or []
        for c in hdr:
            if c not in fields:
                fields.append(c)

    index = {(r.get("code", ""), r.get("rec_date", "")): r for r in existing}

    added = 0
    backfilled = 0
    for new in rows:
        key = (new.get("code", ""), new.get("rec_date", ""))
        old = index.get(key)
        if old is None:
            existing.append(new)
            index[key] = new
            added += 1
            continue
        # 已存在：只补空字段，不覆盖已有值
        touched = False
        for col in ("trend", "ret_1d", "ret_3d", "ret_5d", "ret_15d"):
            nv = str(new.get(col, "") or "").strip()
            ov = str(old.get(col, "") or "").strip()
            if nv and not ov:
                old[col] = new[col]
                touched = True
        if touched:
            backfilled += 1

    print(f"   新增 {added} 条 / 回填 {backfilled} 条历史空记录", file=sys.stderr)

    # 写前备份 + 写后校验（沿用 SKILL.md「缓存是真理之源」预防 SOP）
    if FEEDBACK_CSV.exists():
        shutil.copy2(FEEDBACK_CSV, str(FEEDBACK_CSV) + ".bak")
    _write_csv(FEEDBACK_CSV, fields, existing, mode="w")
    check = _read_csv(FEEDBACK_CSV)
    if len(check) != len(existing):
        # 写坏了就还原，绝不让一次失败的写抹掉历史
        if os.path.exists(str(FEEDBACK_CSV) + ".bak"):
            shutil.copy2(str(FEEDBACK_CSV) + ".bak", FEEDBACK_CSV)
        raise RuntimeError(f"rec_feedback.csv 写后校验失败（{len(check)} != {len(existing)}），已从 .bak 还原")

    return added, backfilled


MAX_ABS_RET = 22.0  # A股单日涨跌上限（创业板/科创板 ±20%）→ 超过即为脏数据


def _valid_rows(rows, top_n=20):
    """
    取用于统计的有效行。

    ⚠️ 2026-08-13 新增两道防线（对齐 SKILL.md「sanity check 阈值表」个股日涨跌 ±22%）：
    1) 剔除 |ret_1d| > 22% 的物理不可能值 —— 这些是历史 _get_kline_close() 回退到
       「最老一根K线」产生的脏数据（实测 278 行，最极端 -58%）。
    2) 按 (code, rec_date) 去重，保留字段最全的一行 —— 历史文件里同一条推荐被
       record_recommendation 多次追加，会让「最近20只」被少数几只重复票占满。
    """
    dedup = {}
    for r in rows:
        ret = _sf(r.get("ret_1d"))
        if ret is None:
            continue
        if abs(ret) > MAX_ABS_RET:
            continue  # 脏数据，跳过
        key = (r.get("code", ""), r.get("rec_date", ""))
        prev = dedup.get(key)
        if prev is None:
            dedup[key] = r
        else:
            # 保留 ret_* 填得更全的那行
            score_new = sum(1 for c in ("ret_1d", "ret_3d", "ret_5d", "ret_15d")
                            if str(r.get(c, "") or "").strip())
            score_old = sum(1 for c in ("ret_1d", "ret_3d", "ret_5d", "ret_15d")
                            if str(prev.get(c, "") or "").strip())
            if score_new >= score_old:
                dedup[key] = r
    valid = sorted(dedup.values(), key=lambda r: (r.get("rec_date", ""), r.get("code", "")))
    return valid[-top_n:] if len(valid) > top_n else valid


def compute_stats(rows, top_n=20):
    """
    计算最近 N 条推荐的统计数据。
    返回 (win_count, total, winrate, avg_win, avg_loss, profit_ratio)
    """
    valid = _valid_rows(rows, top_n)

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
    valid = _valid_rows(rows, top_n)

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

    for r in _valid_rows(feedback_rows, 20):
        ret_1d = _sf(r.get("ret_1d"))
        ret_3d = _sf(r.get("ret_3d"))
        ret_5d = _sf(r.get("ret_5d"))
        ret_15d = _sf(r.get("ret_15d"))
        ret_1d_str = f"{ret_1d:+.2f}%" if ret_1d is not None else "-"
        ret_3d_str = f"{ret_3d:+.2f}%" if ret_3d is not None else "-"
        ret_5d_str = f"{ret_5d:+.2f}%" if ret_5d is not None else "-"
        ret_15d_str = f"{ret_15d:+.2f}%" if ret_15d is not None else "-"
        trend_emoji = "📈" if r.get("trend") == "上升" else "📉" if r.get("trend") == "下降" else "➡️"
        trend_str = r.get("trend", "震荡")
        lines.append(
            f"| {r['date']} | {r['code']} | {r['name']} | {r['rec_date']} | {trend_emoji}{trend_str} | {ret_1d_str} | {ret_3d_str} | {ret_5d_str} | {ret_15d_str} |"
        )

    lines.extend([
        "",
        "---",
        "*本报告由 `scripts/feedback_loop.py` 自动生成*",
    ])

    return "\n".join(lines)


# ── 主入口 ────────────────────────────────────────────────────────────────────

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7,
                    help="回看天数（默认 7）")
    ap.add_argument("--backfill", action="store_true",
                    help="回填模式：扫描 rec_feedback.csv 中所有 ret_* 为空的历史记录并补算")
    args = ap.parse_args()

    print("🔄 加载数据...", file=sys.stderr)

    # 1. 读取推荐（合并 recommendations.csv + rec_feedback.csv 两个源）
    if args.backfill:
        # 回填模式：把所有 ret_* 有缺失的历史记录拉出来重算
        pend = {}
        for r in _read_csv(FEEDBACK_CSV):
            if all(str(r.get(c, "") or "").strip() for c in ("ret_1d", "ret_3d", "ret_5d", "ret_15d")):
                continue
            d = (r.get("rec_date") or "")[:10]
            code = r.get("code", "")
            if d and code:
                pend[(code, d)] = {"code": code, "name": r.get("name", ""), "date": d}
        rec_rows = sorted(pend.values(), key=lambda x: (x["date"], x["code"]))
        print(f"   回填模式: {len(rec_rows)} 条待补记录", file=sys.stderr)
    else:
        rec_rows = load_recent_recommendations(days=args.days)
        print(f"   最近{args.days}日推荐: {len(rec_rows)} 条", file=sys.stderr)

    # 2. 读取持仓记录
    trade_data = load_paper_trades()
    print(f"   历史交易记录: {len(trade_data)} 条", file=sys.stderr)

    if not rec_rows:
        # v2026-08-23 (Phase 1A): 没有推荐是"已知无推荐",不是"静默成功"。
        # exit 2 让 cron wrapper 能识别 — 否则 7/29 那种静默空跑 15 天的事还会复发。
        print("⚠️  无最近推荐数据，exit 2（让 cron 能报警）", file=sys.stderr)
        print("# 📈 推荐反馈报告\n\n> 暂无最近推荐数据。\n\n> 这通常意味着上游 `aana_afternoon_screen.record_recommendation()` "
              "连续 N 日未触发或 `data/recommendations.csv` 写失败。"
              " 排查：1) `python3 scripts/aana_afternoon_screen.py` 单跑一次；"
              "2) `tail -f scripts/cron.log` 看 record_recommendation() 错误；"
              "3) `head data/recommendations.csv` 看末行 mtime。")
        sys.exit(2)

    # 3. 计算 N 日收益率
    print("📐 计算收益率...", file=sys.stderr)
    feedback_rows = calculate_returns(rec_rows, trade_data)
    print(f"   计算完成: {len(feedback_rows)} 条", file=sys.stderr)

    # 4. 合并写入 CSV（新增 + 回填空字段）
    added, backfilled = append_feedback(feedback_rows)
    print(f"   已写入: {FEEDBACK_CSV} (新增 {added} / 回填 {backfilled})", file=sys.stderr)

    # 5. 统计 — 读 CSV 全表末尾 20 条（而不是只统计当天新增的 feedback_rows，
    #    否则样本被压到当天 rec 条数，分母严重偏小 → 胜率误导）
    all_feedback = _read_csv(FEEDBACK_CSV)
    stats = compute_stats(all_feedback, top_n=20)
    print(f"   统计样本: {stats[1]} 只, 胜率: {stats[2]*100:.1f}%, 盈亏比: {stats[5]}", file=sys.stderr)

    # 5b. 趋势胜率统计
    trend_stats = compute_trend_stats(all_feedback, top_n=20)
    if trend_stats:
        print(f"   趋势分布: " + ", ".join(f"{k}({v['count']}只,{v['winrate']}%)" for k, v in trend_stats.items()), file=sys.stderr)

    # v2026-08-23 (Phase 5B): 后置 hook — 调 rec_optimizer 形成闭环
    #   feedback_loop 每次跑完 (写入 N 条 ret_*) → 自动调 rec_optimizer 复盘
    #   rec_optimizer 输出 TuningConfig → data/rec_tuning.json
    #   下次 generate_report.py / aana_afternoon_screen.py 加载配置可参考
    _try_run_rec_optimizer()

    # v2026-08-23 (Phase 8C): DuckDB 同口径交叉验证
    #   feedback_loop 既有 pandas pipeline (calc_ret_3d/5d/15d 等) 计算胜率,
    #   DuckDB 走相同口径的 SQL 算同样的胜率,二者不一致 → stderr WARN。
    #   优势: SQL 是单点真理,业务面胜率计算以后可一只 DuckDB 接管。
    _duckdb_crosscheck(stats)

    # 6. 输出 Markdown 报告（详情表用 CSV 全表末尾 20 条，与统计分母对齐）
    report = build_markdown_report(rec_rows, all_feedback, stats, trend_stats)
    print(report)

    # v2026-08-23 (Phase 1A): exit code 区分
    #   0 = 正常有推荐 + 反馈层计算完成
    #   1 = 有推荐但样本太少（<3）只写反馈但 Markdown 提示
    # 这里一律 exit 0，因为反馈层已经落地、Markdown 报告已输出。报警靠 stderr 而不是 exit code。
    sys.exit(0)


def _try_run_rec_optimizer():
    """Phase 5B: 调用 rec_optimizer.run() 后置 hook — 失败不能阻断 feedback_loop
    只会 stderr WARN + 静默退出 (rec_feedback.csv 已落地才是关键)。
    """
    try:
        from rec_optimizer import RecOptimizer  # noqa: E402
        optimizer = RecOptimizer()
        cfg = optimizer.run()
        optimizer.save_config()
        weak = ", ".join(cfg.weak_sectors) if cfg.weak_sectors else "(none)"
        print(
            f"   [Phase 5B] rec_optimizer 复盘完成: "
            f"score_threshold={cfg.recommended_score_threshold}, "
            f"hold_days={cfg.recommended_hold_days}, "
            f"weak_sectors=[{weak}], win_rate={cfg.overall_win_rate:.1f}%",
            file=sys.stderr,
        )
    except SystemExit as e:
        # rec_optimizer 在 --integrate 时可能 sys.exit，捕获到不抛
        if e.code != 0:
            print(f"   [Phase 5B] rec_optimizer 非零退出 ({e.code})，不阻断", file=sys.stderr)
    except Exception as e:
        # 任何异常都不阻断 feedback_loop 主流程
        print(f"   [Phase 5B] rec_optimizer 失败: {type(e).__name__}: {e}", file=sys.stderr)


def _duckdb_crosscheck(pandas_stats):
    """Phase 8C: DuckDB 同口径交叉验证 — 不阻断,只是 stderr warn。

    pandas_stats: feedback_loop.compute_stats() 返回的 (win_n, total, winrate, avg_win, avg_loss, profit_ratio)
    DuckDB query_winrate() 返回 {n, wins, win_rate, avg_ret, ...}
    同口径应得近似的 winrate (差几个小数点不影响决策):
      - pandas: total = win+loss, winrate = win/total (基于 ret_1d, win=ret_1d>0, loss=ret_1d<=0)
      - DuckDB : winrate = 100 * wins / n (基于 ret_1d, win=ret_1d>0, n=全样本, 包括 ret=0)
    差异容忍: |pandas_winrate - duckdb_winrate| < 1.0pp
    """
    try:
        from analytics_query import query_winrate  # noqa: E402
        db = query_winrate(days=30, min_score=0)
        if not db.get("ok"):
            print(f"   [Phase 8C] DuckDB query 跳过: {db.get('error')}", file=sys.stderr)
            return
        pandas_wr = round(pandas_stats[2] * 100, 1) if len(pandas_stats) > 2 else 0.0
        pandas_n = pandas_stats[1] if len(pandas_stats) > 1 else 0
        db_wr = db.get("win_rate", 0.0)
        db_n = db.get("n", 0)
        diff = abs(pandas_wr - db_wr)
        if diff > 1.0 or pandas_n != db_n:
            print(
                f"   [Phase 8C] ⚠️  不一致: pandas(30d, n={pandas_n}, wr={pandas_wr}%) "
                f"vs DuckDB(n={db_n}, wr={db_wr}%), diff={diff}pp",
                file=sys.stderr,
            )
        else:
            print(
                f"   [Phase 8C] ✅ 一致: pandas 与 DuckDB win_rate 都是 {pandas_wr}% (n={pandas_n})",
                file=sys.stderr,
            )
    except Exception as e:
        # DuckDB 未装,或 import 失败:不阻断
        print(f"   [Phase 8C] DuckDB 跳过: {type(e).__name__}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
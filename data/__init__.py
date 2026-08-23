"""
data/ — AAna 文件持久化层
============================
统一存储所有结构化数据，采用 append-only CSV + 每日 JSON 的混合模式：

data/
├── recommendations.csv      # 追加日志（所有历史推荐，永不覆盖）
├── recommendations/         # 每日推荐快照 JSON（兼容旧格式）
│   └── YYYY-MM-DD.json
├── tracking.csv             # 推荐追踪（次日 outcome 更新）
├── tracking/                # 每日追踪快照 JSON
├── summaries/               # 每日综合报告 JSON
│   └── YYYY-MM-DD.json
├── portfolio.json           # 实盘组合持久化
└── index.json               # 数据索引（按日期快速查找）
"""

import os, csv, json, pathlib
from datetime import datetime, date, timedelta
from typing import Optional

PROJECT = pathlib.Path(__file__).parent.parent.resolve()
DATA = PROJECT / "data"
STATE = PROJECT / "state"
os.makedirs(DATA, exist_ok=True)
os.makedirs(DATA / "recommendations", exist_ok=True)
os.makedirs(DATA / "tracking", exist_ok=True)
os.makedirs(DATA / "summaries", exist_ok=True)

# ── 字段定义 ──────────────────────────────────────────────
REC_FIELDS = [
    "date","code","name","sector","sector_name",
    "reason","expected_high","expected_low",
    "actual_change","hit","created_at"
]
TRACK_FIELDS = [
    "date","code","name","sector","change_pct",
    "hit","consecutive_bad","updated_at"
]

# ── 内部工具 ────────────────────────────────────────────────
def _today():
    return datetime.now().strftime("%Y-%m-%d")

def _now():
    return datetime.now().isoformat()

def _read_csv(path):
    if not path.exists(): return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def _write_csv(path, fields, rows, mode="w"):
    # v2026-08-23 Phase 2: 走 safe_csv_dump —— 防 truncate 0 bytes (与 8/7 JSON dump fp= 同根)
    # mode 参数保留兼容 (a=append 已经在 _read_csv 之后读出来再统一 mode='w' 重新写)。
    # 实际所有调用方只传 mode='w' (全量重写)，保留接口签名。
    import sys
    sys.path.insert(0, str(PROJECT / "scripts"))
    from _safe_io import safe_csv_dump
    safe_csv_dump(str(path), fields, rows)

# ── 推荐写入 ────────────────────────────────────────────────
def append_recommendation(code, name, sector, sector_name,
                          reason, expected_high, expected_low):
    """
    追加一条推荐到 recommendations.csv
    返回是否成功（去重：同日同股不重复写入）
    """
    rec_path = DATA / "recommendations.csv"
    rows = _read_csv(rec_path)
    # 去重
    if any(r["date"] == _today() and r["code"] == code for r in rows):
        return False

    row = {
        "date": _today(), "code": code, "name": name,
        "sector": sector or "", "sector_name": sector_name or "",
        "reason": reason or "", "expected_high": expected_high,
        "expected_low": expected_low,
        "actual_change": "", "hit": "", "created_at": _now()
    }
    _write_csv(rec_path, REC_FIELDS, rows + [row])
    return True

def append_recommendations_batch(stocks):
    """批量追加推荐（用于尾盘选股结果落地）"""
    rec_path = DATA / "recommendations.csv"
    existing = _read_csv(rec_path)
    today_str = _today()
    new_rows = []
    for s in stocks:
        if any(r["date"] == today_str and r["code"] == s["code"] for r in existing + new_rows):
            continue
        new_rows.append({
            "date": today_str, "code": s["code"], "name": s.get("name",""),
            "sector": s.get("sector",""), "sector_name": s.get("sector_name",""),
            "reason": s.get("reason",""),
            "expected_high": s.get("expected_high",""),
            "expected_low": s.get("expected_low",""),
            "actual_change": "", "hit": "", "created_at": _now()
        })
    if new_rows:
        _write_csv(rec_path, REC_FIELDS, existing + new_rows)
    return len(new_rows)

# ── 追踪写入 ────────────────────────────────────────────────
def append_tracking(code, name, sector, change_pct, hit):
    """追加/更新当日追踪记录到 tracking.csv"""
    track_path = DATA / "tracking.csv"
    rows = _read_csv(track_path)
    today_str = _today()

    # 更新已存在的当日记录，或追加新记录
    updated = False
    for r in rows:
        if r["date"] == today_str and r["code"] == code:
            r["change_pct"] = change_pct
            r["hit"] = hit
            r["updated_at"] = _now()
            updated = True
            break

    if not updated:
        rows.append({
            "date": today_str, "code": code, "name": name,
            "sector": sector or "", "change_pct": change_pct,
            "hit": hit, "consecutive_bad": "0", "updated_at": _now()
        })

    _write_csv(track_path, TRACK_FIELDS, rows)
    return True

# ── 快照保存（兼容旧格式）───────────────────────────────────
def save_recommendation_snapshot(date_str, data):
    """保存每日推荐 JSON 快照"""
    p = DATA / "recommendations" / f"{date_str}.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_tracking_snapshot(date_str, data):
    p = DATA / "tracking" / f"{date_str}.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_summary(date_str, data):
    p = DATA / "summaries" / f"{date_str}.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ── 数据查询 ────────────────────────────────────────────────
def get_recommendations_by_date(date_str=None):
    """读取指定日期的推荐快照（优先 CSV，降级 JSON）"""
    date_str = date_str or _today()
    csv_path = DATA / "recommendations.csv"
    rows = [r for r in _read_csv(csv_path) if r["date"] == date_str]
    if rows:
        return rows
    # 降级到 JSON 快照
    json_path = DATA / "recommendations" / f"{date_str}.json"
    if json_path.exists():
        with open(json_path, encoding="utf-8") as f:
            d = json.load(f)
            return d.get("recommended_stocks", [])
    return []

def get_tracking_by_date(date_str=None):
    date_str = date_str or _today()
    csv_path = DATA / "tracking.csv"
    rows = [r for r in _read_csv(csv_path) if r["date"] == date_str]
    if rows:
        return rows
    json_path = DATA / "tracking" / f"{date_str}.json"
    if json_path.exists():
        with open(json_path, encoding="utf-8") as f:
            return json.load(f)
    return []

def get_all_recommendations(limit=None):
    """读取全部历史推荐（倒序）"""
    rows = _read_csv(DATA / "recommendations.csv")
    rows = sorted(rows, key=lambda r: (r["date"], r["code"]), reverse=True)
    return rows[:limit] if limit else rows

def get_stock_history(code, lookback_days=30):
    """查询个股最近N日推荐+追踪记录"""
    today_str = _today()
    rec_rows = [r for r in _read_csv(DATA / "recommendations.csv")
                if r["code"] == code and r["date"] <= today_str]
    track_rows = [r for r in _read_csv(DATA / "tracking.csv")
                  if r["code"] == code and r["date"] <= today_str]
    return {"recommendations": rec_rows[-lookback_days:],
             "tracking": track_rows[-lookback_days:]}

def get_win_rate(code=None, sector=None, days=30):
    """计算个股或板块胜率"""
    today_str = _today()
    rows = _read_csv(DATA / "tracking.csv")
    rows = [r for r in rows if r["date"] <= today_str]
    if code:
        rows = [r for r in rows if r["code"] == code]
    elif sector:
        rows = [r for r in rows if r["sector"] == sector]
    if days:
        cutoff = datetime.strptime(today_str, "%Y-%m-%d")
        rows = [r for r in rows
                if datetime.strptime(r["date"], "%Y-%m-%d") >=
                   cutoff - timedelta(days=days)]
    if not rows:
        return None
    hits = sum(1 for r in rows if r.get("hit") == "True")
    return {"total": len(rows), "hits": hits,
            "win_rate": round(hits/len(rows)*100, 1) if rows else None}

# ── 数据迁移工具 ────────────────────────────────────────────
def migrate_from_state():
    """
    将 state/recommendations/ 下的历史 JSON 迁移到 data/ CSV
    仅迁移，不删除原文件
    """
    rec_dir = STATE / "recommendations"
    imported = 0
    if not rec_dir.exists(): return imported

    for f in rec_dir.glob("*.json"):
        if f.name == "stock_stats.json": continue
        date_str = f.stem  # YYYY-MM-DD
        with open(f, encoding="utf-8") as fp:
            d = json.load(fp)
        stocks = d.get("recommended_stocks", [])
        for s in stocks:
            ok = append_recommendation(
                code=s.get("code",""), name=s.get("name",""),
                sector=s.get("sector",""), sector_name=s.get("sector_name",""),
                reason=s.get("reason",""),
                expected_high=s.get("expected_high",""),
                expected_low=s.get("expected_low","")
            )
            if ok: imported += 1
    return imported


# ── 实盘组合 ────────────────────────────────────────────────────────────────
from data.portfolio import PortfolioTracker, Position, Trade, PortfolioState
from data.paper_trading import (
    record_buy, record_sell, mark_to_market,
    auto_stop_loss, auto_take_profit_trail,
    summary as paper_summary,
    sync_from_recommendations,
)
from scripts.risk_rules import (
    check_concentration_risk,
    get_sentiment_position_ratio,
    log_stop_loss,
    SENTIMENT_POSITION_RULES,
)

__all__ = [
    "append_recommendation", "append_recommendations_batch",
    "append_tracking",
    "save_recommendation_snapshot", "save_tracking_snapshot", "save_summary",
    "get_recommendations_by_date", "get_tracking_by_date",
    "get_all_recommendations", "get_stock_history", "get_win_rate",
    "migrate_from_state",
    "PortfolioTracker", "Position", "Trade", "PortfolioState",
    "record_buy", "record_sell", "mark_to_market",
    "auto_stop_loss", "auto_take_profit_trail",
    "paper_summary", "sync_from_recommendations",
    "check_concentration_risk", "get_sentiment_position_ratio",
    "log_stop_loss", "SENTIMENT_POSITION_RULES",
]

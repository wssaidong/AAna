"""
scripts/analytics_query.py — AAna 数据分析查询层 (DuckDB-backed)

v2026-08-23 Phase 8B:

背景:
  AAna 有 4 个核心 CSV (rec_feedback / recommendations / paper_trades / tracking) +
  3 个 JSON (paper_trades / groups / rec_tuning) + 2 个 JSON snapshot 目录。
  现有 query 路径 (feedback_loop.compute_stats / live_business_perf) 走 pandas +
  全表 scan + Python 聚合,在 1K 行规模就 OK,但 50K 行后会变慢且代码冗长。

策略:
  不迁移数据 (AAna 文件持久化已经设计为人类可读 + 易于 git diff)。
  而是提供 DuckDB-backed query 函数,5 个高频查询出 Python API:
    1. query_recent_recommendations(days=7)
    2. query_winrate(days=30, min_score=0)
    3. query_recent_no_ret() — 反馈循环第二天该算 ret 还缺
    4. query_sector_stats(days=90)
    5. query_today_signal() — 给 cron 后置 hook 看今天状态

设计:
  - 内存 DuckDB 连接 (无持久 .db 文件,符合"不动生产路径"原则)
  - 每次 connect 都从 CSV/JSON 现读,数据是事实之源
  - 函数返回 dict (列名 + 值),便于 JSON 输出或飞书消息

⚠️ 稳定性:
  - 旧 CSV 缺列时 (e.g. recommendations 偶尔缺 sector_name) DuckDB 自动跳过
  - 所有 CAST 走 TRY_CAST (防脏数据崩)
  - 失败的查询返回 {"error": str(e)} 而不是抛错 (feedback_loop main 不能因 query 错崩)

用法:
    from analytics_query import query_winrate
    result = query_winrate(days=30)
    print(f"30日胜率 {result['win_rate']}% (n={result['n']})")
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

PROJECT = Path(__file__).parent.parent.resolve()
DATA_DIR = PROJECT / "data"

REC_FEEDBACK = DATA_DIR / "rec_feedback.csv"
RECOMMENDATIONS = DATA_DIR / "recommendations.csv"
TRACKING = DATA_DIR / "tracking.csv"
PAPER_TRADES = DATA_DIR / "paper_trades.json"
REC_TUNING = DATA_DIR / "rec_tuning.json"

# v2026-08-23 Phase 8B: 接 Phase 1A safe_json_dump 一样的 IO 防护
sys.path.insert(0, str(PROJECT / "scripts"))
try:
    from _safe_io import safe_read_json
except Exception:
    def safe_read_json(path, default=None):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default


def _connect() -> duckdb.DuckDBPyConnection:
    """每次新建内存连接,确保数据是事实之源(读 CSV 现拿)。

    为何不缓存 DuckDB 连接:DuckDB 内存连接无状态,
    单次 query 开销 < 50ms,缓存收益 < 风险 (stale 视图)。
    """
    return duckdb.connect(":memory:")


def _sql_safe(sql: str, params: tuple | None = None) -> dict[str, Any]:
    """执行 SQL,失败返回 error 字段 — 避免 analytics 层抛错阻断主流程"""
    try:
        con = _connect()
        if params:
            result = con.execute(sql, params).fetchall()
        else:
            result = con.execute(sql).fetchall()
        cols = [d[0] for d in con.description] if con.description else []
        return {"ok": True, "rows": [dict(zip(cols, row)) for row in result], "n": len(result)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "rows": [], "n": 0}


# ── 高频查询 API ────────────────────────────────────────────────────────

def query_recent_recommendations(days: int = 7) -> dict[str, Any]:
    """读 recommendations.csv 最近 N 日推荐 (dedup by date, code)"""
    if not RECOMMENDATIONS.exists():
        return {"ok": False, "error": "recommendations.csv not found", "rows": []}
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    sql = """
        SELECT DISTINCT date, code, name, sector, sector_name, reason
        FROM read_csv_auto(?)
        WHERE TRY_CAST(date AS DATE) >= TRY_CAST(? AS DATE)
        ORDER BY date DESC, code
    """
    return _sql_safe(sql, (str(RECOMMENDATIONS), cutoff))


def query_winrate(days: int = 30, min_score: int = 0, score_field: str = "score") -> dict[str, Any]:
    """基于 rec_feedback.csv 算胜率 — 兼容 feedback_loop.compute_stats 的口径

    Args:
        days: 回看天数
        min_score: 最低 score 门槛 (0 = 全样本, 65 = 真下发)
        score_field: 评分字段名 (默认 'score')

    口径 (与 pandas calc_winrate 一致):
      - 只统计 ret_1d 存在且非空的样本
      - win = ret > 0
      - win_rate = 100 * wins / n
      - min_score=0: 空 score 也算,score_field 用 0 替代 (与 pandas `(s or 0)` 等价)
    """
    if not REC_FEEDBACK.exists():
        return {"ok": False, "error": "rec_feedback.csv not found", "n": 0, "win_rate": 0.0}
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    # COALESCE 让空 score 视为 0,这样 min_score=0 时所有非空 ret_1d 样本都计入
    sql = f"""
        WITH cleaned AS (
            SELECT
                TRY_CAST(ret_1d AS DOUBLE) AS ret,
                COALESCE(TRY_CAST({score_field} AS INTEGER), 0) AS score_v
            FROM read_csv_auto(?)
            WHERE ret_1d IS NOT NULL
              AND LENGTH(CAST(ret_1d AS VARCHAR)) > 0
              AND TRY_CAST(rec_date AS DATE) >= TRY_CAST(? AS DATE)
        )
        SELECT
            COUNT(*) AS n,
            SUM(CASE WHEN ret > 0 THEN 1 ELSE 0 END) AS wins,
            ROUND(100.0 * SUM(CASE WHEN ret > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) AS win_rate,
            ROUND(AVG(ret), 2) AS avg_ret
        FROM cleaned
        WHERE score_v >= ?
    """
    result = _sql_safe(sql, (str(REC_FEEDBACK), cutoff, min_score))
    if result["ok"] and result["n"] > 0:
        row = result["rows"][0]
        return {
            "ok": True,
            "n": row["n"],
            "wins": row["wins"],
            "win_rate": row["win_rate"],
            "avg_ret": row["avg_ret"],
            "days": days,
            "min_score": min_score,
        }
    return {"ok": True, "n": 0, "wins": 0, "win_rate": 0.0, "avg_ret": 0.0,
            "days": days, "min_score": min_score}


def query_recent_no_ret() -> dict[str, Any]:
    """找出"推荐 >= N 日, ret_1d 还空"的孤儿 — feedback_loop 第二天该算 ret 还没算"""
    if not REC_FEEDBACK.exists():
        return {"ok": False, "error": "not found", "rows": []}
    # DuckDB 不接受 ret_1d = '' 比较(空字符串强转 DOUBLE 失败)
    # 用 LENGTH(ret_1d) = 0 替代 IS NULL OR ''
    sql = """
        SELECT rec_date, code, name, ret_1d, ret_3d, ret_5d
        FROM read_csv_auto(?)
        WHERE ret_1d IS NULL OR LENGTH(CAST(ret_1d AS VARCHAR)) = 0
        ORDER BY rec_date DESC
        LIMIT 50
    """
    return _sql_safe(sql, (str(REC_FEEDBACK),))


def query_sector_stats(days: int = 90) -> dict[str, Any]:
    """按板块算胜率(给 rec_optimizer.weak_sectors 用 — Phase 5B 闭环)"""
    if not REC_FEEDBACK.exists():
        return {"ok": False, "error": "not found", "rows": []}
    if not RECOMMENDATIONS.exists():
        return {"ok": False, "error": "recommendations.csv missing, can't join", "rows": []}
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    sql = """
        WITH fb AS (
            SELECT
                code,
                rec_date,
                TRY_CAST(ret_1d AS DOUBLE) AS ret
            FROM read_csv_auto(?)
            WHERE ret_1d IS NOT NULL
              AND TRY_CAST(rec_date AS DATE) >= TRY_CAST(? AS DATE)
        ),
        rec AS (
            SELECT code, sector, sector_name
            FROM read_csv_auto(?)
        )
        SELECT
            COALESCE(rec.sector, '(无板块)') AS sector,
            COALESCE(rec.sector_name, '(无板块)') AS sector_name,
            COUNT(*) AS n,
            SUM(CASE WHEN fb.ret > 0 THEN 1 ELSE 0 END) AS wins,
            ROUND(100.0 * SUM(CASE WHEN fb.ret > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) AS win_rate,
            ROUND(AVG(fb.ret), 2) AS avg_ret
        FROM fb
        LEFT JOIN rec ON fb.code = rec.code
        GROUP BY sector, sector_name
        ORDER BY win_rate ASC
    """
    return _sql_safe(sql, (str(REC_FEEDBACK), cutoff, str(RECOMMENDATIONS)))


def query_today_signal() -> dict[str, Any]:
    """给 cron 后置 hook 用 — 今天推荐有几个、ret 已算几个、胜率"""
    today = datetime.now().strftime("%Y-%m-%d")
    if not REC_FEEDBACK.exists():
        return {"ok": False, "error": "not found"}
    sql = """
        SELECT
            COUNT(*) AS total_today,
            SUM(CASE WHEN ret_1d IS NOT NULL THEN 1 ELSE 0 END) AS ret_calculated,
            SUM(CASE WHEN TRY_CAST(ret_1d AS DOUBLE) > 0 THEN 1 ELSE 0 END) AS wins,
            ROUND(AVG(TRY_CAST(ret_1d AS DOUBLE)), 2) AS avg_ret
        FROM read_csv_auto(?)
        WHERE rec_date = ?
    """
    result = _sql_safe(sql, (str(REC_FEEDBACK), today))
    if result["ok"] and result["n"] > 0:
        row = result["rows"][0]
        return {
            "ok": True,
            "today": today,
            "total_today": row["total_today"],
            "ret_calculated": row["ret_calculated"],
            "wins": row["wins"],
            "avg_ret": row["avg_ret"],
        }
    return {"ok": True, "today": today, "total_today": 0,
            "ret_calculated": 0, "wins": 0, "avg_ret": 0.0}


def query_recent_trades(days: int = 7) -> dict[str, Any]:
    """最近 N 日 paper_trades.json 里的 buy/sell"""
    trades = safe_read_json(PAPER_TRADES, default={"trades": []})
    if not trades:
        return {"ok": False, "error": "paper_trades.json missing", "rows": []}
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = [t for t in trades.get("trades", []) if t.get("date", "") >= cutoff]
    # 按日期排序
    rows.sort(key=lambda x: (x.get("date", ""), x.get("action", "")), reverse=True)
    return {"ok": True, "rows": rows, "n": len(rows), "days": days}


def list_all_queries() -> list[str]:
    """列出所有可用查询函数 — 便于 --help 和 discover"""
    return [name for name in globals() if name.startswith("query_")]


# ── 反射调试 helper ──────────────────────────────────────────────────────

def describe_schema(table_csv: str) -> dict[str, Any]:
    """反射一个 CSV 的列结构 + 样本"""
    if not Path(table_csv).exists():
        return {"error": "file not found"}
    sql = f"DESCRIBE (SELECT * FROM read_csv_auto('{table_csv}') LIMIT 1)"
    return _sql_safe(sql)


# ── CLI 入口 ────────────────────────────────────────────────────────────

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("query", choices=list_all_queries() + ["list", "schema"],
                   help="要跑的 query 函数 (list 列出可用)")
    p.add_argument("--days", type=int, default=30, help="回看天数")
    p.add_argument("--min-score", type=int, default=0, help="最低 score 门槛")
    p.add_argument("--csv", type=str, default=str(REC_FEEDBACK),
                   help="DESCRIBE 的 CSV 路径")
    args = p.parse_args()

    if args.query == "list":
        print("可用查询:")
        for q in list_all_queries():
            print(f"  {q}")
        return 0

    if args.query == "schema":
        print(f"Schema for {args.csv}:")
        print(json.dumps(describe_schema(args.csv), indent=2, ensure_ascii=False))
        return 0

    fn = globals()[args.query]
    # 按 query 名 dispatch kwargs
    if "min_score" in fn.__code__.co_varnames:
        result = fn(days=args.days, min_score=args.min_score)
    elif "days" in fn.__code__.co_varnames:
        result = fn(days=args.days)
    else:
        result = fn()

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main() or 0)

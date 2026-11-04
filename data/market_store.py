"""
data/market_store.py — 本地日线库（SQLite）+ 增量同步 + 复权口径显式化
=====================================================================
XWI-80 P0-1。借鉴 Sequoia-X `sequoia_x/data/engine.py` 的存储架构（该仓库
无 LICENSE 文件，仅借鉴设计，未复制代码）：
  - stock_daily 表 UNIQUE(symbol,date) + idx_symbol_date 索引     (engine.py:14-31)
  - 写入前先 DELETE 再 append，幂等重跑安全                        (engine.py:149-153)
  - 已入库自动 skip，断点续传                                       (engine.py:191-197)
  - 单只失败指数退避重试 2**attempt                                 (engine.py:219-253)
  - 批量同步 worker 复用会话/连接（线程池共享一个 QuoteService，
    不逐股票重建服务对象；对应 engine.py:34-53 每 worker 一次 login 的思想）
数据源仍走 AAna 现有腾讯/新浪链路（不引入 baostock）。

复权口径（adjust）是本库的一等公民：
  - 'qfq' 前复权（AAna 主链路统一口径）
  - 'hfq' 后复权
  - 'raw' 不复权（新浪 fallback 与腾讯 NOAJ 降级端点的真实口径）
不同口径分行存储、分行查询，绝不互相顶替 —— 002178 3.73pp 假跌幅事故
（data/quotes.py kline docstring）的根源就是 qfq/raw 混用。

DB 路径：默认 ~/.aana/market_store.db（不进仓库）；环境变量
AANA_MARKET_STORE_DB 可覆盖（测试指向 tempfile），设为 "off" 关闭读写。

CLI:
  python -m data.market_store --sync --date 2026-11-04 --stats
  python -m data.market_store --sync --symbols 600000,000001 --stats
  python -m data.market_store --stats
"""

import argparse
import csv
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).resolve().parent
ENV_DB = "AANA_MARKET_STORE_DB"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS stock_daily (
    symbol     TEXT NOT NULL,
    date       TEXT NOT NULL,
    open       REAL,
    high       REAL,
    low        REAL,
    close      REAL,
    volume     REAL,
    adjust     TEXT NOT NULL DEFAULT 'qfq',
    updated_at TEXT NOT NULL,
    UNIQUE (symbol, date, adjust)
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_symbol_date ON stock_daily (symbol, date);
"""


def _today() -> str:
    return date.today().isoformat()


def default_db_path() -> str:
    """DB 路径：环境变量优先（测试/禁用），默认 ~/.aana/market_store.db"""
    env = os.environ.get(ENV_DB)
    if env:
        return env
    return os.path.join(os.path.expanduser("~/.aana"), "market_store.db")


def normalize_adjust(adjust: Optional[str]) -> str:
    """归一化复权口径：qfq/hfq 直通，其余（''/None/'raw'...）一律 'raw'。"""
    a = (adjust or "").strip().lower()
    return a if a in ("qfq", "hfq") else "raw"


def _new_quote_service():
    """延迟导入避免与 data.quotes 的循环 import。"""
    from data.quotes import QuoteService
    return QuoteService()


def _pick_bar(bars: list[dict], date_str: str) -> Optional[dict]:
    """从多日窗口中取目标日期那根 bar；找不到返回 None（停牌/非交易日）。"""
    for b in bars or []:
        if str(b.get("date", ""))[:10] == date_str:
            return b
    return None


# ── 存储层 ──────────────────────────────────────────────────────────────────

class MarketStore:
    """SQLite 本地日线库。所有 DB 操作都在调用线程完成（sync 的网络层
    在线程池、写库在主线程汇总），无跨线程连接。"""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or default_db_path()
        self.enabled = self.db_path != "off"
        if self.enabled:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE_SQL)
            conn.execute(_CREATE_INDEX_SQL)

    # ── 写入 ──

    def save_bars(self, symbol: str, bars: list[dict], adjust: str = "qfq") -> int:
        """写入一批 bar（kline() 的返回 shape：date/open/high/low/close/vol）。

        幂等：写入前先 DELETE 本 symbol 本口径涉及日期的旧行再 INSERT
        （借鉴 Sequoia-X engine.py:149-153 的「先 DELETE 再 append」，
        按 (symbol, adjust, date) 精细化 —— 多口径/多股票互不误删）。
        返回实际写入行数；缺 date/close 的脏 bar 被丢弃。
        """
        adj = normalize_adjust(adjust)
        rows, seen = [], set()
        for b in bars or []:
            d = str(b.get("date", ""))[:10]
            close = b.get("close")
            if not d or close is None or (d, adj) in seen:
                continue
            seen.add((d, adj))
            rows.append((symbol, d, b.get("open"), b.get("high"), b.get("low"),
                         float(close), b.get("vol"), adj, datetime.now().isoformat()))
        if not rows:
            return 0
        dates = [r[1] for r in rows]
        ph = ",".join("?" * len(dates))
        with self._connect() as conn:
            conn.execute(
                f"DELETE FROM stock_daily WHERE symbol=? AND adjust=? AND date IN ({ph})",
                [symbol, adj] + dates,
            )
            conn.executemany(
                "INSERT INTO stock_daily (symbol,date,open,high,low,close,"
                "volume,adjust,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                rows,
            )
        return len(rows)

    # ── 查询 ──

    def load_kline(self, symbol: str, count: int, adjust: str = "qfq") -> list[dict]:
        """读最近 count 根 bar（升序，shape 同 QuoteService.kline）。

        库里不足 count 根时返回 []（宁缺毋滥：让 kline() 回网络补全量，
        而不是返回一段「看起来像」的截断序列）。
        """
        if not self.enabled or count <= 0:
            return []
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT date,open,high,low,close,volume FROM stock_daily "
                "WHERE symbol=? AND adjust=? ORDER BY date DESC LIMIT ?",
                (symbol, normalize_adjust(adjust), count),
            )
            rows = cur.fetchall()
        if len(rows) < count:
            return []
        out = [
            {"date": r[0], "open": r[1], "high": r[2], "low": r[3],
             "close": r[4], "vol": r[5]}
            for r in reversed(rows)
        ]
        return out

    def has_bar(self, symbol: str, date_str: str, adjust: str = "qfq") -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM stock_daily WHERE symbol=? AND date=? AND adjust=?",
                (symbol, date_str, normalize_adjust(adjust)),
            ).fetchone()
        return row is not None

    def symbols_with_bar(self, date_str: str, adjust: str = "qfq") -> set[str]:
        """已入库某日某口径的股票集合（sync 断点续传的 skip 判定）。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT symbol FROM stock_daily WHERE date=? AND adjust=?",
                (date_str, normalize_adjust(adjust)),
            ).fetchall()
        return {r[0] for r in rows}

    def stats(self) -> dict:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
            symbols = conn.execute(
                "SELECT COUNT(DISTINCT symbol) FROM stock_daily").fetchone()[0]
            lo_hi = conn.execute(
                "SELECT MIN(date),MAX(date) FROM stock_daily").fetchone()
            by_adjust = dict(conn.execute(
                "SELECT adjust,COUNT(*) FROM stock_daily GROUP BY adjust").fetchall())
        return {
            "db": self.db_path, "rows": total, "symbols": symbols,
            "min_date": lo_hi[0], "max_date": lo_hi[1], "by_adjust": by_adjust,
        }

    # ── 增量同步 ──

    def sync_day(self, date_str: str, symbols: Optional[list[str]] = None,
                 adjust: str = "qfq", count: int = 90, workers: int = 8,
                 max_retries: int = 3, qs=None,
                 sleeper=time.sleep) -> "SyncResult":
        """同步指定交易日全池日线（主链路 qfq）。

        - 已入库 (symbol,date,adjust) 自动 skip → 断点续传 + 二次零网络
        - 线程池并发拉取，共享一个 QuoteService（worker 复用会话，
          不逐股票重建服务对象）
        - 单只异常指数退避重试 backoff * 2**attempt
        - 直接走 _tencent_kline(return_adjust=True) 拿真实口径：
          请求 qfq 实得 raw（NOAJ 降级）→ 不入库计 missing，绝不凑数
        - 网络层只拉数据，写库统一在主线程（无 SQLite 跨线程锁冲突）
        """
        from concurrent.futures import ThreadPoolExecutor

        t0 = time.time()
        adj = normalize_adjust(adjust)
        if symbols is None:
            symbols = default_symbols()
        symbols = list(dict.fromkeys(symbols))  # 去重保序

        done = self.symbols_with_bar(date_str, adj) if symbols else set()
        todo = [s for s in symbols if s not in done]

        r = SyncResult(date=date_str, adjust=adj, symbols_total=len(symbols),
                       skipped=len(symbols) - len(todo))

        if todo:
            service = qs or _new_quote_service()

            def fetch_one(code: str):
                for attempt in range(max_retries):
                    try:
                        bars, actual = service._tencent_kline(
                            code, "daily", count, adj, return_adjust=True)
                        if normalize_adjust(actual) != adj:
                            return (code, "missing", None)  # 口径不符，宁缺毋滥
                        bar = _pick_bar(bars, date_str)
                        if bar is None:
                            return (code, "missing", None)  # 停牌/非交易日/无数据
                        return (code, "fetched", bar)
                    except Exception:
                        if attempt < max_retries - 1:
                            sleeper(1.0 * (2 ** attempt))  # 指数退避 1s,2s,4s...
                return (code, "failed", None)

            n_workers = max(1, min(workers, len(todo)))
            with ThreadPoolExecutor(max_workers=n_workers) as pool:
                results = list(pool.map(fetch_one, todo))

            fetched = []
            for code, status, bar in results:
                if status == "fetched" and bar is not None:
                    fetched.append((code, bar))
                elif status == "missing":
                    r.missing += 1
                else:
                    r.failed += 1
            for code, bar in fetched:
                r.inserted_rows += self.save_bars(code, [bar], adjust=adj)
            r.fetched = len(fetched)

        r.elapsed_s = round(time.time() - t0, 2)
        return r


@dataclass
class SyncResult:
    date: str
    adjust: str
    symbols_total: int
    skipped: int
    fetched: int = 0
    missing: int = 0
    failed: int = 0
    inserted_rows: int = 0
    elapsed_s: float = 0.0
    extra: dict = field(default_factory=dict)


# ── 便捷函数（data/quotes.py kline() 的 store 优先/回写入口）──────────────

def load_kline_cached(code: str, count: int, adjust: str = "qfq") -> list[dict]:
    """kline() 的缓存读：库未启用/异常/未命中 → []（不影响主链路）。"""
    try:
        st = MarketStore()
        if not st.enabled:
            return []
        return st.load_kline(code, count=count, adjust=adjust)
    except Exception:
        return []


def save_kline_cached(code: str, bars: list[dict], adjust: str = "qfq") -> int:
    """kline() 的缓存写：当日未收盘 bar 不入库（收盘后由 --sync 落最终值）。"""
    try:
        st = MarketStore()
        if not st.enabled:
            return 0
        today = _today()
        bars = [b for b in (bars or []) if str(b.get("date", ""))[:10] < today]
        return st.save_bars(code, bars, adjust=adjust)
    except Exception:
        return 0


# ── 默认关注池 ──────────────────────────────────────────────────────────────

def default_symbols(data_dir: Optional[str] = None, feed_days: int = 14,
                    rec_days: int = 7, today: Optional[str] = None) -> list[str]:
    """默认同步池 = groups.json 最新组 ∪ rec_feedback.csv 近 feed_days 天
    ∪ recommendations.csv 近 rec_days 天。任何源缺失/损坏只跳过该源。"""
    d = Path(data_dir) if data_dir else DATA_DIR
    t = today or _today()
    codes: list[str] = []

    def _within(row_date: str, days: int) -> bool:
        try:
            cutoff = (date.fromisoformat(t) - timedelta(days=days)).isoformat()
            return bool(row_date) and row_date[:10] >= cutoff
        except ValueError:
            return False

    try:  # groups.json: 最新一组的候选池
        groups = json.loads((d / "groups.json").read_text(encoding="utf-8"))
        latest = max(groups.keys())
        codes += [str(c) for c in groups[latest].get("stocks", [])]
    except Exception:
        pass

    try:  # rec_feedback.csv: 近期反馈跟踪的股票
        with open(d / "rec_feedback.csv", encoding="utf-8") as f:
            codes += [row["code"] for row in csv.DictReader(f)
                      if _within(row.get("date", ""), feed_days) and row.get("code")]
    except Exception:
        pass

    try:  # recommendations.csv: 近期推荐
        with open(d / "recommendations.csv", encoding="utf-8") as f:
            codes += [row["code"] for row in csv.DictReader(f)
                      if _within(row.get("date", ""), rec_days) and row.get("code")]
    except Exception:
        pass

    return [c for c in dict.fromkeys(codes) if c]


# ── CLI ─────────────────────────────────────────────────────────────────────

def _print_stats(st: MarketStore) -> None:
    s = st.stats()
    rng = f"{s['min_date']}..{s['max_date']}" if s['min_date'] else "-"
    print(f"[stats] db={s['db']} rows={s['rows']} symbols={s['symbols']} "
          f"range={rng} adjust={s['by_adjust']}")


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="data.market_store",
        description="AAna 本地日线库：增量同步 + 复权口径显式化")
    parser.add_argument("--sync", action="store_true", help="同步指定交易日")
    parser.add_argument("--date", default=None, help="交易日 YYYY-MM-DD（默认今天）")
    parser.add_argument("--symbols", default=None,
                        help="逗号分隔股票代码；缺省用默认关注池")
    parser.add_argument("--adjust", default="qfq", choices=["qfq", "hfq", "raw"],
                        help="复权口径（默认 qfq，AAna 主链路统一口径）")
    parser.add_argument("--count", type=int, default=90,
                        help="单次拉取的日线窗口根数（用于定位目标日 bar）")
    parser.add_argument("--workers", type=int, default=8, help="并发线程数")
    parser.add_argument("--stats", action="store_true", help="打印库统计")
    parser.add_argument("--db", default=None, help="覆盖 DB 路径")
    args = parser.parse_args(argv)

    st = MarketStore(db_path=args.db)
    print(f"[market_store] db={st.db_path} enabled={st.enabled}")

    if not args.sync and not args.stats:
        parser.print_usage()
        return 0

    if args.sync:
        date_str = args.date or _today()
        if args.symbols:
            symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
        else:
            symbols = default_symbols()
        print(f"[sync] date={date_str} symbols={len(symbols)} "
              f"adjust={args.adjust} workers={args.workers}")
        r = st.sync_day(date_str, symbols=symbols, adjust=args.adjust,
                        count=args.count, workers=args.workers)
        print(f"[sync] skipped={r.skipped} fetched={r.fetched} "
              f"missing={r.missing} failed={r.failed} "
              f"inserted={r.inserted_rows} elapsed={r.elapsed_s}s")
        if r.missing or r.failed:
            print(f"[sync] note: missing={r.missing}（停牌/非交易日/口径不符不凑数） "
                  f"failed={r.failed}（重试耗尽，下次 --sync 自动续传）")
        if date_str == _today():
            now = datetime.now()
            if now.hour < 15 or (now.hour == 15 and now.minute < 5):
                print("[sync] WARN 目标日=今天且未到收盘，当日 bar 可能未生成/"
                      "未收盘；收盘后重跑同命令会幂等覆盖为最终值")

    if args.stats:
        _print_stats(st)
    return 0


if __name__ == "__main__":
    sys.exit(main())

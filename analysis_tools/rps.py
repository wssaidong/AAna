"""
analysis_tools/rps.py — 全市场横截面 RPS（相对强度）（XWI-82 P0-3）
=====================================================================
借鉴 Sequoia-X `sequoia_x/strategy/rps_breakout.py` 的计算口径（该仓库无
LICENSE 文件，仅借鉴设计，未复制代码）：
  - 纵向涨幅: groupby('symbol')['close'].shift(window) → pct_change   (L31-32)
  - 横截面排位: 同一日 rank(pct=True) * 100 = RPS                      (L39)
  - 突破判定: close >= rolling(window).max(high) * 0.90                (L43-52)
全部向量化（rolling/shift/groupby/rank），严禁 iterrows。

RPS 在 AAna 的定位：**候选池扩容信号**，不是打分因子——不改 AAna
技术50%+基本面30%+估值20% 的评分体系；用法是「池外但全市场 RPS 领先的票
→ 进候选池视野」，以及「池内第 1 但全市场 RPS 平庸 → 池子整体防御化」
的背离提示。

复权口径（显式，禁止混用）：
  - 池内 RPS：腾讯 qfq 前复权日线，经 data/market_store（XWI-80 S1）读取，
    adjust 字段过滤，raw 绝不冒充 qfq
  - 全市场 RPS：雪球 screener `current_year_percent`（YTD 涨幅，前复权口径）
    ——push2.eastmoney 全市场快照在本机被 IP 级限流（RemoteDisconnected，
    2026-11-04 实测），且逐票拉全市场几百只 K 线被本 issue 明确禁止，
    故全市场横截面用雪球批量分页（~50 请求一次，落地缓存，重跑零网络）。
    两个窗口（120 日 / YTD）各自独立成列，绝不互相换算。

CLI:
  python -m analysis_tools.rps                       # 全市场分布+Top-N+池内对比
  python -m analysis_tools.rps --pool-only           # 仅池内 120 日 RPS（store）
  python -m analysis_tools.rps --backfill            # 回填池历史（每票 1 次腾讯请求）
"""
import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

RPS_WINDOW = 120          # Sequoia-X rps_period 同款
BREAKOUT_RATIO = 0.90     # close >= roll_high * 0.90（Sequoia-X 同款）
XQ_SCREENER = "https://stock.xueqiu.com/v5/stock/screener/quote/list.json"
XQ_HOME = "https://xueqiu.com"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

RPS_BUCKETS = [f"{i * 10}-{i * 10 + 10}" for i in range(10)]


# ── 核心：横截面 RPS 计算（纯函数，任意 DataFrame 进）─────────────

def compute_returns(df: pd.DataFrame, window: int = RPS_WINDOW) -> pd.DataFrame:
    """纵向 N 日涨幅：close / groupby('symbol') shift(window) - 1。

    - 输入列 [symbol, date, close]（多余列原样带过）
    - 重复 (symbol, date) 去重（防 qfq/raw 或重采脏数据重复计数）
    - 停牌断档按 bar 数对齐（shift 是行序，不是自然日）
    - 基期 close<=0（脏数据）→ ret=NaN，不产出 ±inf
    - 不修改输入 df
    """
    out = df.drop_duplicates(["symbol", "date"], keep="first").copy(deep=True)
    if out.empty:
        out = out.assign(ret=pd.Series(dtype=float))
        return out
    out = out.sort_values(["symbol", "date"], kind="stable")
    prev = out.groupby("symbol")["close"].shift(window)
    with pd.option_context("mode.chained_assignment", None):
        ret = (out["close"] - prev) / prev
    ret = ret.where((prev > 0) & (out["close"] > 0))
    out["ret"] = ret.astype(float)
    return out


def compute_rps(df: pd.DataFrame, window: int = RPS_WINDOW) -> pd.DataFrame:
    """全横截面 RPS：compute_returns 后按日期 rank(pct=True)*100。

    RPS ∈ [0,100]；历史不足（ret=NaN）不参与当日排名（rank 默认跳过 NaN）。
    """
    out = compute_returns(df, window=window)
    if out.empty:
        return out.assign(rps=pd.Series(dtype=float))
    out["rps"] = (out.groupby("date")["ret"].rank(pct=True) * 100).astype(float)
    return out


def rps_distribution(rps: pd.Series) -> dict:
    """RPS 分布：十分位桶计数 + n/min/median/max（NaN 剔除）。"""
    s = pd.Series(rps, dtype=float).dropna()
    if s.empty:
        return {"n": 0, "buckets": {b: 0 for b in RPS_BUCKETS},
                "min": None, "median": None, "max": None}
    idx = (s / 10).astype(int).clip(0, 9)
    buckets = {b: 0 for b in RPS_BUCKETS}
    counts = idx.value_counts()
    for k, v in counts.items():
        buckets[RPS_BUCKETS[int(k)]] = int(v)
    return {"n": int(s.size), "buckets": buckets,
            "min": round(float(s.min()), 1),
            "median": round(float(s.median()), 1),
            "max": round(float(s.max()), 1)}


def top_n_by_rps(df: pd.DataFrame, n: int = 20,
                 date_str: Optional[str] = None) -> pd.DataFrame:
    """取 RPS 最新可得交易日的 Top-N（降序）。历史不足的空表 → 空 DataFrame。"""
    valid = df[df["rps"].notna()] if "rps" in df else df.iloc[0:0]
    if valid.empty:
        return valid
    if date_str is None:
        date_str = valid["date"].max()
    day = valid[valid["date"] == date_str]
    cols = [c for c in ("symbol", "date", "close", "ret", "rps", "breakout")
            if c in day.columns]
    return day[cols].sort_values("rps", ascending=False).head(n).reset_index(drop=True)


def add_breakout(df: pd.DataFrame, window: int = RPS_WINDOW,
                 ratio: float = BREAKOUT_RATIO) -> pd.DataFrame:
    """Sequoia-X 突破判定：close >= 近 window 根最高价 * ratio。

    rolling(window, min_periods=window//2)（Sequoia-X 同款：历史略欠也允许判定）。
    """
    out = df.drop_duplicates(["symbol", "date"], keep="first").copy(deep=True)
    if out.empty or "high" not in out.columns:
        out["breakout"] = pd.Series(dtype=bool)
        return out
    out = out.sort_values(["symbol", "date"], kind="stable")
    roll_high = (out.groupby("symbol")["high"]
                 .rolling(window, min_periods=max(1, window // 2))
                 .max().reset_index(level=0, drop=True))
    out["breakout"] = (out["close"] >= roll_high * ratio).fillna(False)
    return out


# ── 数据源 A：本地日线库（S1 market_store，qfq）───────────────────

def load_pool_history(db_path: Optional[str] = None,
                      adjust: str = "qfq") -> pd.DataFrame:
    """整库读 [symbol, date, close, high]（单条 SQL，向量化前体）。

    adjust 显式过滤——qfq/hfq/raw 分行存储，绝不混口径。
    """
    import sqlite3

    from data import market_store

    path = db_path or market_store.default_db_path()
    if not market_store.MarketStore(db_path=path).enabled:
        return pd.DataFrame(columns=["symbol", "date", "close", "high"])
    with sqlite3.connect(path) as conn:
        df = pd.read_sql(
            "SELECT symbol, date, close, high FROM stock_daily "
            "WHERE adjust = ? ORDER BY symbol, date",
            conn, params=(market_store.normalize_adjust(adjust),))
    return df


def backfill_pool_history(symbols: list[str], count: int = 320,
                          adjust: str = "qfq", store=None, qs=None,
                          workers: int = 8, max_retries: int = 3,
                          sleeper=time.sleep) -> dict:
    """回填池内全量历史（借鉴 Sequoia-X backfill 的断点续传思想）。

    - 每票 1 次腾讯请求拿 count 根（fqkline 单次可返 320+ 根，够 120 日窗口）
    - store 已有 >= count 根 → skip（零网络，重跑幂等）
    - 口径不符（NOAJ 降级=raw）→ missing，绝不存成 qfq
    - 线程池共享一个 QuoteService（S1 sync_day 同款架构）
    """
    from concurrent.futures import ThreadPoolExecutor

    from data import market_store

    st = store or market_store.MarketStore()
    symbols = list(dict.fromkeys(symbols))
    todo = [s for s in symbols if not st.load_kline(s, count=count, adjust=adjust)]
    res = {"symbols_total": len(symbols), "skipped": len(symbols) - len(todo),
           "fetched": 0, "missing": 0, "failed": 0, "inserted_rows": 0,
           "elapsed_s": 0.0}
    if not todo:
        return res

    service = qs or _new_quote_service()
    adj = market_store.normalize_adjust(adjust)

    def fetch_one(code: str):
        for attempt in range(max_retries):
            try:
                bars, actual = service._tencent_kline(
                    code, "daily", count, adjust, return_adjust=True)
                if market_store.normalize_adjust(actual) != adj:
                    return (code, "missing", None)
                if not bars:
                    return (code, "missing", None)
                return (code, "fetched", bars)
            except Exception:
                if attempt < max_retries - 1:
                    sleeper(1.0 * (2 ** attempt))
        return (code, "failed", None)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(todo)))) as pool:
        results = list(pool.map(fetch_one, todo))
    for code, status, bars in results:
        if status == "fetched" and bars:
            res["fetched"] += 1
            res["inserted_rows"] += st.save_bars(code, bars, adjust=adj)
        else:
            res[status] += 1
    res["elapsed_s"] = round(time.time() - t0, 2)
    return res


def _new_quote_service():
    from data.quotes import QuoteService
    return QuoteService()


def default_pool_symbols() -> list[str]:
    """默认池 = market_store.default_symbols（groups.json ∪ 近期反馈/推荐）。"""
    from data import market_store
    return market_store.default_symbols()


# ── 数据源 B：雪球 screener 全市场快照（YTD 涨幅横截面）──────────

def fetch_market_snapshot_ytd(session=None, page_size: int = 100,
                              max_pages: int = 60, sleeper=time.sleep,
                              cache_dir: Optional[str] = None) -> pd.DataFrame:
    """全市场 YTD 涨幅快照（columns: symbol/name/price/ytd_pct）。

    - 批量分页（页大小 ≤100），带 cookie 的 session，页间 sleep 节流
    - 当天缓存命中 → 零网络（缓存写 cache_dir，默认 ~/.aana/）
    - 失败（限流/解析异常）→ 空 DataFrame（宁缺毋滥，调用方自行降级）
    """
    cache = Path(cache_dir) if cache_dir else Path.home() / ".aana"
    cache.mkdir(parents=True, exist_ok=True)
    cache_file = cache / f"rps_market_snapshot_{date.today():%Y%m%d}.csv"
    if cache_file.exists():
        cached = pd.read_csv(cache_file, dtype={"symbol": str})
        if not cached.empty:
            cached["symbol"] = cached["symbol"].str.zfill(6)
            return cached

    import requests

    sess = session or requests.Session()
    sess.headers.update({"User-Agent": UA})
    try:
        sess.get(XQ_HOME, timeout=(5, 10))
    except Exception:
        pass

    rows, page = [], 1
    while page <= max_pages:
        try:
            r = sess.get(XQ_SCREENER, timeout=(5, 10),
                         params={"page": page, "size": page_size,
                                 "order_by": "market_capital",
                                 "order_type": "desc", "market": "CN"})
            data = r.json().get("data") or {}
        except Exception:
            break
        items = data.get("list") or []
        if not items:
            break
        for it in items:
            sym, px, ytd = (it.get("symbol"), it.get("current"),
                            it.get("current_year_percent"))
            if not sym or not px or px <= 0 or ytd is None:
                continue  # 停牌/异常价不凑数
            rows.append({"symbol": sym[2:] if len(sym) == 8 else sym,
                         "name": it.get("name", ""),
                         "price": float(px), "ytd_pct": float(ytd)})
        total_pages = int(data.get("maxPage") or
                          -(-int(data.get("count") or 0) // page_size) or 1)
        if page >= total_pages:
            break
        page += 1
        sleeper(0.25)

    df = (pd.DataFrame(rows).drop_duplicates("symbol")
          if rows else pd.DataFrame(columns=["symbol", "name", "price", "ytd_pct"]))
    if not df.empty:
        df.to_csv(cache_file, index=False)
    return df


def market_rps_ytd(snapshot: pd.DataFrame) -> pd.DataFrame:
    """全市场 YTD 横截面 RPS：ytd_pct.rank(pct=True)*100（Sequoia-X 同款排位式）。"""
    if snapshot.empty:
        return snapshot.assign(rps=pd.Series(dtype=float))
    out = snapshot.copy(deep=True)
    out["rps"] = (out["ytd_pct"].rank(pct=True) * 100).astype(float)
    return out


def pool_vs_market(pool_rps: pd.DataFrame, market_rps: pd.DataFrame,
                   window: int = RPS_WINDOW) -> pd.DataFrame:
    """池内 N 日 RPS × 全市场 YTD RPS 对齐表（背离 = 扩容/防御提示入口）。

    两列口径不同（120日 qfq vs YTD 前复权），只并列展示，绝不互相换算。
    """
    if pool_rps.empty:
        return pd.DataFrame()
    valid = pool_rps[pool_rps["rps"].notna()]
    day = valid[valid["date"] == valid["date"].max()][["symbol", "ret", "rps"]]
    day = day.rename(columns={"ret": f"ret_{window}d", "rps": f"rps_{window}d"})
    day["pool_rank"] = day[f"rps_{window}d"].rank(ascending=False).astype(int)
    if market_rps.empty:
        return day.reset_index(drop=True)
    mk = market_rps[["symbol", "ytd_pct", "rps"]].rename(
        columns={"ytd_pct": "ytd_pct", "rps": "rps_ytd"})
    return day.merge(mk, on="symbol", how="left").reset_index(drop=True)


def _load_aana_score_rank() -> dict[str, int]:
    """读当天深度排名 JSON（data/deep_analysis_YYYYMMDD.json）→ {code: rank}。

    仅供 CLI 展示「评分第几 vs RPS 第几」的背离；文件缺失/形状不符 → {}。
    """
    path = DATA_DIR / f"deep_analysis_{date.today():%Y%m%d}.json"
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        ranked = obj.get("ranked") or obj.get("top10") or obj.get("results") or []
        return {str(r.get("code", r.get("symbol", ""))): i + 1
                for i, r in enumerate(ranked) if r.get("code") or r.get("symbol")}
    except Exception:
        return {}


# ── CLI ─────────────────────────────────────────────────────────

def _fmt_buckets(dist: dict) -> str:
    return " ".join(f"{b}:{v}" for b, v in dist["buckets"].items())


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="analysis_tools.rps",
        description="横截面 RPS：池内 N 日（store qfq）× 全市场 YTD（雪球批量）")
    parser.add_argument("--window", type=int, default=RPS_WINDOW,
                        help=f"池内 RPS 窗口（默认 {RPS_WINDOW}，Sequoia-X 同款）")
    parser.add_argument("--top", type=int, default=20, help="Top-N 条数")
    parser.add_argument("--pool-only", action="store_true",
                        help="只算池内（store，零网络）")
    parser.add_argument("--backfill", action="store_true",
                        help="先回填池内历史（每票 1 次腾讯请求，幂等）")
    parser.add_argument("--symbols", default=None, help="逗号分隔池代码（缺省自动池）")
    parser.add_argument("--db", default=None, help="覆盖 market_store DB 路径")
    parser.add_argument("--market-cache-dir", default=None,
                        help="全市场快照缓存目录（默认 ~/.aana/）")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="JSON 输出（供程序消费）")
    args = parser.parse_args(argv)

    from data import market_store

    db_path = args.db or market_store.default_db_path()
    symbols = ([s.strip() for s in args.symbols.split(",") if s.strip()]
               if args.symbols else None)

    if args.backfill:
        pool = symbols or default_pool_symbols()
        r = backfill_pool_history(pool, count=max(args.window + 200, 320),
                                  store=market_store.MarketStore(db_path=db_path))
        print(f"[backfill] total={r['symbols_total']} skipped={r['skipped']} "
              f"fetched={r['fetched']} missing={r['missing']} failed={r['failed']} "
              f"inserted={r['inserted_rows']} elapsed={r['elapsed_s']}s")

    hist = load_pool_history(db_path=db_path, adjust="qfq")
    pool_rps = compute_rps(hist, window=args.window)
    pool_rps = add_breakout(pool_rps, window=args.window)
    latest_valid = pool_rps[pool_rps["rps"].notna()]
    pool_date = latest_valid["date"].max() if not latest_valid.empty else None
    pool_dist = (rps_distribution(latest_valid[latest_valid["date"] == pool_date]["rps"])
                 if pool_date else rps_distribution(pd.Series(dtype=float)))

    market_rps = pd.DataFrame()
    if not args.pool_only:
        snap = fetch_market_snapshot_ytd(cache_dir=args.market_cache_dir)
        if snap.empty:
            print("[market] WARN 全市场快照获取失败（限流/网络），"
                  "全市场横截面降级为不可用；池内 RPS 不受影响")
        else:
            market_rps = market_rps_ytd(snap)
            mk_dist = rps_distribution(market_rps["rps"])
            print(f"[market] source=xueqiu_screener n={len(market_rps)} "
                  f"window=YTD(前复权)")
            print(f"[market-rps] n={mk_dist['n']} min={mk_dist['min']} "
                  f"median={mk_dist['median']} max={mk_dist['max']}")
            print(f"[market-rps] 分布 {_fmt_buckets(mk_dist)}")
            top_mk = market_rps.sort_values("rps", ascending=False).head(args.top)
            print(f"[market-rps] Top-{len(top_mk)} (YTD涨幅 / RPS):")
            for _, row in top_mk.iterrows():
                in_pool = "*" if hist["symbol"].isin([row["symbol"]]).any() else " "
                print(f"  {in_pool} {row['symbol']} {str(row['name'])[:8]:<8} "
                      f"YTD {row['ytd_pct']:+8.2f}%  RPS {row['rps']:5.1f}"
                      f"{'' if in_pool.strip() else '  <- 池外(扩容候选)'}")

    print(f"[pool] db={db_path} symbols={hist['symbol'].nunique()} "
          f"rows={len(hist)} caliber=qfq window={args.window}d "
          f"date={pool_date or 'n/a'}")
    if pool_date:
        print(f"[pool-rps] n={pool_dist['n']} min={pool_dist['min']} "
              f"median={pool_dist['median']} max={pool_dist['max']}")
        print(f"[pool-rps] 分布 {_fmt_buckets(pool_dist)}")
        top = top_n_by_rps(pool_rps, n=args.top)
        score_rank = _load_aana_score_rank()
        print(f"[pool-rps] Top-{len(top)} (池内横截面):")
        for _, row in top.iterrows():
            sr = score_rank.get(row["symbol"])
            bo = " 突破" if row.get("breakout") else ""
            sr_txt = f" 评分第{sr}" if sr else ""
            print(f"  {row['symbol']}  {row['ret'] * 100:+8.2f}%  "
                  f"RPS {row['rps']:5.1f}{bo}{sr_txt}")

    cmp_df = pool_vs_market(pool_rps, market_rps, window=args.window)
    if not cmp_df.empty and not market_rps.empty:
        print(f"[compare] 池内{args.window}日RPS × 全市场YTD RPS（口径并列，不换算）:")
        show = cmp_df.sort_values(f"rps_{args.window}d", ascending=False)
        for _, row in show.head(args.top).iterrows():
            ytd = "-" if pd.isna(row.get("rps_ytd")) else f"{row['rps_ytd']:.1f}"
            ytd_pct = "-" if pd.isna(row.get("ytd_pct")) else f"{row['ytd_pct']:+.1f}%"
            print(f"  池内第{row['pool_rank']:>2} {row['symbol']}  "
                  f"{args.window}日RPS {row[f'rps_{args.window}d']:5.1f}  |  "
                  f"全市场YTD {ytd_pct:>8} RPS {ytd:>5}")

    if args.as_json:
        payload = {"pool_date": pool_date, "pool_dist": pool_dist,
                   "market_n": int(len(market_rps))}
        print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
尾盘深度分析 2026-11-09 PM — 基于尾盘选股报告 Top5 (14:47 生成)
输入: reports/2026-11-09-尾盘选股.md Top5 = 600732/600501/002943/603375/603666
方法: 复用 deep_analysis_20261022 评分引擎 (技术面50% + 基本面30% + 估值20%)
      + 估值面失真修正 v1 (10-28 PM 规则: 最新单季归母转亏 且 净利同比<-50% → PE 记 0 只留 PB)
      腾讯行情实时快照 (14:5x 盘中) + 腾讯日K(120d, qfq 失败降级 kline/kline) + akshare 财务摘要
      + sina/东财 行业双源核验 + rec_tuning 板块胜率
铁律: 亏损股 (PE<=0) 估值面 PE 记 0; 情绪 回暖 55 (非冰点) → 守卫放行
输出: data/deep_analysis_pm_20261109.json (评分汇总, 由 gen_deep_reports_pm_20261109.py 渲染报告)
"""
import sys, os, json, re, time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import data_sources as ds
from deep_analysis_20261022 import tech_score, fund_score, val_score, rating_of

TODAY = "2026-11-09"
OUT_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_pm_20261109.json")

# (code, name, v24_score, stop, target, chg_pct) — 来自尾盘报告 Top5 (评分降序)
CANDIDATES = [
    ("600732", "爱旭股份", 100, 12.22, 14.45, -1.94),
    ("600501", "航天晨光", 100, 15.90, 18.81, -0.06),
    ("002943", "宇晶股份", 100, 27.91, 33.01, -2.85),
    ("603375", "盛景微", 100, 39.92, 47.22, 4.89),
    ("603666", "亿嘉和", 100, 24.10, 28.50, 3.97),
]

# rec_tuning sector_stats 候选键 (脚本按顺序取第一个真实存在的)
SECTOR_CANDIDATES = {
    "600732": ["光伏设备", "电池", "电力设备", "新能源发电", "太阳能"],
    "600501": ["航天装备", "地面兵装", "专用设备", "仪器仪表", "机械基础件"],
    "002943": ["专用设备", "机械基础件", "其它通用机械", "光伏设备", "半导体设备"],
    "603375": ["半导体", "元件", "光学元件", "电子元件", "印制电路板"],
    "603666": ["计算机设备", "专用设备", "仪器仪表", "软件开发", "工控自动化"],
}

# 邻近键 (仅披露, 不参与主键取值)
SECTOR_NEAR = {
    "600732": [("半导体", "光伏邻近键")],
    "600501": [("军工", "军工邻近键")],
    "002943": [("半导体", "光伏/半导体邻近键")],
    "603375": [("电子元件", "半导体邻近键")],
    "603666": [("机器人", "电力机器人邻近键")],
}

_AK_CACHE = {}


def fetch_kline(code, days=120):
    """腾讯日K 120d — fqkline qfq 端点 WAF 501 时降级 kline/kline 非复权"""
    import requests
    prefix = ds.get_prefix(code)
    sym = f"{prefix}{code}"
    last = None
    variants = (
        ("fqkline/get", "kline_dayqfq", f"{sym},day,,,{days},qfq"),
        ("kline/kline", "kline_day", f"{sym},day,,,{days},"),
        ("kline/kline", "kline_day", f"{sym},day,,,{days},qfq"),
    )
    for path, var, param in variants:
        try:
            url = f"https://web.ifzq.gtimg.cn/appstock/app/{path}?_var={var}&param={param}"
            r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            data = json.loads(re.search(r'=(.+)$', r.text.strip()).group(1))
            kl0 = data['data'][sym]
            kl = [[k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])]
                  for k in (kl0.get("qfqday") or kl0.get("day") or [])]
            if kl:
                return kl
        except Exception as e:
            last = e
    raise RuntimeError(f"K线获取失败: {last}")


def ak_abstract(code):
    """akshare 财务摘要 (带进程内缓存 — fund_score 与 single_quarter 共用一次拉取)"""
    if code in _AK_CACHE:
        return _AK_CACHE[code]
    df = None
    err = None
    try:
        import akshare as ak
        df = ak.stock_financial_abstract(symbol=code)
    except Exception as e:
        err = str(e)[:120]
    _AK_CACHE[code] = (df, err)
    return _AK_CACHE[code]


def single_quarter_profit(code):
    """(最新季报期, 最新单季归母净利(元), 累计, 去年同期累计) — 估值面失真修正 v1 输入"""
    df, err = ak_abstract(code)
    if df is None:
        return {"error": err or "abstract unavailable"}
    try:
        cols = [c for c in df.columns if c not in ('选项', '指标', '指标说明')]
        latest, prev = cols[0], cols[1]

        def np_of(col):
            for nm in ("归母净利润", "归属母公司净利润", "净利润"):
                row = df[df['指标'].astype(str).str.contains(nm, na=False)]
                if not row.empty:
                    try:
                        return float(row.iloc[0][col])
                    except Exception:
                        return None
            return None

        cum, prev_cum = np_of(latest), np_of(prev)
        if cum is None:
            return {"error": "np missing"}
        q = cum - (prev_cum or 0.0)
        return {"period": str(latest), "cum": cum, "prev_cum": prev_cum,
                "single_q": q, "single_q_loss": q < 0}
    except Exception as e:
        return {"error": str(e)[:80]}


def main_business(code):
    """主营业务 — akshare stock_zyjs_ths 主营构成 (取收入占比最高项)"""
    try:
        import akshare as ak
        df = ak.stock_zyjs_ths(symbol=code)
        if df is None or df.empty:
            return None
        cols = list(df.columns)
        item_col = next((c for c in cols if "项目" in c or "主营" in c), cols[0])
        val_col = next((c for c in cols if "收入-占比" in c or "占比" in c), None)
        recs = []
        for _, row in df.iterrows():
            name = str(row[item_col]).strip()
            if name in ("行业", "产品", "地区", "合计"):
                continue
            pct = row[val_col] if val_col and val_col in df.columns else None
            try:
                pct = float(pct)
            except Exception:
                pct = None
            recs.append((name, pct))
        recs = [r for r in recs if r[0] and r[0] != "nan"]
        if not recs:
            return None
        recs.sort(key=lambda x: (x[1] is not None, x[1] or 0), reverse=True)
        parts = [f"{n} {p:.2f}%" if p is not None else n for n, p in recs[:4]]
        return " / ".join(parts)
    except Exception as e:
        return {"error": str(e)[:80]}


def load_sector_stats():
    p = os.path.expanduser("~/code/AAna/data/rec_tuning.json")
    with open(p) as f:
        rt = json.load(f)
    return rt.get("sector_stats", {}), rt.get("overall_win_rate"), rt.get("total_records")


def analyze(code, name, v24s, stop, target, chg, sector_stats):
    print(f"--- {code} {name} (尾盘评分 {v24s}) ---", flush=True)
    try:
        q = ds.tencent_quote([code]).get(code, {})
    except Exception as e:
        q = {}
        print(f"  quote fail: {e}")
    price = q.get("price") or (target / 1.10)
    pe, pb = q.get("pe_ttm"), q.get("pb")

    try:
        kl = fetch_kline(code)
        ts_, tnotes, tstat = tech_score(kl, price)
    except Exception as e:
        ts_, tnotes, tstat = 25, [f"K线失败: {e}"], {}

    try:
        fs_, fnotes, fstat = fund_score(code)
    except Exception as e:
        fs_, fnotes, fstat = 10, [f"财务失败: {e}"], {}

    vs_raw, vnotes = val_score(pe, pb)

    try:
        ind_sina = ds.industry_for_code(code)
    except Exception:
        ind_sina = None
    try:
        ind_em = (ds.eastmoney_stock_info(code) or {}).get("industry") or None
    except Exception:
        ind_em = None
    print(f"  行业双源: sina[{ind_sina}] 东财[{ind_em}]")

    biz = main_business(code)

    # 估值面失真修正 v1 (10-28 PM 规则)
    sq = single_quarter_profit(code)
    ni_growth = fstat.get("ni_growth")
    distorted = bool(sq and sq.get("single_q_loss")
                     and ni_growth is not None and ni_growth < -50)
    if distorted:
        pb_score = 7 if (pb is not None and pb <= 3) else (4 if (pb is not None and pb <= 5) else 1)
        vs_adj = pb_score
        vnotes = list(vnotes) + [
            f"估值面失真修正: 单季归母 {sq['single_q']/1e8:.3f} 亿转亏 + 净利同比 {ni_growth:.0f}% "
            f"→ PE(TTM) {pe:.1f} 系峰值盈利滞后口径记 0 分, 只保留 PB"]
    else:
        vs_adj = vs_raw

    total = round(ts_ / 55 * 50 + fs_ / 30 * 30 + vs_adj / 15 * 20, 1)
    rating = rating_of(total)
    tgt_tech = tstat.get("hi20") if tstat.get("hi20") else price * 1.05
    tgt = round(min(target, max(tgt_tech, price * 1.05)), 2)

    stat_key = next((k for k in SECTOR_CANDIDATES.get(code, []) if k in sector_stats), None)
    sec = sector_stats.get(stat_key, {}) if stat_key else {}
    sec_wr = (f"{sec.get('win_rate'):.0f}% ({sec.get('win_count')}/{sec.get('count')})"
              if sec else "无记录(冷启动)")
    near_wr = ""
    for nk, nd in SECTOR_NEAR.get(code, []):
        ns = sector_stats.get(nk, {})
        if ns:
            near_wr += f" | {nd}[{nk}] {ns.get('win_rate'):.0f}% ({ns.get('win_count')}/{ns.get('count')})"

    rec = {"code": code, "name": name, "price": price, "pe_ttm": pe, "pb": pb,
           "mcap_yi": q.get("mcap_yi"), "float_mcap_yi": q.get("float_mcap_yi"),
           "turnover_pct": q.get("turnover_pct"), "vol_ratio": q.get("vol_ratio"),
           "v24_score": v24s, "ind_sina": ind_sina, "ind_em": ind_em,
           "business": (biz if isinstance(biz, str) else None),
           "tech_score": ts_, "fund_score": fs_, "val_score": vs_adj, "val_score_raw": vs_raw,
           "distorted": distorted,
           "single_quarter": (None if not sq or sq.get("error")
                              else {"period": sq.get("period"),
                                    "single_q_yi": round(sq.get("single_q", 0) / 1e8, 3),
                                    "single_q_loss": sq.get("single_q_loss")}),
           "total": total, "rating": rating, "target": tgt, "stop": stop,
           "tech_notes": tnotes, "fund_notes": fnotes, "val_notes": vnotes,
           "tech_stat": tstat, "fund_stat": fstat,
           "chg_pct": q.get("change_pct"), "chg_report": chg,
           "sector_stat_key": stat_key, "sector_win_rate": sec_wr,
           "sector_near": near_wr.strip(" |") if near_wr else None,
           "stop_broken": (stop is not None and price is not None and price < stop)}
    print(f"  现价 {price} ({q.get('change_pct')}%) PE {pe} PB {pb} 市值 {q.get('mcap_yi')} 亿")
    print(f"  技术面 {ts_}/55 基本面 {fs_}/30 估值 {vs_adj}/15"
          f"{'(修正前' + str(vs_raw) + ')' if distorted else ''} => {total} {rating} | 目标 {tgt} 止损 {stop}")
    print(f"  板块 {stat_key or '(无键)'} → 胜率 {sec_wr}{near_wr}")
    print(f"  主营: {rec['business']}")
    return rec


def main():
    sector_stats, overall_wr, total_rec = load_sector_stats()
    print("=" * 78)
    print(f"AAna 尾盘深度分析 — {TODAY} (周一 14:5x 盘中快照, 尾盘报告 14:47)")
    print(f"候选池 Top5 = {[c[0] for c in CANDIDATES]}")
    print(f"胜率库: {len(sector_stats)} 键 / {total_rec} 笔 / 整体 {overall_wr:.2f}%")
    print("=" * 78)

    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = [ex.submit(analyze, *c, sector_stats) for c in CANDIDATES]
        results = []
        for f in futs:
            try:
                results.append(f.result())
            except Exception as e:
                print(f"  单只失败跳过: {e}")

    results.sort(key=lambda x: (-x["total"], -x["v24_score"]))
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump({"date": TODAY, "generated": time.strftime("%H:%M:%S"),
                   "sector_stats_n": len(sector_stats), "overall_win_rate": overall_wr,
                   "results": results}, f, ensure_ascii=False, indent=1)
    print("\n=== 深度排名 (技术50% + 基本面30% + 估值20%) ===")
    for i, r in enumerate(results, 1):
        dist = " [失真修正]" if r["distorted"] else ""
        print(f"{i}. {r['code']} {r['name']} 深度评分 {r['total']} {r['rating']} "
              f"原评分 {r['v24_score']} 现价 {r['price']} 目标 {r['target']} 止损 {r['stop']}{dist}")
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()

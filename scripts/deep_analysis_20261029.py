#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-10-29 (周四交易日盘前 08:3x) — 亢奋修复日 · 候选池 4 只
当日报告 = reports/2026-10-29-选股报告.md (08:02 盘前版, 涨跌幅=昨收 10-28 周三收盘口径)
候选池 = 当日报告 Top10 表全部 4 只 (10-28 收盘 +4.62%~+4.99%, 报告综合分 70/69x3,
         与 10-28 早盘组 20261028 gid=1796 7 只池重合 4 只 — 池延续第 2 日)
方法: 复用 deep_analysis_20261022 评分引擎 (技术50% + 基本面30% + 估值20%)
      + 估值面失真修正 v1 (10-28 PM 新规则, 口径连续: 最新单季归母转亏 且 净利同比<-50%
        → PE_TTM 系峰值盈利滞后口径, PE 部分记 0 分只保留 PB)
      腾讯行情 + 腾讯日K(120d qfq, 末日 10-28) + akshare 财务摘要 + rec_tuning 板块胜率 (83 键 354 笔 48.9%)
铁律: 最值得购买者需基准交易日 10-28 当日胜出 (强于大盘平均 +1.79% 且居池内前列) + 正盈利
      + 深度评级 ≥增持(65) + 未破报告软止损 (10-24~27 先例: 聚集池内评分优先·如实披露涨幅排名)
P0 冰点守卫: 报告快照情绪 75 (亢奋) → 放行 (仓位 85%, ✅正常交易; 昨 10-28 已脱离冰点
      — 守卫短路 2 日后恢复, 10-28 14:45 尾盘 V 型修复 58→75)
Kimi: 本机无 kimi CLI / moonshot key (10-29 再复核: which kimi 无, env 无)
      — 连续第 14 日由 AAna 深度评分引擎 + LLM 定性层执行 (口径 10-16~10-28 连续)
行业映射: 东财 f127 接口逐股验证 (603683 其他化学制品 / 002242 小家电 / 000810 其它视听器材
          / 001233 轮胎)
T+1 复核: 昨 10-28 尾盘深度 Top5 (601689 拓普 69.0 增持→20261028PP gid=1801 / 603325 博隆 59.3
          / 600802 福建水泥 44.4 / 002792 通宇 39.8 / 002046 国机精工 36.8) 以 10-28 收盘快照验证
"""
import sys, os, json, re, time
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import data_sources as ds
from deep_analysis_20261022 import tech_score, fund_score, val_score, rating_of

TODAY = "2026-10-29"
BASE_DATE = "2026-10-28"   # K 线末日 / 昨收基准 (10-28 周三收盘)
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
TODAY_REPORT = os.path.join(REPORT_DIR, f"{TODAY}-选股报告.md")  # 周四 08:02 盘前版
OUT_JSON = os.path.expanduser(f"~/code/AAna/data/deep_analysis_{TODAY.replace('-','')}.json")
MK_AVG = 1.79           # 报告快照: 大盘平均涨跌 +1.79% (10-28 收盘基准)
SNAP = {"score": 75, "label": "亢奋", "zt_count": 70, "dt_count": 7, "position": 0.85}
RUN_ID = "01a18510-8e05-72de-8ab2-858b76f17331"

# 行业 (东财 f127 接口 10-29 逐股核验) → rec_tuning sector_stats (83 键 354 笔) 映射
# (industry 描述, 主键或 None 冷启动, [(邻近/概念键, 说明), ...])
SECTOR_MAP = {
    "603683": ("化学-其他化学制品(功能性胶粘材料/电子胶带)", "其他化学制品", []),
    "002242": ("家电-小家电(厨房小家电双品牌)", "小家电", []),
    "000810": ("家电-其它视听器材(机顶盒/宽带终端/VR)", None,
               [("显示器件", "邻近键-显示面板"), ("有线电视网络", "邻近键-广电网络")]),
    "001233": ("汽车-轮胎", None, [("汽车零部件", "邻近键-SW汽车产业链")]),
}

# 昨日 (10-28 14:47) 尾盘深度分析 Top5 — 今日 T+1 复核池 (10-28 收盘快照验证)
YDAY_PM_POOL = [
    {"code": "601689", "name": "拓普集团", "total": 69.0, "rating": "增持"},
    {"code": "603325", "name": "博隆技术", "total": 59.3, "rating": "中性"},
    {"code": "600802", "name": "福建水泥", "total": 44.4, "rating": "减持"},
    {"code": "002792", "name": "通宇通讯", "total": 39.8, "rating": "减持"},
    {"code": "002046", "name": "国机精工", "total": 36.8, "rating": "减持"},
]


def parse_top10_full(text):
    """解析 '🏆 重点关注 Top 10' 表格: 排名/名称/代码/价格/涨跌幅/技术分/综合分/软止损 (口径同 10-27/28)"""
    m = re.search(r'重点关注 Top 10(.*?)(?=\n###|\Z)', text, re.S)
    rows = []
    for line in (m.group(1) if m else text).split("\n"):
        ls = line.strip()
        if not ls.startswith("|") or ls.startswith("|:"):
            continue
        cells = [c.strip() for c in ls.strip("|").split("|")]
        if len(cells) >= 8 and re.fullmatch(r"\d{6}", cells[2]):
            try:
                rank = int(cells[0])
            except ValueError:
                continue
            name = re.sub(r'^[^一-龥A-Za-z0-9]+', '', cells[1])
            price = float(cells[3].replace('¥', '').replace(',', ''))
            chg = float(re.search(r'[+-]?\d+\.?\d*', cells[4]).group())
            tech = int(re.sub(r'\D', '', cells[5]) or 0)
            v24 = int(re.sub(r'\D', '', cells[7]) or 0)
            stop = (float(re.search(r'\d+\.?\d*', cells[10]).group())
                    if len(cells) > 10 and re.search(r'\d', cells[10]) else None)
            rows.append({"rank": rank, "code": cells[2], "name": name, "price": price,
                         "chg": chg, "tech": tech, "v24": v24, "stop": stop})
    return rows


def guard_check():
    """P0 冰点守卫 (单一真源 check_ice_point_guard)。盘前未开盘: live 源可能回退,
    以报告快照 75 亢奋为判定口径 (10-28 收盘情绪 → 10-29 盘前延续)"""
    from aana_afternoon_screen import check_ice_point_guard
    live = None
    try:
        live = check_ice_point_guard()
    except Exception as e:
        print(f"  live 情绪源异常(盘前未开盘): {e}")
    snap = check_ice_point_guard(sent={"score": SNAP["score"], "label": SNAP["label"],
                                       "zt_count": SNAP["zt_count"], "dt_count": SNAP["dt_count"]})
    return live, snap


def load_sector_stats():
    with open(os.path.expanduser("~/code/AAna/data/rec_tuning.json")) as f:
        rt = json.load(f)
    return rt.get("sector_stats", {}), rt.get("overall_win_rate"), rt.get("total_records")


def fetch_kline(code):
    """腾讯日K 120d qfq — fqkline qfq 端点 WAF 501 时降级 kline/kline 非复权 (10-26 PM 踩坑)"""
    import requests
    prefix = ds.get_prefix(code)
    sym = f"{prefix}{code}"
    for path, var in (("fqkline/get", "kline_dayqfq"), ("kline/kline", "kline_day")):
        try:
            url = f"https://web.ifzq.gtimg.cn/appstock/app/{path}?_var={var}&param={sym},day,,,120,qfq"
            r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            data = json.loads(re.search(r'=(.+)$', r.text.strip()).group(1))
            kl0 = data['data'][sym]
            kl = [[k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])]
                  for k in (kl0.get("qfqday") or kl0.get("day"))]
            if kl:
                return kl
        except Exception as e:
            last = e
    raise RuntimeError(f"K线获取失败: {last}")


def single_quarter_profit(code):
    """(最新季报期, 最新单季归母净利(元), 累计, 去年同期累计) — 估值面失真修正 v1 输入 (10-28 PM 规则)"""
    try:
        import akshare as ak
        df = ak.stock_financial_abstract(symbol=code)
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
            return None
        q = cum - (prev_cum or 0.0)
        return {"period": str(latest), "cum": cum, "prev_cum": prev_cum,
                "single_q": q, "single_q_loss": q < 0}
    except Exception as e:
        return {"error": str(e)[:80]}


def tencent_quotes(codes):
    """腾讯实时快照: 盘前=昨收口径。返回 {code: (现价, 涨跌幅%, 快照时间戳)}"""
    import requests
    syms = ",".join(("sh" if c.startswith(("6", "9")) else "sz") + c for c in codes)
    r = requests.get(f"https://qt.gtimg.cn/q={syms}", timeout=10,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.encoding = "gbk"
    out = {}
    for m in re.finditer(r'v_(?:sh|sz)(\d{6})="([^"]+)"', r.text):
        p = m.group(2).split("~")
        try:
            out[m.group(1)] = (float(p[3]), float(p[32]), p[30])
        except (ValueError, IndexError):
            continue
    return out


def main():
    print("=" * 78)
    print(f"AAna 深度分析 — {TODAY} (周四交易日盘前, 数据基准 {BASE_DATE} 收盘)")
    print(f"Run: autopilot ca411dd3 深度分析 {RUN_ID}")
    print("=" * 78)
    sz = os.path.getsize(TODAY_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(TODAY_REPORT)))
    print(f"📄 当日报告: {TODAY_REPORT}")
    print(f"   大小: {sz} 字节 | 修改: {mt} (周四交易日 08:02 盘前版, 昨收=10-28 周三收盘口径)")
    text = open(TODAY_REPORT).read()
    pool = parse_top10_full(text)
    # 双重校验: 表区间内含 6 位代码的数据行原始计数 (防解析器误判, 10-28 口径)
    m = re.search(r'重点关注 Top 10(.*?)(?=\n###|\Z)', text, re.S)
    raw_rows = [l for l in (m.group(1) if m else "").split("\n")
                if l.strip().startswith("|") and re.search(r'\d{6}', l)
                and not l.strip().startswith("|:")]
    print(f"   当日 Top10 表: {len(pool)} 只 (原始数据行 {len(raw_rows)} 行) → 候选池 = {len(pool)} 只")
    for p in pool:
        print(f"     #{p['rank']} {p['code']} {p['name']} ¥{p['price']} {p['chg']:+.2f}% "
              f"报告分{p['v24']} 技术分{p['tech']} 软止损{p['stop']}")
    snap_sent = (f"情绪{SNAP['score']}({SNAP['label']}) 仓位{SNAP['position']*100:.0f}% "
                 f"大盘平均{MK_AVG}% 涨停{SNAP['zt_count']}/跌停{SNAP['dt_count']} "
                 f"交易建议✅正常交易")
    print(f"   报告快照 (10-28 收盘口径): {snap_sent}")

    sector_stats, overall_wr, n_rec = load_sector_stats()
    print(f"📊 板块胜率库 (rec_optimizer 口径): {len(sector_stats)} 板块 | 整体胜率 {overall_wr:.1f}% ({n_rec} 笔)")

    live, snap = guard_check()
    print(f"🛡 P0 冰点守卫: 快照口径 情绪{snap['sentiment_score']}({snap['sentiment_label']}) "
          f"仓位{snap['position_ratio']*100:.0f}% is_ice_point={snap['is_ice_point']}")
    if snap.get("reason"):
        print(f"   短路原因: {snap['reason']}")
    if live:
        print(f"   live 口径 情绪{live['sentiment_score']}({live['sentiment_label']}) "
              f"is_ice_point={live['is_ice_point']} (盘前未开盘, 披露用)")
    ice = snap["is_ice_point"]

    # ---- 昨日 (10-28) 尾盘深度 Top5 T+1 复核 (10-28 收盘, 腾讯快照) ----
    codes5 = [r["code"] for r in YDAY_PM_POOL]
    q5 = tencent_quotes(codes5)
    review = []
    for r in YDAY_PM_POOL:
        px, chg, ts = q5.get(r["code"], (None, None, ""))
        review.append({**r, "close": px, "chg_pct": chg, "quote_ts": ts,
                       "beat_mkt": (chg is not None and chg > MK_AVG)})
    review.sort(key=lambda x: (x["chg_pct"] if x["chg_pct"] is not None else -99), reverse=True)
    print(f"\n=== 昨日尾盘深度 Top5 T+1 复核 ({BASE_DATE} 收盘, 腾讯快照口径) ===")
    for i, r in enumerate(review, 1):
        ts = r['quote_ts'][:8]
        print(f"{i}. {r['code']} {r['name']} 深度{r['total']}{r['rating']} "
              f"| 10-28 实收 {r['chg_pct']:+.2f}% ({'✅胜大盘' if r['beat_mkt'] else '❌弱于大盘'})"
              f" | 快照日 {ts}")
    n_beat = sum(1 for r in review if r["beat_mkt"])
    n_pos = sum(1 for r in review if (r["chg_pct"] or 0) > 0)
    print(f"胜大盘({MK_AVG}%): {n_beat}/{len(review)} | 正盈利: {n_pos}/{len(review)}")
    ytop_r = next((r for r in review if r["code"] == "601689"), None)
    if ytop_r:
        print(f"🏁 昨日尾盘 Top1 {ytop_r['code']} {ytop_r['name']} 铁律复核: 10-28 实收 "
              f"{ytop_r['chg_pct']:+.2f}% vs 大盘 {MK_AVG}% → 超额 {ytop_r['chg_pct']-MK_AVG:+.2f}pp "
              f"{'✅ 当日胜出+正盈利' if (ytop_r['beat_mkt'] and ytop_r['chg_pct']>0) else '❌'}")

    # ---- 逐股深度评分 ----
    results = []
    for p in pool:
        code, name, v24s, stop = p["code"], p["name"], p["v24"], p["stop"]
        print(f"--- {code} {name} (报告#{p['rank']} 报告分{v24s}) ---", flush=True)
        try:
            q = ds.tencent_quote([code]).get(f"{code}", {})
        except Exception as e:
            q = {}; print(f"  quote fail: {e}")
        price = q.get("price") or p["price"]
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

        # 估值面失真修正 v1 (10-28 PM 规则, 口径连续)
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
        target = round(max(price * 1.05, tstat.get("hi20") or price * 1.05), 2)
        industry, stat_key, nears = SECTOR_MAP.get(code, (None, None, []))
        sec = sector_stats.get(stat_key, {}) if stat_key else {}
        sec_wr = (f"{sec.get('win_rate'):.0f}% ({sec.get('win_count')}/{sec.get('count')})"
                  if sec else "无记录(冷启动)")
        near_wr = ""
        for nk, nd in nears:
            ns = sector_stats.get(nk, {})
            if ns:
                near_wr += f" | {nd}[{nk}] {ns.get('win_rate'):.0f}% ({ns.get('win_count')}/{ns.get('count')})"
        chg = tstat.get("chg_1d", p["chg"]) or p["chg"]
        rec = {"code": code, "name": name, "rank": p["rank"], "price": price,
               "pe_ttm": pe, "pb": pb, "mcap_yi": q.get("mcap_yi"),
               "float_mcap_yi": q.get("float_mcap_yi"), "turnover_pct": q.get("turnover_pct"),
               "vol_ratio": q.get("vol_ratio"), "v24_score": v24s, "report_tech": p["tech"],
               "tech_score": ts_, "fund_score": fs_, "val_score": vs_adj, "val_score_raw": vs_raw,
               "distorted": distorted, "single_quarter": (None if not sq or sq.get("error")
                                                          else {"period": sq.get("period"),
                                                                "single_q_yi": round(sq.get("single_q", 0) / 1e8, 3),
                                                                "single_q_loss": sq.get("single_q_loss")}),
               "total": total, "rating": rating, "target": target, "stop": stop,
               "tech_notes": tnotes, "fund_notes": fnotes, "val_notes": vnotes,
               "tech_stat": tstat, "fund_stat": fstat,
               "chg_pct": chg, "chg_date": tstat.get("last_date"),
               "beat_mkt": chg > MK_AVG,
               "industry": industry, "sector_stat_key": stat_key, "sector_win_rate": sec_wr,
               "sector_near": near_wr.strip(" |") if near_wr else None,
               "stop_broken": (stop is not None and price is not None and price < stop)}
        results.append(rec)
        print(f"  {BASE_DATE} 涨跌 {chg:+.2f}% (K线末日 {tstat.get('last_date')}, K线 {tstat.get('kline_len')} 根) "
              f"{'✅胜大盘(+1.79%)' if chg > MK_AVG else '❌弱于大盘'}")
        print(f"  技术面 {ts_}/55 基本面 {fs_}/30 估值 {vs_adj}/15"
              f"{'(修正前'+str(vs_raw)+')' if distorted else ''} => {total} {rating} | 止损 {stop} "
              f"{'🔴已破' if rec['stop_broken'] else '未破'}")
        print(f"  板块: {industry} → 胜率 {sec_wr}{near_wr}")
        time.sleep(0.4)

    # 铁律合成: 正盈利 + 强于大盘(胜出) + 评级≥增持 + 未破止损 + 守卫放行
    by_chg = sorted(results, key=lambda x: -(x["chg_pct"] or 0))
    for i, r in enumerate(by_chg, 1):
        next(r2 for r2 in results if r2["code"] == r["code"])["chg_rank"] = i
    positive = [r for r in results if (r["chg_pct"] or 0) > 0]
    eligible = [r for r in results
                if (r["chg_pct"] or 0) > 0 and r.get("beat_mkt")
                and r["total"] >= 65 and not r["stop_broken"] and not ice]
    eligible.sort(key=lambda x: (-x["total"], -x["v24_score"], -(x["chg_pct"] or 0)))
    recommend = eligible[0] if eligible else None
    results.sort(key=lambda x: (-x["total"], -x["v24_score"], -(x["chg_pct"] or 0)))

    with open(OUT_JSON, "w") as f:
        json.dump({"date": TODAY, "base_date": BASE_DATE, "report": TODAY_REPORT,
                   "report_size": sz, "report_mtime": mt,
                   "generated": time.strftime("%H:%M:%S"),
                   "sentiment_snap": SNAP, "mk_avg": MK_AVG,
                   "overall_win_rate": overall_wr, "total_records": n_rec,
                   "sector_count": len(sector_stats),
                   "guard_ice": ice, "run_id": RUN_ID,
                   "yesterday_review": {"source": "10-28 尾盘深度分析 Top5",
                                        "verified_on": BASE_DATE,
                                        "n_beat_mkt": n_beat, "n_positive": n_pos,
                                        "results": review},
                   "recommend": ({"code": recommend["code"], "name": recommend["name"],
                                  "total": recommend["total"], "rating": recommend["rating"],
                                  "chg_pct": recommend["chg_pct"],
                                  "chg_rank": recommend.get("chg_rank"),
                                  "sector_win_rate": recommend["sector_win_rate"],
                                  "industry": recommend["industry"]}
                                 if recommend else None),
                   "results": results}, f, ensure_ascii=False, indent=1)

    print("\n=== 深度排名 (技术50%+基本面30%+估值20%, 含失真修正) ===")
    for i, r in enumerate(results, 1):
        pos = "✅正盈利" if (r["chg_pct"] or 0) > 0 else "❌"
        dist = " [失真修正]" if r["distorted"] else ""
        print(f"{i}. {r['code']} {r['name']} 深度评分 {r['total']} {r['rating']}{dist} "
              f"| {BASE_DATE} {r['chg_pct']:+.2f}% 池内#{r.get('chg_rank')} {pos} "
              f"| 板块 {r['industry']} 胜率 {r['sector_win_rate']}")
    print(f"\n正盈利: {len(positive)}/{len(results)} | 强于大盘(+1.79%): {sum(1 for r in results if r.get('beat_mkt'))}/{len(results)}")
    print(f"铁律合格池 (≥增持+正盈利+胜出+未破止损+守卫放行): {[(r['code'], r['name'], r['total']) for r in eligible]}")
    if recommend:
        print(f"\n🏁 最值得购买: {recommend['code']} {recommend['name']} (深度 {recommend['total']} {recommend['rating']}, "
              f"{BASE_DATE} {recommend['chg_pct']:+.2f}% 池内#{recommend.get('chg_rank')}) → 同步东财 {TODAY.replace('-','')}ZZ")
    else:
        print("\n🏁 0 推荐 → 不创建东财组合")
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()

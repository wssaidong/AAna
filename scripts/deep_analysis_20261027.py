#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-10-27 (周二交易日盘前 08:3x) —
当日报告 = reports/2026-10-27-选股报告.md (08:02 盘前生成, 9320 字节)
早盘副标题口径: 报告"涨跌幅"=昨收(10-26 周一收盘)涨跌幅, 08:3x 未开盘无今日实时数据
候选池 = 当日报告 Top10 表全部 8 只 (10-26 收盘 +1.89%~+4.94%, 报告综合分 65x5/64x3)
方法: 复用 deep_analysis_20261022 评分引擎 (技术50% + 基本面30% + 估值20%, 口径与 10-16~10-26 连续一致)
      腾讯行情 + 腾讯日K(120d qfq, 末日 10-26) + akshare 财务摘要 + rec_tuning 板块胜率 (69 键 295 笔 39.7%)
铁律: 最值得购买者需基准交易日 10-26 当日胜出 (强于大盘平均 -0.69% 且居池内前列) + 正盈利
      + 深度评级 ≥增持(65) + 未破报告软止损 (10-24~26 先例: 聚集池内评分优先·如实披露涨幅排名)
P0 冰点守卫: 报告快照情绪 45 (分歧) → 放行 (分歧非冰点标签, 仓位 50% ≥ 10%, 周二盘前 live 源未开盘以快照为判定口径)
Kimi: 本机无 kimi CLI / moonshot key (10-26 复核 14 agent 无 kimi runtime, 10-27 再复核一次)
      — 连续第 12 日由 AAna 深度评分引擎 + LLM 定性层执行 (口径 10-16~10-26 连续)
行业映射: 东财 f127 接口逐股验证 (600085 中药Ⅱ / 603883 医药商业 / 603707 化学制药 / 601857 炼化及贸易
          / 002362 软件开发 (汉王非"计算机设备", 行业消歧) / 603882 医疗服务 / 002233 水泥制造 / 002265 汽车零部件)
"""
import sys, os, json, re, time

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import data_sources as ds
from deep_analysis_20261022 import tech_score, fund_score, val_score, rating_of

TODAY = "2026-10-27"
BASE_DATE = "2026-10-26"
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
TODAY_REPORT = os.path.join(REPORT_DIR, f"{TODAY}-选股报告.md")  # 周二交易日当日报告 (08:02 盘前版)
OUT_JSON = os.path.expanduser(f"~/code/AAna/data/deep_analysis_{TODAY.replace('-','')}.json")
MK_AVG = -0.69  # 报告快照: 大盘平均涨跌 -0.69% (10-26 收盘基准, 当日胜出口径)

# 行业 (state/industry_cache.json + 东财 f127 接口核对) → rec_tuning sector_stats (69 键) 映射
# (industry 描述, 主键或 None 冷启动, [(邻近/概念键, 说明), ...])
SECTOR_MAP = {
    "600085": ("医药-中药Ⅱ(老字号独家中成药)", "中药", []),
    "603883": ("医药-医药商业(全国连锁药店龙头)", "医药商业", []),
    "603707": ("医药-化学制药(肝素原料药+制剂)", None, []),
    "601857": ("石油石化-炼化及贸易(一体化油气龙头)", None,
               [("energy", "概念键-能源"), ("煤炭开采", "邻近键-传统能源")]),
    "603882": ("医药-医疗服务(ICL独立医学实验室龙头)", None, []),
    "002362": ("计算机-软件开发(AI/OCR/DeepSeek概念)", "软件开发", [("ai_app", "概念键-AI应用")]),
    "002233": ("建材-水泥制造(华南区域水泥)", "水泥制造", []),
    "002265": ("汽车-汽车零部件(连杆龙头+军品)", "汽车零部件", []),
}


def parse_top10_full(text):
    """解析 '🏆 重点关注 Top 10' 表格: 排名/名称/代码/价格/涨跌幅/技术分/综合分/软止损"""
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
    """P0 冰点守卫 (单一真源 check_ice_point_guard)。盘前未开盘: live 源可能回退, 以报告快照 45 分歧为判定口径"""
    from aana_afternoon_screen import check_ice_point_guard
    live = None
    try:
        live = check_ice_point_guard()
    except Exception as e:
        print(f"  live 情绪源异常(盘前未开盘): {e}")
    snap = check_ice_point_guard(sent={"score": 45, "label": "分歧", "zt_count": 59, "dt_count": 6})
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


def main():
    print("=" * 78)
    print(f"AAna 深度分析 — {TODAY} (周二交易日盘前, 数据基准 {BASE_DATE})")
    print("Run: autopilot ca411dd3 深度分析 01a17ac4-0c8b-7be3-adaa-97f809332b3f")
    print("=" * 78)
    sz = os.path.getsize(TODAY_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(TODAY_REPORT)))
    print(f"📄 当日报告: {TODAY_REPORT}")
    print(f"   大小: {sz} 字节 | 修改: {mt} (周二交易日 08:02 盘前版, 昨收=10-26 周一收盘口径, 全新池 8 只)")
    pool = parse_top10_full(open(TODAY_REPORT).read())
    print(f"   当日 Top10 表: {len(pool)} 只 → 候选池 = 全部 {len(pool)} 只")
    for p in pool:
        print(f"     #{p['rank']} {p['code']} {p['name']} ¥{p['price']} {p['chg']:+.2f}% "
              f"报告分{p['v24']} 技术分{p['tech']} 软止损{p['stop']}")

    sector_stats, overall_wr, n_rec = load_sector_stats()
    print(f"📊 板块胜率库 (10-26 20:00 rec_optimizer 口径): {len(sector_stats)} 板块 | 整体胜率 {overall_wr:.1f}% ({n_rec} 笔)")

    live, snap = guard_check()
    print(f"🛡 P0 冰点守卫: 快照口径 情绪{snap['sentiment_score']}({snap['sentiment_label']}) "
          f"仓位{snap['position_ratio']*100:.0f}% is_ice_point={snap['is_ice_point']}")
    if live:
        print(f"   live 口径 情绪{live['sentiment_score']}({live['sentiment_label']}) "
              f"is_ice_point={live['is_ice_point']} (盘前未开盘, 披露用)")
    ice = snap["is_ice_point"]

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
            ts, tnotes, tstat = tech_score(kl, price)
        except Exception as e:
            ts, tnotes, tstat = 25, [f"K线失败: {e}"], {}
        try:
            fs, fnotes, fstat = fund_score(code)
        except Exception as e:
            fs, fnotes, fstat = 10, [f"财务失败: {e}"], {}
        vs, vnotes = val_score(pe, pb)
        total = round(ts / 55 * 50 + fs / 30 * 30 + vs / 15 * 20, 1)
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
               "tech_score": ts, "fund_score": fs, "val_score": vs,
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
              f"{'✅胜大盘(-0.69%)' if chg > MK_AVG else '❌弱于大盘'}")
        print(f"  技术面 {ts}/55 基本面 {fs}/30 估值 {vs}/15 => {total} {rating} | 止损 {stop} "
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
                   "sentiment_snap": {"score": 45, "label": "分歧", "position": 0.5},
                   "guard_ice": ice, "mk_avg": MK_AVG,
                   "overall_win_rate": overall_wr, "total_records": n_rec,
                   "recommend": ({"code": recommend["code"], "name": recommend["name"],
                                  "total": recommend["total"], "rating": recommend["rating"],
                                  "chg_pct": recommend["chg_pct"],
                                  "chg_rank": recommend.get("chg_rank")}
                                 if recommend else None),
                   "results": results}, f, ensure_ascii=False, indent=1)

    print("\n=== 深度排名 (技术50%+基本面30%+估值20%) ===")
    for i, r in enumerate(results, 1):
        pos = "✅正盈利" if (r["chg_pct"] or 0) > 0 else "❌"
        print(f"{i}. {r['code']} {r['name']} 深度评分 {r['total']} {r['rating']} "
              f"| {BASE_DATE} {r['chg_pct']:+.2f}% 池内#{r.get('chg_rank')} {pos} "
              f"| 板块 {r['industry']} 胜率 {r['sector_win_rate']}")
    print(f"\n正盈利: {len(positive)}/{len(results)} | 强于大盘(-0.69%): {sum(1 for r in results if r.get('beat_mkt'))}/{len(results)}")
    print(f"铁律合格池 (≥增持+正盈利+胜出+未破止损+守卫放行): {[(r['code'], r['name'], r['total']) for r in eligible]}")
    if recommend:
        print(f"\n🏁 最值得购买: {recommend['code']} {recommend['name']} (深度 {recommend['total']} {recommend['rating']}, "
              f"{BASE_DATE} {recommend['chg_pct']:+.2f}% 池内#{recommend.get('chg_rank')}) → 同步东财 20261027ZZ")
    else:
        print("\n🏁 0 推荐")
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()

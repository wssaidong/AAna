#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-10-24 (周六非交易日复盘, 下一交易日 10-26 周一备选) —
当日报告 = 最新选股报告 reports/2026-10-23-选股报告.md (17:01:59 盘后重生成版, 8025 字节)
Top10 恢复 10 只 (10-23 情绪 90 亢奋 V 型反转: 上证 +0.89% 收 3690.48, 涨停 84/跌停 8, 仓位 85% 正常交易)
→ 满足 10-23 深度分析设定的恢复条件 (情绪 ≥45 且当日 Top10 恢复有票) — 恢复正常推荐链路
候选池 = 当日报告 Top10 全部 10 只 (10-23 涨跌幅 +4.16%~+4.73% 全正盈利, 报告综合分 70/69/69/65/64/62x5)
方法: 复用 deep_analysis_20261022 评分引擎 (技术50% + 基本面30% + 估值20%, 口径与 10-16~10-23 连续一致)
      腾讯行情 + 腾讯日K(120d qfq, 末日 10-23) + akshare 财务摘要 + rec_tuning 板块胜率 (67 键 293 笔 39.9%)
铁律: 最值得购买者需基准交易日 10-23 当日胜出 (强于大盘平均 +2.39% 且居池内前列) + 正盈利
      + 深度评级 ≥增持(65) + 未破报告软止损 (10-22 先例: 聚集池内评分优先·如实披露涨幅排名)
P0 冰点守卫: 报告快照情绪 90 (亢奋) → 放行 (周六未开盘 live 源回退, 以快照为判定口径, 同 10-23 先例)
Kimi: multica 平台未注册 kimi runtime (10-24 复核 agent list 14 个 agent 无 kimi), 本机无 kimi CLI / moonshot key
      — 连续第 9 日由 AAna 深度评分引擎 + LLM 定性层执行 (口径 10-16~10-23 连续)
"""
import sys, os, json, re, time

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import data_sources as ds
from deep_analysis_20261022 import tech_score, fund_score, val_score, rating_of

TODAY = "2026-10-24"
BASE_DATE = "2026-10-23"
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
TODAY_REPORT = os.path.join(REPORT_DIR, f"{BASE_DATE}-选股报告.md")  # 周六无当日报告 → 最新选股报告
OUT_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_20261024.json")
MK_AVG = 2.39  # 10-23 报告快照: 大盘平均涨跌 +2.39% (当日胜出口径基准)

# 行业 (state/industry_cache.json + 人工核对) → rec_tuning sector_stats (67 键) 映射
# (industry 描述, 主键或 None 冷启动, [(邻近/概念键, 说明), ...])
SECTOR_MAP = {
    "600570": ("金融IT-软件开发", "软件开发", []),
    "002956": ("食品-食品综合(燕麦健康食品)", "食品综合", []),
    "002351": ("消费电子-电子系统组装(音频设备)", None, []),
    "600825": ("传媒-平面媒体(出版发行)", None, []),
    "002696": ("农业-水产养殖", None, [("农林牧渔", "邻近键")]),
    "603960": ("机械-其它专用机械(汽车管路+机器人装备)", None, [("mach", "邻近键"), ("robot", "概念键")]),
    "600885": ("电力设备-低压设备(继电器全球龙头)", "高低压设备", []),
    "600571": ("计算机-IT服务(金融IT+AI应用)", None, [("ai_app", "概念键")]),
    "603725": ("化工-其他化学制品(家居饰面材料)", "其他化学制品", []),
    "600592": ("机械-机械基础件(关节轴承/人形机器人)", None, [("mach", "邻近键"), ("robot", "概念键")]),
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
            name = re.sub(r'^[^\u4e00-\u9fa5A-Za-z0-9]+', '', cells[1])
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
    """P0 冰点守卫 (单一真源 check_ice_point_guard)。周六未开盘: live 源回退, 以报告快照 90 为判定口径"""
    from aana_afternoon_screen import check_ice_point_guard
    live = None
    try:
        live = check_ice_point_guard()
    except Exception as e:
        print(f"  live 情绪源异常(周六未开盘): {e}")
    snap = check_ice_point_guard(sent={"score": 90, "label": "亢奋", "zt_count": 84, "dt_count": 8})
    return live, snap


def load_sector_stats():
    with open(os.path.expanduser("~/code/AAna/data/rec_tuning.json")) as f:
        rt = json.load(f)
    return rt.get("sector_stats", {}), rt.get("overall_win_rate"), rt.get("total_records")


def main():
    print("=" * 78)
    print(f"AAna 深度分析 — {TODAY} (周六复盘, 数据基准 {BASE_DATE}, 下一交易日 10-26 备选)")
    print("Run: autopilot ca411dd3 深度分析 01a16b50-f23c-7328-a1c5-7e07ccd6a1e0")
    print("=" * 78)
    sz = os.path.getsize(TODAY_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(TODAY_REPORT)))
    print(f"📄 当日报告: {TODAY_REPORT}")
    print(f"   大小: {sz} 字节 | 修改: {mt} (周六非交易日 → 取最新选股报告)")
    pool = parse_top10_full(open(TODAY_REPORT).read())
    print(f"   当日 Top10: {len(pool)} 只 → 候选池 = 全部 {len(pool)} 只")
    for p in pool:
        print(f"     #{p['rank']} {p['code']} {p['name']} ¥{p['price']} {p['chg']:+.2f}% "
              f"报告分{p['v24']} 技术分{p['tech']} 软止损{p['stop']}")

    sector_stats, overall_wr, n_rec = load_sector_stats()
    print(f"📊 板块胜率库 (10-23 20:00 rec_optimizer 口径): {len(sector_stats)} 板块 | 整体胜率 {overall_wr:.1f}% ({n_rec} 笔)")

    live, snap = guard_check()
    print(f"🛡 P0 冰点守卫: 快照口径 情绪{snap['sentiment_score']}({snap['sentiment_label']}) "
          f"仓位{snap['position_ratio']*100:.0f}% is_ice_point={snap['is_ice_point']}")
    if live:
        print(f"   live 口径 情绪{live['sentiment_score']}({live['sentiment_label']}) "
              f"is_ice_point={live['is_ice_point']} (周六未开盘, 披露用)")
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
            prefix = ds.get_prefix(code)
            import requests
            url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
                   f"?_var=kline_dayqfq&param={prefix}{code},day,,,120,qfq")
            r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            data = json.loads(re.search(r'=(.+)$', r.text.strip()).group(1))
            kl0 = data['data'][f"{prefix}{code}"]
            kl = [[k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])]
                  for k in (kl0.get("qfqday") or kl0.get("day"))]
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
              f"{'✅胜大盘(+2.39%)' if chg > MK_AVG else '❌弱于大盘'}")
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
                   "sentiment_snap": {"score": 90, "label": "亢奋", "position": 0.85},
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
    print(f"\n正盈利: {len(positive)}/{len(results)} | 强于大盘(+2.39%): {sum(1 for r in results if r.get('beat_mkt'))}/{len(results)}")
    print(f"铁律合格池 (≥增持+正盈利+胜出+未破止损+守卫放行): {[(r['code'], r['name'], r['total']) for r in eligible]}")
    if recommend:
        print(f"\n🏁 最值得购买: {recommend['code']} {recommend['name']} (深度 {recommend['total']} {recommend['rating']}, "
              f"{BASE_DATE} {recommend['chg_pct']:+.2f}% 池内#{recommend.get('chg_rank')}) → 同步东财 20261024ZZ")
    else:
        print("\n🏁 0 推荐")
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()

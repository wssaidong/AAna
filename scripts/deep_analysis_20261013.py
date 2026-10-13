#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-10-13 (周二) — 基于 v2.4 尾盘推荐 Top5 (14:45 生成)
候选源: reports/2026-10-13-v24-尾盘推荐.md
评分模型: 复用 deep_analysis_20261007 6 维评分 (板块40% + 财务30% + 估值15% + 技术面10% + 业务面5%)
输出: reports/2026-10-13-深度分析-{code}.md × N + reports/2026-10-13-deep-analysis-data-v24.json
单只失败兜底: 跳过该只继续, 不阻塞整体
"""
import sys
import os
import json
import time
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data_sources as ds
from deep_analysis_20261007 import map_to_phase10_sector, get_phase10_winrate, calc_composite_score

TODAY = "2026-10-13"
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")

CANDIDATES = [
    {"code": "600026", "name": "中远海能", "v24_price": 22.70, "v24_score": 100, "stop": 21.11},
    {"code": "002962", "name": "五方光电", "v24_price": 14.19, "v24_score": 98, "stop": 13.20},
    {"code": "002528", "name": "*ST英飞", "v24_price": 6.19, "v24_score": 93, "stop": 5.76},
    {"code": "603696", "name": "安记食品", "v24_price": 13.69, "v24_score": 88, "stop": 12.73},
    {"code": "601890", "name": "亚星锚链", "v24_price": 9.42, "v24_score": 88, "stop": 8.76},
]


def get_kline(code, days=60):
    prefix = ds.get_prefix(code)
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?_var=kline_dayqfq&param={prefix}{code},day,,,{days},qfq")
    resp = requests.get(url, timeout=10,
                        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})
    m = resp.text.index("=")
    data = json.loads(resp.text[m + 1:])
    node = data["data"][f"{prefix}{code}"]
    return node.get("qfqday") or node.get("day") or []


def kline_metrics(klines, price_now):
    closes = [float(k[2]) for k in klines]
    highs = [float(k[3]) for k in klines]
    lows = [float(k[4]) for k in klines]
    if not closes:
        return {}
    ma5 = sum(closes[-5:]) / 5
    ma20 = sum(closes[-20:]) / min(20, len(closes))
    high20 = max(highs[-20:])
    low20 = min(lows[-20:])
    chg_60d = (closes[-1] / closes[0] - 1) * 100 if closes[0] else 0
    # MACD (12/26/9)
    ema12 = closes[0]
    ema26 = closes[0]
    dif_list = []
    for c in closes:
        ema12 = ema12 * 11 / 13 + c * 2 / 13
        ema26 = ema26 * 25 / 27 + c * 2 / 27
        dif_list.append(ema12 - ema26)
    dea = dif_list[0]
    for d in dif_list:
        dea = dea * 8 / 10 + d * 2 / 10
    dif = dif_list[-1]
    # 连阳统计 (最近5日)
    up5 = sum(1 for i in range(max(1, len(closes) - 5), len(closes)) if closes[i] > closes[i - 1])
    return {
        "ma5": round(ma5, 2), "ma20": round(ma20, 2),
        "above_ma20": price_now > ma20, "above_ma5": price_now > ma5,
        "high20": round(high20, 2), "low20": round(low20, 2),
        "vs_high20_pct": round((price_now / high20 - 1) * 100, 2) if high20 else None,
        "chg_60d_pct": round(chg_60d, 2),
        "macd_dif": round(dif, 3), "macd_dea": round(dea, 3),
        "macd_golden": dif > dea,
        "up_days_last5": up5,
        "kline_days": len(closes),
    }


def get_financial(code):
    import akshare as ak
    df = ak.stock_financial_abstract(symbol=code)
    out = {}
    for kw, label in [("净资产收益率(ROE)", "ROE"), ("销售毛利率", "毛利率"),
                      ("营业总收入", "营收"), ("净利润", "净利润")]:
        row = df[df["指标"] == kw]
        if not row.empty:
            for col in ("20260630", "20260331", "20251231"):
                if col in df.columns:
                    v = row.iloc[0].get(col)
                    if v is not None and v == v:
                        try:
                            out[label] = float(v)
                            out[label + "_raw"] = f"{float(v) / 1e8:.2f} 亿" if abs(float(v)) > 1e6 else str(v)
                            out[label + "_期"] = col
                            break
                        except (ValueError, TypeError):
                            pass
    return out


def rating_of(score, name):
    if "ST" in name:
        return "减持"
    if score >= 60:
        return "买入"
    if score >= 45:
        return "增持"
    if score >= 30:
        return "中性"
    return "减持"


def main():
    codes = [c["code"] for c in CANDIDATES]
    print(f"[1/5] 实时行情 {len(codes)} 只...")
    quotes = ds.tencent_quote(codes)
    print(f"[2/5] 行业归属...")
    industries = ds.industry_for_codes(codes)
    print(f"[3/5] 日K技术面...")
    klines_map = {}
    for c in CANDIDATES:
        try:
            klines_map[c["code"]] = kline_metrics(get_kline(c["code"]),
                                                  quotes.get(c["code"], {}).get("price", c["v24_price"]))
        except Exception as e:
            print(f"  [warn] {c['code']} K线失败: {e}")
            klines_map[c["code"]] = {}
    print(f"[4/5] 财务摘要...")
    fin_map = {}
    for code in codes:
        try:
            fin_map[code] = get_financial(code)
        except Exception as e:
            print(f"  [warn] {code} 财务失败: {e}")
            fin_map[code] = {}

    print(f"[5/5] 6维评分 + 生成报告...")
    results = []
    for c in CANDIDATES:
        code = c["code"]
        try:
            q = quotes.get(code, {})
            fin = fin_map.get(code, {})
            industry = industries.get(code, "unknown")
            sector = map_to_phase10_sector(industry)
            wr, samples, avg_chg = get_phase10_winrate(sector)
            score = calc_composite_score(q, fin, industry, sector)
            flags = []
            if "ST" in c["name"]:
                score -= 20
                flags.append("ST风险警示(用户禁区,禁止推荐)")
            if sector in ("elec", "semi", "chem", "mach"):
                flags.append(f"板块黑名单 {sector} (胜率{wr}%)")
            kl = klines_map.get(code, {})
            price = q.get("price") or c["v24_price"]
            target = round(max((kl.get("high20") or price) * 0.98, price * 1.04), 2)
            rating = rating_of(score, c["name"])
            results.append({
                "code": code, "name": c["name"], "price": price,
                "change_pct": q.get("change_pct", 0), "pe_ttm": q.get("pe_ttm"),
                "pb": q.get("pb"), "mcap_yi": q.get("mcap_yi"),
                "v24_price": c["v24_price"], "v24_score": c["v24_score"],
                "stop": c["stop"], "target": target,
                "industry": industry, "sector": sector,
                "sector_winrate": wr, "sector_samples": samples,
                "fin": {k: v for k, v in fin.items()},
                "kline": kl, "flags": flags,
                "deep_score": round(score, 2), "rating": rating,
            })
        except Exception as e:
            print(f"  [warn] {code} 深度分析失败, 跳过: {e}")

    results.sort(key=lambda x: (x["deep_score"],
                                {"买入": 4, "增持": 3, "中性": 2, "减持": 1}[x["rating"]]), reverse=True)

    for i, r in enumerate(results, 1):
        md = []
        md.append(f"# 深度分析 · {r['name']} ({r['code']}) · {TODAY}")
        md.append("")
        md.append(f"> 候选来源: 2026-10-13 v2.4 尾盘推荐 (14:45) · 排名第 {i} · 生成时间 {TODAY} 14:4x-15:00 · 目标事件: {TODAY} 尾盘/T+1 开盘")
        md.append("")
        md.append("| 项目 | 值 |")
        md.append("|:---|:---|")
        md.append(f"| 投资评级 | **{r['rating']}** |")
        md.append(f"| 综合评分 | **{r['deep_score']}** / 100 |")
        md.append(f"| 现价 | ¥{r['price']} ({r['change_pct']:+.2f}%) |")
        md.append(f"| 目标价 | ¥{r['target']} |")
        md.append(f"| 止损价 | ¥{r['stop']} (v2.4, ≈-7%) |")
        md.append(f"| v2.4 原评分 | {r['v24_score']} |")
        md.append(f"| 行业 | {r['industry']} → Phase10 板块 {r['sector']} (胜率 {r['sector_winrate']}%, 样本 {r['sector_samples']}) |")
        md.append(f"| 估值 | PE_TTM {r['pe_ttm']} / PB {r['pb']} / 市值 {r['mcap_yi']} 亿 |")
        fin = r["fin"]
        md.append(f"| 财务 | ROE {fin.get('ROE', 'N/A')} / 毛利率 {fin.get('毛利率', 'N/A')} / 净利润 {fin.get('净利润_raw', 'N/A')} ({fin.get('净利润_期', '-')}) |")
        kl = r["kline"]
        if kl:
            md.append(f"| 技术面 | MA5 {kl['ma5']} / MA20 {kl['ma20']} ({'上' if kl['above_ma20'] else '下'}方) / 20日高点 {kl['high20']} (距高 {kl['vs_high20_pct']:+.1f}%) / 60日涨幅 {kl['chg_60d_pct']:+.1f}% / MACD {'金叉' if kl['macd_golden'] else '死叉'} / 近5日 {kl['up_days_last5']} 阳线 |")
        md.append(f"| 风险标记 | {'; '.join(r['flags']) if r['flags'] else '无'} |")
        md.append("")
        md.append("## 核心逻辑")
        md.append("")
        logic = []
        if r["sector"] == "energy":
            logic.append("Phase10 板块 energy 历史胜率 100% (22/22), 板块维度强支撑")
        elif r["sector_winrate"] is not None and r["sector_winrate"] < 40:
            logic.append(f"板块 {r['sector']} 属历史黑名单 (胜率 {r['sector_winrate']}%, 样本 {r['sector_samples']}), 板块维度大幅扣分")
        else:
            logic.append(f"板块 {r['sector']} 无历史样本, 按基线中性处理")
        if kl.get("above_ma20"):
            logic.append("价格站上 MA20, 短期趋势偏多")
        else:
            logic.append("价格位于 MA20 下方, 趋势偏弱")
        if kl and kl.get("vs_high20_pct") is not None and kl["vs_high20_pct"] > -3:
            logic.append("贴近 20 日高点, 突破形态但隔日溢价空间有限")
        v24_gap = (r["price"] / r["v24_price"] - 1) * 100
        logic.append(f"报告价 ¥{r['v24_price']} → 现价 ¥{r['price']} 偏移 {v24_gap:+.2f}% (尾盘 15 分钟价格漂移)")
        if "ST" in r["name"]:
            logic.append("**用户禁区: ST 风险警示股禁止推荐, 评级强制减持**")
        logic.append("v2.4 主策略为 T+1 开盘即卖 (80.2% 胜率 / 11.83 盈亏比), 本评分用于 overnight 候选质量排序")
        md.extend(f"- {x}" for x in logic)
        md.append("")
        md.append("> 仅供参考, 不构成投资建议")
        out_path = os.path.join(REPORT_DIR, f"{TODAY}-深度分析-{r['code']}.md")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md) + "\n")
        print(f"  ✅ {r['code']} {r['name']} score={r['deep_score']} {r['rating']} → {out_path}")

    data_path = os.path.join(REPORT_DIR, f"{TODAY}-deep-analysis-data-v24.json")
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump({"date": TODAY, "source": "2026-10-13-v24-尾盘推荐.md",
                   "model": "deep_analysis_20261007 6维评分", "results": results},
                  f, ensure_ascii=False, indent=2)
    print(f"\n✅ 汇总数据: {data_path}")
    print("\n=== 最终排名 (深度评分降序) ===")
    for i, r in enumerate(results, 1):
        wr = r["sector_winrate"]
        wr_s = f"{wr}%" if wr is not None else "无样本"
        print(f"#{i} {r['code']} {r['name']}: 深度评分 {r['deep_score']} / 评级 {r['rating']} / "
              f"现价 ¥{r['price']} / 目标 ¥{r['target']} / 止损 ¥{r['stop']} / 板块 {r['sector']}({wr_s})")


if __name__ == "__main__":
    main()

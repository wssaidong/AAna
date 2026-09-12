#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-09-11 选股报告（9 只候选）
今日 2026-09-12 周六非交易日，使用 9/11 选股报告（9 只候选）
按照 9/11 深度分析报告 + 6 维评分 SOP 输出
"""
import sys
import json
import os
from datetime import datetime

# 添加 scripts 目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import data_sources as ds
import akshare as ak

REPORT_DATE = "2026-09-11"
TODAY = "2026-09-12"
RUN_ID = "01a09305-afa9-7dbe-8505-69dc7af49a01"

# 9/11 候选池 (9 只)
CANDIDATES = [
    {"code": "600893", "name": "航发动力", "price": 41.61, "tech_score": 80, "composite": 66, "sector_hint": "航空装备"},
    {"code": "600345", "name": "长江通信", "price": 54.62, "tech_score": 78, "composite": 65, "sector_hint": "通信设备"},
    {"code": "000628", "name": "高新发展", "price": 54.95, "tech_score": 80, "composite": 65, "sector_hint": "建筑装饰"},
    {"code": "002491", "name": "通鼎互联", "price": 21.19, "tech_score": 78, "composite": 64, "sector_hint": "通信设备"},
    {"code": "000768", "name": "中航西飞", "price": 23.54, "tech_score": 78, "composite": 64, "sector_hint": "航空装备"},
    {"code": "002714", "name": "牧原股份", "price": 42.18, "tech_score": 70, "composite": 60, "sector_hint": "畜牧业"},
    {"code": "600900", "name": "长江电力", "price": 28.45, "tech_score": 63, "composite": 57, "sector_hint": "电力"},
    {"code": "600887", "name": "伊利股份", "price": 26.66, "tech_score": 63, "composite": 57, "sector_hint": "乳品"},
    {"code": "002230", "name": "科大讯飞", "price": 39.15, "tech_score": 65, "composite": 57, "sector_hint": "软件开发"},
]

def get_quote_batch(codes):
    """批量获取实时行情"""
    print(f"\n[1/5] 拉取实时行情 {len(codes)} 只...")
    quotes = ds.tencent_quote(codes)
    return quotes

def get_industry_batch(codes):
    """批量获取行业归属"""
    print(f"[2/5] 拉取行业归属 {len(codes)} 只...")
    return ds.industry_for_codes(codes)

def get_financial_batch(codes):
    """批量获取财务摘要"""
    print(f"[3/5] 拉取财务摘要 {len(codes)} 只...")
    out = {}
    for code in codes:
        try:
            df = ak.stock_financial_abstract(symbol=code)
            # 提取关键指标
            metrics = {}
            for kw, label in [
                ("净资产收益率(ROE)", "ROE"),
                ("销售毛利率", "毛利率"),
                ("营业总收入", "营收"),
                ("净利润", "净利润"),
                ("基本每股收益", "EPS"),
                ("每股净资产", "BVPS"),
            ]:
                row = df[df['指标'] == kw]
                if not row.empty:
                    val_str = row.iloc[0].get('20251231') or row.iloc[0].get('20250930') or row.iloc[0].get('20250630')
                    if val_str is not None and not (isinstance(val_str, float) and (val_str != val_str)):
                        try:
                            metrics[label] = float(val_str)
                        except (ValueError, TypeError):
                            metrics[label] = None
                    else:
                        metrics[label] = None
            out[code] = metrics
        except Exception as e:
            print(f"  [warn] {code} 财务拉取失败: {e}")
            out[code] = {}
    return out

def map_to_phase10_sector(industry):
    """将申万行业映射到 Phase10 板块枚举"""
    mapping = {
        "航空装备": "mach",
        "通信设备": "elec",
        "建筑装饰": "consumer",
        "畜牧业": "consumer",
        "电力": "energy",
        "乳品": "consumer",
        "软件开发": "ai_app",
        "半导体": "semi",
        "化学制品": "chem",
        "机械": "mach",
        "电子": "elec",
        "电池": "energy",
        "保险": "neutral",
        "银行": "neutral",
        "白酒": "consumer",
        "铜": "neutral",
        "黄金": "neutral",
        "小金属": "neutral",
        "新材料": "neutral",
    }
    return mapping.get(industry, "neutral")

def get_phase10_winrate(sector):
    """从 rec_tuning.json 读取板块胜率"""
    rec_tuning_path = os.path.expanduser("~/code/AAna/data/rec_tuning.json")
    if not os.path.exists(rec_tuning_path):
        return None, 0, 0.0
    with open(rec_tuning_path) as f:
        data = json.load(f)
    sec = data.get("sector_stats", {}).get(sector)
    if sec:
        return sec.get("win_rate"), sec.get("count"), sec.get("avg_change")
    return None, 0, 0.0

def calc_composite_score(quote, fin, industry, phase10_sector):
    """6 维评分: 板块40% + 财务30% + 估值15% + 技术面10% + 业务面5%"""
    score = 0.0

    pe = quote.get("pe_ttm", 0) or 0
    pb = quote.get("pb", 0) or 0
    roe = (fin.get("ROE") or 0)
    rev_2025 = fin.get("营收") or 0  # 亿元
    ni_2025 = fin.get("净利润") or 0  # 亿元

    # --- 板块 (40%) ---
    sector_wr, _, _ = get_phase10_winrate(phase10_sector)
    if sector_wr is None:
        # 中性/未知板块，按 28.9% 整体胜率
        score += 28.9 * 0.40
    elif sector_wr < 40:
        # 黑名单：扣分
        score += sector_wr * 0.40 * 0.3  # 折扣
    else:
        score += sector_wr * 0.40

    # --- 财务 (30%) ---
    fin_score = 0
    if roe > 15:
        fin_score += 30
    elif roe > 10:
        fin_score += 20
    elif roe > 5:
        fin_score += 10
    elif roe > 0:
        fin_score += 5
    else:
        fin_score -= 10
    if rev_2025 > 100:
        fin_score += 10
    elif rev_2025 > 30:
        fin_score += 5
    if ni_2025 > 50:
        fin_score += 10
    elif ni_2025 > 10:
        fin_score += 5
    score += min(40, fin_score) * 0.30 / 30 * 30  # 归一到 0-30

    # --- 估值 (15%) ---
    val_score = 0
    if 0 < pe < 15:
        val_score += 15
    elif 0 < pe < 25:
        val_score += 10
    elif 0 < pe < 40:
        val_score += 5
    elif pe < 0:
        val_score -= 5  # 亏损
    else:
        val_score -= 5  # 极高估
    if 0 < pb < 2:
        val_score += 5
    elif 0 < pb < 5:
        val_score += 3
    score += val_score * 0.50  # 已归一

    # --- 技术面 (10%) ---
    tech_score = 0
    chg_pct = quote.get("change_pct", 0) or 0
    if -3 <= chg_pct <= 0:
        tech_score += 10  # 最佳买点区
    elif -7 <= chg_pct < -3:
        tech_score += 12  # 大幅回调
    elif 0 < chg_pct <= 5:
        tech_score += 8
    elif chg_pct > 9:
        tech_score -= 10  # 涨停风险
    score += tech_score

    # --- 业务面 (5%) ---
    biz_score = 5
    if roe < 5:
        biz_score -= 2
    score += biz_score

    return round(score, 2)

def main():
    print(f"\n{'='*80}")
    print(f"AAna 深度分析 — {REPORT_DATE} 选股报告（9 只候选）")
    print(f"今日 {TODAY} 周六非交易日，复用 9/11 报告")
    print(f"Run ID: {RUN_ID}")
    print(f"{'='*80}")

    codes = [c["code"] for c in CANDIDATES]

    # Step 1: 实时行情
    quotes = get_quote_batch(codes)

    # Step 2: 行业归属
    industries = get_industry_batch(codes)

    # Step 3: 财务摘要
    financials = get_financial_batch(codes)

    # Step 4: Phase10 板块映射
    print(f"\n[4/5] Phase10 板块映射 + 胜率...")
    sector_data = {}
    for c in CANDIDATES:
        code = c["code"]
        industry = industries.get(code, "unknown")
        phase10_sec = map_to_phase10_sector(industry)
        wr, samples, avg_chg = get_phase10_winrate(phase10_sec)
        if phase10_sec == "neutral":
            rating = "⚪ 中性"
        elif wr is None or wr < 40:
            rating = "🔴 黑名单"
        elif wr >= 60:
            rating = "🟢 优"
        else:
            rating = "🟡 可"
        sector_data[code] = {
            "industry": industry,
            "phase10_sector": phase10_sec,
            "win_rate": wr,
            "samples": samples,
            "avg_change": avg_chg,
            "rating": rating,
        }
        print(f"  {code} {c['name']}: {industry} → {phase10_sec} (胜率={wr}, 样本={samples}) {rating}")

    # Step 5: 综合评分
    print(f"\n[5/5] 6 维综合评分...")
    results = []
    for c in CANDIDATES:
        code = c["code"]
        q = quotes.get(code, {})
        fin = financials.get(code, {})
        sec = sector_data[code]
        composite = calc_composite_score(q, fin, sec["industry"], sec["phase10_sector"])
        results.append({
            "code": code,
            "name": c["name"],
            "report_price": c["price"],
            "current_price": q.get("price", 0),
            "change_pct": q.get("change_pct", 0),
            "pe_ttm": q.get("pe_ttm", 0),
            "pe_static": q.get("pe_static", 0),
            "pb": q.get("pb", 0),
            "roe": fin.get("ROE"),
            "revenue_yi": fin.get("营收"),
            "ni_yi": fin.get("净利润"),
            "mcap_yi": q.get("mcap_yi", 0),
            "industry": sec["industry"],
            "phase10_sector": sec["phase10_sector"],
            "sector_winrate": sec["win_rate"],
            "sector_rating": sec["rating"],
            "composite_score": composite,
            "tech_score_report": c["composite"],
        })

    results.sort(key=lambda x: x["composite_score"], reverse=True)

    print(f"\n{'='*80}")
    print(f"综合排名")
    print(f"{'='*80}")
    print(f"{'#':<3} {'代码':<7} {'名称':<10} {'现价':<8} {'PE':<7} {'ROE':<6} {'行业':<12} {'板块':<10} {'胜率':<8} {'综合分':<7}")
    for i, r in enumerate(results, 1):
        wr_str = f"{r['sector_winrate']:.1f}%" if r['sector_winrate'] is not None else "无样本"
        roe_str = f"{r['roe']:.2f}" if r['roe'] is not None else "N/A"
        print(f"{i:<3} {r['code']:<7} {r['name']:<10} ¥{r['current_price']:<6.2f} {r['pe_ttm']:<6.2f} {roe_str:<6} {r['industry']:<12} {r['phase10_sector']:<10} {wr_str:<8} {r['composite_score']:<7.2f}")

    # 保存到文件
    out_dir = os.path.expanduser("~/code/AAna/reports")
    out_path = os.path.join(out_dir, f"{TODAY}-deep-analysis-data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "report_date": REPORT_DATE,
            "today": TODAY,
            "run_id": RUN_ID,
            "candidates_count": len(CANDIDATES),
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 数据保存至: {out_path}")

    return results

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-09-20 (周日非交易日, 复用 2026-09-18 选股报告)
按 9/12 + 9/13 + 9/14 + 9/15 + 9/16 + 9/17 + 9/18 + 9/19 深度分析 SOP + 6 维评分

⚠️ 重要 — 9/20 周日非交易日 (无 9/20 选股报告), 复用 9/18 (周五) 选股报告:
- 9/20 周日 cron 触发 — 但 A 股周末休市, 无新选股报告
- 沿用 9/13 (周日复用 9/11) + 9/19 (周六复用 9/18) 模式 — 复用最近一个交易日 (9/18 周五) 报告
- 复用 9/18 候选池 10 只 — 浙江荣泰/春光科技/光电股份/中京电子/八方股份/科博达/东睦股份/百合花/融捷股份/雷柏科技
- 9/18 复盘: 6/10=60.0% 命中 V2.5 终结连续 2 个正 Alpha 日 (净累计 -0.88pp)
- 9/18 整体均值 +0.23% vs 上证 +0.94% 超额 -0.71pp
- 9/18 假平稳真急涨型·14:45 +0.78% → 收盘 +0.94% 修正 +0.16pp + 科创50 -1.46% → +2.88% 反转 +4.34pp
- 根因E-冷启动盲区(无机盐/房地产开发) → 次日阈值73/仓位45%
- 9/19 周六深度分析结果: 八方股份 Top 1 (62.50) + 融捷股份 Top 2 (44.56) — 组合 20260919ZZ
- 9/20 继续验证 energy 板块 100% 胜率

板块映射沿用 9/13-9/19:
- 稀土/小金属/海缆/氟化工锂电 → energy (100% 胜率)
- 锑/光伏 → energy (9/17 新增)
- 电机/电踏车/锂矿 → energy (9/18 新增 — 八方股份 + 融捷股份修正)
- PCB/电子/通信/半导体 → elec (0%) 或 semi (3%)
- 化工/新材料/染料/绝缘材料 → chem (0%)
- 机械/军工/粉末冶金/磁性材料/军工光学 → mach (0%)
- 海运/航运 → transport (无样本)
- 消费电子/家电 → consumer (无样本)
- 9/20 复用 9/18 全部映射 (与 9/19 一致)
"""
import sys
import json
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import data_sources as ds
import akshare as ak

REPORT_DATE = "2026-09-18"   # 复用的选股报告日期 (周五)
TODAY = "2026-09-20"          # 今天周日非交易日
RUN_ID = "01a0bc38-a3d8-7d1d-be86-0e76f596cb77"

# 9/20 复用 9/18 候选池 (Top 10, 从 2026-09-18 选股报告 Top 10 提取 — 与 9/19 一致)
# 浙江荣泰(云母/新材料) / 春光科技(吸尘器/家电) / 光电股份(光学/军工) / 中京电子(PCB/FPC)
# 八方股份(电踏车/电机) / 科博达(汽车电子) / 东睦股份(粉末冶金) / 百合花(颜料/染料)
# 融捷股份(锂矿) / 雷柏科技(无线键鼠/消费电子)
CANDIDATES = [
    {"code": "603119", "name": "浙江荣泰", "price": 54.35, "tech_score": 78, "composite": 65, "sector_hint": "云母绝缘/新材料"},
    {"code": "603657", "name": "春光科技", "price": 34.95, "tech_score": 78, "composite": 65, "sector_hint": "吸尘器/家电"},
    {"code": "600184", "name": "光电股份", "price": 22.10, "tech_score": 78, "composite": 65, "sector_hint": "光学/军工"},
    {"code": "002579", "name": "中京电子", "price": 20.48, "tech_score": 78, "composite": 64, "sector_hint": "PCB/FPC"},
    {"code": "603489", "name": "八方股份", "price": 28.84, "tech_score": 63, "composite": 57, "sector_hint": "电踏车/电机"},
    {"code": "603786", "name": "科博达", "price": 37.20, "tech_score": 63, "composite": 57, "sector_hint": "汽车电子/控制器"},
    {"code": "600114", "name": "东睦股份", "price": 27.78, "tech_score": 63, "composite": 57, "sector_hint": "粉末冶金/磁性材料"},
    {"code": "603823", "name": "百合花", "price": 57.60, "tech_score": 63, "composite": 57, "sector_hint": "颜料/染料"},
    {"code": "002192", "name": "融捷股份", "price": 60.94, "tech_score": 63, "composite": 56, "sector_hint": "锂矿/锂电材料"},
    {"code": "002577", "name": "雷柏科技", "price": 20.83, "tech_score": 63, "composite": 56, "sector_hint": "无线键鼠/消费电子"},
]


def get_quote_batch(codes):
    """批量获取实时行情"""
    print(f"\n[1/5] 拉取实时行情 {len(codes)} 只...")
    return ds.tencent_quote(codes)


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
    """9/20 板块映射: 完全沿用 9/18 (复用 9/13-9/19 全部映射)
    energy (绿电/储能/锂电/稀土/海缆/锑/电机/锂矿) — 100% 胜率
    elec/semi/chem/mach — 黑名单 0-3% 胜率
    transport — 中性
    consumer — 中性
    """
    mapping = {
        # energy 绿电/储能/锂电/稀土 (100% 胜率)
        "水电": "energy",
        "电力": "energy",
        "火电": "energy",
        "新能源": "energy",
        "电池": "energy",
        "锂电": "energy",
        "锂电池": "energy",
        "锂电负极": "energy",
        "电池材料": "energy",
        "锂": "energy",
        "锂矿": "energy",  # 9/18 新增 — 融捷股份
        "光伏": "energy",
        "稀土": "energy",
        "小金属": "energy",
        "海缆": "energy",
        "线缆部件及其他": "energy",
        "电气设备": "energy",
        "电机": "energy",  # 9/18 新增 — 八方股份
        "氟化工及制冷剂": "energy",
        # elec 电子 (黑名单 0%)
        "电子": "elec",
        "PCB": "elec",
        "印制电路板": "elec",
        "电子元件": "elec",
        "消费电子": "elec",  # 9/18 新增 — 雷柏科技
        "电子零部件制造": "elec",
        "通信设备": "elec",
        "通信传输设备": "elec",
        "光学光电子": "elec",
        "被动元件": "elec",
        "石英晶体": "elec",
        # semi 半导体设备 (黑名单 3%)
        "半导体": "semi",
        "半导体设备": "semi",
        "集成电路": "semi",
        # chem 化工 (黑名单 0%)
        "化学制品": "chem",
        "化工": "chem",
        "新材料": "chem",
        "非金属新材料": "chem",
        "无机盐": "chem",
        "氟化工": "chem",
        "染料": "chem",  # 9/18 新增 — 百合花
        "颜料": "chem",  # 9/18 新增 — 百合花
        # mach 机械 (黑名单 0%)
        "机械": "mach",
        "磨料磨具": "mach",
        "军工": "mach",
        "航空装备": "mach",
        "地面兵装": "mach",
        "机械基础件": "mach",
        "军工连接器": "mach",
        "智能装备": "mach",
        # transport 海运
        "海运": "transport",
        "航运": "transport",
        "油运": "transport",
        "港口": "transport",
        # consumer 消费/家电
        "汽车零部件": "consumer",
        "家居用品": "consumer",
        "家具": "consumer",
        "乳品": "consumer",
        "畜牧业": "consumer",
        "畜禽养殖": "consumer",
        "建筑装饰": "consumer",
        "房屋建设": "consumer",
        "饮料": "consumer",
        "食品饮料": "consumer",
        "传媒": "consumer",
        "营销": "consumer",
        "家电": "consumer",  # 9/18 新增 — 春光科技
        "白色家电": "consumer",  # 9/18 新增 — 春光科技
        "小家电": "consumer",  # 9/18 新增 — 春光科技
        "家用电器": "consumer",  # 9/18 新增 — 春光科技
        # neutral 中性 (候选较杂)
        "保险": "neutral",
        "银行": "neutral",
        "白酒": "consumer",
        "铜": "neutral",
        "黄金": "neutral",
        "铅锌": "neutral",
        "铅锌锑": "neutral",
        "矿业": "neutral",
        "有色金属": "neutral",
        "加油站": "energy",
        "成品油": "energy",
        "石油": "energy",
        "油气": "energy",
        # 9/18 新增映射 — 候选池补充
        "云母": "chem",  # 浙江荣泰主营云母绝缘材料
        "绝缘材料": "chem",
        "玻璃制造": "chem",
        "光学": "mach",  # 光电股份归 mach (军工光学)
        "军工光学": "mach",
        "粉末冶金": "mach",  # 东睦股份归 mach
        "磁性材料": "mach",  # 东睦股份软磁复合
        "电踏车": "consumer",  # 八方股份归 consumer
        "汽车电子": "consumer",  # 科博达归 consumer
        "汽车零部件": "consumer",
        "计算机": "consumer",
        "IT服务": "consumer",
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
    rev_2025 = fin.get("营收") or 0
    ni_2025 = fin.get("净利润") or 0

    # --- 板块 (40%) ---
    sector_wr, _, _ = get_phase10_winrate(phase10_sector)
    if sector_wr is None:
        score += 28.9 * 0.40
    elif sector_wr < 40:
        score += sector_wr * 0.40 * 0.3
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
    score += min(40, fin_score) * 0.30 / 30 * 30

    # --- 估值 (15%) ---
    val_score = 0
    if 0 < pe < 15:
        val_score += 15
    elif 0 < pe < 25:
        val_score += 10
    elif 0 < pe < 40:
        val_score += 5
    elif pe < 0:
        val_score -= 5
    else:
        val_score -= 5
    if 0 < pb < 2:
        val_score += 5
    elif 0 < pb < 5:
        val_score += 3
    score += val_score * 0.50

    # --- 技术面 (10%) ---
    tech_score = 0
    chg_pct = quote.get("change_pct", 0) or 0
    if -3 <= chg_pct <= 0:
        tech_score += 10
    elif -7 <= chg_pct < -3:
        tech_score += 12
    elif 0 < chg_pct <= 5:
        tech_score += 8
    elif chg_pct > 9:
        tech_score -= 10
    score += tech_score

    # --- 业务面 (5%) ---
    biz_score = 5
    if roe < 5:
        biz_score -= 2
    score += biz_score

    return round(score, 2)


def main():
    print(f"\n{'='*80}")
    print(f"AAna 深度分析 — {REPORT_DATE} 选股报告 (复用, 9/20 周日非交易日)")
    print(f"今日 {TODAY} 周日非交易日 — 沿用 9/13 (周日复用 9/11) + 9/19 (周六复用 9/18) 模式")
    print(f"Run ID: {RUN_ID}")
    print(f"{'='*80}")

    # 报告确认 (autopilot 强制要求)
    report_path = os.path.expanduser("~/code/AAna/reports/2026-09-18-选股报告.md")
    print(f"\n📄 报告路径: {report_path}")
    print(f"   文件大小: {os.path.getsize(report_path)} 字节")
    print(f"   修改时间: {datetime.fromtimestamp(os.path.getmtime(report_path)).isoformat(timespec='seconds')}")
    print(f"   ⚠️ 今日 9/20 周日非交易日, 无新选股报告, 复用 9/18 (周五) 报告")

    codes = [c["code"] for c in CANDIDATES]

    quotes = get_quote_batch(codes)
    industries = get_industry_batch(codes)
    financials = get_financial_batch(codes)

    print(f"\n[4/5] Phase10 板块映射 + 胜率...")
    sector_data = {}
    for c in CANDIDATES:
        code = c["code"]
        industry = industries.get(code, "unknown")
        phase10_sec = map_to_phase10_sector(industry)
        wr, samples, avg_chg = get_phase10_winrate(phase10_sec)
        if phase10_sec == "neutral" or wr is None:
            rating = "⚪ 中性 (无样本)"
        elif wr < 40:
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
    print(f"{'#':<3} {'代码':<7} {'名称':<10} {'现价':<8} {'PE':<7} {'ROE':<6} {'行业':<14} {'板块':<10} {'胜率':<8} {'综合分':<7}")
    for i, r in enumerate(results, 1):
        wr_str = f"{r['sector_winrate']:.1f}%" if r['sector_winrate'] is not None else "无样本"
        roe_str = f"{r['roe']:.2f}" if r['roe'] is not None else "N/A"
        print(f"{i:<3} {r['code']:<7} {r['name']:<10} ¥{r['current_price']:<6.2f} {r['pe_ttm']:<6.2f} {roe_str:<6} {r['industry']:<14} {r['phase10_sector']:<10} {wr_str:<8} {r['composite_score']:<7.2f}")

    out_dir = os.path.expanduser("~/code/AAna/reports")
    out_path = os.path.join(out_dir, f"{TODAY}-deep-analysis-data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "report_date": REPORT_DATE,
            "today": TODAY,
            "today_weekday": "周日 (非交易日)",
            "reuse_note": "周日非交易日无新选股报告, 沿用 9/13+9/19 模式复用最近交易日 (9/18 周五) 报告",
            "run_id": RUN_ID,
            "candidates_count": len(CANDIDATES),
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 数据保存至: {out_path}")

    return results


if __name__ == "__main__":
    main()
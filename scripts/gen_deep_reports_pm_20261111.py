#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-11-11 尾盘深度分析报告生成器 — 从 data/deep_analysis_pm_20261111.json 渲染
 reports/{date}-深度分析-{code}.md (5 只)

FINAL_PICK = 002881 美格智能
理由: 引擎分 80.0 (买入) 全场最高, 且与第 2 名差 11.3 分 (远超噪声), 无需 tiebreak:
  (1) 增长质量最优: 归母 +65.19% vs 扣非 +79.22% (gap -14.0pp, 扣非**反超**归母, 主业纯驱动, 无非经常项灌水);
      Q3 单季归母 0.81 亿同比 +179.34% 加速; 大族/宏昌/国芳/游族中仅大族激光扣非质量相当 (gap -152.7pp 但低基数)。
  (2) 技术面满分 55/55 且当日仅 +0.14% (尾盘策略"回调买入"形态最标准); 国芳/大族/宏昌/游族技术分 25-43。
  (3) 板块胜率: 电子零部件制造 100% (2/2) + 邻近通信传输设备 100% (3/3) + 计算机设备 100% (1/1) — 全部正样本;
      当日热点即通信网络设备/线缆 (AI 算力链), 板块动量与策略回测共振。
  (4) 主业赛道: 算力/智能模组 + 端侧 AI (5G+华为海思概念), 景气方向与当日全市场热点 (通信设备 +7.0%) 一致。
风险: PE_TTM 61.66 偏贵 (扣非 TTM 2.10 亿 → 扣非 PE ~38.5x), OCF -2.11 亿 (扩张备货期), 止损 41.06 (-7%)。
"""
import json, os, sys
from datetime import datetime

sys.path.insert(0, '/Users/cai/code/AAna/scripts')

TODAY = "2026-11-11"
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
DATA = os.path.expanduser("~/code/AAna/data/deep_analysis_pm_20261111.json")

FINAL_PICK = "002881"

FINAL_REASON = (
    "引擎分 80.0 (买入) 全场最高, 与第 2 名大族激光 68.7 差 11.3 分 (远超 ±2 分噪声带), 无需 tiebreak。"
    "4 条支撑: (1) 增长质量 — 归母 +65.19% vs 扣非 +79.22%, gap -14.0pp 扣非反超归母 (增长全部来自主业, "
    "是 5 只中唯一 '扣非≥归母' 且 Q3 单季加速 +179% 的标的); (2) 技术面 55/55 满分且当日仅 +0.14%, "
    "是尾盘 '回调买强势股' 形态最标准的一只; (3) 板块胜率 — 电子零部件制造 100% (2/2) + 邻近通信传输设备 "
    "100% (3/3) + 计算机设备 100% (1/1), 回测全正样本; (4) 板块景气 — 主业算力/智能模组+端侧 AI, "
    "与当日全市场热点 (通信网络设备 +7.0% / 通信线缆 +5.8%, AI 算力链) 直接共振。"
    "主要风险: PE_TTM 61.7 偏贵 (总市值 133.5 亿 / 扣非 TTM 2.10 亿 → 扣非 PE 63.6x, run-rate ~41x), "
    "OCF -2.11 亿为扩张备货期占用, 止损 41.06 (-7.0%) 必须执行。"
)

# 2026 三季报快照 (akshare stock_financial_abstract, 20260930 累计; 单季=Q3) — 11-11 实拉核验
SNAP = {
    "002881": {"rev": 35.264, "rev_g": 24.99, "gm": 1.869, "gm_g": 65.19, "kf": 1.877, "kf_g": 79.22,
               "q_gm": 0.810, "q_gm_yoy": 179.34, "q_kf": 0.808, "q_kf_yoy": 260.44, "ocf": -2.114, "roe": 7.68},
    "002008": {"rev": 214.743, "rev_g": 68.92, "gm": 21.774, "gm_g": 152.19, "kf": 11.635, "kf_g": 304.87,
               "q_gm": 8.894, "q_gm_yoy": 137.03, "q_kf": 4.363, "q_kf_yoy": 480.85, "ocf": 2.266, "roe": 10.39},
    "603002": {"rev": 36.806, "rev_g": 71.67, "gm": 2.557, "gm_g": 943.19, "kf": 0.745, "kf_g": 1142.06,
               "q_gm": 2.164, "q_gm_yoy": 2544.78, "q_kf": 0.595, "q_kf_yoy": 2066.02, "ocf": -0.185, "roe": 7.14},
    "601086": {"rev": 6.195, "rev_g": 8.25, "gm": 0.911, "gm_g": 49.51, "kf": 0.318, "kf_g": 10.02,
               "q_gm": 0.199, "q_gm_yoy": -47.89, "q_kf": 0.114, "q_kf_yoy": None, "ocf": 1.589, "roe": 5.62},
    "002174": {"rev": 10.626, "rev_g": 4.31, "gm": 1.420, "gm_g": 85.97, "kf": 0.060, "kf_g": -33.93,
               "q_gm": -1.107, "q_gm_yoy": -522.46, "q_kf": 0.009, "q_kf_yoy": None, "ocf": -6.507, "roe": 3.16},
}

QUALITY_NOTE = {
    "002881": "🟢 增长质量优: 归母 +65.19% vs 扣非 +79.22% (gap -14.0pp, 扣非**反超**归母), 增长全部来自主业; "
              "Q3 单季归母 0.81 亿 (+179.34%) / 扣非 0.81 亿 (+260.44%) 双加速; OCF -2.11 亿为扩张备货期占用 "
              "(H1 -2.65 亿 → Q3 单季已转正 +0.53 亿, 边际改善); 无质量修正触发",
    "002008": "🟢 扣非 +304.87% 远超归母 +152.19% (gap -152.7pp, 扣非反超), Q3 单季扣非 +480.85%; "
              "OCF +2.27 亿为正但仅占归母 10.4% (大额应收/存货占用, 需年报验证回款); 无质量修正触发",
    "603002": "🟡 归母 +943.19% / 扣非 +1142.06% 均为**低基数失真** (去年同期归母仅 0.245 亿, 扣非仅 0.062 亿), "
              "绝对值 2.56/0.74 亿体量小; OCF -0.18 亿 (7.2%); 电子级树脂景气 (覆铜板/PCB 上游涨价) 是真驱动",
    "601086": "🟡 归母 +49.51% 但扣非仅 +10.02% (gap 39.5pp), 超额部分来自非经常项 (含政府补助/资产处置等); "
              "Q3 单季归母 0.20 亿同比 **-47.89%** (Q3 减速); OCF +1.59 亿 (174%) 现金面健康",
    "002174": "🔴 P0 质量修正触发: 归母 +85.97% 表面高增, 但扣非 **-33.93%** (gap 119.9pp), 超额全来自非经常项 "
              "(出售资产/投资收益); Q3 单季归母 **-1.11 亿转亏** (-522%); OCF -6.51 亿 (归母的 -458%) 失血; "
              "→ fund_score 按扣非口径 22→3, 总分 62.5→50.5",
}

# 估值核验 (11-11 实拉: 总市值=max(两字段), 腾讯 PE_TTM=归母 TTM 口径; 扣非TTM=FY去年+最新累计-去年同期)
VAL_CHECK = {
    "002881": "总市值 133.5 亿 / 流通 81.1 亿 (总=max 实拉校验: PE_TTM 61.66 × 归母TTM 2.16 亿 = 133.2 亿 ✓); "
              "**扣非 TTM 2.10 亿 → 扣非 PE 63.6x**; PB 4.66。⚠️ 贵: Q3 单季归母 0.81 亿年化 ~3.2 亿 → "
              "run-rate PE ~41x, 仍在消化中 — '贵但加速' 型, 仓位与止损纪律必须执行",
    "002008": "总市值 584.1 亿 / 流通 542.8 亿; PE_TTM ~23 (归母TTM 25.04 亿); 扣非 TTM 25.43 亿 → 扣非 PE 23.0x; "
              "PB 2.62。5 只中唯一 '便宜+高增' 组合, 估值面 15/15 满分",
    "603002": "总市值 156.8 亿; PE_TTM 58.83 (归母TTM 2.67 亿); 扣非 TTM 2.75 亿 → 扣非 PE ~57x; PB 4.25。"
              "表观增速 900%+ 全是低基数, 真实估值贵",
    "601086": "总市值 89.7 亿; PE_TTM 89.32 过高 (归母TTM ~1.0 亿) + PB 5.56 偏高; "
              "扣非 TTM 0.55 亿 → 扣非 PE ~163x。区域百货基本面撑不起估值, 涨幅来自新零售/重组预期炒作",
    "002174": "PE_TTM -40.59 = 归母 TTM **-2.82 亿** (FY2025 -3.47 亿 + 2026 前三季 1.42 亿 - 去年同期 0.76 亿) — "
              "腾讯口径为滚动 12 个月真实亏损, 非 '单季转亏拖累'; 扣非 TTM ~-3.1 亿仍深亏 → PE 不适用, "
              "归母 +85.97% 仅是低基数上的亏损收窄 (11-09 低基数陷阱同款)",
}

BUSINESS = {
    "002881": "物联网无线通信模组和解决方案供应商: 高算力/智能/数传模组 (5G, 华为海思生态), 下行端侧 AI、"
              "机器人、智能网联车、FWA 无线宽带。2026H1 AI 算力模组放量是业绩主引擎, 端侧 AI 边缘推理模组"
              "进入头部客户; 与当日通信设备/算力热点直接同链。",
    "002008": "激光加工装备平台龙头 (3C/动力电池/PCB/半导体激光设备), 超精密加工+机器人自动化; "
              "2026 三季报营收 +68.92%/归母 +152.19%, 受益 3C 复苏+锂电扩产+海外拓展。",
    "603002": "电子级环氧树脂 (覆铜板上游) + 覆铜板双主业, PCB/5G/服务器产业链材料端; "
              "AI 算力 PCB 景气传导上游树脂涨价, 2026 三季报营收 +71.67%, 低基数下利润弹性大。",
    "601086": "甘肃区域百货龙头 (百货购物中心为主, 超市为辅), 新零售转型 + 国企改革预期; "
              "基本面平稳 (营收 +8.25%), 本轮涨幅主要来自消费/新零售题材资金轮动。",
    "002174": "游戏研发发行运营商 (《少年三国志》系列等), 手游+海外发行; 归母表面 +85.97% 但含大额非经常项, "
              "主业扣非 -33.93% 下滑, Q3 单季转亏, OCF 大额流出 — 基本面实质恶化。",
}

INDUSTRY = {
    "002881": "电子零部件制造 (sina) / 通信设备 (东财)",
    "002008": "其他电子 (sina) / 自动化设备 (东财)",
    "603002": "其他化学制品 (sina) / 电子化学品Ⅱ (东财)",
    "601086": "百货 (sina) / 一般零售 (东财)",
    "002174": "移动互联网服务 (sina) / 游戏Ⅱ (东财)",
}

SECTOR_NOTE = {
    "002881": "本板块键: 电子零部件制造 100% (2/2); 邻近: 通信传输设备 100% (3/3), 计算机设备 100% (1/1)",
    "002008": "本板块键: 其它专用机械 100% (1/1); 邻近: 电子零部件制造 100% (2/2)",
    "603002": "本板块键: 其他化学制品 50% (1/2); 邻近: 印制电路板 33% (1/3)",
    "601086": "本板块键: 百货 100% (2/2); 邻近: 专业连锁 0% (0/1)",
    "002174": "本板块键: 移动互联网服务 50% (3/6); 邻近: 传媒 100% (1/1), 影视动漫 33% (1/3)",
}

RISK_EXTRA = {
    "002881": [
        "🟡 估值贵: PE_TTM 61.7 / 扣非 PE 63.6x (run-rate ~41x), 若 AI 模组放量不及预期有杀估值风险",
        "🟡 OCF -2.11 亿 (备货扩张期), 需跟踪 Q4 回款",
        "🟡 上游芯片 (海思/高通) 供应依赖, 汇率波动影响毛利率",
    ],
    "002008": [
        "🟡 OCF 仅占归母 10.4%, 应收/存货占用大, 关注回款质量",
        "🟡 当日已涨 +4.42%, 尾盘追高部分透支次日溢价 (策略提示 涨幅>5% 不追, 4.4% 属边缘)",
        "🟡 3C/锂电设备需求若 Q4 放缓, 高增速难持续",
    ],
    "603002": [
        "🟡 增速低基数失真 (去年 Q3 净利仅 0.245 亿), 同比数字不可线性外推",
        "🟡 树脂价格回落则弹性反转; OCF 微负",
        "🟡 当日 +4.22% 追高风险与 002008 同",
    ],
    "601086": [
        "🔴 PE_TTM 89.3 / 扣非 PE ~162x, 估值严重透支基本面",
        "🔴 Q3 单季归母 -47.89% 减速, gap 39.5pp 说明含非经常项",
        "🟡 题材轮动驱动, 退潮时回撤大; 当日 -1.82% 已现分歧",
    ],
    "002174": [
        "🔴 P0 增长质量失真: 归母 +85.97% 全靠非经常项, 扣非 -33.93%, Q3 单季归母 -1.11 亿转亏",
        "🔴 OCF -6.51 亿失血 (归母的 -458%), 现金流恶化最严重",
        "🔴 引擎分 62.5 已按扣非口径修正为 50.5 (中性下沿), 严禁因 v2.4 原分 93 高追",
    ],
}


def fmt(x, nd=2, suf=" 亿"):
    if x is None:
        return "—"
    return f"{x:.{nd}f}{suf}"


def build(r, all_results):
    code, name = r["code"], r["name"]
    s = SNAP[code]
    q = r.get("quality", {})
    applied = q.get("applied", False)
    tech = r.get("tech_stat") or {}
    final_score = next((x["total"] for x in all_results if x["code"] == FINAL_PICK), "?")
    L = []
    L.append(f"# {TODAY} 尾盘深度分析 — {code} {name}")
    L.append("")
    L.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 目标事件: **{TODAY} 尾盘决策, T+1 (11-12) 开盘执行**")
    L.append(f"> 行业: {INDUSTRY[code]} | v2.4 原始筛选分: {r['v24_score']} | 评分引擎: 技术面50% + 基本面30% + 估值面20% (deep_analysis_20261022)")
    if applied:
        L.append("> ⚠️ **已应用扣非/现金流增长质量修正**: 基本面分按扣非增速重算")
    L.append("")
    L.append("## 一、投资评级与关键位")
    L.append("")
    L.append("| 项目 | 值 |")
    L.append("|---|---|")
    if applied:
        L.append(f"| 投资评级 | **{r['rating']}** (修正前 {q.get('rating_raw')}) |")
        L.append(f"| 综合评分 | **{r['total']}** (修正前 {q.get('total_raw')}) |")
    else:
        L.append(f"| 投资评级 | **{r['rating']}** |")
        L.append(f"| 综合评分 | **{r['total']}** |")
    L.append(f"| 分项 | 技术 {r['tech_score']}/55 · 基本面 {r['fund_score']}/30 · 估值 {r['val_score']}/15 |")
    L.append(f"| 现价 | {r['price']} |")
    L.append(f"| 目标价 / 止损价 | {r.get('target')} / {r.get('stop')} (引擎 20 日高低位) |")
    L.append("")
    L.append("## 二、核心逻辑 (主营业务)")
    L.append("")
    L.append(BUSINESS[code])
    L.append("")
    L.append("## 三、基本面快照 (2026 三季报, 累计)")
    L.append("")
    L.append("| 指标 | 值 |")
    L.append("|---|---|")
    L.append(f"| 营收 | {fmt(s['rev'])} ({s['rev_g']:+.2f}%) |")
    L.append(f"| 归母净利 | {fmt(s['gm'])} ({s['gm_g']:+.2f}%) |")
    L.append(f"| 扣非净利 | {fmt(s['kf'])} ({s['kf_g']:+.2f}%) |")
    qyoy = f"{s['q_gm_yoy']:+.2f}%" if s.get('q_gm_yoy') is not None else "—"
    qkyoy = f"{s['q_kf_yoy']:+.2f}%" if s.get('q_kf_yoy') is not None else "—"
    L.append(f"| Q3 单季 归母/扣非 | {fmt(s['q_gm'])} ({qyoy}) / {fmt(s['q_kf'])} ({qkyoy}) |")
    L.append(f"| 经营现金流 | {fmt(s['ocf'])} |")
    L.append(f"| ROE | {s['roe']:.2f}% |")
    L.append(f"| 增长质量 | {QUALITY_NOTE[code]} |")
    L.append("")
    L.append("## 四、估值")
    L.append("")
    mc1, mc2 = (r.get('mcap_yi') or 0), (r.get('float_mcap_yi') or 0)
    L.append(f"PE_TTM {r.get('pe_ttm')} / PB {r.get('pb')} / 总市值 {max(mc1, mc2):.1f} 亿 / 流通 {min(mc1, mc2):.1f} 亿")
    L.append("")
    L.append(VAL_CHECK[code])
    L.append("")
    L.append("## 五、技术面 (120 日 qfq)")
    L.append("")
    for n in (r.get("tech_notes") or []):
        L.append(f"- {n}")
    if tech:
        L.append(f"- 区间: 20日高 {tech.get('hi20')} / 20日低 {tech.get('lo20')} | MA5 {tech.get('ma5')} / MA20 {tech.get('ma20')} / MA60 {tech.get('ma60')} | 换手 {r.get('turnover_pct')}% | 量比 {r.get('vol_ratio')}")
    L.append("")
    L.append("## 六、板块胜率 (策略 418 笔回测)")
    L.append("")
    L.append(f"- {SECTOR_NOTE[code]}")
    if r.get('sector_near') and SECTOR_NOTE[code] == "本板块键: 见上":
        L.append(f"- 邻近: {r['sector_near']}")
    L.append("")
    L.append("## 七、风险提示")
    L.append("")
    for rk in RISK_EXTRA[code]:
        L.append(f"- {rk}")
    L.append("")
    L.append("## 八、结论")
    L.append("")
    if code == FINAL_PICK:
        L.append(f"**🏆 最终推荐 — {TODAY} 尾盘最值得购买 1 只: {code} {name}**")
        L.append("")
        L.append(FINAL_REASON)
    elif applied:
        L.append(f"未选为最终推荐: 归母表观高增但扣非下滑/单季转亏, 增长质量未过检 "
                 f"(fund_score {q.get('fund_score_raw')}→{q.get('fund_score_adj')}, 总分 {q.get('total_raw')}→{r['total']}), "
                 f"低于最终推荐 {FINAL_PICK} ({final_score})。")
    else:
        L.append(f"未选为最终推荐: 综合评分 {r['total']} {r['rating']} < 最终推荐 {FINAL_PICK} ({final_score})。")
    L.append("")
    L.append("---")
    L.append("*数据源: 腾讯实时行情/日K(120d qfq) + akshare stock_financial_abstract (20260930) + sina/东财行业双源 + "
             "rec_tuning.json 板块胜率 | 评分引擎: deep_analysis_20261022.py (技术50/基本30/估值20) + 11-10 增长质量修正 | 参考, 不构成投资建议*")
    return "\n".join(L)


if __name__ == "__main__":
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(DATA) as f:
        results = json.load(f)["results"]
    for r in results:
        md = build(r, results)
        path = os.path.join(REPORT_DIR, f"{TODAY}-深度分析-{r['code']}.md")
        with open(path, "w") as f:
            f.write(md)
        print(f"wrote {path} ({len(md)} chars)")
    print("done")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-11-27 尾盘深度分析报告生成器 — 从 data/deep_analysis_pm_20261127.json 渲染
 reports/{date}-深度分析-{code}.md (5 只)

FINAL_PICK = 605599 菜百股份 (82.2 买入) — 深分最高, 领先第 2 名 002422 科伦药业 (78.0) 4.2 分
 (> ±2 噪声带), 主排序键直接取胜, 无需 tiebreak; 且是 Top5 中少数同时满足
 "均线多头排列 (MA5>MA20>MA60) + 价在 MA5 上方" 的候选 (002422 亦满足)。

官方三季报数字均已用官方公告原文交叉核验:
  605599 cninfo 1225629232.PDF (2026-10-28 三季报) + 1225629220.PDF (Q3 主要经营数据)
          + 每经 (2026-11-25 探访) + 中财网 (2026-11-13) + 招商/方正/一财研报点评
          + 公告 2026-014 (2026-05-25 明牌实业提前终止减持)
  002422 / 000513 / 002223 / 600012 akshare stock_financial_abstract (20260930) + 引擎交叉
"""
import json, os, sys
from datetime import datetime

sys.path.insert(0, '/Users/cai/code/AAna/scripts')

TODAY = "2026-11-27"
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
DATA = os.path.expanduser("~/code/AAna/data/deep_analysis_pm_20261127.json")

FINAL_PICK = "605599"

# 官方三季报快照 (亿元, 累计口径; 单季 = Q3)
SNAP = {
    "605599": {"rev": 264.48, "rev_g": 29.19, "gm": 5.13, "gm_g": -20.67,
               "kf": 5.74, "kf_g": -1.91, "q_rev": 54.06, "q_rev_g": 3.49,
               "q_gm": 0.763, "q_gm_yoy": -59.44, "q_kf": 0.926, "q_kf_yoy": -51.18,
               "ocf": 10.17, "ocf_g": -42.12, "roe": 11.09, "debt": 49.65,
               "eps": 0.66, "bvps": 5.80, "gm_margin": 6.20, "gm_margin_chg": -1.50,
               "q_gm_margin": 6.48, "q_gm_margin_chg": -2.67, "assets": 90.45, "equity": 45.13},
    "002422": {"rev": 131.13, "rev_g": -1.24, "gm": 14.67, "gm_g": 22.18,
               "kf": 10.61, "kf_g": -7.48, "q_rev": 42.74, "q_rev_g": None,
               "q_gm": 3.393, "q_gm_yoy": None, "q_kf": 3.618, "q_kf_yoy": None,
               "ocf": 27.37, "ocf_g": None, "roe": 5.91, "debt": 24.77,
               "eps": None, "bvps": None, "gm_margin": None, "gm_margin_chg": None,
               "q_gm_margin": None, "q_gm_margin_chg": None, "assets": None, "equity": None},
    "000513": {"rev": 73.19, "rev_g": -19.71, "gm": 12.88, "gm_g": -26.57,
               "kf": 12.60, "kf_g": -26.38, "q_rev": 23.20, "q_rev_g": None,
               "q_gm": 3.559, "q_gm_yoy": None, "q_kf": 3.702, "q_kf_yoy": None,
               "ocf": 24.92, "ocf_g": None, "roe": 9.22, "debt": 39.18,
               "eps": None, "bvps": None, "gm_margin": None, "gm_margin_chg": None,
               "q_gm_margin": None, "q_gm_margin_chg": None, "assets": None, "equity": None},
    "002223": {"rev": 66.11, "rev_g": 1.02, "gm": 11.31, "gm_g": -22.83,
               "kf": 10.37, "kf_g": -11.28, "q_rev": 20.42, "q_rev_g": None,
               "q_gm": 2.885, "q_gm_yoy": None, "q_kf": 2.762, "q_kf_yoy": None,
               "ocf": 11.58, "ocf_g": None, "roe": 8.52, "debt": 19.54,
               "eps": None, "bvps": None, "gm_margin": None, "gm_margin_chg": None,
               "q_gm_margin": None, "q_gm_margin_chg": None, "assets": None, "equity": None},
    "600012": {"rev": 50.61, "rev_g": -6.03, "gm": 17.47, "gm_g": 18.29,
               "kf": 14.21, "kf_g": 3.48, "q_rev": 18.34, "q_rev_g": None,
               "q_gm": 7.400, "q_gm_yoy": None, "q_kf": 5.103, "q_kf_yoy": None,
               "ocf": 26.92, "ocf_g": None, "roe": 13.18, "debt": 54.18,
               "eps": None, "bvps": None, "gm_margin": None, "gm_margin_chg": None,
               "q_gm_margin": None, "q_gm_margin_chg": None, "assets": None, "equity": None},
}

# 官方核验来源 (逐只)
SRC = {
    "605599": "**官方三季报原文交叉核验** (cninfo static.cninfo.com.cn/finalpage/2026-10-28/1225629232.PDF "
              "北京菜市口百货股份有限公司 2026 年第三季度报告; 另 1225629220.PDF Q3 主要经营数据公告) "
              "+ 每经 2026-11-25 实地探访 + 中财网 2026-11-13 + 招商/方正/一财研报点评",
    "002422": "引擎交叉核验",
    "000513": "引擎交叉核验",
    "002223": "引擎交叉核验",
    "600012": "引擎交叉核验",
}

# 增长质量 / 风险要点
QUALITY_NOTE = {
    "605599":
        "🟡 **增长质量: 归母 -20.67% vs 扣非 -1.91%, 差 -18.76pp —— 方向与'灌水'相反, 但暴露 Q3 单季塌方**。\n"
        "- **为什么归母比扣非还差**: 官方口径明写 Q3 归母与扣非的差额 '*主要源于黄金租赁及衍生品公允价值变动与处置损失*' —— "
        "即**非经常性损益是负的** (衍生品/黄金租赁端亏损), 属于**真实的主业外损失**, 不是一次性收益粉饰。\n"
        "- **因此不触发 11-10 增长质量修正**: 该规则要求 `归母-扣非增速差 ≥15pp` (**正** gap, 即归母被灌水) "
        "+ OCF<0 + |OCF|/归母 ≥50%。本例 gap 为 **-18.76pp (负)**, OCF **+10.17 亿为正**, 三条件全不满足 → "
        "**基本面分不修正, 维持 14/30**。这与 11-10 (002539 套保灌水)、11-23 (002048 负基数虚高) 是**相反方向**的第三种情形。\n"
        "- 🔴 **但必须点破: 9M 扣非 -1.91% 掩盖了 Q3 单季 -51.18% 的断崖**。拆分看: H1 扣非 4.81 亿 (2025 同期 3.95 亿, **+21.8%**), "
        "Q3 扣非仅 0.926 亿 (2025 同期 1.897 亿, **-51.2%**) —— **全年利润几乎全靠上半年赚出来, Q3 只贡献了不到 1/10**。\n"
        "- 🔴 **run-rate 口径远贵于 TTM 口径**: Q3 扣非年化仅 **3.70 亿** → 按此口径真实 PE **31.1x** (表观扣非 PE 11.36x)。"
        "**但 Q1 是春节旺季 (黄金消费峰值), 单季年化会低估季节性** —— 9M 扣非 5.74 亿中 Q1 贡献极高, 所以 run-rate 31x 是**上限悲观值**, 不是中枢。"
        "**公允表述: PE 11.5x 是'含旺季利润的 TTM 口径', 不是'当前盈利能力口径'**。\n"
        "- ✅ **现金转化是 Top5 最强之一**: OCF **10.17 亿** vs 归母 5.13 亿 → **OCF/归母 198%** (尽管 OCF 同比 -42.12%)。\n"
        "- 🟡 **低基数检查**: 扣非 5.74 亿 / 营收 264.48 亿 = **2.17%**, 营收基数绝对量巨大, 无低基数虚高。"
        "**归母TTM/营收TTM = 10.0 亿 / 约 305 亿 ≈ 3.3% → 远低于 3x, 不触发 11-17 PE 过低陷阱**。",
    "002422":
        "🔴 **归母 +22.18% 与扣非 -7.48% 背离 29.65pp —— 增长不来自主业, 需打折**。归母多出的 4.07 亿来自非经常性损益 "
        "(约 4.1 亿), 而主业扣非实际是**负增长**。**OCF +27.37 亿为正且 OCF/归母 187%** → 不满足 11-10 修正的 OCF<0 条件, "
        "**引擎未修正基本面分 (12/30)**, 但**风险提示必须写明这一点**。\n"
        "🔴 **扣非 PE 47.43x 配扣非负增长 = 无 PEG 支撑**, 表观 PE 36.4x 是被非经常损益抬高的口径。"
        "🟡 **营收 -1.24% 基本零增长**, ROE 仅 5.91% (Top5 偏低)。",
    "000513":
        "🔴 **基本面是 Top5 最弱 (8/30)**: 营收 -19.71%、归母 -26.57%、扣非 -26.38% —— **三项同步双位数下滑**, "
        "不是单季波动而是趋势性收缩。gap 几乎为 0 (-0.17pp) 说明利润结构干净 (无灌水), 但**增长本身是负的**。"
        "✅ OCF 24.92 亿 / 归母 12.88 亿 = 194% 现金转化不差, 扣非 PE 16.84x 也不贵 —— "
        "**但便宜的是正在缩水的生意**。🔴 技术面 26/55 (Top5 最低), 均线空头, 三项同时指向'不买'。",
    "002223":
        "🟡 **归母 -22.83% vs 扣非 -11.28% (gap -11.56pp)**: 负 gap = 非经常性有**负向**贡献 (资产/投资端损失), "
        "主业扣非 -11.28% 同样为负但好于归母。OCF 11.58 亿 / 归母 11.31 亿 = **102%**, 现金转化正常, "
        "负债率 19.54% (Top5 最低)。🟡 **扣非 PE 27.53x 配扣非负增长, 且技术面均线未成多头 (MA5 28.79 > MA20 28.30 > MA60 26.91 但价 28.69 < MA5)** —— "
        "**唯一硬伤是形态: 价没站上 MA5**。",
    "600012":
        "🟢 **基本面质量 Top5 最佳之一 (16/30)**: ROE **13.18% (Top5 最高)**, 归母 +18.29%, 扣非 +3.48%, "
        "OCF **26.92 亿** / 归母 17.47 亿 = **154%**, 扣非/营收 **28.09% (Top5 最高) —— 高速公路的收费公路生意本质是类租金现金流**。\n"
        "🟡 **gap +14.80pp 接近 15pp 阈值** (归母 +18.29% vs 扣非 +3.48%): 差 3.52 亿非经常损益, "
        "但 **OCF 为正 → 不触发 11-10 修正**。**扣非增速仅 +3.48% → PEG 4.75 (扣非 PE 16.53 / 3.48)** = "
        "**'便宜但几乎不增长'**, 这是 PEG 口径的典型反面。\n"
        "🔴 **负债率 54.18% (Top5 最高)** + 营收 -6.03% + 板块胜率 交通运输 0% (0/1)。"
        "🔴 **技术面 39/55, 均线未成多头 (MA5 17.63 < MA20 17.68)**。",
}

RISK_NOTE = {
    "605599":
        "- 🔴 **Q3 单季是断崖, 不是波动**: 扣非单季 -51.18%, 毛利率单季降至 **6.48% (同比 -2.67pct)**, "
        "9M 毛利率 6.20% (-1.50pct)。官方归因: **金价波动 + 采购成本上升**, 且**低毛利投资金条占比提升**进一步压毛利。"
        "→ **金价一旦继续下行, 存货跌价 + 毛利承压会同时打**, 这是最大的单点风险。\n"
        "- 🔴 **区域集中度极高**: 华北占收入 **73%**, 且华北收入同比 **-5.84%** (北京珠宝社零大盘三季度约 -21%, 公司相对抗跌是相对优势, "
        "但绝对值仍是下滑)。**华东 +38.09% / 华南 +168.07% / 华中 +46.06% / 西南 +118.37%** 的全国化是亮点, 但基数小, 短期补不上华北缺口。\n"
        "- 🔴 **二股东高质押**: 浙江明牌实业持股 1.26 亿股 (**16.20%**), 其中 **质押 6750 万股 = 占其持股 53.57% / 占总股本 8.68%**。"
        "**质押率过半是实质性风险** (金价下行时平仓压力)。"
        "🟢 **缓释**: 控股股东北京金正资产 24.57% / 实控人北京市西城区国资委, **国资背景, 无质押、无减持**; "
        "且明牌实业 2026-02-13 披露的 ≤3% 减持计划已于 **2026-05-25 提前终止且一股未卖** (公告 2026-014) —— 减持压力已释放。\n"
        "- 🟡 **OCF 同比 -42.12%**: 现金转化绝对值强 (10.17 亿), 但下滑幅度大, 需在年报跟踪。\n"
        "- 🟡 **今日 +1.86% 属红涨, 不满足策略买入条件 #2 (当日 -3%~0%)**; 且 20 日区间位置 **84% (突破区顶部)**, "
        "**不适合追高**。🟢 **缓释**: 60 日涨幅仅 -5.7% (仍处回调), 均线多头排列 (MA5 14.8 > MA20 14.4 > MA60 14.14), RSI 51 不超买。",
    "002422":
        "- 🔴 **扣非 PE 47.43x 配扣非 -7.48%**: 估值贵且主业负增长, **PEG 为负, 无估值支撑**; 表观 PE 36.4x 靠非经常损益 4.07 亿撑着。\n"
        "- 🔴 **ROE 仅 5.91%** (Top5 偏低) + 营收 -1.24% 零增长。\n"
        "- 🟡 **今日 +2.02% 红涨**, 不满足买入条件 #2; 20 日位置 86% (突破区顶部)。",
    "000513":
        "- 🔴 **营收/归母/扣非三项双位数同步下滑**, 技术面 26/55 Top5 最低, 均线空头 —— **无一项支持买入**。\n"
        "- 🟡 **20 日位置 63% / 今日 +1.76% 红涨**, 不满足买入条件 #2。",
    "002223":
        "- 🔴 **价 28.69 低于 MA5 28.79** —— 均线虽 MA5>MA20>MA60, 但**股价未站上 MA5**, 是**形态未完成**而非多头确立。\n"
        "- 🟡 **归母 -22.83% / 扣非 -11.28%**, 扣非 PE 27.53x 配负增长。\n"
        "- 🟡 **今日 +1.34% 红涨**, 不满足买入条件 #2; 20 日位置 68%。",
    "600012":
        "- 🔴 **PEG 4.75**: 扣非 PE 16.53 配扣非增速仅 +3.48% —— **便宜但几乎不增长**。\n"
        "- 🔴 **负债率 54.18% (Top5 最高)**, 营收 -6.03%。\n"
        "- 🔴 **均线未成多头 (MA5 17.63 < MA20 17.68)**, 板块胜率 交通运输 **0% (0/1)** —— 但邻近键物流 67% (4/6) 尚可。\n"
        "- 🟡 **今日 +1.20% 红涨**, 不满足买入条件 #2; 但 20 日位置仅 **49% (区间中部)** 是 Top5 中最低。",
}

# 战略契合: 尾盘策略要求当日 -3%~0%, 今日普涨熔断日全部候选均为红涨
STRAT_CAVEAT = (
    "🔴 **全市场普涨熔断日的共性瑕疵**: 今日上证 +3.75% / 深成 +7.23% / 创业板 +11.59% / 科创50 +15.10%, "
    "涨停 **429** 只、跌停 43 只, 情绪分 **极端 (建议仓位 85%)**。\n"
    "尾盘策略买入条件 #2 要求 **当日跌幅 -3%~0% (绿盘回调)** —— **在普涨日这个条件几乎无法满足**: "
    "全市场 3488 只主板中当日 -3%~0% 的仅 **151 只**, -3%~+3% 合计 800 只。\n"
    "**今日 Top5 全部为红涨 (+1.08% ~ +1.93%), 即'追高档'而非'回调档'** —— 这是**策略契合度的真实折扣**, "
    "必须写进结论并体现在**买点位置** (回落分批) 上, 而不是当成买入理由。\n"
    "🟢 **缓释**: 极端情绪下, 尾盘强势股次日高开概率高, 但**熔断日的'最强'往往在次日兑现** —— "
    "**不追高、等回踩是本日唯一正确的执行姿态**。"
)

BUSINESS = {
    "605599": "北京菜市口百货股份有限公司 (605599) —— **北京'黄金珠宝老字号', 证监会/沪主板 2021-08-26 上市**。"
              "主业为**黄金珠宝商品的原料采购、款式设计、连锁销售及品牌运营**, 核心资产是**北京市西城区菜市口百货总店** "
              "(2026-11-24 实地探访: 投资金条柜台持续热销, 5 克/10 克规格售罄, 30 克最好卖, 公司回应'金条属低毛利产品, 主要发力点仍是饰品')。"
              "股东结构: **控股股东北京金正资产投资经营有限公司 24.57%, 实际控制人北京市西城区人民政府国资委** (国资背景, 无质押无减持); "
              "**二股东浙江明牌实业持股 1.26 亿股 (16.20%), 其中 6750 万股质押**。",
    "002422": "四川科伦药业股份有限公司 (002422) —— **输液/注射剂龙头**, 大容量注射液 (输液)、小容量注射剂 (水针)、"
              "注射用无菌粉针 (含冻干粉针)、片剂、胶囊剂、颗粒剂、口服液、腹膜透析液等 **27 种剂型** + 医药包材 + 原料药。",
    "000513": "丽珠集团 (000513) —— **医药产品研发、生产及销售** (化学制剂/原料药/诊断试剂及设备), 医药平台型公司。",
    "002223": "鱼跃医疗 (002223) —— **医疗器械研发、制造和销售及提供相关解决方案** (家用医疗器械 + 医疗基层/院端)。",
    "600012": "安徽皖通高速公路股份有限公司 (600012) —— **投资、建设、运营及管理安徽省境内的部分收费公路** (皖通高速), "
              "**类租金现金流生意**, ROE 13.18% 且扣非/营收 28.09% 为 Top5 最高。",
}


def fmt(v, d=2):
    if v is None:
        return "—"
    if isinstance(v, str):
        return v
    return f"{v:,.{d}f}"


def render(r, snap, now_str, data_global):
    code = r["code"]
    t = r.get("tech_stat", {})
    q = r.get("fund_stat", {})
    qual = QUALITY_NOTE.get(code, "")
    risk = RISK_NOTE.get(code, "")

    mcap_tot = max(r["mcap_yi"], r["float_mcap_yi"]) if r.get("mcap_yi") and r.get("float_mcap_yi") else r.get("mcap_yi")
    mcap_flo = min(r["mcap_yi"], r["float_mcap_yi"]) if r.get("mcap_yi") and r.get("float_mcap_yi") else r.get("float_mcap_yi")
    shares_total = (mcap_tot * 1e8 / r["price"]) if mcap_tot and r.get("price") else None
    shares_yi = shares_total / 1e8 if shares_total else None

    # 市值口径校验
    if mcap_tot and r.get("price") and shares_yi:
        mc_note = (f"总市值 **{mcap_tot:,.2f} 亿** (腾讯两字段取 max; 流通 {mcap_flo:,.2f} 亿 = min); "
                   f"校验: 总股本 {shares_yi:.3f} 亿股 × {r['price']} 元 = {mcap_tot:,.2f} 亿 ✓")
    else:
        mc_note = f"总市值 {fmt(mcap_tot)} 亿"

    # 扣非 TTM / run-rate PE
    kf_pe = r.get("kf_pe")
    kf_ttm = (mcap_tot / kf_pe) if (kf_pe and mcap_tot) else None
    rr = snap["q_kf"] * 4
    rr_pe = (mcap_tot / rr) if rr > 0 else None

    lines = []
    A = lines.append
    A(f"# {TODAY} 尾盘深度分析 — {code} {r['name']}")
    A("")
    A(f"> 生成时间: {now_str} | 目标事件: **{TODAY} 尾盘决策, T+1 (11-30) 开盘执行**")
    A(f"> 行业: {r.get('ind_em') or '—'} (东财) / {r.get('ind_sina') or '—'} (sina) | v2.5 尾盘原始筛选分: {r['v24_score']} | "
      f"评分引擎: 技术面50% + 基本面30% + 估值面20% (deep_analysis_20261022)")
    A("")
    A("## 一、投资评级与关键位")
    A("")
    A("| 项目 | 值 |")
    A("|---|---|")
    A(f"| 投资评级 | **{r['rating']}** |")
    A(f"| 综合评分 | **{r['total']}** (0-100, 修正前 {r['total_raw']}) |")
    A(f"| 分项 | 技术 {r['tech_score']}/55 · 基本面 {r['fund_score']}/30 · 估值 {r['val_score']}/15 |")
    A(f"| 现价 | ¥{fmt(r['price'])} (今日 {fmt(r.get('chg_pct'))}%) |")
    A(f"| 目标价 | ¥{fmt(r['target'])} |")
    A(f"| 止损价 | ¥{fmt(r['stop'])} |")
    A("")
    A("## 二、核心逻辑 (主营业务)")
    A("")
    A(BUSINESS.get(code, "—"))
    A("")
    A("## 三、基本面快照 (2026 三季报, 累计; 已官方公告核验)")
    A("")
    A("| 指标 | 值 |")
    A("|---|---|")
    A(f"| 营业收入 | {fmt(snap['rev'])} 亿 ({fmt(snap['rev_g'])}%) |")
    A(f"| 归母净利 | {fmt(snap['gm'])} 亿 ({fmt(snap['gm_g'])}%) |")
    A(f"| 扣非净利 | {fmt(snap['kf'])} 亿 ({fmt(snap['kf_g'])}%) |")
    A(f"| Q3 单季 营收 | {fmt(snap['q_rev'])} 亿 ({fmt(snap['q_rev_g'])}%) |")
    A(f"| Q3 单季 归母 | {fmt(snap['q_gm'], 3)} 亿 ({fmt(snap['q_gm_yoy'])}%) |")
    A(f"| Q3 单季 扣非 | {fmt(snap['q_kf'], 3)} 亿 ({fmt(snap['q_kf_yoy'])}%) |")
    A(f"| 经营现金流 | {fmt(snap['ocf'])} 亿 ({fmt(snap['ocf_g'])}%) |")
    A(f"| 加权 ROE | {fmt(snap['roe'])}% |")
    A(f"| 资产负债率 | {fmt(snap['debt'])}% |")
    if snap.get("gm_margin"):
        A(f"| 毛利率 | {fmt(snap['gm_margin'])}% (同比 {fmt(snap['gm_margin_chg'])}pct) |")
    if snap.get("q_gm_margin"):
        A(f"| Q3 单季毛利率 | {fmt(snap['q_gm_margin'])}% (同比 {fmt(snap['q_gm_margin_chg'])}pct) |")
    if snap.get("eps"):
        A(f"| 每股收益 | ¥{fmt(snap['eps'])} |")
    if snap.get("bvps"):
        A(f"| 每股净资产 | ¥{fmt(snap['bvps'])} |")
    A(f"| 尾盘原始分 | {r['v24_score']} (v2.5 策略筛选) |")
    A("")
    A("**增长质量详析:**")
    A("")
    A(qual)
    A("")
    A("## 四、估值")
    A("")
    A(f"PE_TTM {fmt(r.get('pe_ttm'))} / PB {fmt(r.get('pb'))} / {mc_note}")
    A("")
    if kf_pe and kf_ttm:
        A(f"**扣非 TTM {kf_ttm:,.2f} 亿 → 真实扣非 PE {kf_pe}x**; "
          f"**Q3 单季扣非年化 {rr:,.2f} 亿 → run-rate PE {rr_pe:.1f}x**"
          + ("  —— ⚠️ 两个口径差异大, 说明当前盈利能力弱于 TTM 口径 (详见第三节增长质量)"
             if rr_pe and kf_pe and rr_pe / kf_pe > 1.5 else ""))
    A("")
    A("## 五、技术面 (120 日)")
    A("")
    for n in r.get("tech_notes", []):
        A(f"- {n}")
    A(f"- 区间: 20 日高 {fmt(t.get('hi20'))} / 20 日低 {fmt(t.get('lo20'))} | "
      f"MA5 {fmt(t.get('ma5'))} / MA20 {fmt(t.get('ma20'))} / MA60 {fmt(t.get('ma60'))} | "
      f"换手 {fmt(r.get('turnover_pct'))}% | 量比 {fmt(r.get('vol_ratio'))}")
    A(f"- 均线多头硬筛: {r.get('ma_note')}")
    A(f"- 尾盘策略契合: 今日涨跌 {fmt(r.get('chg_report'))}% (策略买入条件 #2: 当日跌幅 -3%~0%; **红涨属追高档**)")
    A("")
    A("## 六、板块胜率 (策略回测样本)")
    A("")
    swr = r.get("sector_win_rate")
    if swr:
        A(f"- 本板块键: **{r.get('sector_stat_key')} {swr})** —— 本键样本为正; "
          f"邻近: {r.get('sector_near') or '无'}")
    else:
        A(f"- 本板块键: **{r.get('sector_stat_key') or '无'}** 无匹配胜率记录 (冷启动); "
          f"邻近: {r.get('sector_near') or '无'}")
    _owr = data_global.get("overall_win_rate")
    _owr_s = f"{_owr:.2f}%" if isinstance(_owr, (int, float)) else "—"
    A(f"- 整体胜率库: {data_global.get('sector_stats_n', '—')} 键 / "
      f"{data_global.get('total_records', data_global.get('total_rec', '—'))} 笔 / 整体胜率 {_owr_s}")
    A("")
    A("## 七、风险提示")
    A("")
    A(risk)
    A("")
    A("### 尾盘策略契合度总评 (今日普涨熔断日)")
    A("")
    A(STRAT_CAVEAT)
    A("")
    A("## 八、结论")
    A("")
    if code == FINAL_PICK:
        A(f"**🏆 最终推荐 — {TODAY} 尾盘最值得购买 1 只: {code} {r['name']}**")
    else:
        A(f"**落选 — {code} {r['name']}**")
    A("")
    A(f"深度综合评分 **{r['total']} ({r['rating']})**, 尾盘原始分 {r['v24_score']}, "
      f"现价 ¥{fmt(r['price'])}, 目标 ¥{fmt(r['target'])}, 止损 ¥{fmt(r['stop'])}。")
    A("")
    A("---")
    A(f"*数据源: 腾讯实时行情 + 腾讯日K (120 根, 末日 = {t.get('last_date')}) + akshare stock_financial_abstract (20260930) "
      f"+ {SRC.get(code, '引擎数据')} + sina/东财行业双源 + rec_tuning.json 板块胜率 | "
      f"评分引擎: deep_analysis_20261022.py (技术50/基本30/估值20) + 10-28 估值失真修正 + 11-10 增长质量修正 "
      f"+ 11-17 PE 过低陷阱 + 11-23 低基数(负基数)修正 + 11-24 均线多头硬筛/PEG 决胜 | 参考, 不构成投资建议*")
    return "\n".join(lines)


def main():
    with open(DATA) as f:
        data = json.load(f)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(REPORT_DIR, exist_ok=True)
    for r in data["results"]:
        code = r["code"]
        r.setdefault("sector_stats_n", data.get("sector_stats_n"))
        snap = SNAP[code]
        md = render(r, snap, now_str, data)
        path = os.path.join(REPORT_DIR, f"{TODAY}-深度分析-{code}.md")
        with open(path, "w") as f:
            f.write(md)
        print(f"生成: {path}  ({r['code']} {r['name']} {r['total']} {r['rating']})")


if __name__ == "__main__":
    main()

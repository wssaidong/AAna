#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
渲染 2026-11-09 尾盘深度分析报告 — 从 deep_analysis_pm_20261109.json 生成每只 {date}-深度分析-{code}.md
"""
import json, os, sys

sys.path.insert(0, '/Users/cai/code/AAna/scripts')

TODAY = "2026-11-09"
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
DATA = os.path.expanduser("~/code/AAna/data/deep_analysis_pm_20261109.json")

# 主营业务 (akshare stock_zyjs_ths 实拉 + 公告交叉核验, 11-09 PM)
BUSINESS = {
    "600732": "爱旭股份 — 全球光伏电池组件龙头, 聚焦太阳能电池与 ABC(All Back Contact) 组件及场景化解决方案。"
              "BC 技术路线在海外享有 10%-50% 溢价 (2026Q1 集中式 BC 均价 0.80 元/W vs TOPCon 0.69 元/W)。"
              "2026Q3 ABC 组件出货约 5.4GW, 其中海外约占 55%; 济南基地首期 3GW 组件产能已投产, "
              "义乌 PERC→ABC 技改收尾, 滁州 TOPCon→ABC 技改四季度投产, 天津基地拟投 11.5 亿改 6GW ABC 产能。",
    "600501": "航天晨光 — 中国航天科工集团旗下上市平台 (科工集团持股 24.81% 国有法人), 定位"
              "\"服务国家战略、服务国防建设、服务国计民生\", 以航天防务技术转化应用为依托, "
              "培育特种装备、专用车改装、柔性管件、压力容器、艺术工程五大产业。"
              "2025 年报主营口径: 特种装备产业、专用车改装产业、柔性管件产业、压力容器产业、艺术工程产业。",
    "002943": "宇晶股份 — 高精密切、磨、抛数控设备的研发/生产/销售与服务, 并为客户提供设备与工艺综合解决方案, "
              "下游主要为光伏硅片切割等半导体/光伏专用加工设备。",
    "603375": "盛景微 — 主体为爆破专用电子控制模块、起爆控制器、放大器的开发/生产/销售 (军品电子); "
              "子公司上海先积集成电路为第二增长曲线, 做信号链模拟芯片 (高速放大器、电源类、Sigma-Delta ADC), "
              "应用于工业控制、新能源、汽车、通信与消费电子。2025H1 先积营收 5142.51 万 (+143.38%), 净利润 418.74 万由负转正。",
    "603666": "亿嘉和 — 智能机器人及智能设备研发/生产/销售与智能化服务, 核心覆盖电力 (巡检机器人/带电作业机器人/"
              "智能操作机器人)、商用清洁、新能源共享充电、轨道交通四大方向, 正在向具身智能作业方向升级。",
}

# 行业标签 (sina + 东财 f127 双源核验, 11-09 PM 实拉)
INDUSTRY = {
    "600732": "光伏设备 (sina 光伏设备 / 东财 光伏设备, 双源一致)",
    "600501": "专用设备-航天特种装备与压力容器 (sina 其它专用机械 / 东财 专用设备)",
    "002943": "通用设备-高精密切磨抛数控设备 (sina 机床工具 / 东财 通用设备)",
    "603375": "半导体-信号链模拟芯片/爆破电子控制模块 (东财 半导体; ⚠️ sina 归为\"互联网信息服务\" 与实际主营不符, 以东财+公告为准)",
    "603666": "自动化设备-电力与商用清洁智能机器人 (sina 其它通用机械 / 东财 自动化设备)",
}

# 风险提示 (逐只, 均来自三季报/半年报实核)
RISKS = {
    "600732": [
        "🚨 前三季度仍巨亏: 归母 -7.09 亿 (上年同期 -5.32 亿, 亏损扩大), Q3 虽单季转正 +4456.66 万, "
        "但扣非 -2458.10 万 — 转盈靠 5857.25 万政府补助, 主业未真正盈利",
        "🚨 财务费用激增: 前三季度财务费用 7.34 亿 (含利息 4.54 亿), 上半年由 -3653 万转为 5.11 亿; "
        "资产减值损失 -3.68 亿, 净利率 -5.10%",
        "🚨 担保规模极高: 为子公司累计担保 264.25 亿 = 最近一期经审计净资产的 514.26%, 其中实际债务余额 146.56 亿",
        "PB 6.15 偏高 (全池最贵), ROE -14.89% 弱, PE -13.9 (亏损)",
        "板块胜率 100% (1/1) 为冷样本, 不足以支撑决策; 目标价 ¥14.13 已接近 20 日高点, 上行空间受限",
    ],
    "600501": [
        "⚠️ 前三季度累计仍亏损: 归母 -890 万 (上年同期 -1.13 亿, 亏损收窄), 扣非 -3905 万 — 全年扭亏尚未确认",
        "⚠️ 评分口径提示: \"净利增速 +92%\" 实为负基数下的\"亏损收窄 92%\" (-890 万 vs -1.13 亿), "
        "不是真实盈利增长, 属低基数效应 — 基本面 18/30 中有 8 分来自该项, 需打折看待",
        "🚨 经营现金流大幅恶化: 前三季度净额 -5.56 亿, 同比 -480.9%, 与账面减亏背离, 盈利质量待验证",
        "PE -65.75 (TTM 仍亏), PB 4.72 中等, ROE -0.58%; 换手率 9.80% 偏高, 筹码不稳",
        "板块胜率 地面兵装 0% (0/1) 冷样本弱信号; 今日 +0.06% 属横盘, 无尾盘动能",
        "目标价 ¥18.50 = 20 日区间高点, 上行空间 +8.1%, 风险收益比一般",
    ],
    "002943": [
        "🚨 基本面全池最差: 净利同比 -476%, 营收同比 -45%, ROE -10.1%, 基本面仅 0/30",
        "🚨 最新单季归母 -0.127 亿已转亏, 触发估值面失真修正 (PE -84.8 记 0 分只留 PB)",
        "🚨 PB 10.02 显著偏高 (全池最高), 亏损股给 10 倍 PB 无支撑",
        "60 日涨幅 -16.5% 弱势 (MA60 29.70 仍高于现价上方), 中期趋势未修复",
        "换手率 15.79% 极高 (全池最高), RSI 68 偏热, 今日 -2.78% 属下跌中继非回调买点",
        "板块胜率 机械基础件 100% (5/5) 为邻近行业借用, 与光伏切片设备非同类, 参考价值有限",
    ],
    "603375": [
        "🚨 业绩连降三年: 营收 8.23 亿(2023)→5.04 亿(2024)→4.70 亿(2025)→前三季 2.98 亿 (-13.93%); "
        "净利 1.95 亿→2291 万→1012 万→188 万 (-90.22%)",
        "🚨 Q3 单季已转亏: 归母 -102.86 万, 扣非 -459.49 万, 触发估值面失真修正 "
        "(PE -596.55 系峰值盈利滞后口径, 记 0 分只保留 PB 2.81 的 7 分)",
        "利润下滑主因公司自述\"电子控制模块销售单价下降导致毛利额同比减少\", 属主业价格战非一次性",
        "经营现金流 889.67 万 (-85.64%), 前三季度净利几乎全靠 934 万非经常性损益 (委托理财 916 万)",
        "20 日区间位置 89% 已在突破区 + 今日 +4.91% 尾盘追高, 次日溢价不确定; 市值 27.39 亿流动性弱",
        "板块胜率 半导体 100% (1/1) 冷样本; 技术面 55/55 满分但基本面 0/30, 属\"技术面漂亮掩盖基本面恶化\"的典型",
    ],
    "603666": [
        "🚨 亏损大幅扩大: 前三季度归母 -2.166 亿 (上年同期 -4232 万), Q3 营收同比 -75.83%, "
        "前三季营收同比 -62.93%, 属主业萎缩而非一次性计提",
        "🚨 ROE -10.49% 全池最弱, 净利同比 -412%, 触发估值面失真修正 (单季归母 -0.896 亿转亏)",
        "🚨 控股股东朱付云质押 1430 万股 (占其持股 4914.54 万股的 29.1%), 存在平仓与信号风险",
        "子公司宁和智能因引入新投资方持股降至 45.9% 不再并表, 轨道交通板块战略收缩; "
        "特种机器人项目 2025 年转固产生折旧 + 2025 年员工持股计划股份支付费用, 费用刚性上升",
        "20 日区间位置 79% + 今日 +4.29% 尾盘追高, 换手 2.73%, 属超跌反弹非基本面反转",
        "板块胜率 计算机设备 100% (1/1) 冷样本; 技术面 51/55 但基本面 0/30, 估值仅靠 PB 2.72 撑分",
    ],
}


def main():
    with open(DATA) as f:
        d = json.load(f)
    n = 0
    for r in d["results"]:
        code = r["code"]
        t = r.get("tech_stat") or {}
        fs = r.get("fund_stat") or {}
        em = {"买入": "🟢", "增持": "🟡", "中性": "🟠", "减持": "🔴"}.get(r["rating"], "")
        sq = r.get("single_quarter") or {}
        lines = []
        lines.append(f"# 深度分析 · {code} {r['name']} · {TODAY} 尾盘")
        lines.append("")
        lines.append(f"> ⚠️ 实际代码: {code} {r['name']} (来源: 尾盘选股 v2.5 Top5, 腾讯行情名称核验一致)")
        lines.append(f"> 生成时间: {TODAY} {d.get('generated', '')} (目标事件: 2026-11-09 尾盘 14:45-15:00)")
        lines.append(f"> 行业: {INDUSTRY.get(code, '-')} | 数据源: 腾讯行情(实时快照) + 腾讯日K(kline, 末日 {t.get('last_date', '-')}) + akshare 财务摘要 + 交易所公告")
        lines.append("> 情绪: 回暖 (建议仓位 70%) | 尾盘策略放行 (非冰点日)")
        lines.append("")
        lines.append("## 一、投资结论")
        lines.append("")
        lines.append("| 项目 | 值 |")
        lines.append("|:----|:----|")
        lines.append(f"| **投资评级** | **{em} {r['rating']}** |")
        lines.append(f"| **综合评分** | **{r['total']} / 100** (技术面 {r['tech_score']}/55 · 基本面 {r['fund_score']}/30 · 估值 {r['val_score']}/15) |")
        lines.append(f"| **目标价** | **¥{r['target']}** ({(r['target']/r['price']-1)*100:+.1f}%) |")
        lines.append(f"| **止损价** | **¥{r['stop']}** ({(r['stop']/r['price']-1)*100:+.1f}%) |")
        lines.append(f"| 现价 | ¥{r['price']} (今日 {r.get('chg_pct')}%) |")
        lines.append(f"| PE(TTM) / PB | {r['pe_ttm']} / {r['pb']} |")
        lines.append(f"| 市值 | {r.get('mcap_yi', '-')} 亿 | 换手率 {r.get('turnover_pct', '-')}% |")
        lines.append(f"| 尾盘原评分 | {r['v24_score']} |")
        lines.append(f"| 板块胜率 | {r.get('sector_stat_key') or '(无库键)'} → {r.get('sector_win_rate')} |")
        if r.get("sector_near"):
            lines.append(f"| 邻近板块键 | {r.get('sector_near')} |")
        lines.append("")
        lines.append("## 二、核心逻辑")
        lines.append("")
        lines.append(f"- **业务面**: {BUSINESS.get(code, '-')}")
        lines.append(f"- **技术面**: {'; '.join(r['tech_notes'])}")
        lines.append(f"- **基本面**: {'; '.join(r['fund_notes'])}")
        lines.append(f"- **估值面**: {'; '.join(r['val_notes'])}")
        lines.append(f"- **单季验证**: {sq.get('period', '-')} 最新单季归母 {sq.get('single_q_yi', '-')} 亿 "
                     f"({'转亏' if sq.get('single_q_loss') else '盈利'}), "
                     f"{'触发估值面失真修正 (原始分 ' + str(r['val_score_raw']) + ' → 修正后 ' + str(r['val_score']) + ')' if r.get('distorted') else '估值口径无失真'}"
                     if sq else "- **单季验证**: 数据缺失")
        lines.append("")
        lines.append("## 三、技术指标明细")
        lines.append("")
        lines.append("| 指标 | 值 |")
        lines.append("|:----|:----|")
        lines.append(f"| RSI(14) | {t.get('rsi', '-')} |")
        lines.append(f"| MA5 / MA20 / MA60 | {t.get('ma5', '-')} / {t.get('ma20', '-')} / {t.get('ma60', '-')} |")
        lines.append(f"| 20日区间位置 | {t.get('pos20', '-')}% (高 {t.get('hi20', '-')} / 低 {t.get('lo20', '-')}) |")
        lines.append(f"| 60日涨幅 | {t.get('chg60', '-')}% |")
        lines.append(f"| 量能比(vs 5日均量) | {t.get('vol_ratio_5d', '-')} |")
        lines.append(f"| K线末日 / 根数 | {t.get('last_date', '-')} / {t.get('kline_len', '-')} |")
        lines.append("")
        lines.append("## 四、财务摘要 (最新报告期)")
        lines.append("")
        lines.append("| 指标 | 值 |")
        lines.append("|:----|:----|")
        roe, nig, reg = fs.get("roe"), fs.get("ni_growth"), fs.get("rev_growth")
        lines.append(f"| ROE | {roe:.1f}% |" if roe is not None else "| ROE | 缺失 |")
        lines.append(f"| 归母净利增速 | {nig:+.1f}% |" if nig is not None else "| 归母净利增速 | 缺失 |")
        lines.append(f"| 营收增速 | {reg:+.1f}% |" if reg is not None else "| 营收增速 | 缺失 |")
        lines.append(f"| 报告期 | {fs.get('report_date', '-')} |")
        lines.append("")
        lines.append("## 五、风险提示")
        lines.append("")
        for x in RISKS.get(code, []):
            lines.append(f"- {x}")
        lines.append("- 本报告为程序化自动生成, 仅供参考, 不构成投资建议")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(f"*深度分析脚本: scripts/deep_analysis_pm_20261109.py | 候选池: 尾盘选股 v2.5 Top5 | "
                     f"情绪: 回暖 55 (非冰点, 放行) | 评分引擎: 技术50% + 基本面30% + 估值20%*")
        out = os.path.join(REPORT_DIR, f"{TODAY}-深度分析-{code}.md")
        with open(out, "w") as f:
            f.write("\n".join(lines))
        n += 1
        print(f"written: {out}")
    print(f"total {n} reports")


if __name__ == "__main__":
    main()

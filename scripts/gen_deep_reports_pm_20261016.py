#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 4 只候选的深度分析报告 md (从 deep_analysis_pm_20261016.json 渲染)"""
import json, os

TODAY = "2026-10-16"
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
DATA = os.path.expanduser("~/code/AAna/data/deep_analysis_pm_20261016.json")

BUSINESS = {
    "002270": "华明装备 — 国内分接开关龙头 (全球第2/中国第1, 市占率~90%国内), 主业电网设备核心部件, 现金流稳定, 出海+特高压驱动",
    "603101": "汇嘉时代 — 新疆区域零售龙头 (超市+百货), 净利高增 +46%, 受益区域消费复苏",
    "002674": "兴业科技 — 牛皮革龙头 (鞋面革主业), 净利 +37% 低基数修复, 周期属性强",
    "002264": "新华都 — 福建零售+电商代运营, 净利 -4% 负增长, 60日已涨 25.6% 透支部分预期",
}

with open(DATA) as f:
    d = json.load(f)

for r in d["results"]:
    code = r["code"]
    t = r["tech_stat"]; fs = r["fund_stat"]
    lines = []
    lines.append(f"# 深度分析 · {code} {r['name']} · {TODAY} 尾盘")
    lines.append("")
    lines.append(f"> ⚠️ 实际代码: {code} {r['name']} (来源: 尾盘选股 Top5, 腾讯行情名称核验一致)")
    lines.append(f"> 生成时间: {TODAY} {d['generated']} | 数据源: 腾讯行情+日K(qfq) / akshare 财务摘要({fs.get('error','ok')})")
    lines.append("")
    lines.append("## 一、投资结论")
    lines.append("")
    lines.append(f"| 项目 | 值 |")
    lines.append(f"|:----|:----|")
    rating_emoji = {"买入": "🟢", "增持": "🟡", "中性": "🟠", "减持": "🔴"}.get(r["rating"], "")
    lines.append(f"| **投资评级** | **{rating_emoji} {r['rating']}** |")
    lines.append(f"| **综合评分** | **{r['total']} / 100** (技术面 {r['tech_score']}/55 · 基本面 {r['fund_score']}/30 · 估值 {r['val_score']}/15) |")
    lines.append(f"| **目标价** | **¥{r['target']}** (+{(r['target']/r['price']-1)*100:.1f}%) |")
    lines.append(f"| **止损价** | **¥{r['stop']}** ({(r['stop']/r['price']-1)*100:.1f}%) |")
    lines.append(f"| 现价 | ¥{r['price']} (今日 {r['chg_pct']:+.2f}%) |")
    lines.append(f"| 市值 | {r['mcap_yi']:.1f} 亿 |")
    lines.append(f"| PE(TTM) / PB | {r['pe_ttm']:.1f} / {r['pb']:.2f} |")
    lines.append("")
    lines.append("## 二、核心逻辑")
    lines.append("")
    lines.append(f"- **业务面**: {BUSINESS.get(code, '-')}")
    lines.append(f"- **技术面**: {'; '.join(r['tech_notes'])}")
    lines.append(f"- **基本面**: {'; '.join(r['fund_notes'])}")
    lines.append(f"- **估值面**: {'; '.join(r['val_notes'])}")
    lines.append("")
    lines.append("## 三、技术指标明细")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|:----|:----|")
    lines.append(f"| RSI(14) | {t.get('rsi')} |")
    lines.append(f"| MA5 / MA20 / MA60 | {t.get('ma5')} / {t.get('ma20')} / {t.get('ma60')} |")
    lines.append(f"| 20日区间位置 | {t.get('pos20')}% (高 {t.get('hi20')} / 低 {t.get('lo20')}) |")
    lines.append(f"| 60日涨幅 | {t.get('chg60'):+.1f}% |")
    lines.append(f"| 量能比(vs 5日均量) | {t.get('vol_ratio_5d')} |")
    lines.append("")
    lines.append("## 四、财务摘要 (最新报告期)")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|:----|:----|")
    roe = fs.get("roe"); nig = fs.get("ni_growth"); reg = fs.get("rev_growth")
    lines.append(f"| ROE | {roe:.1f}% |" if roe is not None else "| ROE | 缺失 |")
    lines.append(f"| 归母净利增速 | {nig:+.1f}% |" if nig is not None else "| 归母净利增速 | 缺失 |")
    lines.append(f"| 营收增速 | {reg:+.1f}% |" if reg is not None else "| 营收增速 | 缺失 |")
    lines.append("")
    lines.append("## 五、风险提示")
    lines.append("")
    if code == "002270":
        lines.append("- PB 5.38 偏高于板块均值; 出口/汇率波动影响海外分接开关业务")
        lines.append("- 20日位置 89% 突破区, 短线追高需控制仓位")
    elif code == "603101":
        lines.append("- 区域零售天花板明显; 净利高增或含低基数效应")
        lines.append("- PE 33.9 对零售业偏高, 增速不可持续则估值回归")
    elif code == "002674":
        lines.append("- 制革业强周期, 60日 -18.4% 弱势反弹性质待确认; PE 55 偏高")
    elif code == "002264":
        lines.append("- 净利负增长 -4%; 60日 +25.6% 已透支, 电商代运营竞争激烈")
    lines.append("- 本报告为程序化自动生成, 仅供参考, 不构成投资建议")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"*深度分析脚本: scripts/deep_analysis_pm_20261016.py | 候选池: 尾盘选股 v2.5 Top5 (剔除 ST)*")

    out = os.path.join(REPORT_DIR, f"{TODAY}-深度分析-{code}.md")
    with open(out, "w") as f:
        f.write("\n".join(lines))
    print(f"written: {out} ({len(chr(10).join(lines))} chars)")

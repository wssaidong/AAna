#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
渲染 2026-11-04 尾盘深度分析报告 — 从 deep_analysis_pm_20261104.json 生成每只 {date}-深度分析-{code}.md
"""
import json, os, sys

sys.path.insert(0, '/Users/cai/code/AAna/scripts')

TODAY = "2026-11-04"
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
DATA = os.path.expanduser("~/code/AAna/data/deep_analysis_pm_20261104.json")

# 主营业务 (akshare stock_zyjs_ths 实拉, 11-04 PM)
BUSINESS = {
    "002352": "顺丰控股 — 综合性快递物流服务 (时效快递/快运/冷运/供应链), 鄂州枢纽 + 科技驱动, "
              "现金流与盈利质量为行业最优, 估值长期低于国际同业",
    "002518": "科士达 — 研发/生产/销售 UPS 电源、太阳能逆变器及配套阀控式密封铅酸蓄电池, "
              "数据中心与储能双场景受益, 海外渠道占比高",
    "600487": "亨通光电 — 光通信 + 智能电网 + 工业与新能源智能 + 海洋能源/海洋通信 全套解决方案, "
              "AI 数据中心光纤光缆与海缆景气受益",
    "603859": "能科科技 — AI 产品与服务、云产品与服务、软件系统服务、工业工程与工业电气产品服务 "
              "(石化/流程工业数字化与智能制造)",
    "603407": "长裕集团 — 锆类产品、特种尼龙产品及精细化工产品的研发/生产/销售 "
              "(锆系新材料 + 特种尼龙, 化工新材料赛道)",
}

# 行业标签 (sina + 东财 f127 双源核验 + akshare stock_zyjs_ths 主营, 11-04 PM 实拉)
INDUSTRY = {
    "002352": "交通运输-物流 (综合性快递物流服务)",
    "002518": "电力设备-UPS/光伏逆变器 (储能设备 / 其他电源设备)",
    "600487": "通信-通信传输设备 (光通信/智能电网/海洋能源)",
    "603859": "工控自动化-IT服务 (AI/云/软件系统服务, 流程工业数字化)",
    "603407": "基础化工-其他化学制品 (锆产品/特种尼龙/精细化工)",
}

# 风险提示 (逐只)
RISKS = {
    "002352": [
        "净利同比 -1% 基本停滞, 营收仅 +5.5%, 盈利拐点尚未确认 (基本面仅 11/30)",
        "RSI 70.7 偏热, 20日区间位置 85% 已在突破区, 短线追高风险上升",
        "快递价格战持续, 单票收入承压; 行业监管/加盟商稳定性风险",
    ],
    "002518": [
        "价格在 MA20/MA60 下方 (MA20 28.53 vs 现价 27.82), 60日涨幅 -13.5%, 属超跌反弹而非趋势反转",
        "今日 +6.8% 已过 5% 追高线, 尾盘买入次日溢价不确定",
        "储能/数据中心板块波动大, 订单能见度受资本开支周期影响",
    ],
    "600487": [
        "基本面最优 (ROE 17.9%/净利 +159%), 但技术面弱: 价 < MA20 < MA60, 60日涨幅 -13.6%, 20日位置仅 28%",
        "今日 +7.4% 属追高, 尾盘纪律 (涨幅>5% 不追) 不适配",
        "光通信板块前期涨幅大, 海缆订单交付节奏决定业绩兑现",
    ],
    "603859": [
        "ROE 3.4% 偏弱 + 净利同比 -25%, 基本面仅 6/30",
        "PE 55 显著偏高, 与其盈利质量不匹配",
        "IT/软件服务估值与业绩兑现节奏错配风险, 客户结构决定订单波动",
    ],
    "603407": [
        "PE 52 + PB 7.69 双重偏高, 估值面仅 3/15",
        "市值仅 15.4 亿, 流动性风险高, 波动剧烈",
        "锆产品/特种尼龙属小众化工新材料, 需求与价格波动大, 客户集中风险",
        "60日涨幅 -26.6% 全池最弱, 技术面 15/55 (价 < MA20 < MA60)",
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
        lines.append(f"> 生成时间: {TODAY} {d.get('generated', '')} (目标事件: 2026-11-04 尾盘 14:45-15:00)")
        lines.append(f"> 行业: {INDUSTRY.get(code, '-')} | 数据源: 腾讯行情(实时快照) + 腾讯日K(kline/kline, 末日 {t.get('last_date', '-')}) + akshare 财务摘要")
        lines.append(f"> 情绪: 亢奋 (建议仓位 85%) | 尾盘策略放行 (非冰点日)")
        lines.append("")
        lines.append("## 一、投资结论")
        lines.append("")
        lines.append("| 项目 | 值 |")
        lines.append("|:----|:----|")
        lines.append(f"| **投资评级** | **{em} {r['rating']}** |")
        lines.append(f"| **综合评分** | **{r['total']} / 100** (技术面 {r['tech_score']}/55 · 基本面 {r['fund_score']}/30 · 估值 {r['val_score']}/15) |")
        lines.append(f"| **目标价** | **¥{r['target']}** ({(r['target']/r['price']-1)*100:+.1f}%) |")
        lines.append(f"| **止损价** | **¥{r['stop']}** ({(r['stop']/r['price']-1)*100:.1f}%) |")
        lines.append(f"| 现价 | ¥{r['price']} (今日 {r.get('chg_pct')}%) |")
        lines.append(f"| PE(TTM) / PB | {r['pe_ttm']} / {r['pb']} |")
        lines.append(f"| 市值 | {r.get('mcap_yi', '-')} 亿 |")
        lines.append(f"| 尾盘原评分 | {r['v24_score']} |")
        lines.append(f"| 板块胜率 | {r.get('sector_stat_key') or '(无库键)'} → {r.get('sector_win_rate')} |")
        lines.append("")
        lines.append("## 二、核心逻辑")
        lines.append("")
        lines.append(f"- **业务面**: {BUSINESS.get(code, '-')}")
        lines.append(f"- **技术面**: {'; '.join(r['tech_notes'])}")
        lines.append(f"- **基本面**: {'; '.join(r['fund_notes'])}")
        lines.append(f"- **估值面**: {'; '.join(r['val_notes'])}")
        lines.append(f"- **单季验证**: {sq.get('period', '-')} 最新单季归母 {sq.get('single_q_yi', '-')} 亿 "
                     f"({'转亏' if sq.get('single_q_loss') else '盈利'}), 估值口径无失真"
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
        lines.append(f"*深度分析脚本: scripts/deep_analysis_pm_20261104.py | 候选池: 尾盘选股 v2.5 Top5 | "
                     f"情绪: 亢奋 (非冰点, 放行) | 评分引擎: 技术50% + 基本面30% + 估值20%*")
        out = os.path.join(REPORT_DIR, f"{TODAY}-深度分析-{code}.md")
        with open(out, "w") as f:
            f.write("\n".join(lines))
        n += 1
        print(f"written: {out}")
    print(f"total {n} reports")


if __name__ == "__main__":
    main()

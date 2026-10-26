#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""渲染 2026-10-26 尾盘深度分析报告 — 从 deep_analysis_pm_20261026.json 生成每只 {date}-深度分析-{code}.md"""
import json, os

TODAY = "2026-10-26"
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
DATA = os.path.expanduser("~/code/AAna/data/deep_analysis_pm_20261026.json")

# 主营业务 (akshare stock_zyjs_ths 2026-10-26 实拉)
BUSINESS = {
    "603348": "文灿股份 — 汽车铝合金精密压铸件 (车身结构/一体化压铸/底盘), 客户含新能源车企, 2026 亏损 (PE 负) 但 PB 1.23 低位",
    "603882": "金域医学 — 第三方医学检验 (ICL) 龙头, 病理诊断+特检业务, 普检价格承压致 PE(TTM) 偏高, 基本面温和修复",
    "603355": "莱克电气 — 超高速数码电机为核心, 清洁电器/智能净饮机/园林工具/空气压缩机, 自有品牌+代工双轮, ROE 亏损口径",
    "001239": "永达股份 — 大型专用设备金属结构件+高速重载齿轮锻件 (风电塔筒法兰/船用锻件), 风电产业链, 净利负增长 (PE 负)",
    "603037": "凯众股份 — 汽车底盘悬架减震元件+轻量化踏板总成, 聚氨酯承载轮 (非汽车), 智能驾驶/新能源客户延伸, 净利负增长",
}

# 行业标签 (人工修正; 001239 为 申万通用设备/风电锻件, 非汽车经销 — 消歧教训)
INDUSTRY = {
    "603348": "汽车零部件-铝合金压铸",
    "603882": "医疗服务-ICL 医学检验",
    "603355": "小家电-电机/清洁电器",
    "001239": "通用设备-风电/重载锻件",
    "603037": "汽车零部件-底盘减震/踏板",
}


def main():
    with open(DATA) as f:
        d = json.load(f)
    n = 0
    for r in d["results"]:
        code = r["code"]
        t = r.get("tech_stat") or {}
        fs = r.get("fund_stat") or {}
        lines = []
        lines.append(f"# 深度分析 · {code} {r['name']} · {TODAY} 尾盘")
        lines.append("")
        lines.append(f"> ⚠️ 实际代码: {code} {r['name']} (来源: 尾盘选股 v2.5 Top5, 腾讯行情名称核验一致)")
        lines.append(f"> 生成时间: {TODAY} {d.get('generated','')} (目标事件: 2026-10-26 尾盘 14:50-15:00)")
        lines.append(f"> 行业: {INDUSTRY.get(code, '-')} | 数据源: 腾讯行情 + 腾讯日K(kline/kline, 末日 {t.get('last_kline_date','-')}) + akshare 财务摘要({fs.get('error','ok')})")
        lines.append("")
        lines.append("## 一、投资结论")
        lines.append("")
        lines.append("| 项目 | 值 |")
        lines.append("|:----|:----|")
        em = {"买入": "🟢", "增持": "🟡", "中性": "🟠", "减持": "🔴"}.get(r["rating"], "")
        lines.append(f"| **投资评级** | **{em} {r['rating']}** |")
        lines.append(f"| **综合评分** | **{r['total']} / 100** (技术面 {r['tech_score']}/55 · 基本面 {r['fund_score']}/30 · 估值 {r['val_score']}/15) |")
        lines.append(f"| **目标价** | **¥{r['target']}** ({(r['target']/r['price']-1)*100:+.1f}%) |")
        lines.append(f"| **止损价** | **¥{r['stop']}** ({(r['stop']/r['price']-1)*100:.1f}%) |")
        lines.append(f"| 现价 | ¥{r['price']} (盘中 {r.get('live_chg_pct','?')}%) |")
        lines.append(f"| PE(TTM) / PB | {r['pe_ttm']} / {r['pb']} |")
        lines.append(f"| 市值 | {r.get('mcap_yi','-')} 亿 |")
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
        lines.append(f"| RSI(14) | {t.get('rsi','-')} |")
        lines.append(f"| MA5 / MA20 / MA60 | {t.get('ma5','-')} / {t.get('ma20','-')} / {t.get('ma60','-')} |")
        lines.append(f"| 20日区间位置 | {t.get('pos20','-')}% (高 {t.get('hi20','-')} / 低 {t.get('lo20','-')}) |")
        lines.append(f"| 60日涨幅 | {t.get('chg60','-')}% |")
        lines.append(f"| 量能比(vs 5日均量) | {t.get('vol_ratio_5d','-')} |")
        lines.append("")
        lines.append("## 四、财务摘要 (最新报告期)")
        lines.append("")
        lines.append("| 指标 | 值 |")
        lines.append("|:----|:----|")
        roe, nig, reg = fs.get("roe"), fs.get("ni_growth"), fs.get("rev_growth")
        lines.append(f"| ROE | {roe:.1f}% |" if roe is not None else "| ROE | 缺失 |")
        lines.append(f"| 归母净利增速 | {nig:+.1f}% |" if nig is not None else "| 归母净利增速 | 缺失 |")
        lines.append(f"| 营收增速 | {reg:+.1f}% |" if reg is not None else "| 营收增速 | 缺失 |")
        lines.append(f"| 报告期 | {fs.get('report_date','-')} |")
        lines.append("")
        lines.append("## 五、风险提示")
        lines.append("")
        if code == "603348":
            lines.append("- 2026 年报亏损 (PE 为负), 一体化压铸价格战+客户账期压力, 左侧属性强")
            lines.append("- 技术面 60日涨幅偏高区间, 追涨盈亏比一般")
        elif code == "603882":
            lines.append("- PE(TTM) 145 高企, ICL 普检降价周期未结束, 盈利修复速度存疑")
            lines.append("- 医疗服务板块 2026 政策扰动 (集采/DRG) 持续")
        elif code == "603355":
            lines.append("- 小家电出口占比高, 关税/汇率波动直接影响利润")
            lines.append("- 净利负增长 (ROE 口径弱), 估值面中性")
        elif code == "001239":
            lines.append("- 风电塔筒法兰竞争加剧, 净利负增长 (PE 负), 行业景气依赖招标落地")
            lines.append("- 市值仅 14.5 亿, 流动性/波动风险高")
        elif code == "603037":
            lines.append("- 汽车零部件年降压力, 净利负增长; 承载轮新业务放量待验证")
            lines.append("- PE 43 对零部件行业偏高, 增长兑现是关键")
        lines.append("- 本报告为程序化自动生成, 仅供参考, 不构成投资建议")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(f"*深度分析脚本: scripts/deep_analysis_pm_20261026.py | 候选池: 尾盘选股 v2.5 Top5 | 冰点守卫: 情绪 45 (分歧) 放行*")
        out = os.path.join(REPORT_DIR, f"{TODAY}-深度分析-{code}.md")
        with open(out, "w") as f:
            f.write("\n".join(lines))
        n += 1
        print(f"written: {out}")
    print(f"total {n} reports")


if __name__ == "__main__":
    main()

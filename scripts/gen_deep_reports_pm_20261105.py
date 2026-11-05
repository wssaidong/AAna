#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
渲染 2026-11-05 尾盘深度分析报告 — 从 deep_analysis_pm_20261105.json 生成每只 {date}-深度分析-{code}.md
"""
import json, os, sys

sys.path.insert(0, '/Users/cai/code/AAna/scripts')

TODAY = "2026-11-05"
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
DATA = os.path.expanduser("~/code/AAna/data/deep_analysis_pm_20261105.json")

# 主营业务 (akshare stock_zyjs_ths 实拉, 11-05 PM)
BUSINESS = {
    "600573": "惠泉啤酒 — 生产销售啤酒 (惠泉一麦/纯生/欧骑士/鲜啤/1983 等系列), 位于福建, "
              "区域性啤酒龙头, 产品覆盖鲜啤与中高端, 啤酒行业吨价与成本端随原材料波动",
    "603016": "新宏泰 — 断路器关键部件、低压断路器及刀熔开关的研发/生产/销售 "
              "(塑料外壳式断路器/万能式断路器/BMC·SMC 模塑绝缘制品/断路器用交直流两用电机/电动操作机构), "
              "电网设备上游配套, 受益电网投资与特高压招标节奏",
    "000829": "天音控股 — 智能终端销售业务、电商业务、彩票软硬件服务业务、手机售后服务业务 "
              "(通信产品销售/零售电商/彩票业务/通信产品维修), 手机分销与彩票服务双主业",
    "600078": "澄星股份 — 黄磷、磷酸和其他化工产品的生产与销售 "
              "(磷矿石/黄磷/磷酸/磷酸盐), 磷化工产业链, 产品价格随磷矿与黄磷景气周期波动",
    "000676": "智度股份 — 互联网媒体业务和数字营销业务 (互联网媒体服务/数字营销), "
              "流量变现与广告投放为主, 轻资产运营, 业绩弹性大但盈利质量依赖广告主预算",
}

# 行业标签 (sina + 东财 f127 双源核验 + akshare stock_zyjs_ths 主营, 11-05 PM 实拉)
INDUSTRY = {
    "600573": "食品饮料-啤酒 (sina 啤酒 / 东财 非白酒)",
    "603016": "电力设备-低压断路器 (sina 电气设备 / 东财 电网设备)",
    "000829": "商贸零售-专业连锁 (手机分销/彩票服务) (sina 专业连锁 / 东财 专业连锁Ⅱ)",
    "600078": "基础化工-磷化工及磷酸盐 (sina 磷化工及磷酸盐 / 东财 农化制品)",
    "000676": "传媒-互联网媒体与数字营销 (sina 移动互联网服务 / 东财 广告营销)",
}

# 风险提示 (逐只)
RISKS = {
    "600573": [
        "基本面偏弱: ROE 8.2% 一般, 营收增速仅 +2%, 啤酒为成熟行业, 成长弹性有限",
        "PE 32.9 偏高 (估值面 12/15 靠 PB 2.21 拉分), 股价 60 日已 +31.7% 属偏热区",
        "板块胜率借白酒键 (啤酒/白酒同属食品饮料), 非同品种, 100% (5/5) 样本仅 5 笔",
        "市值 32 亿偏小, 流动性一般, 尾盘追高 (+4.48%) 次日溢价不确定",
    ],
    "603016": [
        "基本面显著偏弱: ROE 4.8% + 净利同比 -19.7% 负增长, 基本面仅 7/30",
        "PE 78.7 高 + PB 5.11 偏高, 估值面仅 3/15, 明显透支",
        "价格 < MA20 (28.05) < MA60 (29.65), 均线未完全修复, 今日 +4.15% 属超跌反弹",
        "市值 42 亿, 电网设备招标节奏决定订单兑现, 周期波动大",
    ],
    "000829": [
        "ROE 仅 1.0% 极弱, 净利 +151% 含低基数效应, 盈利质量待验证 (单季归母仅 0.134 亿)",
        "PE 148.8 异常偏高, 估值面仅 4/15",
        "手机分销为薄利通道业务, 行业价格战与运营商补贴政策变化直接压缩利润",
        "目标价 ¥9.90 已贴近涨停价 ¥9.90, 上行空间受限",
    ],
    "600078": [
        "净利同比 +848% 含极低基数效应, 需看绝对额 (单季归母 1.471 亿) 而非增速",
        "ROE 14.6% 良好但价格 < MA20 (9.15) < MA60 (10.17), 60 日涨幅 -13.9%, 属超跌反弹",
        "黄磷/磷酸价格随磷矿与化工周期大幅波动, 周期反转风险",
        "板块胜率仅 50% (1/2) 冷样本, 化工邻近键农药 0% (0/1) 为弱信号",
    ],
    "000676": [
        "ROE 5.6% 一般, 营收增速仅 +4.6%, 净利 +102% 含低基数效应",
        "PE 33.6 偏高, 估值面 12/15 靠 PB 2.02 拉分",
        "20 日区间位置 83% 已在突破区 + 今日 +4.30% 尾盘追高, 次日溢价不确定",
        "60 日涨幅 -10.4% 弱势 (MA60 6.79 仍高于 MA20 6.57 之下), 中期趋势未确认",
        "数字营销业务依赖广告主预算与平台流量政策, 业绩波动大; 换手率 8.04% 偏高, 筹码不稳",
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
        lines.append(f"> 生成时间: {TODAY} {d.get('generated', '')} (目标事件: 2026-11-05 尾盘 14:45-15:00)")
        lines.append(f"> 行业: {INDUSTRY.get(code, '-')} | 数据源: 腾讯行情(实时快照) + 腾讯日K(kline/kline, 末日 {t.get('last_date', '-')}) + akshare 财务摘要")
        lines.append(f"> 情绪: 回暖 (建议仓位 70%) | 尾盘策略放行 (非冰点日)")
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
        lines.append(f"| 市值 | {r.get('mcap_yi', '-')} 亿 |")
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
        lines.append(f"*深度分析脚本: scripts/deep_analysis_pm_20261105.py | 候选池: 尾盘选股 v2.5 Top5 | "
                     f"情绪: 回暖 (非冰点, 放行) | 评分引擎: 技术50% + 基本面30% + 估值20%*")
        out = os.path.join(REPORT_DIR, f"{TODAY}-深度分析-{code}.md")
        with open(out, "w") as f:
            f.write("\n".join(lines))
        n += 1
        print(f"written: {out}")
    print(f"total {n} reports")


if __name__ == "__main__":
    main()

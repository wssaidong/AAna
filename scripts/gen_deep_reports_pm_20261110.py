#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-11-10 尾盘深度分析报告生成器 — 从 data/deep_analysis_pm_20261110.json 渲染
 reports/{date}-深度分析-{code}.md (5 只)

FINAL_PICK = 002979 雷赛智能
理由: 引擎原始分 002539(87.2) > 002979(82.5), 经扣非/OCF 增长质量修正后 83.2 vs 82.5 (差 0.7 = 噪声内)
      → 视为平局, 用 5 条 tiebreak 决出 (见 FINAL_REASON)。
      关键: 002539 的 "PE 13.7 便宜" 是套保/公允价值收益撑起的滞后口径假信号 (Q3 单季扣非 -31.18%),
      属 10-28 skill P0 教训 "PE 看起来合理方向上的变体 — 比高估更危险"。
所有基本面数字均经 akshare stock_financial_abstract (20260930 累计口径) 实拉核验, 与官方三季报一致。
"""
import json, os, sys
from datetime import datetime

sys.path.insert(0, '/Users/cai/code/AAna/scripts')

TODAY = "2026-11-10"
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
DATA = os.path.expanduser("~/code/AAna/data/deep_analysis_pm_20261110.json")

FINAL_PICK = "002979"

FINAL_REASON = (
    "引擎原始分 002539 云图控股 87.2 > 002979 雷赛智能 82.5; 经扣非/经营现金流增长质量修正后 83.2 vs 82.5, "
    "差距 0.7 分在引擎噪声内 (基本面 30% 权重下单一指标跨档即 ±4 分), 视为平局, 用 5 条 tiebreak 决出: "
    "(1) 盈利质量 — 002979 前三季扣非 +87.81% ≈ 归母 +86.80% (gap -1.0pp, 增长全部来自主业); "
    "002539 归母 +29.74% vs 扣非仅 +9.23% (gap +20.5pp), 超额部分来自套保工具投资收益及公允价值变动收益, "
    "且 Q3 单季扣非同比 -31.18% (H1 扣非 +23% 强 → Q3 急刹, 官方三季报口径); "
    "(2) 现金转化 — 002979 OCF -0.52 亿仅占归母 17% (扩产备货时点因素); 002539 OCF -7.88 亿占归母 90%, 同比 -241.94%; "
    "(3) 资产负债表 — 002979 负债率 36.93% 且持续下降; 002539 负债率 66.07%, 对外担保 143.99 亿=净资产 153.16%, "
    "控股股东质押占其持股 38.66%; "
    "(4) 策略自身板块胜率 (405 笔回测) — 002979 工控自动化 100% (4/4) + 邻近仪器仪表 100% (5/5) + 电机 75% (3/4); "
    "002539 磷化工及磷酸盐 0% (0/1); "
    "(5) 板块景气 — 002979 处 AI 资本开支 + 工控国产替代 + 泛人形机器人上行 (Q3 伺服单季 +66.47%, "
    "无框力矩电机月交付破 15 万台, 关节模组在手订单超 6 万台, 11.44 亿定增已过会); "
    "002539 处磷化工周期低位 (同行云天化 Q3 归母 -62.20%, 新洋丰 +0.23%), 属左侧周期股。"
    "结论: 002979 雷赛智能为最值得购买 1 只; 002539 为价值型备选 (PB 1.4 + 扣非 TTM PE 16.2x, 若磷化工/黄磷涨价传导将再评级)。"
)

# 2026 三季报快照 (akshare stock_financial_abstract, 20260930 累计; 单季=Q3) — 11-10 实拉核验
SNAP = {
    "002539": {"rev": 161.974, "rev_g": 2.07, "gm": 8.756, "gm_g": 29.74, "kf": 7.238, "kf_g": 9.23,
               "q_gm": 1.675, "q_kf": 1.157, "ocf": -7.881, "roe": 9.0},
    "002979": {"rev": 19.086, "rev_g": 46.77, "gm": 2.992, "gm_g": 86.80, "kf": 2.915, "kf_g": 87.81,
               "q_gm": 1.056, "q_kf": 1.038, "ocf": -0.515, "roe": 15.36},
    "600699": {"rev": 418.872, "rev_g": -8.63, "gm": 9.577, "gm_g": -14.51, "kf": 8.710, "kf_g": -22.39,
               "q_gm": 2.188, "q_kf": 2.157, "ocf": 26.555, "roe": 5.61},
    "003033": {"rev": 14.963, "rev_g": 7.66, "gm": 1.050, "gm_g": -20.83, "kf": 0.998, "kf_g": -5.74,
               "q_gm": 0.350, "q_kf": 0.327, "ocf": 1.632, "roe": 7.24},
    "603721": {"rev": 1.726, "rev_g": -8.13, "gm": -0.174, "gm_g": -55.28, "kf": -0.266, "kf_g": None,
               "q_gm": -0.046, "q_kf": -0.092, "ocf": -0.422, "roe": -3.59},
}

QUALITY_NOTE = {
    "002539": "🔴 P0 增长质量失真: 归母 +29.74% 中约 2/3 来自套保/公允价值等非经常项 (扣非仅 +9.23%, gap 20.5pp); "
              "Q3 单季扣非同比 -31.18% (H1 +23% → Q3 急刹); OCF -7.88 亿 (-241.94%); 负债率 66.07%, "
              "对外担保 143.99 亿=净资产 153%, 控股股东质押 38.66% → 引擎分 87.2 已按扣非口径修正为 83.2",
    "002979": "🟢 扣非 +87.81% ≈ 归母 +86.80% (gap -1.0pp), 增长全部来自主业; 扣非/归母比 97%; "
              "OCF -0.52 亿仅占归母 17% (扩产备货时点因素); 负债率 36.93% 且持续下降 → 增长质量优",
    "600699": "🟡 归母 -14.51% / 扣非 -22.39% 双降, 但 OCF +26.56 亿 (归母的 2.8 倍) 现金转化极强; "
              "扣非弱于归母 (gap +7.9pp) 说明利润里非经常项为正贡献",
    "003033": "🟡 归母 -20.83% 但扣非仅 -5.74% (gap -15.1pp, 扣非好于归母), OCF +1.63 亿覆盖归母 1.55 倍 → "
              "主业实际下滑温和, 归母降幅含一次性损失",
    "603721": "🔴 亏损股 (PE<=0, 估值面 PE 记 0 只留 PB, 10-28 铁律): 归母 -0.174 亿亏损同比扩大 55.28%, "
              "Q3 单季继续亏损; 扣非表观 '+49.18%' 为负基数下亏损收窄失真 (11-09 低基数陷阱), 不计分",
}

# 估值核验 (11-10 实拉: 总市值=max(两字段), 腾讯 PE_TTM=归母 TTM 口径)
VAL_CHECK = {
    "002539": "PE_TTM 13.68 = 归母 TTM 10.28 亿 / 总市值 140.5 亿; **扣非 TTM 8.65 亿 → 扣非 PE 16.2x**; PB 1.4。"
              "⚠️ PE 13.7 是套保收益撑起的滞后口径 — Q3 单季扣非 1.16 亿年化 4.6 亿对应 run-rate PE ~30x",
    "002979": "PE_TTM 48.6 = 归母 TTM 3.64 亿 / 总市值 177.0 亿; 扣非 TTM 3.53 亿 → 扣非 PE 50.1x; PB 8.31。"
              "贵, 但 Q3 单季扣非 1.04 亿年化 4.2 亿对应 run-rate PE ~42x, 且增长在加速",
    "600699": "低 PE 低 PB; 收入/归母/扣非三降下按中性估值处理",
    "003033": "PE 中性偏高, PB 中性; 主业温和下滑",
    "603721": "亏损, PE 不适用 (记 0), 仅 PB 参考",
}

BUSINESS = {
    "002539": "复合肥研发/生产/销售为主业, 产业链延伸至磷肥(磷酸一铵)、黄磷、磷酸铁、纯碱(联产氯化铵), "
              "磷复肥+磷化工+新能源材料三线布局。磷矿设计产能 690→1090 万吨/年 (阿居洛呷 290 万吨、牛牛寨 400 万吨"
              "采选工程为未来两年利润弹性); 本轮黄磷涨价使黄磷毛利率同比 +18.96pct 至 38.83%。"
              "另经藏格矿业境外合资平台约 1.71 亿美元收购刚果(布)钾盐项目 92% 股权 (ODI 审批中)。"
              "属磷化工周期股: 当前处周期低位, 弹性来自黄磷/磷矿石涨价传导。",
    "002979": "智能装备运动控制核心部件 (控制技术/步进/伺服系统) 研发生产销售。2026 前三季度: 伺服系统 10.08 亿 "
              "(+58.64%, 占比 53%), Q3 单季伺服 3.47 亿 (+66.47%) 为核心增量; 综合毛利率 39.21%, 净利率 15.77% "
              "(+3.01pct), 期间费用率 23.98% 同比 -3.29pct 摊薄。第二曲线泛人形机器人核心零部件 (无框力矩电机/"
              "灵巧手/关节模组): 无框力矩电机月交付破 15 万台, 关节模组在手订单超 6 万台, 进入国内 80% 主流"
              "人形机器人厂商供应体系; 11.44 亿定增 (7.53 亿投东莞产业化项目) 已获深交所+证监会审核通过。",
    "600699": "全球汽车安全系统主要供应商之一, 主营汽车安全系统与汽车电子系统 (车身电子控制、内外饰件等), "
              "另布局智能驾驶/机器人业务。汽车零部件景气偏弱, 收入 -8.63%。",
    "003033": "链传动系统研发/制造/销售: 摩托车链、汽车链、农机链、工业设备链四大方向, 摩托车链条细分龙头。",
    "603721": "电视/互联网视频内容制作发行营销, 兼营电视剧播映权运营、影视剧投资、MCN、文旅演播等, "
              "影视内容与版权运营服务商。内容行业景气低迷, 持续亏损。",
}

INDUSTRY = {
    "002539": "复合肥 (sina) / 农化制品 (东财)",
    "002979": "工控自动化 (sina) / 自动化设备 (东财)",
    "600699": "汽车零部件 (sina) / 摩托车及其他 (东财)",
    "003033": "汽车零部件 (双源一致)",
    "603721": "传媒 (sina) / 影视院线 (东财)",
}

SECTOR_NOTE = {
    "002539": "本板块键: 磷化工及磷酸盐 0% (0/1) — 无历史胜率支撑",
    "002979": "本板块键: 工控自动化 100% (4/4)",
    "600699": "汽车零部件 — 无显著胜率样本",
    "003033": "汽车零部件 — 无显著胜率样本",
    "603721": "传媒 — 无显著胜率样本",
}

RISK_EXTRA = {
    "002539": [
        "🔴 对外担保余额 143.99 亿 = 净资产 153.16% — 或有负债风险高",
        "🔴 控股股东质押占其持股 38.66%; 资产负债率 66.07% 高位",
        "🔴 增长依赖黄磷/磷化工价格弹性, 价格回落则 Q3 已现的扣非减速将延续",
    ],
    "002979": [
        "🟡 估值贵 (扣非 PE ~50x): 若机器人订单交付/定增进度不及预期有杀估值风险",
        "🟡 OCF 为负的备货性质需年报验证 (存货周转/预收款)",
        "🟡 60 日涨幅 -5.2% 处回调中, PB 8.31 高位, 短线波动大",
    ],
    "600699": ["🟡 营收/归母/扣非三降, 汽车零部件景气未见拐点"],
    "003033": ["🟡 归母 -20.83%, 摩托车链主业与出口/内销景气相关"],
    "603721": ["🔴 持续亏损且亏损扩大, Q3 单季仍亏; 传媒板块景气低迷"],
}


def fmt(x, nd=2, suf=" 亿"):
    if x is None:
        return "—"
    return f"{x:.{nd}f}{suf}"


def build(r, all_results):
    code, name = r["code"], r["name"]
    s = SNAP[code]
    applied = r.get("quality", {}).get("applied", False)
    tech = r.get("tech_stat") or {}
    final_score = next((x["total"] for x in all_results if x["code"] == FINAL_PICK), "?")
    L = []
    L.append(f"# {TODAY} 尾盘深度分析 — {code} {name}")
    L.append("")
    L.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 目标事件: **2026-11-10 尾盘决策, T+1 (11-11) 开盘执行**")
    L.append(f"> 行业: {INDUSTRY[code]} | v2.4 原始筛选分: {r['v24_score']} | 评分引擎: 技术面50% + 基本面30% + 估值面20% (deep_analysis_20261022)")
    if applied:
        L.append("> ⚠️ **已应用扣非/现金流增长质量修正**: 基本面分按扣非增速重算 (总分 87.2 → 83.2)")
    L.append("")
    L.append("## 一、投资评级与关键位")
    L.append("")
    L.append("| 项目 | 值 |")
    L.append("|---|---|")
    L.append(f"| 投资评级 | **{r['rating']}** (原始 {r.get('rating_raw')}) |")
    L.append(f"| 综合评分 | **{r['total']}** (原始 {r.get('total_raw')}) |")
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
    kf_str = f"{s['kf_g']:+.2f}%" if s['kf_g'] is not None else "—(亏损, 增速失真)"
    L.append(f"| 扣非净利 | {fmt(s['kf'])} ({kf_str}) |")
    L.append(f"| Q3 单季 归母/扣非 | {fmt(s['q_gm'])} / {fmt(s['q_kf'])} |")
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
    L.append("## 六、板块胜率 (策略 405 笔回测)")
    L.append("")
    L.append(f"- {SECTOR_NOTE[code]}")
    if r.get('sector_near'):
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
        L.append(f"未选为最终推荐: 原始分最高 ({r.get('total_raw')}) 但增长质量未过检 (扣非/现金流修正后 {r['total']}), "
                 f"与最终推荐 {FINAL_PICK} ({final_score}) 差距在噪声内, tiebreak 落败 (详见 {FINAL_PICK} 报告)。")
    else:
        L.append(f"未选为最终推荐: 综合评分 {r['total']} {r['rating']} < 最终推荐 {FINAL_PICK} ({final_score})。")
    L.append("")
    L.append("---")
    L.append("*数据源: 腾讯实时行情/日K(120d qfq) + akshare stock_financial_abstract (20260930) + sina/东财行业双源 + "
             "rec_tuning.json 板块胜率 | 评分引擎: deep_analysis_20261022.py (技术50/基本30/估值20) | 参考, 不构成投资建议*")
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

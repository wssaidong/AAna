#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-11-25 (周三交易日盘前 08:3x) — 报告 Top10 共 2 只 · 许继电气 000400 / 常山北明 000158
当日报告 = reports/2026-11-25-选股报告.md (08:02:07 盘前版, 涨跌幅=昨收=11-24 周二收盘口径)
候选池 = 2 只:
  000400 许继电气 (Top10#1+强势榜, 报告综合 64, 技术分 78, +1.94%, 软止损 25.43, MA多头MACD金叉)
  000158 常山北明 (Top10#2+潜力榜, 报告综合 64, 技术分 78, +3.82%, 软止损 13.44, MA多头MACD金叉)
基准 = 11-24 周二收盘 (信息冻结点, 今日 09:30 开盘前无新行情): 上证 3548.37 +0.27% ·
      深成 10423.60 -0.29% · 创业板 2278.99 -0.05% · 科创50 1250.09 +1.81% → 四均 +0.435%
      大盘平均 +0.02% (报告口径) · 涨停 64/跌停 6 · 晨盘冲高回落型 (09:00 口径 +1.1/+2.5/+4.0 → 收盘收敛)
铁律: 最值得购买者需基准交易日当日胜出 (强于四均+上证+大盘均) + 正盈利 + 深度评级 ≥增持(65) +
      未破止损 + 守卫放行 (情绪 63 回暖非冰点)
评分: 技术面50% + 基本面30% + 估值面20% (deep_analysis_20261022 引擎) + 全部修正规则:
      估值失真 v1 (10-28) / 增长质量 v1 (11-10) / 低基数·负基数 v2 (11-09) / PE过低陷阱 v1 (11-17) /
      累计亏损基本面硬约束 v1 (本日新增: 累计归母<0 → 净利分支记 0, 增速%不作加分)
板块: 000400 sina[电网自动化] (胜率库无键 → 冷启动) + 巨潮[电气机械/输变电设备];
      邻近键: 工控自动化 100% (5/5) · 电机 75% (3/4) · 电气设备 0% (0/1)
      000158 sina[IT服务] 100% (1/1) + 巨潮[软件和信息技术服务业];
      邻近键: 软件开发 75% (3/4) · 计算机设备 100% (2/2) · 互联网信息服务 100% (1/1) · 计算机应用 0% (0/1)
早盘简报 (08:30) 第 3 天复现冻结快照失真: 上证 ¥12.34 (真值 3548.37) + 科创50 ¥17.10 (真值 1250.09) +
      深成/创业板用 11-23 昨收冒充现价 + 四值族 +0.49/-2.37/-3.74/-2.29 与昨日 11:28/14:45 腿逐字相同 +
      情绪「悲观」与主链快照 63 回暖矛盾 → 不采信, 候选池只认主链报告 Top10 表
东财: 铁律达标则建 20261125ZZ 入 Top1; 裸日期组 20261125 (gid=2096 空占位) / 20261124 (gid=2091) /
      20261124ZZ (gid=2076 菜百股份) 严禁触碰
Kimi: 本机无 kimi CLI / moonshot key — 由 AAna 引擎 + LLM 定性层执行
"""
import sys, os, json, re, time
import datetime
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import requests
import akshare as ak
import data_sources as ds
from deep_analysis_20261022 import kline, rsi, ma, tech_score, val_score, rating_of

TODAY = "2026-11-25"
BASE_DATE = "2026-11-24"   # K 线末日 / 收盘基准 (11-24 周二, 开盘前信息冻结点)
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
TODAY_REPORT = os.path.join(REPORT_DIR, f"{TODAY}-选股报告.md")
OUT_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_20261125.json")
RUN_ID = "01a2101c-51ef-72cc-b2c3-7143e221c77c"
GROUPS_FILE = os.path.expanduser(
    "~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json")

# 11-24 收盘基准 (腾讯快照 202611241614xx 冻结口径, 与报告头部互证: 上证 3548.37 +0.27% ✓)
IDX_CLOSE = {"sh000001": 0.27, "sz399001": -0.29, "sz399006": -0.05, "sh000688": 1.81}
MK_FOUR_AVG = round(sum(IDX_CLOSE.values()) / 4, 3)   # +0.435
SH_CLOSE = 0.27        # 上证 收 3548.37
MK_AVG_ALL = 0.02      # 全市场大盘平均涨跌 (报告口径)
SNAP = {"score": 63, "label": "回暖", "position": 0.70, "zt_count": 64, "dt_count": 6}

NAMES = {"000400": "许继电气", "000158": "常山北明"}
# 巨潮行业副源 (profile 口径; sina 主键 industry_for_code 运行时拉取)
CNINFO_IND = {"000400": "电气机械和器材制造业 (输变电/直流输电设备)",
              "000158": "软件和信息技术服务业"}

BUSINESS = {
    "000400": ("许继电气 —— 国家电网系输变电装备龙头 (中国电气装备集团旗下), 主营直流输电换流阀、"
               "继电保护、智能电表、充电设施等电力装备。2026 前三季营收 100.30 亿 (+6.10%), "
               "国网投资加码 + 特高压/直流工程景气托底营收, 但归母 6.01 亿 (-33.36%) 利润端明显承压——"
               "营收加速 (Q3 单季 +16.6%) 与利润降速 (Q3 单季归母 -30.9%) 剪刀差, 毛利率受行业竞价格压。"
               "PE_TTM 30.8 / PB 2.15, 估值中性偏上"),
    "000158": ("常山北明 —— 河北国资背景软件企业 (北明软件 + 常山纺织双主业), 主营金融/政务/央企"
               "行业数字化解决方案, 华为鸿蒙/鲲鹏生态概念常客。基本面持续亏损: 2026 前三季归母 -1.55 亿 "
               "(同比亏损收窄 0.4%), 扣非 -1.67 亿 (收窄 20.9%), FY25 全年归母 +0.33 亿系非经常项扭亏 "
               "(扣非 -0.84 亿)。PE_TTM 650 / PB 4.26, 估值完全脱离基本面, 11-24 换手 12.53% "
               "题材博弈属性极强"),
}

# 邻近板块键 (胜率库语义邻近; 电网自动化 冷启动 → 工控/电机/电气)
NEIGHBORS = {
    "000400": ["工控自动化", "电机", "电气设备"],
    "000158": ["软件开发", "计算机设备", "互联网信息服务", "计算机应用"],
}

RISKS = {
    "000400": [
        "🟡 **利润承压剪刀差**: 前三季营收 +6.10% 但归母 -33.36% / 扣非 -34.25%, Q3 单季营收 +16.6% 而归母 -30.9% — 行业竞价格压毛利率, 营收加速未转化为利润",
        "🟡 **估值中性偏上**: PE_TTM 30.8 处合理上沿 (0<PE≤30 满分档外), 上行空间需盈利修复配合, 而盈利趋势向下",
        "🟡 **板块冷启动**: 电网自动化无回测记录, 邻近 工控自动化 100% (5/5) / 电机 75% (3/4) 样本合计 10 笔, 统计意义有限",
        "🟢 缓释项: PB 2.15 合理 / 负债率 47.7% / 央企 (中国电气装备) 背景 / 国网投资+特高压直流景气托底营收",
    ],
    "000158": [
        "🔴 **累计亏损**: 前三季归母 -1.55 亿 / 扣非 -1.67 亿双负, FY25 全年扭亏系非经常项 (扣非 -0.84 亿) — 基本面不支持现价",
        "🔴 **估值完全脱离基本面**: PE_TTM 650 / PB 4.26, 纯题材定价; 11-24 换手 12.53% 高换手博弈属性, 次日波动放大",
        "🔴 **追高风险**: +3.82% 已属温和上涨上档, 高换手 + 高 PB 组合下回落风险大于突破概率",
        "🟡 **板块胜率样本薄**: IT服务 100% 仅 1/1, 邻近 软件开发 3/4 / 计算机设备 2/2 — 合计 8 笔无统计保险",
        "🟢 缓释项: 亏损收窄 (Q3 单季扣非亏损收窄 46.4%) / 河北国资背景 / 华为鸿蒙鲲鹏生态题材催化仍在",
    ],
}

SECTOR_VERDICT = {
    "000400": ("本键冷启动无记录; 邻近 工控自动化 100% (5/5) + 电机 75% (3/4) 方向偏正, 电气设备 0% (0/1) "
               "样本极薄 — 邻近键不构成负向排除, 亦不构成买入保险; 胜率库整体 49.7% (477 笔) 中性"),
    "000158": ("本键 IT服务 100% (1/1) + 邻近 计算机设备 100% (2/2) / 互联网信息服务 100% (1/1) / 软件开发 "
               "75% (3/4) 方向偏正, 计算机应用 0% (0/1) — 合计仅 8 笔样本极薄, 方向中性偏正; 关联板块胜率"
               "对该股今日表现无统计约束力"),
}


def parse_top10_full(text):
    """解析 '🏆 重点关注 Top 10' 表格 (口径同 deep_analysis_20261121/22/23/24)。"""
    m = re.search(r'重点关注 Top 10(.*?)(?=\n###|\Z)', text, re.S)
    rows = []
    for line in (m.group(1) if m else text).split("\n"):
        ls = line.strip()
        if not ls.startswith("|") or ls.startswith("|:"):
            continue
        cells = [c.strip() for c in ls.strip("|").split("|")]
        if len(cells) >= 8 and re.fullmatch(r"\d{6}", cells[2]):
            try:
                rank = int(cells[0])
            except ValueError:
                continue
            rows.append({"rank": rank, "code": cells[2], "name_raw": cells[1],
                         "v24_total": cells[7] if len(cells) > 7 else None,
                         "stop_raw": cells[10] if len(cells) > 10 else None})
    return rows


def tencent_quotes(codes):
    """腾讯快照: 盘前=11-24 收盘冻结口径。返回 {code: (现价, 涨跌幅%, 时间戳, 昨收)}"""
    syms = ",".join(("sh" if c.startswith(("6", "9")) else "sz") + c for c in codes)
    r = requests.get(f"https://qt.gtimg.cn/q={syms}", timeout=10,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.encoding = "gbk"
    out = {}
    for m in re.finditer(r'v_(?:sh|sz)(\d{6})="([^"]+)"', r.text):
        p = m.group(2).split("~")
        try:
            out[m.group(1)] = (float(p[3]), float(p[32]), p[30], float(p[4]))
        except (ValueError, IndexError):
            continue
    return out


def fin_extract(code):
    """akshare 财务摘要多期提取 → FIN dict (结构同 deep_analysis_20261124, 运行时拉取)。"""
    df = ak.stock_financial_abstract(symbol=code)
    cols = [c for c in df.columns if re.fullmatch(r"\d{8}", str(c))]
    C, PC, H1, PH1, FY25 = "20260930", "20250930", "20260630", "20250630", "20251231"

    def val(ind_names, col):
        for n in ind_names:
            rows = df[df["指标"] == n]
            if rows.empty:
                rows = df[df["指标"].astype(str).str.contains(re.escape(n), na=False)]
            if not rows.empty and col in df.columns:
                try:
                    return float(rows.iloc[0][col])
                except (TypeError, ValueError):
                    continue
        return None

    f = {}
    for key, inds, col in [
        ("gm_cum", ["归母净利润"], C), ("gm_prior_cum", ["归母净利润"], PC),
        ("gm_h1", ["归母净利润"], H1), ("gm_prior_h1", ["归母净利润"], PH1),
        ("kf_cum", ["扣非净利润", "扣除非经常性损益后的净利润"], C),
        ("kf_prior_cum", ["扣非净利润", "扣除非经常性损益后的净利润"], PC),
        ("kf_h1", ["扣非净利润", "扣除非经常性损益后的净利润"], H1),
        ("kf_prior_h1", ["扣非净利润", "扣除非经常性损益后的净利润"], PH1),
        ("rev_cum", ["营业总收入", "营业收入"], C), ("rev_prior_cum", ["营业总收入", "营业收入"], PC),
        ("rev_h1", ["营业总收入", "营业收入"], H1), ("rev_prior_h1", ["营业总收入", "营业收入"], PH1),
        ("gm_fy25", ["归母净利润"], FY25), ("rev_fy25", ["营业总收入", "营业收入"], FY25),
        ("ocf_cum", ["经营活动产生的现金流量净额", "经营活动现金流量净额"], C),
        ("roe", ["摊薄净资产收益率"], C), ("roe_kf", ["扣非净资产收益率"], C),
        ("bps", ["每股净资产"], C), ("debt_ratio", ["资产负债率"], C),
    ]:
        f[key] = val(inds, col)
    f["period"] = C
    f["gm_yoy"] = (f["gm_cum"] / f["gm_prior_cum"] - 1) * 100 if \
        f["gm_cum"] is not None and f["gm_prior_cum"] else None
    f["rev_yoy"] = (f["rev_cum"] / f["rev_prior_cum"] - 1) * 100 if \
        f["rev_cum"] is not None and f["rev_prior_cum"] else None
    return f


def fund_score_with(ni_growth, roe, rev_growth, loss_note=None):
    """基本面打分 (同 deep_analysis_20261124) + 累计亏损硬约束 v1: loss_note 非空时净利分支记 0。"""
    s, notes = 0, []
    if roe is not None:
        if roe >= 15: s += 12; notes.append(f"ROE {roe:.1f}% 优秀")
        elif roe >= 8: s += 8; notes.append(f"ROE {roe:.1f}% 良好")
        elif roe >= 4: s += 4; notes.append(f"ROE {roe:.1f}% 一般")
        else: s += 0; notes.append(f"ROE {roe:.1f}% 弱")
    else:
        s += 4; notes.append("ROE 缺失")
    if loss_note:
        s += 0; notes.append(loss_note)
    elif ni_growth is not None:
        if ni_growth >= 30: s += 12; notes.append(f"净利增速 +{ni_growth:.0f}%")
        elif ni_growth >= 10: s += 8; notes.append(f"净利增速 +{ni_growth:.0f}%")
        elif ni_growth >= 0: s += 4; notes.append(f"净利增速 +{ni_growth:.0f}%")
        else: s += 0; notes.append(f"净利增速 {ni_growth:.0f}% 负增长")
    else:
        s += 4; notes.append("净利增速缺失")
    if rev_growth is not None:
        if rev_growth >= 15: s += 6; notes.append(f"营收增速 +{rev_growth:.0f}%")
        elif rev_growth >= 0: s += 3; notes.append(f"营收增速 +{rev_growth:.0f}%")
        else: s += 0; notes.append(f"营收增速 {rev_growth:.0f}%")
    else:
        s += 2; notes.append("营收增速缺失")
    return s, notes


def quality_metrics(f):
    """多期财务指标 → 累计/单季/TTM 增速 + 修正触发判定 (口径同 deep_analysis_pm_20261123)。"""
    kf_yoy = (f["kf_cum"] / f["kf_prior_cum"] - 1) * 100 if \
        f["kf_cum"] is not None and f["kf_prior_cum"] else None
    q_gm = f["gm_cum"] - f["gm_h1"]                       # 2026Q3 单季归母
    q_kf = f["kf_cum"] - f["kf_h1"]                       # 单季扣非
    q_rev = f["rev_cum"] - f["rev_h1"]                    # 单季营收
    q_gm_prior = f["gm_prior_cum"] - f["gm_prior_h1"]
    q_kf_prior = f["kf_prior_cum"] - f["kf_prior_h1"]
    q_rev_prior = f["rev_prior_cum"] - f["rev_prior_h1"]
    gm_ttm = f["gm_fy25"] + f["gm_cum"] - f["gm_prior_cum"]
    rev_ttm = f["rev_fy25"] + f["rev_cum"] - f["rev_prior_cum"]
    gap = (f["gm_yoy"] - kf_yoy) if (f["gm_yoy"] is not None and kf_yoy is not None) else None
    ratio = abs(f["ocf_cum"]) / abs(f["gm_cum"]) if f["ocf_cum"] is not None else None
    # 增长质量修正 v1 (11-10): gap≥15 + OCF<0 + |OCF|/|归母|≥0.5 (OCF 缺失 → 不触发, 标注)
    q_triggered = bool(gap is not None and gap >= 15 and f.get("ocf_cum") is not None
                       and f["ocf_cum"] < 0 and ratio is not None and ratio >= 0.5)
    # 低基数/负基数修正 v2 (11-09): gap≥15 + 上期归母<0.5×上期扣非 + 扣非增速<0
    base_depressed = bool(f["gm_prior_cum"] and f["kf_prior_cum"]
                          and f["gm_prior_cum"] > 0 and f["kf_prior_cum"] > 0
                          and f["gm_prior_cum"] < 0.5 * f["kf_prior_cum"])
    lb_triggered = bool(gap is not None and gap >= 15 and base_depressed and
                        (kf_yoy or 0) < 0)
    # 估值失真修正 v1 (10-28): 单季归母<0 + 净利同比<-50
    distorted = bool(q_gm is not None and q_gm < 0 and
                     (f["gm_yoy"] is not None and f["gm_yoy"] < -50))
    # PE 过低陷阱 v1 (11-17): 归母TTM/营收TTM > 3
    pe_trap = bool(gm_ttm and rev_ttm and gm_ttm > 0 and rev_ttm > 0 and gm_ttm / rev_ttm > 3)
    # 累计亏损硬约束 v1 (本日新增): 累计归母<0 或 扣非<0 → 净利分支记 0
    loss_cum = bool((f["gm_cum"] or 0) < 0 or (f["kf_cum"] or 0) < 0)
    return {"kf_yoy": kf_yoy, "q_gm": q_gm, "q_kf": q_kf, "q_rev": q_rev,
            "q_gm_prior": q_gm_prior, "q_kf_prior": q_kf_prior, "q_rev_prior": q_rev_prior,
            "q_gm_yoy": ((q_gm / q_gm_prior - 1) * 100 if q_gm is not None and q_gm_prior else None),
            "q_kf_yoy": ((q_kf / q_kf_prior - 1) * 100 if q_kf is not None and q_kf_prior else None),
            "q_rev_yoy": ((q_rev / q_rev_prior - 1) * 100 if q_rev is not None and q_rev_prior else None),
            "gm_ttm": gm_ttm, "rev_ttm": rev_ttm,
            "ttm_ratio": (gm_ttm / rev_ttm if gm_ttm and rev_ttm else None),
            "gap": gap, "ocf_ratio": ratio, "ocf_cum": f["ocf_cum"],
            "loss_cum": loss_cum,
            "q_triggered": q_triggered, "lb_triggered": lb_triggered, "distorted": distorted,
            "pe_trap": pe_trap,
            "triggered": q_triggered or lb_triggered,
            "trigger_reason": ("增长质量修正: 归母-扣非增速差 ≥15pp + OCF<0 + |OCF|/归母 ≥50%" if q_triggered
                               else ("低基数(负基数)修正: 归母增速系基数年非经常项压低所致, 按扣非增速重算" if lb_triggered
                                     else None))}


def sh_index_quote():
    """上证指数 sh000001 (指数必须显式 sh 前缀, 否则 sz000001=平安银行)。"""
    r = requests.get("https://qt.gtimg.cn/q=sh000001", timeout=10,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.encoding = "gbk"
    m = re.search(r'v_sh000001="([^"]+)"', r.text)
    if not m:
        return None
    p = m.group(1).split("~")
    return float(p[3]), float(p[32]), p[30]


def trading_day_verify():
    """交易日三副腿核验 (周三: 今日报告存在 + cron 生成记录)。"""
    d = datetime.date(2026, 11, 25)
    legs = {"weekday": "周三" if d.weekday() == 2 else f"非周三?!({d.weekday()})",
            "report_today": os.path.isfile(TODAY_REPORT),
            "cron_generated": None, "cron_pool_line": None, "cron_moneyflow_fallback": False}
    try:
        with open(os.path.expanduser("~/code/AAna/scripts/cron.log")) as f:
            for line in f:
                if "生成 2026-11-25 动态选股报告" in line:
                    legs["cron_generated"] = True
                if "动态股票池" in line:
                    legs["cron_pool_line"] = line.strip()[:120]
                if "只 fallback" in line and "2026-11-25" not in line:
                    legs["cron_moneyflow_fallback"] = True
    except Exception:
        pass
    return legs


def guard_check():
    """P0 冰点守卫 (单一真源 check_ice_point_guard)。盘前 live 源 (ths) = 11-24 收盘口径。"""
    from aana_afternoon_screen import check_ice_point_guard
    live = None
    try:
        live = check_ice_point_guard()
    except Exception as e:
        print(f"  live 情绪源异常(盘前): {e}")
    snap = check_ice_point_guard(sent={"score": SNAP["score"], "label": SNAP["label"],
                                       "zt_count": SNAP["zt_count"], "dt_count": SNAP["dt_count"]})
    return live, snap


def briefing_anomaly():
    """早盘简报异常取证: 今日 08:30 简报第 3 天复现冻结快照失真。"""
    brief = os.path.join(REPORT_DIR, TODAY, "盘前", f"{TODAY}_0830_早盘简报.md")
    ev = {"brief": brief, "exists": os.path.isfile(brief),
          "sh_price_claimed": None, "sh_change_claimed": None,
          "kc50_price_claimed": None, "sentiment_claimed": None,
          "recommend_rows": 0, "verdict": None}
    if not ev["exists"]:
        ev["verdict"] = "简报不存在"
        return ev
    txt = open(brief).read()
    m = re.search(r'上证指数\s*\|\s*¥?([\d.]+)\s*\|\s*(🔴|🟢)\s*([+-][\d.]+%)', txt)
    if m:
        ev["sh_price_claimed"] = float(m.group(1))
        ev["sh_change_claimed"] = m.group(3)
    m2 = re.search(r'科创50\s*\|\s*¥?([\d.]+)', txt)
    if m2:
        ev["kc50_price_claimed"] = float(m2.group(1))
    m3 = re.search(r'市场情绪:\*?\*?\s*(\S+)', txt)
    if m3:
        ev["sentiment_claimed"] = m3.group(1)
    rows = [l for l in txt.split("\n")
            if l.strip().startswith("|") and re.search(r'[+-]\d+\.\d+%', l)
            and not l.strip().startswith("|:")]
    ev["recommend_rows"] = len(rows)
    ev["verdict"] = (f"简报记上证 ¥{ev['sh_price_claimed']} {ev['sh_change_claimed']}"
                     f" (真值 3548.37 +0.27% 周二收盘, 价格字段失真第 3 天) + 科创50 ¥{ev['kc50_price_claimed']}"
                     f" (真值 1250.09) + 四值族 +0.49/-2.37/-3.74/-2.29 与昨日 11:28/14:45 腿逐字相同"
                     f" (跨日冻结缓存) + 情绪「{ev['sentiment_claimed']}」与主链快照 63 回暖矛盾"
                     f" → 不采信, 候选池只认主链报告")
    return ev


def yoy_disp(cur, prior):
    """负基数-safe 增速展示: 负/负时公式符号与经济含义相反 (比率<1=收窄)。"""
    if cur is None or not prior:
        return "n/a"
    pct = (cur / prior - 1) * 100
    if prior < 0 and cur < 0:
        p = abs(pct)
        return f"亏损收窄 {p:.1f}%" if cur > prior else f"亏损扩大 {p:.1f}%"
    if prior < 0:
        return f"扭亏 (去年同期 {prior/1e8:.2f} 亿)"
    return f"{pct:+.2f}%"


def q_gm_y(qm, kind):
    return yoy_disp(qm["q_gm"], qm["q_gm_prior"])


def md_report(rec, rt_meta, out):
    """单股深度分析 md (结构同 2026-11-24-深度分析-605599.md)。"""
    code = rec["code"]
    t = rec["tech_stat"]; q = rec["quality"]; f = rec["fin"]
    sec_wr = rec["sector_win_rate"]
    nb = rec["neighbor_sectors"]
    nb_str = " · ".join(f"{k} {v}" for k, v in nb.items()) or "无邻近键"
    ocf_line = (f"{q['ocf_cum']/1e8:+.2f} 亿 (OCF/归母 {q['ocf_ratio']:.2f})"
                if q["ocf_cum"] is not None else "缺失 (摘要表无该行, 修正链不因此触发)")
    law = out["law_detail"][code]
    chg = rec["chg_pct"] or 0
    loss_note = ("⚠️ **累计亏损**: 前三季归母/扣非双负, 净利分支记 0"
                 if q["loss_cum"] else "")
    return f"""# {TODAY} 盘前深度分析 — {code} {NAMES[code]}

> 生成时间: {TODAY} 08:3x | 数据基准: **{BASE_DATE} 周二收盘** (信息冻结点, 今日 09:30 开盘前无新行情) | 目标事件: **T+0 今日盘中决策**
> 报告: reports/{TODAY}-选股报告.md (08:02:07 盘前版, Top10 共 2 只, 本股 Top10#{rec['rank']}) | 行业: {rec['industry_sina']} (sina) / {CNINFO_IND[code]} (巨潮) | v2.5 报告综合分: {rec['v24_score']} | 评分引擎: 技术面50% + 基本面30% + 估值面20% (deep_analysis_20261022 + 全部修正规则)

## 一、投资评级与关键位

| 项目 | 值 |
|---|---|
| 投资评级 | **{rec['rating']}** |
| 综合评分 | **{rec['total']}** (0-100) |
| 分项 | 技术 {rec['tech_score']}/55 · 基本面 {rec['fund_score']}/30 · 估值 {rec['val_score']}/15 |
| 现价 | ¥{rec['price']} ({BASE_DATE} 收盘, 当日 {chg:+.2f}%) |
| 目标价 | ¥{rec['target']} (20日高 {t.get('hi20')} / +5%) |
| 止损价 | ¥{rec['report_stop']} (报告软止损, 距现价 {(rec['price']/rec['report_stop']-1)*100:+.1f}%) |
| 市值 | {rec['mcap_yi']} 亿 (流通 {rec['float_mcap_yi']} 亿) · PE_TTM {rec['pe_ttm']} · PB {rec['pb']} |

## 二、核心逻辑 (主营业务)

{BUSINESS[code]}

## 三、基本面快照 (2026 三季报, akshare 财务摘要, 官方口径)

| 指标 | 值 |
|---|---|
| 营业收入 | {f['rev_cum']/1e8:.2f} 亿 ({f['rev_yoy']:+.2f}%) |
| 归母净利 | {f['gm_cum']/1e8:.2f} 亿 ({yoy_disp(f['gm_cum'], f['gm_prior_cum'])}) |
| 扣非净利 | {f['kf_cum']/1e8:.2f} 亿 ({yoy_disp(f['kf_cum'], f['kf_prior_cum'])}) |
| Q3 单季 营收 | {q['q_rev']/1e8:.1f} 亿 ({q['q_rev_yoy']:+.1f}%) |
| Q3 单季 归母 | {q['q_gm']/1e8:.2f} 亿 ({yoy_disp(q['q_gm'], q['q_gm_prior'])}) |
| Q3 单季 扣非 | {q['q_kf']/1e8:.2f} 亿 ({yoy_disp(q['q_kf'], q['q_kf_prior'])}) |
| 经营现金流 | {ocf_line} |
| ROE (摊薄) | {f['roe']:.2f}% |
| 资产负债率 | {f['debt_ratio']:.2f}% |
| 每股净资产 | ¥{f['bps']:.2f} |
| 增长质量 | {rec['quality_verdict']} |

## 四、估值

PE_TTM {rec['pe_ttm']} / PB {rec['pb']} / 总市值 {rec['mcap_yi']} 亿

估值面 **{rec['val_score']}/15**: {'; '.join(rec['val_notes'])}。修正规则核验: 估值失真修正{'触发' if q['distorted'] else '未触发'} / PE 过低陷阱{'触发' if q['pe_trap'] else '未触发'} (TTM 归母/营收 = {q['ttm_ratio']:.3f})。

## 五、技术面 (120 日)

{chr(10).join('- ' + n for n in rec['tech_notes'])}
- {BASE_DATE} {chg:+.2f}% (K线末日 {t.get('last_date')}, K线 {t.get('kline_len')} 根) | 换手 {rec['turnover_pct']}% 量比 {rec['vol_ratio']}

## 六、板块胜率 (策略回测样本)

- **本板块键: {rec['industry_sina']}** —— {sec_wr}
- 邻近: {nb_str}
- 结论: {rec['sector_verdict']}

## 七、风险提示

{chr(10).join('- ' + l for l in rec['risk_lines'])}

## 八、结论

**铁律核验 (基准 {BASE_DATE}: 强于四均 {MK_FOUR_AVG:+.3f}% + 上证 +{SH_CLOSE}% + 大盘均 +{MK_AVG_ALL}% + 正盈利 + 评级 ≥增持 + 未破止损 + 守卫放行)**:

{chr(10).join('- ' + l for l in law)}

**评级: {'✅ 铁律达标' if rec['law_pass'] else '❌ 铁律未达标'}**

---
*数据源: 腾讯实时行情/日K(120d qfq) + akshare stock_financial_abstract ({f['period']} 多期) + sina 行业 + rec_tuning.json 板块胜率 ({rt_meta['sectors']} 板块 {rt_meta['records']} 笔) | 评分引擎: deep_analysis_20261022.py (技术50/基本30/估值20) + 10-28 估值失真 + 11-10 增长质量 + 11-09 低基数 + 11-17 PE 过低陷阱 + 本日新增 累计亏损硬约束 | 参考, 不构成投资建议*
"""


def main():
    print("=" * 78)
    print(f"AAna 深度分析 — {TODAY} (周三交易日盘前, 数据基准 {BASE_DATE} 周二收盘冻结)")
    print(f"Run: autopilot ca411dd3 深度分析 {RUN_ID}")
    print("=" * 78)

    # ---- 报告确认 (autopilot 强制: 打印报告名称防错) ----
    sz = os.path.getsize(TODAY_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(TODAY_REPORT)))
    print(f"📄 当日报告: {TODAY_REPORT}")
    print(f"   → 存在 | 大小: {sz} 字节 | 修改: {mt} (08:02:07 盘前版, 主链 cron 生成)")
    text = open(TODAY_REPORT).read()
    pool = parse_top10_full(text)
    print(f"   报告 Top10 表: {len(pool)} 只 → 候选池 = {len(pool)} 只: "
          + ", ".join(f"{p['rank']}#{p['code']} {NAMES.get(p['code'], p['name_raw'])}" for p in pool))
    print(f"   报告快照: 情绪{SNAP['score']}({SNAP['label']}) 仓位{SNAP['position']*100:.0f}% "
          f"涨停{SNAP['zt_count']}/跌停{SNAP['dt_count']} ✅正常交易 | 大盘平均 +{MK_AVG_ALL}% "
          f"上证 +{SH_CLOSE}% 收 3548.37")

    legs = trading_day_verify()
    legs_ok = legs["weekday"] == "周三" and legs["report_today"] and legs["cron_generated"]
    print(f"\n📅 交易日三副腿核验: weekday={legs['weekday']} | 今日报告存在={legs['report_today']} "
          f"| cron生成记录={'✅' if legs['cron_generated'] else '❌未见'} | 池行: {legs['cron_pool_line']} "
          f"→ {'PASS' if legs_ok else 'FAIL'}")

    # ---- 基准指数核验 (腾讯收盘快照 vs 报告头部) ----
    sh_live = sh_index_quote() or (None, None, None)
    sh_ok = sh_live[0] == 3548.37 and abs(sh_live[1] - SH_CLOSE) < 0.01
    print(f"\n📊 基准核验: 上证收盘快照 {sh_live[0]} {sh_live[1]:+.2f}% (ts {sh_live[2]}) "
          f"vs 报告 3548.37 +0.27% → {'✅一致' if sh_ok else '🔴漂移'} | "
          f"四均 {MK_FOUR_AVG:+.3f}% (上证+0.27/深成-0.29/创业板-0.05/科创50+1.81) | 大盘均 +{MK_AVG_ALL}%")

    # ---- 胜率库 ----
    with open(os.path.expanduser("~/code/AAna/data/rec_tuning.json")) as f:
        rt = json.load(f)
    sector_stats = rt.get("sector_stats", {})
    rt_meta = {"generated": rt.get("generated_at", "")[:10], "sectors": len(sector_stats),
               "records": rt.get("total_records"),
               "overall": rt.get("overall_win_rate")}
    print(f"📊 板块胜率库 ({rt_meta['generated']}): {rt_meta['sectors']} 板块 | "
          f"整体胜率 {rt_meta['overall']:.1f}% ({rt_meta['records']} 笔)")

    # ---- 冰点守卫 ----
    live, snap = guard_check()
    print(f"\n🛡 P0 冰点守卫: 快照口径 情绪{snap['sentiment_score']}({snap['sentiment_label']}) "
          f"仓位{snap.get('position_ratio', SNAP['position'])*100:.0f}% is_ice_point={snap['is_ice_point']}")
    if live:
        print(f"   live 口径 情绪{live['sentiment_score']}({live['sentiment_label']}) is_ice_point="
              f"{live['is_ice_point']} fallback={live['data_source_fallback']}")
    ice = snap["is_ice_point"] and (live["is_ice_point"] if live else True)
    guard_pass = not ice
    print(f"   守卫放行: {'✅ (情绪 63 回暖, 非冰点)' if guard_pass else '❌ 冰点不放行'}")

    # ---- 逐股深度评分 ----
    results = []
    print(f"\n=== 逐股深度评分 (技术50%+基本面30%+估值20%, 引擎 deep_analysis_20261022 + 全部修正规则) ===")
    for p in pool:
        code = p["code"]
        stop = float(p["stop_raw"]) if p.get("stop_raw") else None
        try:
            q = ds.tencent_quote([code]).get(code, {})
        except Exception as e:
            q = {}; print(f"  quote fail: {e}")
        price, pe, pb = q.get("price"), q.get("pe_ttm"), q.get("pb")
        try:
            kl = kline(code)
            ts_, tnotes, tstat = tech_score(kl, price)
        except Exception as e:
            ts_, tnotes, tstat = 25, [f"K线失败: {e}"], {}
        try:
            fin = fin_extract(code)
        except Exception as e:
            fin = {"period": None, "gm_cum": None, "gm_prior_cum": None, "gm_h1": None,
                   "gm_prior_h1": None, "kf_cum": None, "kf_prior_cum": None, "kf_h1": None,
                   "kf_prior_h1": None, "rev_cum": None, "rev_prior_cum": None, "rev_h1": None,
                   "rev_prior_h1": None, "gm_fy25": None, "rev_fy25": None, "ocf_cum": None,
                   "roe": None, "roe_kf": None, "bps": None, "debt_ratio": None,
                   "gm_yoy": None, "rev_yoy": None, "error": str(e)[:80]}
        qm = quality_metrics(fin)
        # 累计亏损硬约束 v1: 双负 → 净利分支 0
        if qm["loss_cum"]:
            loss_note = (f"累计亏损: 归母 {fin['gm_cum']/1e8:.2f} 亿 / 扣非 {fin['kf_cum']/1e8:.2f} 亿 双负 "
                         f"(增速% 失真, 记 0)")
            fs_, fnotes = fund_score_with(qm["kf_yoy"], fin["roe"], fin["rev_yoy"], loss_note=loss_note)
        elif qm["triggered"]:
            fs_, fnotes = fund_score_with(qm["kf_yoy"], fin["roe"], fin["rev_yoy"])
            fnotes = fnotes + [f"[{qm['trigger_reason']}] 归母 {fin['gm_yoy']:+.1f}% → 扣非 {qm['kf_yoy']:+.1f}%"]
        else:
            fs_, fnotes = fund_score_with(fin["gm_yoy"], fin["roe"], fin["rev_yoy"])
            fnotes = fnotes + ["无修正触发 (gap<15pp 或 OCF>0, 归母口径有效)"]
        vs_, vnotes = val_score(pe, pb)
        vs_adj = vs_
        if qm["distorted"]:
            pb_score = 7 if (pb is not None and pb <= 3) else (4 if (pb is not None and pb <= 5) else 1)
            vs_adj = min(vs_adj, pb_score)
            vnotes.append("估值面失真修正: 单季归母转亏 → PE 记 0 只留 PB")
        if qm["pe_trap"]:
            pb_score = 7 if (pb is not None and pb <= 3) else (4 if (pb is not None and pb <= 5) else 1)
            vs_adj = min(vs_adj, pb_score)
            vnotes.append(f"PE过低陷阱: 归母TTM/营收TTM = {qm['ttm_ratio']:.2f}x (>3) → PE 记 0 只留 PB")
        total = round(ts_ / 55 * 50 + fs_ / 30 * 30 + vs_adj / 15 * 20, 1)
        rating = rating_of(total)
        try:
            hi20 = tstat.get("hi20") or price * 1.05
            target = round(max(hi20, price * 1.05), 2)
        except Exception:
            target = round(price * 1.05, 2)
        # 板块: sina 主键 + 邻近键
        try:
            ind_sina = ds.industry_for_code(code)
        except Exception:
            ind_sina = None
        stat_key = ind_sina if ind_sina in sector_stats else None
        sec = sector_stats.get(stat_key, {}) if stat_key else {}
        sec_wr = (f"{sec.get('win_rate'):.1f}% ({sec.get('win_count')}/{sec.get('count')})"
                  if sec else "无记录(冷启动)")
        neighbors = {k: (f"{sector_stats[k]['win_rate']:.1f}% "
                         f"({sector_stats[k]['win_count']}/{sector_stats[k]['count']})")
                     for k in NEIGHBORS.get(code, []) if k in sector_stats}
        # 增长质量定性
        if qm["loss_cum"]:
            quality_verdict = (f"🔴 **累计亏损** (归母 {fin['gm_cum']/1e8:.2f} 亿 {yoy_disp(fin['gm_cum'], fin['gm_prior_cum'])} / "
                               f"扣非 {fin['kf_cum']/1e8:.2f} 亿 {yoy_disp(fin['kf_cum'], fin['kf_prior_cum'])} 双负): "
                               f"Q3 单季归母 {q_gm_y(qm, 'gm')}, 修正规则形式上未触发但亏损事实已由 累计亏损硬约束 v1 处理; "
                               f"TTM 归母 {qm['gm_ttm']/1e8:.2f} 亿 (FY25 靠非经常项扭亏, 扣非口径仍弱)")
        elif qm["triggered"]:
            quality_verdict = f"🟡 {qm['trigger_reason']}; 归母 {fin['gm_yoy']:+.2f}% → 扣非 {qm['kf_yoy']:+.2f}% 重算"
        else:
            quality_verdict = (f"🟢 无修正触发 (归母-扣非增速差 {qm['gap']:+.1f}pp <15pp, OCF "
                               f"{'+' if (qm['ocf_cum'] or 0) > 0 else '缺失/非负'}), 归母口径有效; "
                               f"⚠️ Q3 单季归母 {qm['q_gm_yoy']:+.1f}% 增速需跟踪" if qm["gap"] is not None else "财务字段缺失")
        results.append({
            "code": code, "name": NAMES[code], "rank": p["rank"], "price": price,
            "pe_ttm": pe, "pb": pb, "mcap_yi": q.get("mcap_yi"),
            "float_mcap_yi": q.get("float_mcap_yi"), "turnover_pct": q.get("turnover_pct"),
            "vol_ratio": q.get("vol_ratio"), "v24_score": p.get("v24_total"),
            "report_stop": stop,
            "tech_score": ts_, "fund_score": fs_, "val_score_raw": vs_, "val_score": vs_adj,
            "total": total, "rating": rating, "target": target,
            "tech_notes": tnotes, "fund_notes": fnotes, "val_notes": vnotes,
            "tech_stat": tstat, "fin": fin, "quality": qm,
            "quality_verdict": quality_verdict,
            "risk_lines": RISKS.get(code, []),
            "sector_verdict": SECTOR_VERDICT.get(code, "邻近键样本极薄, 中性参考"),
            "chg_pct": tstat.get("chg_1d"), "chg_date": tstat.get("last_date"),
            "industry_sina": ind_sina, "sector_stat_key": stat_key, "sector_win_rate": sec_wr,
            "neighbor_sectors": neighbors})
        print(f"\n--- {code} {NAMES[code]} (Top10#{p['rank']}, 报告综合 {p.get('v24_total')}, 软止损 {stop}) ---")
        print(f"  {BASE_DATE} 收盘 {price} {tstat.get('chg_1d', 0):+.2f}% (K线末日 {tstat.get('last_date')}, "
              f"K线 {tstat.get('kline_len')} 根) | PE {pe} PB {pb} 市值 {q.get('mcap_yi')}亿 "
              f"换手 {q.get('turnover_pct')}% 量比 {q.get('vol_ratio')}")
        print(f"  技术面 {ts_}/55: {'; '.join(tnotes)}")
        print(f"  基本面 {fs_}/30: {'; '.join(fnotes)}")
        ocf_s = (f"OCF {qm['ocf_cum']/1e8:.2f}亿 (OCF/归母 {qm['ocf_ratio']:.2f})"
                 if qm["ocf_cum"] is not None else "OCF 缺失")
        gm_disp = yoy_disp(fin["gm_cum"], fin["gm_prior_cum"]) if qm["loss_cum"] else f"{fin['gm_yoy']:+.2f}%"
        kf_disp = yoy_disp(fin["kf_cum"], fin["kf_prior_cum"]) if qm["loss_cum"] else f"{qm['kf_yoy']:+.2f}%"
        qgm_disp = yoy_disp(qm["q_gm"], qm["q_gm_prior"])
        qkf_disp = yoy_disp(qm["q_kf"], qm["q_kf_prior"])
        print(f"  财务质量: 累计归母 {gm_disp} / 扣非 {kf_disp} / 营收 {fin['rev_yoy']:+.2f}% | "
              f"Q3单季 归母 {qm['q_gm']/1e8:.2f}亿 ({qgm_disp}) 扣非 {qm['q_kf']/1e8:.2f}亿 "
              f"({qkf_disp}) 营收 {qm['q_rev']/1e8:.1f}亿 ({qm['q_rev_yoy']:+.1f}%) | {ocf_s} | "
              f"TTM 归母/营收 {(qm['ttm_ratio'] or 0):.3f} (陷阱阈值 3)")
        print(f"  估值 {vs_adj}/15: {'; '.join(vnotes)}")
        print(f"  ⇒ 深度评分 {total} {rating} | 目标 {target} 止损 {stop} "
              f"(距止损 {(price/stop-1)*100:+.1f}%)")
        print(f"  板块: sina[{ind_sina}] → 库键[{stat_key or '冷启动'}] {sec_wr} | "
              f"邻近: " + " · ".join(f"{k} {v}" for k, v in neighbors.items()))

    results.sort(key=lambda x: (-x["total"], -(x["chg_pct"] or 0)))

    # ---- 铁律裁定 ----
    print(f"\n=== 铁律裁定 (基准 {BASE_DATE}: 强于四均{MK_FOUR_AVG:+.3f}%+上证{SH_CLOSE:+.2f}%+大盘均+{MK_AVG_ALL}% "
          f"+ 正盈利 + 评级≥增持65 + 未破止损 + 守卫放行) ===")
    law_detail, eligible = {}, []
    for r in results:
        chg = r["chg_pct"] or 0
        r["beat_four"] = chg > MK_FOUR_AVG
        r["beat_sh"] = chg > SH_CLOSE
        r["beat_mkt_avg"] = chg > MK_AVG_ALL
        r["pos"] = chg > 0
        r["stop_broken"] = r["price"] < (r["report_stop"] or 0)
        r["rating_ok"] = r["total"] >= 65
        ok = all([r["pos"], r["beat_four"], r["beat_sh"], r["beat_mkt_avg"],
                  r["rating_ok"], not r["stop_broken"], guard_pass])
        r["law_pass"] = ok
        law_detail[r["code"]] = [
            f"{'✅' if r['beat_four'] else '❌'} 胜四均: {chg:+.2f}% vs {MK_FOUR_AVG:+.3f}%",
            f"{'✅' if r['beat_sh'] else '❌'} 胜上证: vs +{SH_CLOSE}%",
            f"{'✅' if r['beat_mkt_avg'] else '❌'} 胜大盘均: vs +{MK_AVG_ALL}%",
            f"{'✅' if r['pos'] else '❌'} 正盈利",
            f"{'✅' if r['rating_ok'] else '❌'} 深度评级 ≥增持: {r['total']} {r['rating']}",
            f"{'✅' if not r['stop_broken'] else '❌'} 未破止损 {r['report_stop']}",
            f"{'✅' if guard_pass else '❌'} 守卫放行 (情绪 {SNAP['score']} {SNAP['label']})",
        ]
        if ok:
            eligible.append(r)
        print(f"  {r['code']} {r['name']}: {chg:+.2f}% → "
              f"{'✅' if r['beat_four'] else '❌'}四均 {'✅' if r['beat_sh'] else '❌'}上证 "
              f"{'✅' if r['beat_mkt_avg'] else '❌'}大盘均 {'✅' if r['pos'] else '❌'}正盈利 "
              f"深度{r['total']} {'✅' if r['rating_ok'] else '❌'}≥增持 "
              f"{'✅' if not r['stop_broken'] else '❌'}未破止损 {'✅' if guard_pass else '❌'}守卫 "
              f"→ {'✅达标' if ok else '❌未达标'}")
    recommend = eligible[0] if eligible else None
    if recommend:
        print(f"\n🏆 Top1 推荐: {recommend['code']} {recommend['name']} 深度 {recommend['total']} "
              f"{recommend['rating']} | 板块[{recommend['sector_stat_key'] or '冷启动'}] "
              f"{recommend['sector_win_rate']}")
    else:
        print(f"\n🏁 0 推荐 (铁律无候选达标)")

    # ---- 早盘简报异常披露 ----
    ev = briefing_anomaly()
    print(f"\n⚠️ 早盘简报异常披露 (不采信): {ev['exists']}")
    if ev["exists"]:
        print(f"   {ev['verdict']}")

    # ---- 东财同步裁定 ----
    sync_action, sync_result = "skip", None
    try:
        with open(GROUPS_FILE) as f:
            hist = json.load(f)
        occ = {k: v.get("gid") for k, v in hist.items() if k.startswith("20261125")}
        n_groups = len(hist)
    except Exception as e:
        occ, n_groups, hist = {"error": str(e)[:60]}, 0, {}
    FORBIDDEN_GID = occ.get("20261125")   # 裸日期组 20261125 空占位 gid=2096
    print(f"\n📁 东财 groups.json 只读预检: 共 {n_groups} 组 | 20261125* 占用: {occ}")
    if recommend:
        name = "20261125ZZ"
        codes = [recommend["code"]]
        print(f"\n=== 东财同步: 创建 {name} ← {codes} (Top1 单票先例) ===")
        import eastmoney_portfolio as ep
        if name in hist and hist[name].get("gid"):
            print(f"⚠️ {name} 已在缓存: {hist[name]} — 疑似重复建组, 跳过创建")
            sync_action, sync_result = "skip", "already_in_cache"
        else:
            if name in hist:
                print(f"⚠️ 清理 {name} 僵尸缓存: {hist[name]}")
                del hist[name]
            gid = ep.create_group(name)
            print(f"  新 gid: {gid}")
            if gid is None:
                print("❌ create_group 返回 None — 检查 cookie, 跳过同步")
                sync_action, sync_result = "fail", "create_group_none"
            elif str(gid) == str(FORBIDDEN_GID):
                print(f"❌ 防御校验失败: gid={gid} 撞裸日期组 20261125 — 终止同步")
                sync_action, sync_result = "fail", "gid_collision_with_bare_group"
            else:
                added = ep.add_stocks(gid, codes)
                print(f"  add_stocks: {added}")
                rr, _ = ep.api_call(ep.mkurl('gstkinfos', g=gid))
                got = [s['security'].split('$')[1] for s in rr['data']['stkinfolist']]
                print(f"  验证 gstkinfos: gid={gid} 实际含 {len(got)} 只: {got}")
                if set(codes) == set(got):
                    sync_action, sync_result = "done", {"gid": gid, "stocks": got}
                    hist[name] = {
                        'gid': str(gid), 'date': '2026-11-25', 'stocks': codes,
                        'type': 'deep_analysis_zz',
                        'report': f'{TODAY}-选股报告.md (Top10 2 只, 情绪 63 回暖, 仓位 70%)',
                        'top1': (f"{recommend['code']} {NAMES[recommend['code']]} (深度 {recommend['total']} "
                                 f"{recommend['rating']}, 11-24 收盘 {(recommend['chg_pct'] or 0):+.2f}% "
                                 f"胜四均{MK_FOUR_AVG:+.3f}%/上证+{SH_CLOSE}%/大盘均+{MK_AVG_ALL}% + 正盈利; "
                                 f"技{recommend['tech_score']}/基{recommend['fund_score']}/估{recommend['val_score']}; "
                                 f"板块[{recommend['industry_sina']}]{recommend['sector_win_rate']}; "
                                 f"软止损 {recommend['report_stop']} 未破)"),
                        'excluded': ('000158 常山北明 (铁律未达标: 深度评分不足增持 + 累计亏损 + PE 650)'
                                     if recommend["code"] == "000400" else '无'),
                        'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
                        'note': ('11/25 周三盘前, 情绪 63 回暖; 裸日期组 20261125 gid=2096 空占位未触碰'),
                    }
                    with open(GROUPS_FILE, 'w') as f:
                        json.dump(hist, f, ensure_ascii=False, indent=2)
                    print(f"  groups.json 缓存已更新")
                else:
                    sync_action, sync_result = "fail", f"verify_mismatch expect={codes} got={got}"
    else:
        print(f"\n=== 东财同步: 跳过 (0 推荐 → 不创建 20261125ZZ) ===")
        print(f"    先例: 11-13/11-14/11-15/11-19/11-21/11-22/11-23 早盘 0 推荐日均不建组")

    # ---- 输出 JSON + 深度分析报告 md ----
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    out = {"date": TODAY, "base_date": BASE_DATE, "report": TODAY_REPORT,
           "report_note": "08:02:07 盘前版, Top10 表 2 只, 涨跌幅=昨收(11-24)口径",
           "report_size": sz, "report_mtime": mt,
           "trading_day": True, "session": "trading_day_premarket",
           "generated": time.strftime("%H:%M:%S"), "run_id": RUN_ID,
           "trading_legs": legs, "trading_legs_ok": legs_ok,
           "sentiment_snap": SNAP,
           "mk_four_avg_close": MK_FOUR_AVG, "sh_close_pct": SH_CLOSE, "mk_avg_all": MK_AVG_ALL,
           "idx_close_pct": IDX_CLOSE,
           "pool_size": len(pool), "guard_ice": ice, "guard_pass": guard_pass,
           "guard_live": ({"score": live["sentiment_score"], "label": live["sentiment_label"],
                           "is_ice_point": live["is_ice_point"],
                           "data_source_fallback": live["data_source_fallback"]} if live else None),
           "briefing_anomaly": ev,
           "overall_win_rate": rt_meta["overall"], "total_records": rt_meta["records"],
           "sector_count": rt_meta["sectors"],
           "results": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()
                        if k not in ("fin", "quality")} for r in results],
           "eligible_pool": [r["code"] for r in eligible],
           "law_detail": law_detail,
           "recommend": ({"code": recommend["code"], "name": recommend["name"],
                          "total": recommend["total"], "rating": recommend["rating"],
                          "price": recommend["price"], "chg_pct": recommend["chg_pct"],
                          "target": recommend["target"], "stop": recommend["report_stop"],
                          "sector_stat_key": recommend["sector_stat_key"],
                          "sector_win_rate": recommend["sector_win_rate"],
                          "neighbor_sectors": recommend["neighbor_sectors"]} if recommend else None),
           "eastmoney_sync": {"action": sync_action, "result": sync_result,
                              "groups_20261125_occupied": occ,
                              "forbidden_bare_gid": FORBIDDEN_GID}}
    # law_detail 补进 results 视图
    for r in out["results"]:
        r["law_detail"] = law_detail[r["code"]]
    with open(OUT_JSON, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\nJSON: {OUT_JSON}")

    # ---- 生成单股深度分析 md ----
    for r in results:
        out_md = os.path.join(REPORT_DIR, f"{TODAY}-深度分析-{r['code']}.md")
        with open(out_md, "w") as f:
            f.write(md_report(r, rt_meta, out))
        print(f"MD: {out_md}")

    return out, recommend, ev


if __name__ == "__main__":
    main()

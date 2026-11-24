#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-11-24 (周二交易日盘前 08:4x) — 报告 Top10 仅 1 只 · 菜百股份 605599
当日报告 = reports/2026-11-24-选股报告.md (08:02:03 盘前版, 涨跌幅=昨收=11-23 周一收盘口径)
候选池 = 1 只: 605599 菜百股份 (报告综合 69, 技术分 77, +6.33%, 软止损 14.51, 温和上涨+缩量整理)
情绪 V 型修复兑现: 11-23 快照 20 冰点 → 11-24 快照 75 亢奋 (仓位 10%→85%), 与 10-28 先例 (20→58→75) 同型
基准 = 11-23 周一收盘 (信息冻结点, 今日 09:30 开盘前无新行情): 上证 3538.95 +0.15% ·
      深成 10454.37 +1.93% · 创业板 2280.20 +3.08% · 科创50 1227.89 -0.26% → 四均 +1.225%
      大盘平均 +1.31% (报告口径) · 涨停 150/跌停 15
铁律: 最值得购买者需基准交易日当日胜出 (强于四均+上证+大盘均) + 正盈利 + 深度评级 ≥增持(65) +
      未破止损 + 守卫放行 (情绪 75 亢奋非冰点)
评分: 技术面50% + 基本面30% + 估值面20% (deep_analysis_20261022 引擎) + 全部修正规则:
      估值失真 v1 (10-28) / 增长质量 v1 (11-10) / 低基数·负基数 v2 (11-09) / PE过低陷阱 v1 (11-17)
板块: 菜百股份 sina[珠宝首饰] (胜率库无键 → 冷启动) + 巨潮[零售业] 双源;
      邻近键: 黄金 100% (1/1) · 百货 100% (3/3) · 专业连锁 0% (0/1) — 样本极薄
早盘简报 (08:30) 复现昨日同款失真: 上证 ¥12.22 (真值 3538.95) + 深成/创业板用昨收冒充现价 +
      盘前伪实时涨幅 → 不采信, 候选池只认主链报告 Top10 表
东财: 铁律达标则建 20261124ZZ 入 Top1; 裸日期组 20261124 (gid=2071 空占位) / 20261123 (gid=2066) /
      20261123PP (gid=2061, 实持 000410 沈阳机床) 严禁触碰
Kimi: 本机无 kimi CLI / moonshot key — 由 AAna 引擎 + LLM 定性层执行
"""
import sys, os, json, re, time
import datetime
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import requests
import data_sources as ds
from deep_analysis_20261022 import kline, rsi, ma, tech_score, val_score, rating_of

TODAY = "2026-11-24"
BASE_DATE = "2026-11-23"   # K 线末日 / 收盘基准 (11-23 周一, 开盘前信息冻结点)
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
TODAY_REPORT = os.path.join(REPORT_DIR, f"{TODAY}-选股报告.md")
OUT_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_20261124.json")
OUT_MD = os.path.join(REPORT_DIR, f"{TODAY}-深度分析-605599.md")
RUN_ID = "01a20af6-44f4-79ec-9728-aaea8beb354e"
GROUPS_FILE = os.path.expanduser(
    "~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json")

# 11-23 收盘基准 (腾讯快照 2026112316142x 冻结口径, 与报告头部互证: 上证 3538.95 +0.15% ✓)
IDX_CLOSE = {"sh000001": 0.15, "sz399001": 1.93, "sz399006": 3.08, "sh000688": -0.26}
MK_FOUR_AVG = round(sum(IDX_CLOSE.values()) / 4, 3)   # +1.225
SH_CLOSE = 0.15        # 上证 收 3538.95
MK_AVG_ALL = 1.31      # 全市场大盘平均涨跌 (报告口径)
SNAP = {"score": 75, "label": "亢奋", "position": 0.85, "zt_count": 150, "dt_count": 15}

# 菜百股份 2026 三季报关键值 (akshare stock_financial_abstract @20260930, 08:3x 实测)
FIN = {"period": "20260930",
       "gm_cum": 513054797.4, "kf_cum": 573957457.81, "rev_cum": 26448395430.44,
       "gm_prior_cum": 646755626.25, "kf_prior_cum": 585127345.23, "rev_prior_cum": 20471910139.77,
       "gm_h1": 436779234.85, "kf_h1": 481391402.2, "rev_h1": 21042253790.74,
       "gm_prior_h1": 458687579.13, "kf_prior_h1": 395502554.94, "rev_prior_h1": 15247849590.22,
       "gm_fy25": 1133066364.04, "rev_fy25": 28819547398.6,
       "ocf_cum": 1017353298.36, "roe": 11.09, "roe_kf_avg": 12.496184,
       "bps": 5.802496, "mrate": 6.167021, "nrate": 1.978028, "debt_ratio": 49.645105,
       "gm_yoy": -20.672542, "rev_yoy": 29.193588}

# 实持 / 前池 (卖出腿归 daily_v24_sell, 本任务只做盘前预检)
HELD = {"002415": {"zz": "20261120ZZ", "gid": 2051, "entry_ctx": "11-20 早盘关注价 35.38", "stop": 34.64},
        "002142": {"zz": "20261118ZZ", "gid": 2016, "entry": 35.53, "stop": 34.34},
        "000410": {"zz": "20261123PP", "gid": 2061, "stop": 5.84,
                   "note": "尾盘报告建议: 回落 5.9-6.1 分批, 高开>2% (>6.39) 放弃, T+1 今日开盘执行"}}
POOL_PM_1123 = [("000410", "沈阳机床"), ("002048", "宁波华翔"), ("002674", "兴业科技"),
                ("603270", "金帝股份"), ("603767", "中马传动")]


def parse_top10_full(text):
    """解析 '🏆 重点关注 Top 10' 表格 (口径同 deep_analysis_20261121/22/23)。"""
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
    """腾讯快照: 盘前=11-23 收盘冻结口径。返回 {code: (现价, 涨跌幅%, 时间戳, 昨收)}"""
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


def fund_score_with(ni_growth, roe, rev_growth):
    s, notes = 0, []
    if roe is not None:
        if roe >= 15: s += 12; notes.append(f"ROE {roe:.1f}% 优秀")
        elif roe >= 8: s += 8; notes.append(f"ROE {roe:.1f}% 良好")
        elif roe >= 4: s += 4; notes.append(f"ROE {roe:.1f}% 一般")
        else: s += 0; notes.append(f"ROE {roe:.1f}% 弱")
    else:
        s += 4; notes.append("ROE 缺失")
    if ni_growth is not None:
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


def quality_metrics():
    """多期财务指标 → 累计/单季/TTM 增速 + 修正触发判定 (口径同 deep_analysis_pm_20261123)。"""
    f = FIN
    kf_yoy = (f["kf_cum"] / f["kf_prior_cum"] - 1) * 100
    q_gm = f["gm_cum"] - f["gm_h1"]                       # 2026Q3 单季归母
    q_kf = f["kf_cum"] - f["kf_h1"]                       # 单季扣非
    q_rev = f["rev_cum"] - f["rev_h1"]                    # 单季营收
    q_gm_prior = f["gm_prior_cum"] - f["gm_prior_h1"]
    q_kf_prior = f["kf_prior_cum"] - f["kf_prior_h1"]
    q_rev_prior = f["rev_prior_cum"] - f["rev_prior_h1"]
    gm_ttm = f["gm_fy25"] + f["gm_cum"] - f["gm_prior_cum"]
    rev_ttm = f["rev_fy25"] + f["rev_cum"] - f["rev_prior_cum"]
    gap = f["gm_yoy"] - kf_yoy
    ratio = abs(f["ocf_cum"]) / abs(f["gm_cum"])
    # 增长质量修正 v1 (11-10): gap≥15 + OCF<0 + |OCF|/|归母|≥0.5
    q_triggered = bool(gap >= 15 and f["ocf_cum"] < 0 and ratio >= 0.5)
    # 低基数/负基数修正 v2 (11-09): gap≥15 + 上期归母<0.5×上期扣非 + 扣非增速<0
    base_depressed = bool(f["gm_prior_cum"] > 0 and f["kf_prior_cum"] > 0
                          and f["gm_prior_cum"] < 0.5 * f["kf_prior_cum"])
    lb_triggered = bool(gap >= 15 and base_depressed and kf_yoy < 0)
    # 估值失真修正 v1 (10-28): 单季归母<0 + 净利同比<-50
    distorted = bool(q_gm < 0 and f["gm_yoy"] < -50)
    # PE 过低陷阱 v1 (11-17): 归母TTM/营收TTM > 3
    pe_trap = bool(gm_ttm > 0 and rev_ttm > 0 and gm_ttm / rev_ttm > 3)
    return {"kf_yoy": kf_yoy, "q_gm": q_gm, "q_kf": q_kf, "q_rev": q_rev,
            "q_gm_yoy": (q_gm / q_gm_prior - 1) * 100, "q_kf_yoy": (q_kf / q_kf_prior - 1) * 100,
            "q_rev_yoy": (q_rev / q_rev_prior - 1) * 100,
            "gm_ttm": gm_ttm, "rev_ttm": rev_ttm, "ttm_ratio": gm_ttm / rev_ttm,
            "gap": gap, "ocf_ratio": ratio, "ocf_cum": f["ocf_cum"],
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


POOL_NAMES = {"000410": "沈阳机床", "002048": "宁波华翔", "002674": "兴业科技",
              "603270": "金帝股份", "603767": "中马传动",
              "002415": "海康威视", "002142": "宁波银行"}


def trading_day_verify():
    """交易日三副腿核验 (周二: 今日报告存在 + cron 生成记录)。"""
    d = datetime.date(2026, 11, 24)
    legs = {"weekday": "周二" if d.weekday() == 1 else f"非周二?!({d.weekday()})",
            "report_today": os.path.isfile(TODAY_REPORT),
            "cron_generated": None, "cron_pool_line": None, "cron_moneyflow_fallback": False}
    try:
        with open(os.path.expanduser("~/code/AAna/scripts/cron.log")) as f:
            for line in f:
                if "生成 2026-11-24 动态选股报告" in line:
                    legs["cron_generated"] = True
                if "动态股票池" in line:
                    legs["cron_pool_line"] = line.strip()[:120]
                if "只 fallback" in line and "2026-11-24" not in line:
                    legs["cron_moneyflow_fallback"] = True
    except Exception:
        pass
    return legs


def guard_check():
    """P0 冰点守卫 (单一真源 check_ice_point_guard)。盘前 live 源 (ths) = 11-23 收盘口径。"""
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
    """早盘简报异常取证: 今日 08:30 简报复现昨日同款失真。"""
    brief = os.path.join(REPORT_DIR, TODAY, "盘前", f"{TODAY}_0830_早盘简报.md")
    ev = {"brief": brief, "exists": os.path.isfile(brief),
          "sh_price_claimed": None, "sh_change_claimed": None,
          "recommend_rows": 0, "verdict": None}
    if not ev["exists"]:
        ev["verdict"] = "简报不存在"
        return ev
    txt = open(brief).read()
    m = re.search(r'上证指数\s*\|\s*¥?([\d.]+)\s*\|\s*(🔴|🟢)\s*([+-][\d.]+%)', txt)
    if m:
        ev["sh_price_claimed"] = float(m.group(1))
        ev["sh_change_claimed"] = m.group(3)
    rows = [l for l in txt.split("\n")
            if l.strip().startswith("|") and re.search(r'\+\d+\.\d+%', l)
            and not l.strip().startswith("|:")]
    ev["recommend_rows"] = len(rows)
    ev["verdict"] = (f"简报记上证 ¥{ev['sh_price_claimed']} {ev['sh_change_claimed']}"
                     f" (真值 3538.95 +0.15% 周一收盘, 价格字段失真) + 深成/创业板以昨收冒充现价"
                     f" + 盘前 09:30 开盘前列 {ev['recommend_rows']} 行伪实时涨幅 → 不采信, 候选池只认主链报告")
    return ev


def main():
    print("=" * 78)
    print(f"AAna 深度分析 — {TODAY} (周二交易日盘前, 数据基准 {BASE_DATE} 周一收盘冻结)")
    print(f"Run: autopilot ca411dd3 深度分析 {RUN_ID}")
    print("=" * 78)

    # ---- 报告确认 (autopilot 强制: 打印报告名称防错) ----
    sz = os.path.getsize(TODAY_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(TODAY_REPORT)))
    print(f"📄 当日报告: {TODAY_REPORT}")
    print(f"   → 存在 | 大小: {sz} 字节 | 修改: {mt} (08:02:03 盘前版, 主链 cron 生成)")
    text = open(TODAY_REPORT).read()
    pool = parse_top10_full(text)
    print(f"   报告 Top10 表: {len(pool)} 只 → 候选池 = {len(pool)} 只")
    print(f"   报告快照: 情绪{SNAP['score']}({SNAP['label']}) 仓位{SNAP['position']*100:.0f}% "
          f"涨停{SNAP['zt_count']}/跌停{SNAP['dt_count']} ✅正常交易 | 大盘平均 +{MK_AVG_ALL}% "
          f"上证 +{SH_CLOSE}% 收 3538.95 | 情绪 20→75 V 型修复兑现 (10-28 同型先例)")

    legs = trading_day_verify()
    legs_ok = legs["weekday"] == "周二" and legs["report_today"] and legs["cron_generated"]
    print(f"\n📅 交易日三副腿核验: weekday={legs['weekday']} | 今日报告存在={legs['report_today']} "
          f"| cron生成记录={'✅' if legs['cron_generated'] else '❌未见'} | 池行: {legs['cron_pool_line']} "
          f"→ {'PASS' if legs_ok else 'FAIL'}")

    # ---- 基准指数核验 (腾讯收盘快照 vs 报告头部) ----
    sh_live = sh_index_quote() or (None, None, None)
    sh_ok = sh_live[0] == 3538.95 and abs(sh_live[1] - SH_CLOSE) < 0.01
    print(f"\n📊 基准核验: 上证收盘快照 {sh_live[0]} {sh_live[1]:+.2f}% (ts {sh_live[2]}) "
          f"vs 报告 3538.95 +0.15% → {'✅一致' if sh_ok else '🔴漂移'} | "
          f"四均 {MK_FOUR_AVG:+.3f}% (上证+0.15/深成+1.93/创业板+3.08/科创50-0.26) | 大盘均 +{MK_AVG_ALL}%")

    # ---- 胜率库 ----
    with open(os.path.expanduser("~/code/AAna/data/rec_tuning.json")) as f:
        rt = json.load(f)
    sector_stats = rt.get("sector_stats", {})
    print(f"📊 板块胜率库 ({rt.get('generated_at', '')[:10]}): {len(sector_stats)} 板块 | "
          f"整体胜率 {rt.get('overall_win_rate'):.1f}% ({rt.get('total_records')} 笔)")

    # ---- 冰点守卫 ----
    live, snap = guard_check()
    print(f"\n🛡 P0 冰点守卫: 快照口径 情绪{snap['sentiment_score']}({snap['sentiment_label']}) "
          f"仓位{snap.get('position_ratio', SNAP['position'])*100:.0f}% is_ice_point={snap['is_ice_point']}")
    if live:
        print(f"   live 口径 情绪{live['sentiment_score']}({live['sentiment_label']}) is_ice_point="
              f"{live['is_ice_point']} fallback={live['data_source_fallback']}")
    ice = snap["is_ice_point"] and (live["is_ice_point"] if live else True)
    guard_pass = not ice
    print(f"   守卫放行: {'✅ (情绪 75 亢奋, 非冰点)' if guard_pass else '❌ 冰点不放行'}")

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
        qm = quality_metrics()
        fs_ = 0
        if qm["triggered"]:
            fs_, fnotes = fund_score_with(qm["kf_yoy"], FIN["roe"], FIN["rev_yoy"])
            fnotes = fnotes + [f"[{qm['trigger_reason']}] 归母 {FIN['gm_yoy']:+.1f}% → 扣非 {qm['kf_yoy']:+.1f}%"]
        else:
            fs_, fnotes = fund_score_with(FIN["gm_yoy"], FIN["roe"], FIN["rev_yoy"])
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
        # 板块: sina 主键 + 巨潮副源 + 邻近键
        try:
            ind_sina = ds.industry_for_code(code)
        except Exception:
            ind_sina = None
        stat_key = ind_sina if ind_sina in sector_stats else None
        neighbors = [k for k in ("黄金", "百货", "专业连锁", "超市") if k in sector_stats]
        sec = sector_stats.get(stat_key, {}) if stat_key else {}
        sec_wr = (f"{sec.get('win_rate'):.1f}% ({sec.get('win_count')}/{sec.get('count')})"
                  if sec else "无记录(冷启动)")
        nb_str = " | ".join(f"{k} {sector_stats[k]['win_rate']:.0f}% "
                            f"({sector_stats[k]['win_count']}/{sector_stats[k]['count']})"
                            for k in neighbors)
        rec = {"code": code, "name": "菜百股份", "price": price, "pe_ttm": pe, "pb": pb,
               "mcap_yi": q.get("mcap_yi"), "float_mcap_yi": q.get("float_mcap_yi"),
               "turnover_pct": q.get("turnover_pct"), "vol_ratio": q.get("vol_ratio"),
               "v24_score": p.get("v24_total"), "report_stop": stop,
               "tech_score": ts_, "fund_score": fs_, "val_score_raw": vs_, "val_score": vs_adj,
               "total": total, "rating": rating, "target": target,
               "tech_notes": tnotes, "fund_notes": fnotes, "val_notes": vnotes,
               "tech_stat": tstat, "quality": {k: (round(v, 4) if isinstance(v, float) else v)
                                                for k, v in qm.items()},
               "chg_pct": tstat.get("chg_1d"), "chg_date": tstat.get("last_date"),
               "industry_sina": ind_sina, "industry_cninfo": "零售业",
               "sector_stat_key": stat_key, "sector_win_rate": sec_wr,
               "neighbor_sectors": {k: f"{sector_stats[k]['win_rate']:.1f}% "
                                       f"({sector_stats[k]['win_count']}/{sector_stats[k]['count']})"
                                    for k in neighbors}}
        results.append(rec)
        print(f"\n--- {code} 菜百股份 (报告综合 {p.get('v24_total')}, 软止损 {stop}) ---")
        print(f"  {BASE_DATE} 收盘 {price} {tstat.get('chg_1d', 0):+.2f}% (K线末日 {tstat.get('last_date')}, "
              f"K线 {tstat.get('kline_len')} 根) | PE {pe} PB {pb} 市值 {q.get('mcap_yi')}亿 "
              f"换手 {q.get('turnover_pct')}% 量比 {q.get('vol_ratio')}")
        print(f"  技术面 {ts_}/55: {'; '.join(tnotes)}")
        print(f"  基本面 {fs_}/30: {'; '.join(fnotes)}")
        print(f"  财务质量: 累计归母 {FIN['gm_yoy']:+.2f}% / 扣非 {qm['kf_yoy']:+.2f}% / 营收 +{FIN['rev_yoy']:.2f}% | "
              f"Q3单季 归母 {qm['q_gm']/1e8:.2f}亿 ({qm['q_gm_yoy']:+.1f}%) 扣非 {qm['q_kf']/1e8:.2f}亿 "
              f"({qm['q_kf_yoy']:+.1f}%) 营收 {qm['q_rev']/1e8:.1f}亿 ({qm['q_rev_yoy']:+.1f}%) | "
              f"OCF {qm['ocf_cum']/1e8:.2f}亿 (OCF/归母 {qm['ocf_ratio']:.2f}) | "
              f"TTM 归母/营收 {qm['ttm_ratio']:.3f} (陷阱阈值 3)")
        print(f"  估值 {vs_adj}/15: {'; '.join(vnotes)}")
        print(f"  ⇒ 深度评分 {total} {rating} | 目标 {target} 止损 {stop} "
              f"(距止损 {(price/stop-1)*100:+.1f}%)")
        print(f"  板块: sina[{ind_sina}] 巨潮[零售业] → 库键[{stat_key or '冷启动'}] {sec_wr} | 邻近: {nb_str}")

    results.sort(key=lambda x: (-x["total"], -(x["chg_pct"] or 0)))

    # ---- 铁律裁定 ----
    print(f"\n=== 铁律裁定 (基准 {BASE_DATE}: 强于四均{MK_FOUR_AVG:+.3f}%+上证{SH_CLOSE:+.2f}%+大盘均+{MK_AVG_ALL}% "
          f"+ 正盈利 + 评级≥增持65 + 未破止损 + 守卫放行) ===")
    eligible = []
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

    # ---- 实持 / 前池盘前预检 ----
    print(f"\n=== 实持 + 11-23 尾盘池 盘前预检 (收盘冻结口径; 卖出腿归 daily_v24_sell) ===")
    codes_prev = ["002415", "002142"] + [c for c, _ in POOL_PM_1123]
    quotes_prev = tencent_quotes(codes_prev)
    prev_review = []
    for code in codes_prev:
        px, chg, ts_, prev = quotes_prev.get(code, (None, None, "", None))
        h = HELD.get(code)
        row = {"code": code, "close": px, "chg_pct": chg, "quote_ts": ts_,
               "stop": h["stop"] if h else None,
               "stop_broken": (h and px is not None and px < h["stop"]),
               "held_group": h["zz"] if h else None,
               "pnl": (round((px / h["entry"] - 1) * 100, 2) if h and h.get("entry") and px else None),
               "pnl_ctx": (round((px / 35.38 - 1) * 100, 2) if code == "002415" and px else None)}
        prev_review.append(row)
        mark = f"[实持 {row['held_group']}]" if row["held_group"] else "[11-23尾盘池]"
        stop_mark = f"🔴破止损{row['stop']}" if row["stop_broken"] else "止损未破"
        pnl = f" vs入场{row['pnl']:+.2f}%" if row["pnl"] is not None else \
              (f" vs关注价{row['pnl_ctx']:+.2f}%" if row["pnl_ctx"] is not None else "")
        print(f"  {code} {POOL_NAMES.get(code, code)} "
              f"收 {px} {chg:+.2f}% {mark} {stop_mark}{pnl}")
    held_hk = next(r for r in prev_review if r["code"] == "002415")
    held_nb = next(r for r in prev_review if r["code"] == "002142")
    held_sy = next(r for r in prev_review if r["code"] == "000410")

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
        occ = {k: v.get("gid") for k, v in hist.items() if k.startswith("20261124")}
        n_groups, latest_gid = len(hist), max((int(v.get("gid", 0)) for v in hist.values()
                                               if str(v.get("gid", "")).isdigit()), default=None)
    except Exception as e:
        occ, latest_gid, n_groups = {"error": str(e)[:60]}, None, 0
    print(f"\n📁 东财 groups.json 只读预检: 共 {n_groups} 组 | 最新 gid {latest_gid} | "
          f"20261124* 占用: {occ}")
    FORBIDDEN_GID = occ.get("20261124")   # 裸日期组 20261124 空占位
    if recommend:
        name = "20261124ZZ"
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
                print(f"❌ 防御校验失败: gid={gid} 撞裸日期组 20261124 — 终止同步")
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
                        'gid': str(gid), 'date': '2026-11-24', 'stocks': codes,
                        'type': 'deep_analysis_zz',
                        'report': '2026-11-24-选股报告.md (Top10 仅 1 只, 情绪 75 亢奋, 仓位 85%)',
                        'top1': (f"{recommend['code']} 菜百股份 (深度 {recommend['total']} "
                                 f"{recommend['rating']}, 11-23 收盘 +{(recommend['chg_pct'] or 0):.2f}% "
                                 f"胜四均{MK_FOUR_AVG:+.3f}%/上证+{SH_CLOSE}%/大盘均+{MK_AVG_ALL}% + 正盈利; "
                                 f"技{recommend['tech_score']}/基{recommend['fund_score']}/估{recommend['val_score']}; "
                                 f"板块[珠宝首饰]冷启动, 邻近 黄金100%(1/1)/百货100%(3/3); "
                                 f"软止损 {recommend['report_stop']} 未破)"),
                        'excluded': '无 (候选池仅 1 只, 全部入组)',
                        'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
                        'note': ('11/24 周二盘前, 情绪 20→75 V 型修复兑现; 铁律合格池 1/1; '
                                 '裸日期组 20261124 gid=2071 空占位未触碰'),
                    }
                    with open(GROUPS_FILE, 'w') as f:
                        json.dump(hist, f, ensure_ascii=False, indent=2)
                    print(f"  groups.json 缓存已更新")
                else:
                    sync_action, sync_result = "fail", f"verify_mismatch expect={codes} got={got}"
    else:
        print(f"\n=== 东财同步: 跳过 (0 推荐 → 不创建 20261124ZZ) ===")
        print(f"    先例: 11-13/11-14/11-15/11-19/11-21/11-22/11-23 早盘 0 推荐日均不建组")

    # ---- 输出 JSON + 深度分析报告 md ----
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    out = {"date": TODAY, "base_date": BASE_DATE, "report": TODAY_REPORT,
           "report_note": "08:02:03 盘前版, Top10 表 1 只 (菜百股份), 涨跌幅=昨收(11-23)口径",
           "report_size": sz, "report_mtime": mt,
           "trading_day": True, "session": "trading_day_premarket",
           "generated": time.strftime("%H:%M:%S"), "run_id": RUN_ID,
           "trading_legs": legs, "trading_legs_ok": legs_ok,
           "sentiment_snap": SNAP, "sentiment_v_recovery": "11-23 情绪 20 冰点 → 11-24 快照 75 亢奋 (V 型修复兑现, 10-28 同型)",
           "mk_four_avg_close": MK_FOUR_AVG, "sh_close_pct": SH_CLOSE, "mk_avg_all": MK_AVG_ALL,
           "idx_close_pct": IDX_CLOSE,
           "pool_size": len(pool), "guard_ice": ice, "guard_pass": guard_pass,
           "guard_live": ({"score": live["sentiment_score"], "label": live["sentiment_label"],
                           "is_ice_point": live["is_ice_point"],
                           "data_source_fallback": live["data_source_fallback"]} if live else None),
           "briefing_anomaly": ev,
           "overall_win_rate": rt.get("overall_win_rate"), "total_records": rt.get("total_records"),
           "sector_count": len(sector_stats),
           "results": results, "eligible_pool": [r["code"] for r in eligible],
           "recommend": ({"code": recommend["code"], "name": recommend["name"],
                          "total": recommend["total"], "rating": recommend["rating"],
                          "price": recommend["price"], "chg_pct": recommend["chg_pct"],
                          "target": recommend["target"], "stop": recommend["report_stop"],
                          "sector_stat_key": recommend["sector_stat_key"],
                          "sector_win_rate": recommend["sector_win_rate"],
                          "neighbor_sectors": recommend["neighbor_sectors"]} if recommend else None),
           "prev_pool_precheck": prev_review,
           "held_zz": [
               {"group": "20261120ZZ", "gid": 2051, "code": "002415", "name": "海康威视",
                "close": held_hk["close"], "chg_pct": held_hk["chg_pct"], "stop": 34.64,
                "stop_broken": held_hk["stop_broken"], "entry_ctx": "11-20 早盘关注价 35.38",
                "pnl_vs_entry_ctx": held_hk["pnl_ctx"]},
               {"group": "20261118ZZ", "gid": 2016, "code": "002142", "name": "宁波银行",
                "entry": 35.53, "close": held_nb["close"], "chg_pct": held_nb["chg_pct"],
                "stop": 34.34, "stop_broken": held_nb["stop_broken"],
                "pnl_vs_entry": held_nb["pnl"]},
               {"group": "20261123PP", "gid": 2061, "code": "000410", "name": "沈阳机床",
                "close": held_sy["close"], "chg_pct": held_sy["chg_pct"], "stop": 5.84,
                "stop_broken": held_sy["stop_broken"],
                "note": "11-23 尾盘推荐 T+1 开盘执行: 回落 5.9-6.1 分批, 高开>2% (>6.39) 放弃"}],
           "eastmoney_sync": {"action": sync_action, "result": sync_result,
                              "groups_20261124_occupied": occ,
                              "forbidden_bare_gid": FORBIDDEN_GID}}
    with open(OUT_JSON, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\nJSON: {OUT_JSON}")
    return out, recommend, ev, prev_review


if __name__ == "__main__":
    main()

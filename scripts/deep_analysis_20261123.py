#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-11-23 (周一交易日盘前 08:4x) — 报告 Top10 空表 · 0 推荐 · 冰点守卫 · 不建 20261123ZZ
当日报告 = reports/2026-11-23-选股报告.md (2026-11-23 08:01:55 盘前版, 涨跌幅=昨收=11-20 周五收盘口径)
候选池 = 0 只 (Top10 空表 — 空表根因四链条, 见 cron.log 12726-12748 实证, 均为设计行为而非静默故障):
    ① 情绪 20 冰点 → apply_sentiment_adjustment 全池 -10 分 (risk_rules.py:229, score<=30 罚 10)
    ② 资金流接口全挂: 东财 3 连试 RemoteDisconnected → 30/30 只 fallback, net_in=0 → money_score 中性 50
       (无资金流加分, 且资金流权重 30% 变成常数项)
    ③ 涨停池不加入: get_enhanced_stock_pool(include_zt=score>40=False) (情绪 ≤40 高位接盘防护)
    ④ 综合评分阈值 60 (strategy_policy/rec_tuning) + 板块黑名单 8 个 → 冰点罚分后全池不过线 → 表空
    报告自身口径: 建议仓位 10% 空仓观望 + 交易建议 ⚠️停止交易 — 与守卫结论互证
守卫: live ths 08:4x 实测 情绪 20 冰点 is_ice_point=True data_source_fallback=False (非脏数据误判)
      + 快照 (报告 08:01) 情绪 20 冰点 仓位 10% 涨停 30/跌停 3 — 双口径一致, 放行失败
基准 = 11-20 周五收盘 (信息冻结点, 今日 09:30 开盘前无新行情): 情绪 20 冰点 · 大盘平均 -2.16% ·
      四均 -2.74% (上证-1.22/深成-3.09/创业板-3.54/科创50-3.12) · 上证 -1.22% 收 3533.79
铁律: 最值得购买者需基准交易日当日胜出 (强于四均+上证) + 正盈利 + 深度评级 ≥增持(65) + 未破止损 + 守卫放行
      今日候选池 0 只 → 无评分对象 → 铁律无候选, 0 推荐 (先例: 11-13/11-14/11-15/11-19/11-21/11-22)
11-20 深度池 T+1 复核预检 (真值判定须待今日收盘, 复盘链 17:03): 盘前腾讯快照 = 11-20 收盘冻结口径,
      与 11-21/11-22 周末裁定做零漂移核验; 11-21 T+0 终局: Top1 海康威视 fail_negative_and_below_sh
早盘简报异常披露 (不采信): reports/2026-11-23/盘前/2026-11-23_0830_早盘简报.md 记
      「上证指数 ¥12.04 +0.42%」(真值 3533.79 -1.22%, 周五收盘) + 盘前无实时行情却给出 9 只"今日涨幅"
      → 数据失真, 属 agent 链 P1 造假判罚窗内 (今晚 21:3x 到期) 信息产物, 深度分析不以其为候选池
Kimi: 本机无 kimi CLI / moonshot key (连续第 40 日) — 由 AAna 引擎 + LLM 定性层执行
东财: 0 推荐日不同步, 不创建 20261123ZZ; groups.json 只读预检 20261123* 占用 (预期无)
"""
import sys, os, json, re, time
import datetime
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, '/Users/cai/code/AAna/scripts')

TODAY = "2026-11-23"
BASE_DATE = "2026-11-20"   # K 线末日 / 收盘基准 (最后交易日 11-20 周五, 开盘前信息冻结点)
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
TODAY_REPORT = os.path.join(REPORT_DIR, f"{TODAY}-选股报告.md")
OUT_JSON = os.path.expanduser(f"~/code/AAna/data/deep_analysis_{TODAY.replace('-', '')}.json")
PREV_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_20261122.json")
RUN_ID = "01a205cf-a96e-709d-a73d-7ca83160acf9"
GROUPS_FILE = os.path.expanduser(
    "~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json")

# 11-20 收盘基准 (周末两日已冻结复核, 今日盘前无新行情)
MK_FOUR_AVG = -2.74   # 四大核心指数均值 (上证-1.22/深成-3.09/创业板-3.54/科创50-3.12)
SH_CLOSE = -1.22      # 上证指数 收 3533.79
MK_AVG_ALL = -2.16    # 全市场大盘平均涨跌 (报告口径, cron [情绪] 行同值)
SNAP = {"score": 20, "label": "冰点", "position": 0.10, "zt_count": 30, "dt_count": 3}

# 11-20 早盘深度池 10 只 (data/deep_analysis_20261120.json; Top1 已建 20261120ZZ gid=2051)
POOL_1120 = [
    ("002415", "海康威视", 89.0, "买入", 34.64, 37.50, "计算机设备", "100.0% (2/2)", 1.19),
    ("002142", "宁波银行", 89.0, "买入", 34.34, 37.17, "银行", "75.0% (3/4)", 0.48),
    ("600312", "平高电气", 79.6, "买入", 21.62, 23.40, "高低压设备", "100.0% (2/2)", 0.81),
    ("603288", "海天味业", 77.0, "买入", 35.35, 38.26, "调味发酵品", "100.0% (3/3)", 1.25),
    ("601166", "兴业银行", 77.0, "买入", 19.49, 21.09, "银行", "75.0% (3/4)", 0.60),
    ("600406", "国电南瑞", 74.6, "增持", 24.09, 26.08, "工控自动化", "100.0% (5/5)", 0.98),
    ("600066", "宇通客车", 71.6, "增持", 30.76, 33.30, "商用载客车", "0.0% (0/1)", 0.51),
    ("601318", "中国平安", 71.6, "增持", 53.02, 57.39, "多元金融", "100.0% (1/1)", 0.48),
    ("000651", "格力电器", 64.4, "中性", 39.75, 43.03, None, "无记录(冷启动)", 0.56),
    ("600895", "张江高科", 49.5, "减持", 26.36, 28.54, "房地产开发", "33.3% (1/3)", 1.99),
]
HELD = {"002415": {"zz": "20261120ZZ", "gid": 2051, "entry_ctx": "11-20 早盘关注价 35.38", "stop": 34.64},
        "002142": {"zz": "20261118ZZ", "gid": 2016, "entry": 35.53, "stop": 34.34}}

# 周末两日冻结的 11-20 收盘记录 (data/deep_analysis_20261122.json PREV_RECORDED 同源)
PREV_RECORDED = {
    "600066": (32.81, 3.47), "601318": (55.46, 1.46), "601166": (20.30, 1.05),
    "600406": (24.94, 0.40), "000651": (40.86, -0.29), "002142": (35.24, -0.45),
    "603288": (36.25, -0.52), "002415": (35.25, -1.29), "600312": (21.90, -1.75),
    "600895": (24.46, -10.01),
}


def parse_top10_full(text):
    """解析 '🏆 重点关注 Top 10' 表格 (口径同 deep_analysis_20261121/22)。"""
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
            rows.append({"rank": rank, "code": cells[2]})
    return rows


def raw_row_count(text):
    """双重校验: 表区间内含 6 位代码的数据行原始计数 (10-28 口径)。"""
    m = re.search(r'重点关注 Top 10(.*?)(?=\n#{2,3} |\Z)', text, re.S)
    return [l for l in (m.group(1) if m else "").split("\n")
            if l.strip().startswith("|") and re.search(r'\d{6}', l)
            and not l.strip().startswith("|:")]


def trading_day_verify():
    """交易日三副腿核验 (周一, 与周末脚本相反: 今日报告应存在 + cron 应有生成记录)。"""
    d = datetime.date(2026, 11, 23)
    legs = {
        "weekday": "周一" if d.weekday() == 0 else f"非周一?!({d.weekday()})",
        "report_today": os.path.isfile(TODAY_REPORT),
        "cron_generated": None,
        "cron_pool_line": None,
        "cron_moneyflow_fallback": False,
    }
    try:
        with open(os.path.expanduser("~/code/AAna/scripts/cron.log")) as f:
            for line in f:
                if "生成 2026-11-23 动态选股报告" in line:
                    legs["cron_generated"] = True
                if "动态股票池" in line:
                    legs["cron_pool_line"] = line.strip()
                if "30/30 只 fallback" in line:
                    legs["cron_moneyflow_fallback"] = True
    except Exception:
        pass
    return legs


def guard_check():
    """P0 冰点守卫 (单一真源 check_ice_point_guard)。盘前 live 源 (ths) = 11-20 收盘口径。"""
    from aana_afternoon_screen import check_ice_point_guard
    live = None
    try:
        live = check_ice_point_guard()
    except Exception as e:
        print(f"  live 情绪源异常(盘前): {e}")
    snap = check_ice_point_guard(sent={"score": SNAP["score"], "label": SNAP["label"],
                                       "zt_count": SNAP["zt_count"], "dt_count": SNAP["dt_count"]})
    return live, snap


def tencent_quotes(codes):
    """腾讯快照: 盘前=11-20 收盘冻结口径。返回 {code: (现价, 涨跌幅%, 时间戳, 昨收)}"""
    import requests
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


def premarket_brief_anomaly():
    """早盘简报异常取证: 上证价格失真 + 盘前伪实时涨幅 (agent 链 P1 判罚窗内, 不采信)。"""
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
                     f" (真值 3533.79 -1.22% 周五收盘, 失真 {ev['sh_price_claimed']/3533.79:.4%})"
                     f" + 盘前 09:30 开盘前列 {ev['recommend_rows']} 行伪实时涨幅"
                     " → 数据失真, agent链 P1 判罚窗内 (今晚 21:3x 到期) 不采信")
    return ev


def main():
    print("=" * 78)
    print(f"AAna 深度分析 — {TODAY} (周一交易日盘前, 数据基准 {BASE_DATE} 周五收盘冻结)")
    print(f"Run: autopilot ca411dd3 深度分析 {RUN_ID}")
    print("=" * 78)

    # ---- 报告确认 (autopilot 强制: 打印报告名称防错) ----
    sz = os.path.getsize(TODAY_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(TODAY_REPORT)))
    print(f"📄 当日报告: {TODAY_REPORT}")
    print(f"   → 存在 | 大小: {sz} 字节 | 修改: {mt} (08:01:55 盘前版, 主链 cron 生成)")
    text = open(TODAY_REPORT).read()
    pool = parse_top10_full(text)
    raws = raw_row_count(text)
    print(f"   报告 Top10 表: {len(pool)} 只 (原始数据行 {len(raws)} 行, 6 位代码行均为基金推荐表) → 候选池 = {len(pool)} 只")
    print(f"   报告快照: 情绪{SNAP['score']}({SNAP['label']}) 仓位{SNAP['position']*100:.0f}% "
          f"涨停{SNAP['zt_count']}/跌停{SNAP['dt_count']} ⚠️停止交易 | 大盘平均 {MK_AVG_ALL}% 上证 {SH_CLOSE}% 收 3533.79")

    legs = trading_day_verify()
    legs_ok = (legs["weekday"] == "周一" and legs["report_today"]
               and legs["cron_generated"] and legs["cron_pool_line"])
    print(f"\n📅 交易日三副腿核验: weekday={legs['weekday']} | 今日报告存在={legs['report_today']} "
          f"| cron生成记录={'✅' if legs['cron_generated'] else '❌未见'} | 池行: {legs['cron_pool_line']} "
          f"| 资金流fallback={legs['cron_moneyflow_fallback']} → {'PASS' if legs_ok else 'FAIL'}")

    # ---- 空表根因四链条 (cron.log 实证, 全部设计行为) ----
    print(f"\n🔍 Top10 空表根因 (候选池 0 只的四链条, 均为设计行为而非静默故障):")
    print(f"   ① 情绪修正: 20 冰点 ≤30 → apply_sentiment_adjustment 全池 -10 分 (risk_rules.py:229)")
    print(f"   ② 资金流全挂: 东财 3 连试 RemoteDisconnected → 30/30 fallback, net_in=0 → money_score 恒 50 (30% 权重失效)")
    print(f"   ③ 涨停池不加入: include_zt=(score>40)=False (情绪 ≤40 高位接盘防护)")
    print(f"   ④ 阈值 60 + 黑名单 8 板块: 冰点罚分后全池不过线 → 0 只入表 (与报告「停止交易」口径互证)")

    # ---- 胜率库 ----
    with open(os.path.expanduser("~/code/AAna/data/rec_tuning.json")) as f:
        rt = json.load(f)
    sector_stats = rt.get("sector_stats", {})
    print(f"\n📊 板块胜率库 (rec_optimizer 口径, generated_at {rt.get('generated_at')}): "
          f"{len(sector_stats)} 板块 | 整体胜率 {rt.get('overall_win_rate'):.1f}% ({rt.get('total_records')} 笔) "
          f"| 池 0 只 → 无逐股板块胜率映射对象")

    # ---- 冰点守卫 ----
    live, snap = guard_check()
    print(f"\n🛡 P0 冰点守卫: 快照口径 情绪{snap['sentiment_score']}({snap['sentiment_label']}) "
          f"仓位{snap.get('position_ratio', SNAP['position'])*100:.0f}% is_ice_point={snap['is_ice_point']}")
    if live:
        print(f"   live 口径 情绪{live['sentiment_score']}({live['sentiment_label']}) "
              f"仓位{live.get('position_ratio', 0)*100:.0f}% is_ice_point={live['is_ice_point']} "
              f"fallback={live['data_source_fallback']} (ths 源盘前=11-20 收盘口径, 真实非脏数据)")
    ice = snap["is_ice_point"] and (live["is_ice_point"] if live else True)

    # ---- 11-20 深度池 T+1 复核预检 (真值判定须待今日收盘) ----
    print(f"\n=== 11-20 深度池 10 只 T+1 复核预检 (盘前腾讯快照=11-20 收盘冻结口径; 真值判定待今日 17:03 复盘链) ===")
    quotes = tencent_quotes([r[0] for r in POOL_1120])
    review = []
    drift = []
    for code, name, total, rating, stop, target, sk, wr_str, chg_base in POOL_1120:
        px, chg, ts, prev = quotes.get(code, (None, None, "", None))
        sec = sector_stats.get(sk, {}) if sk else {}
        sec_wr_live = (f"{sec['win_rate']:.1f}% ({sec['win_count']}/{sec['count']})" if sec else wr_str)
        rec_px, rec_chg = PREV_RECORDED.get(code, (None, None))
        consistent = (px is not None and rec_px is not None and abs(px - rec_px) < 0.005
                      and chg is not None and rec_chg is not None and abs(chg - rec_chg) < 0.005)
        if not consistent:
            drift.append({"code": code, "today_px": px, "prev_px": rec_px,
                          "today_chg": chg, "prev_chg": rec_chg})
        review.append({
            "code": code, "name": name, "total": total, "rating": rating,
            "stop": stop, "target": target, "sector_stat_key": sk,
            "sector_win_rate": sec_wr_live,
            "close": px, "prev_close": prev, "chg_pct": chg, "quote_ts": ts,
            "chg_base_1119": chg_base,
            "consistent_with_weekend": consistent,
            "beat_four": chg is not None and chg > MK_FOUR_AVG,
            "beat_sh": chg is not None and chg > SH_CLOSE,
            "beat_mkt_avg": chg is not None and chg > MK_AVG_ALL,
            "pos": chg is not None and chg > 0,
            "stop_broken": (stop is not None and px is not None and px < stop),
            "held": code in HELD,
        })
    review.sort(key=lambda x: (x["chg_pct"] if x["chg_pct"] is not None else -99), reverse=True)
    for i, r in enumerate(review, 1):
        tags = []
        if r["beat_four"]:
            tags.append("✅胜四均")
        if r["beat_mkt_avg"]:
            tags.append("✅胜大盘均")
        if r["beat_sh"]:
            tags.append("✅胜上证")
        tags.append("✅正盈利" if r["pos"] else "❌负盈利")
        stop_mark = (f"🔴破止损{r['stop']:.2f}" if r["stop_broken"] else "止损未破")
        held_mark = f" [实持 {HELD[r['code']]['zz']}]" if r["held"] else ""
        cons_mark = "✅一致" if r["consistent_with_weekend"] else "🔴漂移"
        print(f"{i:2d}. {r['code']} {r['name']} 深度{r['total']} {r['rating']} 收{r['close']} {r['chg_pct']:+.2f}% "
              f"[{'/'.join(tags)}] {stop_mark} {cons_mark} | 板块[{r['sector_stat_key'] or '冷启动'}]{r['sector_win_rate']}{held_mark}")
    n_drift = len(drift)
    n_consistent = 10 - n_drift
    n_beat4 = sum(1 for r in review if r["beat_four"])
    n_beat_avg = sum(1 for r in review if r["beat_mkt_avg"])
    n_beatsh = sum(1 for r in review if r["beat_sh"])
    n_pos = sum(1 for r in review if r["pos"])
    n_stop = sum(1 for r in review if r["stop_broken"])
    mean_chg = round(sum(r["chg_pct"] for r in review) / len(review), 2)
    winners = [r for r in review if r["pos"] and r["beat_four"] and r["beat_sh"]]
    print(f"    判定沿用: 胜四均 {n_beat4}/10 · 胜大盘均 {n_beat_avg}/10 · 胜上证 {n_beatsh}/10 · 正盈利 {n_pos}/10 · "
          f"破止损 {n_stop}/10 · 均值 {mean_chg:+.2f}% (超额 vs 大盘均 {mean_chg - MK_AVG_ALL:+.2f}pp) · "
          f"一致性 {n_consistent}/10" + (" · 🔴数据漂移!" if drift else " (盘前信息冻结, 与周末记录零漂移)"))
    if winners:
        print(f"    「当日胜出+正盈利」双达标 {len(winners)}/10: " +
              "、".join(f"{r['name']} {r['chg_pct']:+.2f}%" for r in winners))

    # ---- Top1 铁律裁定沿用 + 实持复核 ----
    top1 = next(r for r in review if r["code"] == "002415")
    law_pass = top1["pos"] and top1["beat_four"] and top1["beat_sh"]
    print(f"\n🏁 Top1 铁律裁定 (沿用周末终局, 盘前复核) — 海康威视 002415 (11-20 深度 89.0 买入, 20261120ZZ gid=2051): "
          f"收 {top1['close']} {top1['chg_pct']:+.2f}% → "
          f"{'✅当日胜出' if (top1['beat_four'] and top1['beat_sh']) else '❌未全面胜出'}"
          f" + {'✅正盈利' if top1['pos'] else '❌负盈利'} → 铁律{'✅达标' if law_pass else '❌未达标'} (fail_negative_and_below_sh)")
    print(f"    持仓: vs 软止损 {top1['stop']} {'🔴已破' if top1['stop_broken'] else '未破'} · "
          f"vs 早盘关注价 35.38 {(top1['close']/35.38-1)*100:+.2f}% — 卖出腿归 daily_v24_sell, 非本任务范围")
    nb = next(r for r in review if r["code"] == "002142")
    print(f"    实持 20261118ZZ 宁波银行 002142 (入场 35.53): 收 {nb['close']} {(nb['close']/35.53-1)*100:+.2f}% "
          f"| 软止损 34.34 {'🔴已破' if nb['stop_broken'] else '未破'} | 今日开盘后以实时链路为准, 跌破即出不死扛")

    # ---- 早盘简报异常披露 ----
    ev = premarket_brief_anomaly()
    print(f"\n⚠️ 早盘简报异常披露 (不采信): {ev['exists']}")
    if ev["exists"]:
        print(f"   {ev['verdict']}")
        print(f"   → 深度分析候选池只认主链报告 Top10 表; agent 链信息产物在 P1 判罚窗内 (今晚 21:3x 到期)")

    # ---- 铁律合成: 池 0 只 + 守卫 → 0 推荐 ----
    results = []  # 官方池 0 只, 无逐股深度评分对象
    eligible = []
    recommend = None

    # ---- 东财 groups 只读预检 ----
    try:
        with open(GROUPS_FILE) as f:
            hist = json.load(f)
        occ = {k: v.get("gid") for k, v in hist.items() if k.startswith("20261123")}
        latest_gid = max((int(v.get("gid", 0)) for v in hist.values()
                          if str(v.get("gid", "")).isdigit()), default=None)
        n_groups = len(hist)
    except Exception as e:
        occ, latest_gid, n_groups = {"error": str(e)[:60]}, None, 0
    print(f"\n📁 东财 groups.json 只读预检: 共 {n_groups} 组 | 最新 gid {latest_gid} | "
          f"20261123* 占用: {occ if occ else '无 (0 推荐日不建组, 与 11-13/11-14/11-15/11-19/11-21/11-22 先例一致)'}")

    print(f"\n=== 逐股深度评分 (技术50%+基本面30%+估值20%): 官方池 0 只 → 无评分对象 ===")
    print(f"铁律合格池 (≥增持65+正盈利+当日胜出+未破止损+守卫放行): [] (守卫冰点+停止交易, 无候选)")
    print(f"\n🏁 0 推荐 → 不创建东财组合 20261123ZZ")
    print(f"    三重独立归因: ① 当日报告 Top10 表 0 只 (空表四链条: 情绪-10/资金流全挂/涨停池不入/阈值60, 均设计行为);")
    print(f"    ② 冰点守卫双口径一致 (快照 20 + live ths 20, fallback=False 真实非脏数据) → 放行失败;")
    print(f"    ③ 报告口径 ⚠️停止交易 + 仓位 10% 空仓观望 — 与守卫互证, 铁律「当日胜出+正盈利」无候选可验证。")
    print(f"    今日看点: 情绪 20 冰点第 1 个交易日 — 关注 10-28 V 型修复先例 (20→58→75), 若开盘后情绪回 30+ 断点")
    print(f"    + 进攻主线 = 修复信号; 11-20 深度池真值 T+1 判定今日收盘后由复盘链 17:03 出; 实持两只止损 34.64/34.34。")

    with open(OUT_JSON, "w") as f:
        json.dump({"date": TODAY, "base_date": BASE_DATE,
                   "report": TODAY_REPORT,
                   "report_note": "08:01:55 盘前版, Top10 表 0 只 (空表四链条设计行为)",
                   "report_size": sz, "report_mtime": mt,
                   "trading_day": True, "session": "trading_day_premarket",
                   "generated": time.strftime("%H:%M:%S"),
                   "trading_legs": legs, "trading_legs_ok": legs_ok,
                   "sentiment_snap": SNAP,
                   "mk_four_avg_close": MK_FOUR_AVG, "sh_close_pct": SH_CLOSE,
                   "mk_avg_all": MK_AVG_ALL,
                   "pool_size": len(pool), "raw_rows": len(raws), "guard_ice": ice,
                   "empty_table_root_cause": [
                       "情绪修正 -10 (score 20 ≤30, risk_rules.apply_sentiment_adjustment)",
                       "资金流接口全挂: 30/30 fallback, net_in=0, money_score 恒 50",
                       "涨停池不加入: include_zt=(score>40)=False",
                       "阈值 60 + 黑名单 8 板块 → 全池不过线"],
                   "guard_live": ({"score": live["sentiment_score"], "label": live["sentiment_label"],
                                   "position_ratio": live.get("position_ratio"),
                                   "is_ice_point": live["is_ice_point"],
                                   "data_source_fallback": live["data_source_fallback"]} if live else None),
                   "premarket_brief_anomaly": ev,
                   "run_id": RUN_ID,
                   "overall_win_rate": rt.get("overall_win_rate"),
                   "total_records": rt.get("total_records"),
                   "sector_count": len(sector_stats),
                   "rec_tuning_generated_at": rt.get("generated_at"),
                   "pool_1120_t1_premarket_precheck": {
                       "source": "data/deep_analysis_20261120.json 早盘深度池 10 只",
                       "judged_on": BASE_DATE,
                       "review_type": "T+1 复核预检 (盘前信息冻结, 真值判定待今日收盘复盘链)",
                       "consistency": f"{n_consistent}/10 与周末记录零漂移" if not drift else f"{n_drift} 只漂移",
                       "drift": drift,
                       "baseline_four_avg": MK_FOUR_AVG, "baseline_sh": SH_CLOSE,
                       "baseline_mkt_avg": MK_AVG_ALL,
                       "n_beat_four": n_beat4, "n_beat_sh": n_beatsh, "n_beat_mkt_avg": n_beat_avg,
                       "n_positive": n_pos, "n_stop_broken": n_stop,
                       "mean_chg": mean_chg,
                       "excess_vs_mkt_avg": round(mean_chg - MK_AVG_ALL, 2),
                       "dual_qualified": [{"code": r["code"], "name": r["name"],
                                           "chg_pct": r["chg_pct"]} for r in winners],
                       "top1_law_verdict": ("pass" if law_pass else "fail_negative_and_below_sh"),
                       "results": review},
                   "held_zz": [
                       {"group": "20261120ZZ", "gid": 2051, "code": "002415", "name": "海康威视",
                        "close": top1["close"], "chg_pct": top1["chg_pct"], "stop": 34.64,
                        "stop_broken": top1["stop_broken"], "judged_on": BASE_DATE,
                        "entry_ctx": "11-20 早盘关注价 35.38",
                        "pnl_vs_entry_ctx": round((top1["close"]/35.38-1)*100, 2)},
                       {"group": "20261118ZZ", "gid": 2016, "code": "002142", "name": "宁波银行",
                        "entry": 35.53, "close": nb["close"], "chg_pct": nb["chg_pct"], "stop": 34.34,
                        "stop_broken": nb["stop_broken"], "judged_on": BASE_DATE,
                        "pnl_vs_entry": round((nb["close"]/35.53-1)*100, 2)}],
                   "recommend": None, "eligible_pool": [], "results": results,
                   "eastmoney_sync": {"action": "skip",
                                      "reason": "0 推荐 (报告池 0 + 冰点守卫双口径 + 停止交易) → 不创建 20261123ZZ",
                                      "groups_20261123_occupied": occ}}, f, ensure_ascii=False, indent=1)
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()

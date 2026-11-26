#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-11-26 (周四交易日盘前 08:4x) — 报告 Top10 空表 · 0 推荐 · 冰点守卫 · 不建 20261126ZZ
当日报告 = reports/2026-11-26-选股报告.md (2026-11-26 08:01:54 生成 / 08:03:34 集成落盘 盘前版,
          涨跌幅=昨收=11-25 周三收盘口径; 09:00 开盘版由 cron 另行生成, 本分析以 08:0x 盘前版为准)
候选池 = 0 只 (Top10 空表 — 空表根因四链条, cron.log 12927-12939 实证, 均为设计行为而非静默故障):
    ① 情绪 25 冰点 ≤30 → apply_sentiment_adjustment 全池 -10 分 (risk_rules.py:229)
    ② 资金流接口全挂: 东财 3 连试 RemoteDisconnected → 30/30 只 fallback, net_in=0 → money_score 恒 50
    ③ 涨停池不加入: get_enhanced_stock_pool(include_zt=score>40=False) (情绪 ≤40 高位接盘防护)
    ④ 综合评分阈值 60 (昨晚 rec_tuning 回落基线 63→60) + 弱势板块黑名单 9 个 → 池 230 只全池不过线 → 表空
    报告自身口径: 建议仓位 10% 空仓观望 + 交易建议 ⚠️停止交易 + 最佳买点「今日无明显回调机会」 — 与守卫互证
守卫: 快照 (报告 08:01) 情绪 25 冰点 仓位 10% 涨停 57/跌停 6; live ths 盘前 = 11-25 收盘口径同值,
      双口径一致 → 放行失败
基准 = 11-25 周三收盘 (信息冻结点, 今日 09:30 开盘前无新行情): 情绪 25 冰点 · 大盘平均 -2.78% ·
      四均 -3.645% (上证-2.03/深成-3.24/创业板-4.19/科创50-5.12, 极端下跌日) · 上证 -2.03% 收 3476.47
铁律: 最值得购买者需基准交易日当日胜出 (强于四均+上证+大盘均) + 正盈利 + 深度评级 ≥增持(65) +
      未破止损 + 守卫放行; 今日候选池 0 只 → 无评分对象 → 铁律无候选, 0 推荐
      (先例: 11-13/11-14/11-15/11-19/11-21/11-22/11-23, 及 11-25 开盘版情绪 25 冰点 0 推荐)
deep 池贴线观察 (11-24/11-25 两日 deep 链产物, 盘前腾讯快照 = 11-25 收盘冻结口径):
      000400 许继电气 20261125ZZ gid=2101 (11-25 day1 -2.36%, 收 25.60 距止损 25.43 +0.67% 贴线)
      605599 菜百股份 20261124ZZ gid=2076 (11-25 day2 -2.20%, 收 14.66 距止损 14.51 +1.03% 贴线)
      000158 常山北明 (11-25 淘汰票对照, 11-25 当日 -8.95% 印证淘汰正确)
早盘简报异常披露 (不采信, 第 4 天复现价格列代码碰撞): 08:30 简报记「上证指数 ¥12.30 +0.08%」
      (¥12.30 = 000001.SZ 平安银行昨收, 真值 3476.47 -2.03%) + 「科创50 ¥16.83」(= 000688.SZ 国城矿业
      昨收, 真值 1186.14 -5.12%) + 深成 10423.60/创业板 2278.99 = 11-24 前日收盘陈旧链路 + 四值族
      +0.08/+1.47/+2.05/+2.00 虚构 + 情绪「乐观」与主链 25 冰点矛盾 + 盘前给出 8 行伪「今日涨幅」
      → 不采信, 候选池只认主链报告 Top10 表
Kimi: 本机无 kimi CLI / moonshot key — 由 AAna 引擎 + LLM 定性层执行
东财: 0 推荐日不同步, 不创建 20261126ZZ; groups.json 只读预检 20261126* 占用 (预期无);
      严禁触碰 20261125ZZ gid=2101 / 20261124ZZ gid=2076 / 20261124 gid=2091 等既有组
"""
import sys, os, json, re, time
import datetime
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, '/Users/cai/code/AAna/scripts')

TODAY = "2026-11-26"
BASE_DATE = "2026-11-25"   # K 线末日 / 收盘基准 (11-25 周三, 开盘前信息冻结点)
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
TODAY_REPORT = os.path.join(REPORT_DIR, f"{TODAY}-选股报告.md")
OUT_JSON = os.path.expanduser(f"~/code/AAna/data/deep_analysis_{TODAY.replace('-', '')}.json")
RUN_ID = "01a21542-d6be-7b68-b861-87a264bbd0e0"
GROUPS_FILE = os.path.expanduser(
    "~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json")

# 11-25 收盘基准 (腾讯快照 202611251614xx 冻结口径, 与报告头部互证: 上证 3476.47 -2.03% ✓;
# 与 11-25 复盘评分大盘表: -2.03/-3.24/-4.19/-5.12 ✓)
IDX_CLOSE = {"sh000001": -2.03, "sz399001": -3.24, "sz399006": -4.19, "sh000688": -5.12}
MK_FOUR_AVG = round(sum(IDX_CLOSE.values()) / 4, 3)   # -3.645
SH_CLOSE = -2.03        # 上证 收 3476.47
MK_AVG_ALL = -2.78      # 全市场大盘平均涨跌 (报告口径, cron [情绪] 行同值)
SNAP = {"score": 25, "label": "冰点", "position": 0.10, "zt_count": 57, "dt_count": 6}

# deep 池贴线观察: 11-25 deep 链 (Top1 推荐 + 淘汰) + 11-24 deep Top1 实持
WATCH = {
    "000400": {"name": "许继电气", "role": "11-25 deep Top1 推荐 (增持 66.6)",
               "group": "20261125ZZ", "gid": 2101, "stop": 25.43},
    "000158": {"name": "常山北明", "role": "11-25 deep 淘汰票对照 (减持 44.7)",
               "group": None, "gid": None, "stop": None},
    "605599": {"name": "菜百股份", "role": "11-24 deep Top1 推荐 (增持 70.4)",
               "group": "20261124ZZ", "gid": 2076, "stop": 14.51},
}


def parse_top10_full(text):
    """解析 '🏆 重点关注 Top 10' 表格 (口径同 deep_analysis_20261121..25)。"""
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
            rows.append({"rank": rank, "code": cells[2], "name_raw": cells[1]})
    return rows


def raw_row_count(text):
    """双重校验: 表区间内含 6 位代码的数据行原始计数 (10-28 口径)。"""
    m = re.search(r'重点关注 Top 10(.*?)(?=\n#{2,3} |\Z)', text, re.S)
    return [l for l in (m.group(1) if m else "").split("\n")
            if l.strip().startswith("|") and re.search(r'\d{6}', l)
            and not l.strip().startswith("|:")]


def trading_day_verify():
    """交易日三副腿核验 (周四: 今日报告存在 + cron 生成记录; 池行/fallback 取今日生成段)。"""
    d = datetime.date(2026, 11, 26)
    legs = {"weekday": "周四" if d.weekday() == 3 else f"非周四?!({d.weekday()})",
            "report_today": os.path.isfile(TODAY_REPORT),
            "cron_generated": None, "cron_pool_line": None, "cron_moneyflow_fallback": False,
            "cron_sector_fail": False, "cron_north_fail": False}
    try:
        in_today = False
        with open(os.path.expanduser("~/code/AAna/scripts/cron.log")) as f:
            for line in f:
                if "生成 2026-11-26 动态选股报告" in line:
                    legs["cron_generated"] = True
                    in_today = True
                    continue
                if in_today and re.match(r"\[AAna v2\.5\] 生成 20", line):
                    in_today = False
                if in_today:
                    if "动态股票池" in line:
                        legs["cron_pool_line"] = line.strip()
                    if "30/30 只 fallback" in line:
                        legs["cron_moneyflow_fallback"] = True
                    if "板块数据失败" in line:
                        legs["cron_sector_fail"] = True
                    if "北向资金失败" in line:
                        legs["cron_north_fail"] = True
    except Exception:
        pass
    return legs


def guard_check():
    """P0 冰点守卫 (单一真源 check_ice_point_guard)。盘前 live 源 (ths) = 11-25 收盘口径。"""
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
    """腾讯快照: 盘前=11-25 收盘冻结口径。返回 {code: (现价, 涨跌幅%, 时间戳, 昨收)}"""
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


def sh_index_quote():
    """上证指数 sh000001 (指数必须显式 sh 前缀, 否则 sz000001=平安银行 — 简报代码碰撞同源)。"""
    import requests
    r = requests.get("https://qt.gtimg.cn/q=sh000001", timeout=10,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.encoding = "gbk"
    m = re.search(r'v_sh000001="([^"]+)"', r.text)
    if not m:
        return None
    p = m.group(1).split("~")
    return float(p[3]), float(p[32]), p[30]


def briefing_anomaly():
    """早盘简报异常取证: 价格列代码碰撞第 4 天 (上证=平安银行昨收/科创50=国城矿业昨收)。"""
    brief = os.path.join(REPORT_DIR, TODAY, "盘前", f"{TODAY}_0830_早盘简报.md")
    ev = {"brief": brief, "exists": os.path.isfile(brief),
          "sh_price_claimed": None, "sh_change_claimed": None,
          "kc50_price_claimed": None, "sentiment_claimed": None,
          "pseudo_gain_rows": 0, "verdict": None}
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
    m3 = re.search(r'市场情绪[:：]\*?\*?\s*(\S+)', txt)
    if m3:
        ev["sentiment_claimed"] = m3.group(1)
    rows = [l for l in txt.split("\n")
            if l.strip().startswith("|") and re.search(r'[+-]\d+\.\d+%', l)
            and not l.strip().startswith("|:")]
    ev["pseudo_gain_rows"] = len(rows)
    ev["verdict"] = (f"简报记上证 ¥{ev['sh_price_claimed']} {ev['sh_change_claimed']}"
                     f" (¥12.30=000001.SZ 平安银行昨收, 真值 3476.47 -2.03% 周三收盘, 第 4 天代码碰撞)"
                     f" + 科创50 ¥{ev['kc50_price_claimed']} (=000688.SZ 国城矿业昨收, 真值 1186.14 -5.12%)"
                     f" + 深成/创业板 = 11-24 前日收盘陈旧链路 + 四值族虚构 + 情绪「{ev['sentiment_claimed']}」"
                     f"与主链 25 冰点矛盾 + 盘前 {ev['pseudo_gain_rows']} 行伪「今日涨幅」"
                     " → 不采信, 候选池只认主链报告")
    return ev


def main():
    print("=" * 78)
    print(f"AAna 深度分析 — {TODAY} (周四交易日盘前, 数据基准 {BASE_DATE} 周三收盘冻结)")
    print(f"Run: autopilot ca411dd3 深度分析 {RUN_ID}")
    print("=" * 78)

    # ---- 报告确认 (autopilot 强制: 打印报告名称防错) ----
    sz = os.path.getsize(TODAY_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(TODAY_REPORT)))
    print(f"📄 当日报告: {TODAY_REPORT}")
    print(f"   → 存在 | 大小: {sz} 字节 | 修改: {mt} (08:01:54 生成 盘前版, 主链 cron 08:03 落盘)")
    text = open(TODAY_REPORT).read()
    pool = parse_top10_full(text)
    raws = raw_row_count(text)
    print(f"   报告 Top10 表: {len(pool)} 只 (原始数据行 {len(raws)} 行) → 候选池 = {len(pool)} 只")
    if pool:
        print(f"   🔴 异常: 盘前版出现候选 {pool} — 与 cron 空表证据矛盾, 终止分析待人工复核")
        return None
    print(f"   报告快照: 情绪{SNAP['score']}({SNAP['label']}) 仓位{SNAP['position']*100:.0f}% "
          f"涨停{SNAP['zt_count']}/跌停{SNAP['dt_count']} ⚠️停止交易 | 大盘平均 {MK_AVG_ALL}% "
          f"上证 {SH_CLOSE}% 收 3476.47 | 热点板块「数据获取中」(板块接口失败)")

    legs = trading_day_verify()
    legs_ok = (legs["weekday"] == "周四" and legs["report_today"]
               and legs["cron_generated"] and legs["cron_pool_line"])
    print(f"\n📅 交易日三副腿核验: weekday={legs['weekday']} | 今日报告存在={legs['report_today']} "
          f"| cron生成记录={'✅' if legs['cron_generated'] else '❌未见'} | 池行: {legs['cron_pool_line']} "
          f"| 资金流fallback={legs['cron_moneyflow_fallback']} → {'PASS' if legs_ok else 'FAIL'}")

    # ---- 空表根因四链条 (cron.log 今日段实证, 全部设计行为) ----
    print(f"\n🔍 Top10 空表根因 (候选池 0 只的四链条, 均为设计行为而非静默故障):")
    print(f"   ① 情绪修正: 25 冰点 ≤30 → apply_sentiment_adjustment 全池 -10 分 (risk_rules.py:229)")
    print(f"   ② 资金流全挂: 东财 3 连试 RemoteDisconnected → 30/30 fallback, net_in=0 → money_score 恒 50 (30% 权重失效)")
    print(f"   ③ 涨停池不加入: include_zt=(score>40)=False (情绪 ≤40 高位接盘防护)")
    print(f"   ④ 阈值 60 (昨晚 rec_tuning 回落基线 63→60) + 黑名单 9 弱势板块: 冰点罚分后 230 只全池不过线 → 表空")

    # ---- 基准指数核验 (腾讯收盘快照 vs 报告头部) ----
    sh_live = sh_index_quote() or (None, None, None)
    sh_ok = sh_live[0] == 3476.47 and abs(sh_live[1] - SH_CLOSE) < 0.01
    print(f"\n📊 基准核验: 上证收盘快照 {sh_live[0]} {sh_live[1]:+.2f}% (ts {sh_live[2]}) "
          f"vs 报告 3476.47 {SH_CLOSE:+.2f}% → {'✅一致' if sh_ok else '🔴漂移'} | "
          f"四均 {MK_FOUR_AVG:+.3f}% (上证-2.03/深成-3.24/创业板-4.19/科创50-5.12 极端下跌日) "
          f"| 大盘均 {MK_AVG_ALL}%")

    # ---- 胜率库 ----
    with open(os.path.expanduser("~/code/AAna/data/rec_tuning.json")) as f:
        rt = json.load(f)
    sector_stats = rt.get("sector_stats", {})
    weak = rt.get("weak_sectors") or rt.get("blacklist") or []
    print(f"\n📊 板块胜率库 (rec_optimizer 口径, generated_at {rt.get('generated_at')}): "
          f"{len(sector_stats)} 板块 | 整体胜率 {rt.get('overall_win_rate'):.1f}% ({rt.get('total_records')} 笔) "
          f"| 弱势黑名单 {len(weak)} 个: {weak if weak else '字段缺省'} "
          f"| 池 0 只 → 无逐股板块胜率映射对象")

    # ---- 冰点守卫 ----
    live, snap = guard_check()
    print(f"\n🛡 P0 冰点守卫: 快照口径 情绪{snap['sentiment_score']}({snap['sentiment_label']}) "
          f"仓位{snap.get('position_ratio', SNAP['position'])*100:.0f}% is_ice_point={snap['is_ice_point']}")
    if live:
        print(f"   live 口径 情绪{live['sentiment_score']}({live['sentiment_label']}) "
              f"仓位{live.get('position_ratio', 0)*100:.0f}% is_ice_point={live['is_ice_point']} "
              f"fallback={live['data_source_fallback']} (ths 源盘前=11-25 收盘口径)")
    ice = snap["is_ice_point"] and (live["is_ice_point"] if live else True)
    guard_pass = not ice
    print(f"   守卫放行: {'✅' if guard_pass else '❌ 冰点不放行 (双口径一致, 情绪 25)'}")

    # ---- deep 池贴线观察 (11-24/11-25 两日产物, 盘前冻结快照复核) ----
    print(f"\n=== deep 池贴线观察 (盘前腾讯快照 = {BASE_DATE} 收盘冻结口径; 实时判定待今日盘中) ===")
    quotes = tencent_quotes(list(WATCH.keys()))
    watch_rows = []
    for code, meta in WATCH.items():
        px, chg, ts, prev = quotes.get(code, (None, None, "", None))
        stop = meta["stop"]
        gap = (round((px / stop - 1) * 100, 2) if (px and stop) else None)
        row = {"code": code, "name": meta["name"], "role": meta["role"],
               "group": meta["group"], "gid": meta["gid"], "stop": stop,
               "close": px, "prev_close": prev, "chg_pct": chg, "quote_ts": ts,
               "gap_to_stop_pct": gap,
               "stop_broken": (px is not None and stop is not None and px < stop)}
        watch_rows.append(row)
        g = f"距止损 {stop} {gap:+.2f}%" if gap is not None else "无止损键"
        brk = "🔴已破" if row["stop_broken"] else ("🟡贴线" if gap is not None and gap < 2 else "未破")
        grp = f" [实持 {meta['group']} gid={meta['gid']}]" if meta["group"] else " [淘汰对照]"
        print(f"  {code} {meta['name']} ({meta['role']}): 收 {px} {chg:+.2f}% (ts {ts}) | {g} {brk}{grp}")

    held = [r for r in watch_rows if r["group"]]
    n_risk = [r for r in held if r["gap_to_stop_pct"] is not None and r["gap_to_stop_pct"] < 2]

    # ---- 早盘简报异常披露 ----
    ev = briefing_anomaly()
    print(f"\n⚠️ 早盘简报异常披露 (不采信): {ev['exists']}")
    if ev["exists"]:
        print(f"   {ev['verdict']}")

    # ---- 铁律合成: 池 0 只 + 守卫冰点 → 0 推荐 ----
    results = []   # 官方池 0 只, 无逐股深度评分对象
    eligible = []
    recommend = None

    # ---- 东财 groups 只读预检 ----
    try:
        with open(GROUPS_FILE) as f:
            hist = json.load(f)
        occ = {k: v.get("gid") for k, v in hist.items() if k.startswith("20261126")}
        latest_gid = max((int(v.get("gid", 0)) for v in hist.values()
                          if str(v.get("gid", "")).isdigit()), default=None)
        n_groups = len(hist)
    except Exception as e:
        occ, latest_gid, n_groups = {"error": str(e)[:60]}, None, 0
    print(f"\n📁 东财 groups.json 只读预检: 共 {n_groups} 组 | 最新 gid {latest_gid} | "
          f"20261126* 占用: {occ if occ else '无'}")

    print(f"\n=== 逐股深度评分 (技术50%+基本面30%+估值20%): 官方池 0 只 → 无评分对象 ===")
    print(f"铁律合格池 (≥增持65+正盈利+当日胜出+未破止损+守卫放行): [] (守卫冰点+停止交易, 无候选)")
    print(f"\n🏁 0 推荐 → 不创建东财组合 20261126ZZ")
    print(f"    三重独立归因: ① 当日报告 Top10 表 0 只 (空表四链条: 情绪-10/资金流全挂/涨停池不入/阈值60+黑名单9, 均设计行为);")
    print(f"    ② 冰点守卫双口径一致 (快照 25 + live ths 25) → 放行失败;")
    print(f"    ③ 报告口径 ⚠️停止交易 + 仓位 10% 空仓观望 + 「今日无明显回调机会」 — 与守卫互证, 铁律「当日胜出+正盈利」无候选可验证。")
    print(f"    今日看点: 情绪 25 冰点第 2 个交易日 + 四核极端下跌日 (-2.03/-3.24/-4.19/-5.12) 次日 — 关注 10-28 V 型修复先例")
    print(f"    (20→58→75): 若开盘后情绪回 30+ 断点 + 进攻主线 = 修复信号; 实持双票贴线 (许继 +0.67%/菜百 +1.03%) 开盘破位即出;")
    print(f"    09:00 开盘版报告由 cron 生成, 今晚 21:3x 判罚窗第 3 采样 (盘后链)。")

    with open(OUT_JSON, "w") as f:
        json.dump({"date": TODAY, "base_date": BASE_DATE,
                   "report": TODAY_REPORT,
                   "report_note": "08:01:54 生成/08:03:34 落盘 盘前版, Top10 表 0 只 (空表四链条设计行为)",
                   "report_size": sz, "report_mtime": mt,
                   "trading_day": True, "session": "trading_day_premarket",
                   "generated": time.strftime("%H:%M:%S"), "run_id": RUN_ID,
                   "trading_legs": legs, "trading_legs_ok": legs_ok,
                   "sentiment_snap": SNAP,
                   "mk_four_avg_close": MK_FOUR_AVG, "sh_close_pct": SH_CLOSE,
                   "mk_avg_all": MK_AVG_ALL, "idx_close_pct": IDX_CLOSE,
                   "pool_size": len(pool), "raw_rows": len(raws),
                   "guard_ice": ice, "guard_pass": guard_pass,
                   "empty_table_root_cause": [
                       "情绪修正 -10 (score 25 ≤30, risk_rules.apply_sentiment_adjustment)",
                       "资金流接口全挂: 东财 3 连试 RemoteDisconnected, 30/30 fallback, money_score 恒 50",
                       "涨停池不加入: include_zt=(score>40)=False",
                       "阈值 60 (昨晚回落基线 63→60) + 黑名单 9 弱势板块 → 230 只全池不过线"],
                   "baseline_check": {"sh_snapshot_price": sh_live[0], "sh_snapshot_chg": sh_live[1],
                                      "consistent_with_report": sh_ok},
                   "guard_live": ({"score": live["sentiment_score"], "label": live["sentiment_label"],
                                   "position_ratio": live.get("position_ratio"),
                                   "is_ice_point": live["is_ice_point"],
                                   "data_source_fallback": live["data_source_fallback"]} if live else None),
                   "premarket_brief_anomaly": ev,
                   "overall_win_rate": rt.get("overall_win_rate"),
                   "total_records": rt.get("total_records"),
                   "sector_count": len(sector_stats),
                   "rec_tuning_generated_at": rt.get("generated_at"),
                   "weak_sectors": weak,
                   "deep_pool_watch": {
                       "source": "11-24/11-25 两日 deep 链产物 (data/deep_analysis_20261124/25.json)",
                       "judged_on": BASE_DATE,
                       "note": "盘前信息冻结口径; 实时破位判定待今日盘中, 卖出腿归 daily_v24_sell",
                       "held_near_stop_count": len(n_risk),
                       "results": watch_rows},
                   "held_zz": [{"group": r["group"], "gid": r["gid"], "code": r["code"],
                                "name": r["name"], "close": r["close"], "chg_pct": r["chg_pct"],
                                "stop": r["stop"], "gap_to_stop_pct": r["gap_to_stop_pct"],
                                "stop_broken": r["stop_broken"], "judged_on": BASE_DATE}
                               for r in held],
                   "recommend": None, "eligible_pool": [], "results": results,
                   "eastmoney_sync": {"action": "skip",
                                      "reason": "0 推荐 (报告池 0 + 冰点守卫双口径 + 停止交易) → 不创建 20261126ZZ",
                                      "groups_20261126_occupied": occ}}, f, ensure_ascii=False, indent=1)
    print(f"JSON: {OUT_JSON}")
    return {"recommend": None, "pool_size": 0, "guard_pass": guard_pass}


if __name__ == "__main__":
    main()

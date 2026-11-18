#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-11-18 (周三交易日盘前 08:5x) — 情绪 40 分歧 · 仓位 20% · 候选池 10 只
当日报告 = reports/2026-11-18-选股报告.md (11-18 08:01:58 盘前版, 涨跌幅=昨收=11-17 周二收盘口径)
候选池 = 当日报告 Top10 表全部 10 只 (600415 小商品城 / 603283 赛腾股份 / 600406 国电南瑞 /
         600660 福耀玻璃 / 600801 华新建材 / 600483 福能股份 / 002945 华林证券 /
         000066 中国长城 / 000651 格力电器 / 002142 宁波银行, 11-17 收盘 +0.85~+1.94% 全正,
         报告综合分 65x6+64x4; 裸日期组 20261118 gid=2011 今晨空占位组 严禁触碰)
方法: 复用 deep_analysis_20261022 评分引擎 (技术50% + 基本面30% + 估值20%)
      + 估值面失真修正 v1 (10-28 PM 规则: 最新单季归母转亏 且 净利同比<-50% → PE 记 0 只留 PB)
      腾讯行情(盘前=11-17 收盘冻结口径) + 腾讯日K(120d qfq, 末日 11-17) + akshare 财务摘要
      + 东财 f127/sina 行业双源核验 + rec_tuning 板块胜率 (117 键 439 笔 50.1%, 11-18 08:51 更新)
铁律: 最值得购买者需基准交易日 11-17 当日胜出 (强于大盘平均 -0.57% 且正盈利) + 深度评级 ≥增持(65)
      + 未破报告软止损 + 守卫放行 (40 分歧/仓位 20% ≥10% → 放行)
链路语境: 11-14~11-16 连续 3 日 0 推荐 (冰点守卫短路/池空) → 11-17 情绪回暖但仍 30→40 边缘分歧带;
      11-17 早盘腿无深度分析 JSON (无 ZZ 组), 裸日期组 20261117 (gid=2006) 与今日 Top10 完全同池 10 只
      (连续性披露, note 陈旧标注"早盘 7 只"与实际 10 只不符); 11-17 尾盘腿池 5 只 → PP 组实持模塑科技
      000700, T+0 判决今日以 11-17 收盘口径执行; 中国长城 000066 同时出现在 11-17 尾盘池 + 今日 Top10
      + 模拟仓 (11-14 建仓 ¥11.68) — 三重身份披露
今日热点错位披露: 报告热点板块 集成电路制造/橡胶助剂/厨房小家电/半导体材料/钼 与推荐池板块
      (消费/金融/基建/家电/银行) 基本无交集 — 11-11 先例: 题材主线命中 6/10 均值 +2.70% vs
      未命中 -4.28% (差 +6.97pp), 错位日历史胜率偏低, 降权披露
Kimi: 本机无 kimi CLI / moonshot key (连续第 35 日) — 由 AAna 引擎 + LLM 定性层执行
东财: 依铁律合格池 Top1 → 20261118ZZ (先例: 仅 Top1 入组); 裸日期 20261118 (gid=2011 空占位) 严禁触碰;
      昨日 20261117 (gid=2006) / 20261117PP (gid=2001) 不动; 创建后必须 gid∉当日占用集 防御校验
"""
import sys, os, json, re, time
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import data_sources as ds
from deep_analysis_20261022 import tech_score, fund_score, val_score, rating_of

TODAY = "2026-11-18"
BASE_DATE = "2026-11-17"   # K 线末日 / 昨收基准 (11-17 周二收盘)
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
TODAY_REPORT = os.path.join(REPORT_DIR, f"{TODAY}-选股报告.md")  # 今日 08:01:58 盘前版
OUT_JSON = os.path.expanduser(f"~/code/AAna/data/deep_analysis_{TODAY.replace('-', '')}.json")
YDAY_AM_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_20261117.json")
YDAY_PM_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_pm_20261117.json")
MK_AVG = -0.57            # 报告快照: 大盘平均涨跌 -0.57% (11-17 收盘基准)
SH_CLOSE = -0.50          # 上证 -0.50% 收 3584.58 (11-17 收盘基准)
SNAP = {"score": 40, "label": "分歧", "zt_count": 36, "dt_count": 4, "position": 0.20}
HOT_SECTORS = ["集成电路制造", "橡胶助剂", "厨房小家电", "半导体材料", "钼"]
RUN_ID = "01a1e6e9-8bda-7355-90fd-0ba4203a163e"
GROUPS_FILE = os.path.expanduser(
    "~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json")

# 行业 (双源 runtime 核验 11-18 08:5x; stat_key → rec_tuning sector_stats 117 键 439 笔) 映射
SECTOR_MAP = {
    "600415": ("商贸零售-义乌小商品市场经营+Chinagoods 平台+贸易服务 (市场经营主业+数字贸易)",
               None, [], "冷启动预期: 商贸零售/贸易类键不在板块胜率库 (117 键无对应)"),
    "603283": ("专用设备-3C 自动化检测设备+半导体量测设备 (并购瑞士 Optima 布局半导体检测)",
               "专用设备",
               [("其它专用机械", "邻键-其它专用机械(1/1 薄样本, cold_sectors)")],
               "披露: 东财键「专用设备」胜率库 0% (0/1) 薄样本; sina 键「其它专用机械」在 cold_sectors "
               "(11-11 根因 E 冷启动盲区 8 板块之一)"),
    "600406": ("电网设备-电网自动化+特高压+电力信息化龙头 (国网系二次设备绝对龙头)",
               None, [("火电", "邻键-火电(2/3)")],
               "冷启动预期: 电网设备/电力设备类键不在板块胜率库"),
    "600660": ("汽车零部件-汽车玻璃全球龙头 (全球市占率 30%+, 智能玻璃升级)",
               "汽车零部件", [], None),
    "600801": ("建材-水泥+骨料 (华中水泥龙头, 水泥主业+海外布局)",
               None, [("火电", "远邻键-火电(2/3) 仅作参照")],
               "冷启动预期: 水泥/建材类键不在板块胜率库"),
    "600483": ("电力-福建风电+火电+热电联产 (新能源运营商)",
               "火电", [("热电", "邻键-热电(1/1 薄样本)")], None),
    "002945": ("证券-经纪+自营中小券商 (互联网证券差异化)",
               None, [], "冷启动预期: 证券/券商类键不在板块胜率库"),
    "000066": ("计算机设备-信创 PC/服务器+飞腾 CPU 参股 (党政信创主力)",
               "计算机设备", [],
               "披露: 东财键「计算机设备」在 cold_sectors (11-11 根因 E 冷启动盲区), "
               "胜率库 100% (1/1) 薄样本不可依赖"),
    "000651": ("家电-空调白电龙头 (空调主业+工业装备+再生资源)",
               None, [("厨房小家电", "热点板块邻键(今涨+3.2%) 非胜率库键")],
               "冷启动预期: 家电/白色家电类键不在板块胜率库"),
    "002142": ("银行-城商行 (宁波本地中小微+消费贷特色, 不良率低位)",
               "银行", [], None),
}


def parse_top10_full(text):
    """解析 '🏆 重点关注 Top 10' 表格: 排名/名称/代码/价格/涨跌幅/技术分/综合分/软止损 (口径同 11-12)"""
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
            name = re.sub(r'^[^一-龥A-Za-z0-9]+', '', cells[1])
            price = float(cells[3].replace('¥', '').replace(',', ''))
            chg = float(re.search(r'[+-]?\d+\.?\d*', cells[4]).group())
            tech = int(re.sub(r'\D', '', cells[5]) or 0)
            v24 = int(re.sub(r'\D', '', cells[7]) or 0)
            stop = (float(re.search(r'\d+\.?\d*', cells[10]).group())
                    if len(cells) > 10 and re.search(r'\d', cells[10]) else None)
            rows.append({"rank": rank, "code": cells[2], "name": name, "price": price,
                         "chg": chg, "tech": tech, "v24": v24, "stop": stop})
    return rows


def raw_row_count(text):
    """双重校验: 表区间内含 6 位代码的数据行原始计数 (防解析器误判, 10-28 口径)。"""
    m = re.search(r'重点关注 Top 10(.*?)(?=\n#{2,3} |\Z)', text, re.S)
    return [l for l in (m.group(1) if m else "").split("\n")
            if l.strip().startswith("|") and re.search(r'\d{6}', l)
            and not l.strip().startswith("|:")]


def guard_check():
    """P0 冰点守卫 (单一真源 check_ice_point_guard)。盘前未开盘: live 源 (ths) = 11-17 收盘口径,
    以报告快照 40 分歧为判定口径 (11-17 收盘情绪 → 11-18 盘前延续)"""
    from aana_afternoon_screen import check_ice_point_guard
    live = None
    try:
        live = check_ice_point_guard()
    except Exception as e:
        print(f"  live 情绪源异常(盘前未开盘): {e}")
    snap = check_ice_point_guard(sent={"score": SNAP["score"], "label": SNAP["label"],
                                       "zt_count": SNAP["zt_count"], "dt_count": SNAP["dt_count"]})
    return live, snap


def load_sector_stats():
    with open(os.path.expanduser("~/code/AAna/data/rec_tuning.json")) as f:
        rt = json.load(f)
    return (rt.get("sector_stats", {}), rt.get("overall_win_rate"),
            rt.get("total_records"), rt.get("generated_at"))


def load_nds():
    with open(os.path.expanduser("~/code/AAna/data/next_day_strategy.json")) as f:
        return json.load(f)


def load_yday_pool(path):
    """昨日深度池动态加载: entry=分析时点价, stop=止损, total/rating=当日深度分"""
    with open(os.path.expanduser(path)) as f:
        d = json.load(f)
    out = []
    for r in d.get("results", []):
        out.append({"code": r["code"], "name": r["name"], "total": r.get("total"),
                    "rating": r.get("rating"), "stop": r.get("stop"), "entry": r.get("price"),
                    "sector": r.get("sector_stat_key") or r.get("industry")})
    out.sort(key=lambda x: -(x["total"] or 0))
    return out


def fetch_kline(code):
    """腾讯日K 120d qfq — fqkline qfq 端点 WAF 501 时降级 kline/kline 非复权 (10-26 PM 踩坑)"""
    import requests
    prefix = ds.get_prefix(code)
    sym = f"{prefix}{code}"
    for path, var in (("fqkline/get", "kline_dayqfq"), ("kline/kline", "kline_day")):
        try:
            url = f"https://web.ifzq.gtimg.cn/appstock/app/{path}?_var={var}&param={sym},day,,,120,qfq"
            r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            data = json.loads(re.search(r'=(.+)$', r.text.strip()).group(1))
            kl0 = data['data'][sym]
            kl = [[k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])]
                  for k in (kl0.get("qfqday") or kl0.get("day"))]
            if kl:
                return kl
        except Exception as e:
            last = e
    raise RuntimeError(f"K线获取失败: {last}")


def single_quarter_profit(code):
    """(最新季报期, 最新单季归母净利(元), 累计, 去年同期累计) — 估值面失真修正 v1 输入 (10-28 PM 规则)"""
    try:
        import akshare as ak
        df = ak.stock_financial_abstract(symbol=code)
        cols = [c for c in df.columns if c not in ('选项', '指标', '指标说明')]
        latest, prev = cols[0], cols[1]

        def np_of(col):
            for nm in ("归母净利润", "归属母公司净利润", "净利润"):
                row = df[df['指标'].astype(str).str.contains(nm, na=False)]
                if not row.empty:
                    try:
                        return float(row.iloc[0][col])
                    except Exception:
                        return None
            return None

        cum, prev_cum = np_of(latest), np_of(prev)
        if cum is None:
            return None
        q = cum - (prev_cum or 0.0)
        return {"period": str(latest), "cum": cum, "prev_cum": prev_cum,
                "single_q": q, "single_q_loss": q < 0}
    except Exception as e:
        return {"error": str(e)[:80]}


def tencent_quotes(codes):
    """腾讯实时快照: 盘前=昨收(11-17 收盘)口径。返回 {code: (现价, 涨跌幅%, 快照时间戳, 昨收)}"""
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


def groups_occupancy():
    """东财 groups.json 只读预检: 20261118* 占用 (裸日期空占位组 gid=2011 + 预期无 ZZ)。"""
    try:
        with open(GROUPS_FILE) as f:
            hist = json.load(f)
        hits = {k: v.get("gid") for k, v in hist.items() if k.startswith("20261118")}
        latest = max((int(v.get("gid", 0)) for v in hist.values()
                      if str(v.get("gid", "")).isdigit()), default=None)
        return hits, latest, len(hist)
    except Exception as e:
        return {"error": str(e)[:60]}, None, 0


def main():
    print("=" * 78)
    print(f"AAna 深度分析 — {TODAY} (周三交易日盘前, 数据基准 {BASE_DATE} 收盘)")
    print(f"Run: autopilot ca411dd3 深度分析 {RUN_ID}")
    print("=" * 78)

    # ---- 报告确认 (autopilot 强制: 打印报告名称防错) ----
    sz = os.path.getsize(TODAY_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(TODAY_REPORT)))
    print(f"📄 当日报告: {TODAY_REPORT}")
    print(f"   → 存在 | 大小: {sz} 字节 | 修改: {mt} (今日 08:01:58 盘前版, '涨跌幅'=昨收=11-17 收盘口径)")
    text = open(TODAY_REPORT).read()
    pool = parse_top10_full(text)
    raws = raw_row_count(text)
    print(f"   当日 Top10 表: {len(pool)} 只 (原始数据行 {len(raws)} 行) → 候选池 = {len(pool)} 只 "
          f"(11-14~11-16 连续 3 日 0 推荐后首个完整池)")
    for p in pool:
        print(f"     #{p['rank']} {p['code']} {p['name']} ¥{p['price']} {p['chg']:+.2f}% "
              f"报告分{p['v24']} 技术分{p['tech']} 软止损{p['stop']}")
    print(f"   报告快照 (= 11-17 周二收盘口径): 情绪{SNAP['score']}({SNAP['label']}) "
          f"仓位{SNAP['position']*100:.0f}% 大盘平均{MK_AVG:+.2f}% 涨停{SNAP['zt_count']}/跌停{SNAP['dt_count']} "
          f"上证{SH_CLOSE:+.2f}% 收3584.58 交易建议✅正常交易 | 热点: {'/'.join(HOT_SECTORS)}")
    print("   ⚠️ 报告异常披露: ① 热点主线表标注「2026年4月」为陈旧静态文案 (与 11-16 同病灶, AI算力/"
          "人形机器人/半导体设备 非当日热点); ② 盘前简报大盘指数点位异常 (上证¥12.30 = 数据污染, "
          "以 08:02 选股报告为准); ③ 基金推荐/模拟仓区块正常")
    print("   链路状态: 11-14~11-16 连续 3 日 0 推荐 (11-14/15 池空 + 11-16 冰点守卫短路) → 11-17 尾盘腿"
          "重启建仓 (池 5 只, PP 组实持模塑科技) → 今日情绪 30→40 回暖至边缘分歧带, Top10 完整池重现")

    # ---- 胜率库 / 调参披露 ----
    sector_stats, overall_wr, n_rec, rt_gen = load_sector_stats()
    print(f"\n📊 板块胜率库 (rec_optimizer 口径, generated_at {rt_gen}): {len(sector_stats)} 板块 | "
          f"整体胜率 {overall_wr:.1f}% ({n_rec} 笔)")
    nds = load_nds()
    cold_l, weak_l = nds.get("cold_sectors", []), nds.get("weak_sectors", [])
    print(f"   调参披露 (next_day_strategy {nds.get('generated_at')}): v24 阈值 {nds.get('score_threshold')} "
          f"| cold_sectors {len(cold_l)} 个 ({'/'.join(cold_l[:6])}…) | weak_sectors {len(weak_l)} 个 "
          f"({'/'.join(weak_l[:6])}…)")

    # ---- 冰点守卫 (双口径) ----
    live, snap = guard_check()
    print(f"\n🛡 P0 冰点守卫: 快照口径 情绪{snap['sentiment_score']}({snap['sentiment_label']}) "
          f"仓位{snap['position_ratio']*100:.0f}% is_ice_point={snap['is_ice_point']}")
    if snap.get("reason"):
        print(f"   短路原因: {snap['reason']}")
    if live:
        print(f"   live 口径 情绪{live['sentiment_score']}({live['sentiment_label']}) "
              f"is_ice_point={live['is_ice_point']} (ths 源盘前=11-17 收盘口径, 披露用)")
    ice = snap["is_ice_point"] and (live["is_ice_point"] if live else True)
    print(f"   判定: {'❄️ 冰点短路' if ice else '✅ 守卫放行 (40 分歧/仓位 20% ≥10%, 边缘分歧带轻仓语境)'}")

    # ---- 昨日 (11-17) 两腿复核 ----
    print(f"\n=== 昨日 (11-17) 复核范围 ===")
    am_exists = os.path.exists(YDAY_AM_JSON)
    pm_pool = load_yday_pool(YDAY_PM_JSON) if os.path.exists(YDAY_PM_JSON) else []
    am_txt = ("deep_analysis_20261117.json 存在" if am_exists else
              "deep_analysis_20261117.json 不存在 → 11-17 早盘深度分析未产出 (无 20261117ZZ 组)"
              " → AM 腿 T+1 复核 N/A")
    print(f"   早盘腿: {am_txt}")
    print(f"   连续性披露: 裸日期组 20261117 (gid=2006) 股票列表与今日 Top10 完全同池 10 只 "
          f"(002142/000651/000066/002945/600483/600801/600660/600406/603283/600415) — "
          f"昨晨 08:03 筛选池与今晨报告同源; note 陈旧标注「早盘 7 只」与实际 10 只不符")
    print(f"   尾盘腿: deep_analysis_pm_20261117.json 池 {len(pm_pool)} 只 → PP 组 (gid=2001) 实持模塑科技 000700, "
          f"T+0 判决以 11-17 收盘口径执行")
    pm_rev = []
    if pm_pool:
        q = tencent_quotes([r["code"] for r in pm_pool])
        for r in pm_pool:
            px, chg, ts, prev = q.get(r["code"], (None, None, "", None))
            pm_rev.append({**r, "close": px, "chg_pct": chg, "quote_ts": ts,
                           "beat_mkt": (chg is not None and chg > MK_AVG),
                           "pos": (chg is not None and chg > 0),
                           "pnl_vs_entry": (round((px / r["entry"] - 1) * 100, 2) if px else None),
                           "stop_broken": (r["stop"] is not None and px is not None and px < r["stop"])})
        pm_rev.sort(key=lambda x: (x["chg_pct"] if x["chg_pct"] is not None else -99), reverse=True)
        print(f"\n=== 昨尾盘深度池 {len(pm_rev)} 只 T+0 复核 (11-17 收盘, 腾讯快照口径; 基准=大盘平均 {MK_AVG:+.2f}%) ===")
        for i, r in enumerate(pm_rev, 1):
            print(f"{i}. {r['code']} {r['name']} 深度{r['total']}{r['rating']} [{r['sector']}]"
                  f" | 11-17 收盘 {r['chg_pct']:+.2f}% "
                  f"({'✅胜大盘' if r['beat_mkt'] else '❌弱于大盘'} {'✅正盈利' if r['pos'] else '❌负'})"
                  f" | vs 尾盘入场参考 ¥{r['entry']} → {r['pnl_vs_entry']:+.2f}%"
                  f"{' 🔴破软止损' + str(r['stop']) if r['stop_broken'] else ''}")
        pp = next((r for r in pm_rev if r["code"] == "000700"), None)
        if pp:
            print(f"🏁 昨尾盘 PP 实持 模塑科技 000700 铁律复核: 11-17 收盘 {pp['chg_pct']:+.2f}% "
                  f"vs 大盘 {MK_AVG:+.2f}% → 超额 {(pp['chg_pct'] or 0)-MK_AVG:+.2f}pp "
                  f"{'✅ 当日胜出+正盈利' if (pp['beat_mkt'] and pp['pos']) else '❌ 未同时满足'} "
                  f"(vs 入场参考 ¥{pp['entry']} → {pp['pnl_vs_entry']:+.2f}%; 软止损 {pp['stop']} "
                  f"{'🔴已破' if pp['stop_broken'] else '未破'})")
    gw = sum(1 for r in pm_rev if r.get("beat_mkt"))
    gp = sum(1 for r in pm_rev if r.get("pos"))
    print(f"   尾盘池汇总: 胜大盘({MK_AVG:+.2f}%) {gw}/{len(pm_rev)} | 正盈利 {gp}/{len(pm_rev)}")

    # ---- 价格真实性双重校验 (报告价 vs 腾讯快照, 盘前腿口径) ----
    print(f"\n=== 价格真实性双重校验 (报告价 vs 腾讯快照, 11-17 收盘口径) ===")
    q_pool = tencent_quotes([p["code"] for p in pool])
    n_match = 0
    for p in pool:
        px, chg, ts, prev = q_pool.get(p["code"], (None, None, "", None))
        match = (px is not None and abs(px - p["price"]) < 0.005 and ts[:8] == "20261117")
        n_match += bool(match)
        print(f"   {p['code']} {p['name']}: 报告 ¥{p['price']} vs 快照 ¥{px} ({ts[:8]}) "
              f"{'✅一致' if match else '⚠️不一致'}")
    print(f"   一致性: {n_match}/{len(pool)} → {'判定数据真实, 放行深度评分' if n_match == len(pool) else '存在不一致, 结果需谨慎'}")

    # ---- baseline 自查 (涨幅约束 + 热点错位) ----
    chgs = [p["chg"] for p in pool]
    print(f"\n=== baseline 涨幅约束自查 ===")
    print(f"   今日池 11-17 涨幅带: +{min(chgs):.2f}% ~ +{max(chgs):.2f}% | >5% 追高标的: "
          f"{sum(1 for c in chgs if c > 5)} 只 | >7%: {sum(1 for c in chgs if c > 7)} 只 "
          f"→ {'✅ 全池温和带 (<5%), 无追高约束违例' if max(chgs) <= 5 else '⚠️ 存在追高标的, 需人工复核'}")
    print(f"   池 11-17 全部正盈利且胜大盘: {'✅ 10/10 (vs 大盘平均 -0.57%)' if min(chgs) > 0 and min(chgs) > MK_AVG else '⚠️ 存在未胜出标的'}")

    # ---- 逐股深度评分 ----
    results = []
    hot_hit = 0
    for p in pool:
        code, name, v24s, stop = p["code"], p["name"], p["v24"], p["stop"]
        print(f"--- {code} {name} (报告#{p['rank']} 报告分{v24s}) ---", flush=True)
        try:
            q = ds.tencent_quote([code]).get(f"{code}", {})
        except Exception as e:
            q = {}; print(f"  quote fail: {e}")
        price = q.get("price") or p["price"]
        pe, pb = q.get("pe_ttm"), q.get("pb")
        try:
            kl = fetch_kline(code)
            ts_, tnotes, tstat = tech_score(kl, price)
        except Exception as e:
            ts_, tnotes, tstat = 25, [f"K线失败: {e}"], {}
        try:
            fs_, fnotes, fstat = fund_score(code)
        except Exception as e:
            fs_, fnotes, fstat = 10, [f"财务失败: {e}"], {}
        vs_raw, vnotes = val_score(pe, pb)

        # 行业双源核验 (sina industry_for_code + 东财 f127) + cold/weak 命中检查
        try:
            ind_sina = ds.industry_for_code(code)
        except Exception:
            ind_sina = None
        try:
            ind_em = ds.eastmoney_stock_info(code).get("industry") or None
        except Exception:
            ind_em = None
        print(f"  行业双源: sina[{ind_sina}] 东财f127[{ind_em}]")
        cw_hits = [f"cold:{k}" for k in (ind_sina, ind_em) if k in cold_l]
        cw_hits += [f"weak:{k}" for k in (ind_sina, ind_em) if k in weak_l]
        if cw_hits:
            print(f"  ⚠️ cold/weak 板块命中: {' '.join(cw_hits)}")

        # 估值面失真修正 v1 (10-28 PM 规则, 口径连续)
        sq = single_quarter_profit(code)
        ni_growth = fstat.get("ni_growth")
        distorted = bool(sq and sq.get("single_q_loss")
                         and ni_growth is not None and ni_growth < -50)
        if distorted:
            pb_score = 7 if (pb is not None and pb <= 3) else (4 if (pb is not None and pb <= 5) else 1)
            vs_adj = pb_score
            vnotes = list(vnotes) + [
                f"估值面失真修正: 单季归母 {sq['single_q']/1e8:.3f} 亿转亏 + 净利同比 {ni_growth:.0f}% "
                f"→ PE(TTM) {pe:.1f} 系峰值盈利滞后口径记 0 分, 只保留 PB"]
        else:
            vs_adj = vs_raw

        total = round(ts_ / 55 * 50 + fs_ / 30 * 30 + vs_adj / 15 * 20, 1)
        rating = rating_of(total)
        target = round(max(price * 1.05, tstat.get("hi20") or price * 1.05), 2)
        industry, stat_key, nears, cold_warn = SECTOR_MAP.get(code, (None, None, [], None))
        # stat_key 双源兜底: 预设键不在胜率库时尝试双源 live 键
        sec = sector_stats.get(stat_key, {}) if stat_key else {}
        if not sec:
            for cand in (ind_sina, ind_em):
                if cand and sector_stats.get(cand):
                    sec = sector_stats[cand]
                    stat_key = cand
                    break
        sec_wr = (f"{sec.get('win_rate'):.1f}% ({sec.get('win_count')}/{sec.get('count')})"
                  if sec else "无记录(冷启动)")
        near_wr = ""
        for nk, nd in nears:
            ns = sector_stats.get(nk, {})
            if ns:
                near_wr += f" | {nd}: {ns.get('win_rate'):.0f}% ({ns.get('win_count')}/{ns.get('count')})"
        hot_overlap = [h for h in HOT_SECTORS
                       if h and ((industry and h in industry) or (ind_sina and h in ind_sina)
                                 or (ind_em and h in ind_em))]
        hot_hit += bool(hot_overlap)
        chg = tstat.get("chg_1d", p["chg"]) or p["chg"]
        rec = {"code": code, "name": name, "rank": p["rank"], "price": price,
               "pe_ttm": pe, "pb": pb, "mcap_yi": q.get("mcap_yi"),
               "float_mcap_yi": q.get("float_mcap_yi"), "turnover_pct": q.get("turnover_pct"),
               "vol_ratio": q.get("vol_ratio"), "v24_score": v24s, "report_tech": p["tech"],
               "ind_sina": ind_sina, "ind_em": ind_em, "cold_weak_hits": cw_hits,
               "tech_score": ts_, "fund_score": fs_, "val_score": vs_adj, "val_score_raw": vs_raw,
               "distorted": distorted,
               "single_quarter": (None if not sq or sq.get("error")
                                  else {"period": sq.get("period"),
                                        "single_q_yi": round(sq.get("single_q", 0) / 1e8, 3),
                                        "single_q_loss": sq.get("single_q_loss")}),
               "total": total, "rating": rating, "target": target, "stop": stop,
               "tech_notes": tnotes, "fund_notes": fnotes, "val_notes": vnotes,
               "tech_stat": tstat, "fund_stat": fstat,
               "chg_pct": chg, "chg_date": tstat.get("last_date"),
               "beat_mkt": chg > MK_AVG, "positive": chg > 0,
               "industry": industry, "sector_stat_key": stat_key, "sector_win_rate": sec_wr,
               "sector_near": near_wr.strip(" |") if near_wr else None,
               "sector_cold_warn": cold_warn,
               "hot_sector_overlap": hot_overlap,
               "stop_broken": (stop is not None and price is not None and price < stop)}
        results.append(rec)
        print(f"  {BASE_DATE} 涨跌 {chg:+.2f}% (K线末日 {tstat.get('last_date')}, K线 {tstat.get('kline_len')} 根) "
              f"{'✅胜大盘(' + format(MK_AVG, '+.2f') + '%)+正盈利' if chg > MK_AVG and chg > 0 else '❌未同时满足'}")
        print(f"  技术面 {ts_}/55 基本面 {fs_}/30 估值 {vs_adj}/15"
              f"{'(修正前'+str(vs_raw)+')' if distorted else ''} => {total} {rating} | 止损 {stop} "
              f"{'🔴已破' if rec['stop_broken'] else '未破'}")
        print(f"  板块: {industry} → 胜率 {sec_wr}{near_wr} "
              f"{'⚠️ ' + ' '.join(cw_hits) if cw_hits else ''} "
              f"{'🎯热点命中' + str(hot_overlap) if hot_overlap else '热点错位'} {cold_warn or ''}")
        time.sleep(0.4)

    print(f"\n=== 热点关联度 (报告热点 vs 池板块, 11-11 先例: 题材命中均值 +2.70% vs 未命中 -4.28%) ===")
    print(f"   热点板块: {'/'.join(HOT_SECTORS)} | 池内命中: {hot_hit}/{len(pool)} 只 → "
          f"{'⚠️ 基本错位, 历史先例下整体胜率折扣' if hot_hit == 0 else f'部分关联 {hot_hit} 只'}")

    # 铁律合成: 正盈利 + 强于大盘(胜出) + 评级≥增持(65) + 未破止损 + 守卫放行
    by_chg = sorted(results, key=lambda x: -(x["chg_pct"] or 0))
    for i, r in enumerate(by_chg, 1):
        next(r2 for r2 in results if r2["code"] == r["code"])["chg_rank"] = i
    positive = [r for r in results if (r["chg_pct"] or 0) > 0]
    beat = [r for r in results if r.get("beat_mkt")]
    eligible = [r for r in results
                if (r["chg_pct"] or 0) > 0 and r.get("beat_mkt")
                and r["total"] >= 65 and not r["stop_broken"] and not ice]
    eligible.sort(key=lambda x: (-x["total"], -x["v24_score"], -(x["chg_pct"] or 0)))
    recommend = eligible[0] if eligible else None
    results.sort(key=lambda x: (-x["total"], -x["v24_score"], -(x["chg_pct"] or 0)))

    occ, latest_gid, n_groups = groups_occupancy()
    print(f"\n📁 东财 groups.json 只读预检: 共 {n_groups} 组 | 最新 gid {latest_gid} | "
          f"20261118* 占用: {occ} (裸日期 gid=2011 为今晨空占位组, 严禁触碰; ZZ 预期未占用)")

    with open(OUT_JSON, "w") as f:
        json.dump({"date": TODAY, "base_date": BASE_DATE, "report": TODAY_REPORT,
                   "report_size": sz, "report_mtime": mt,
                   "trading_day": True, "session": "pre_market",
                   "generated": time.strftime("%H:%M:%S"),
                   "sentiment_snap": SNAP, "mk_avg": MK_AVG, "sh_close_pct": SH_CLOSE,
                   "hot_sectors": HOT_SECTORS, "hot_hit_count": hot_hit,
                   "pool_size": len(pool), "guard_ice": ice,
                   "guard_reason": snap.get("reason"),
                   "guard_live": ({"score": live["sentiment_score"], "label": live["sentiment_label"],
                                   "is_ice_point": live["is_ice_point"]} if live else None),
                   "run_id": RUN_ID,
                   "report_anomalies": ["热点主线表标注「2026年4月」陈旧静态文案 (与 11-16 同病灶)",
                                        "盘前简报大盘指数点位异常 (上证¥12.30 数据污染)"],
                   "overall_win_rate": overall_wr, "total_records": n_rec,
                   "sector_count": len(sector_stats), "rec_tuning_generated_at": rt_gen,
                   "nds_tuning": {"score_threshold": nds.get("score_threshold"),
                                  "cold_sectors": cold_l, "weak_sectors": weak_l},
                   "price_check_match": n_match,
                   "baseline_check": {"chg_min": min(chgs), "chg_max": max(chgs),
                                      "n_gt5": sum(1 for c in chgs if c > 5),
                                      "n_gt7": sum(1 for c in chgs if c > 7)},
                   "yesterday_review": {
                       "am_leg": ("N/A — deep_analysis_20261117.json 不存在, 11-17 早盘深度分析未产出"
                                  " (无 20261117ZZ 组); 裸日期组 20261117 (gid=2006) 与今日 Top10 完全同池"),
                       "pm_pool": {"source": "deep_analysis_pm_20261117.json 尾盘池 5 只",
                                   "pp_holding": "000700 模塑科技 (gid=2001)",
                                   "judged_on": BASE_DATE,
                                   "n_beat_mkt": gw, "n_positive": gp,
                                   "results": pm_rev}},
                   "recommend": ({"code": recommend["code"], "name": recommend["name"],
                                  "total": recommend["total"], "rating": recommend["rating"],
                                  "stop": recommend["stop"], "target": recommend["target"]}
                                 if recommend else None),
                   "eligible_pool": [{"code": r["code"], "name": r["name"], "total": r["total"],
                                      "rating": r["rating"]} for r in eligible],
                   "eastmoney_sync": {"action": "create_zz_if_recommend",
                                      "group_name": f"{TODAY.replace('-', '')}ZZ",
                                      "precheck_20261118_occupied": occ,
                                      "reason": (f"铁律合格池 Top1 {recommend['code']} {recommend['name']} "
                                                 f"({recommend['total']} {recommend['rating']}) → 仅 Top1 入组"
                                                 if recommend else "铁律合格池空 → 不建组")},
                   "results": results}, f, ensure_ascii=False, indent=1)

    print(f"\n=== 深度排名 (技术50%+基本面30%+估值20%) ===")
    for i, r in enumerate(results, 1):
        print(f"{i}. {r['code']} {r['name']} 综合 {r['total']} {r['rating']} "
              f"(技{r['tech_score']}/基{r['fund_score']}/估{r['val_score']}) | 11-17 实收 {r['chg_pct']:+.2f}% "
              f"池内涨幅第{r['chg_rank']} | 板块胜率 {r['sector_win_rate']} | "
              f"{'✅铁律合格' if r in eligible else '不合格'}")
    print(f"\n正盈利: {len(positive)}/{len(results)} | 胜大盘({MK_AVG:+.2f}%): {len(beat)}/{len(results)}")
    print(f"铁律合格池 (≥增持65+正盈利+胜出+未破止损+守卫放行): "
          f"{[(r['code'], r['name'], r['total']) for r in eligible]}")
    if recommend:
        print(f"\n🏁 最值得购买: {recommend['code']} {recommend['name']} — "
              f"深度 {recommend['total']} {recommend['rating']} | 板块 [{recommend['sector_stat_key']}] "
              f"胜率 {recommend['sector_win_rate']} | 软止损 {recommend['stop']} | 目标参考 {recommend['target']}")
        print(f"   → 同步东财组合 {TODAY.replace('-', '')}ZZ (仅 Top1 入组, 先例口径)")
    else:
        print(f"\n🏁 0 推荐 (铁律合格池空) → 不创建东财组合 {TODAY.replace('-', '')}ZZ")
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()

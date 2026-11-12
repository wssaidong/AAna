#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-11-12 (周四交易日盘前 08:3x) — 情绪 80 亢奋连续第 3 日回暖 · 仓位 85% · 候选池 10 只 · 第 7 样本判决日盘前腿
当日报告 = reports/2026-11-12-选股报告.md (11-12 08:02 盘前版, 涨跌幅=昨收 11-11 周三收盘口径)
候选池 = 当日报告 Top10 表全部 10 只 (603990 麦迪科技 / 603009 北特科技 / 603337 杰克科技 / 002553 南方精工 /
         002979 雷赛智能 / 002472 双环传动 / 002009 天奇股份 / 000888 峨眉山Ａ / 002911 佛燃能源 / 001283 豪鹏科技,
         11-11 收盘 +3.21~+4.65% 全正, 报告综合分 70x3+69x6+64x1; 裸日期组 20261112 (gid=1976, 今晨建, 空))
方法: 复用 deep_analysis_20261022 评分引擎 (技术50% + 基本面30% + 估值20%)
      + 估值面失真修正 v1 (10-28 PM 规则: 最新单季归母转亏 且 净利同比<-50% → PE 记 0 只留 PB)
      腾讯行情(盘前=11-11 收盘冻结口径) + 腾讯日K(120d qfq, 末日 11-11) + akshare 财务摘要
      + 东财 f127/sina 行业双源核验 + rec_tuning 板块胜率 (114 键 428 笔 50.9%, 11-11 20:01 更新)
铁律: 最值得购买者需基准交易日 11-11 当日胜出 (强于大盘平均 +1.32% 且居池内前列) + 正盈利
      + 深度评级 ≥增持(65) + 未破报告软止损 + 守卫放行
链路语境: 11-11 盘前 68 回暖 (Top1 水晶光电 002273 74.2 → 20261111ZZ gid=1951; 池 10/10 正+10/10 胜 11-10 口径)
      → 11-11 实际判决: 候选池 5/10 命中 均值 -0.09%, 8/10 负延续 (模式①追高延续性失败), Top1 水晶光电
      实收 -1.54% ❌高位回吐未胜大盘 (+1.46pp 差距), 飞亚达 +10.02% 最强 — 题材主线命中 6/10 均值 +2.70%
      vs 未命中 -4.28% (差 +6.97pp, 题材选择有效)
      → 🔴第 6 样本判决 (11-11 09:30 T1 卖): 2胜8负 -¥91 (批内 -0.47%), 第 5 批盈利未延续 (6批2盈4亏);
      P1「守卫放行日 T+1 竞价卖系统性负α」假设重获支持
      → 11-11 14:45 亢奋 85% → 14:46 第 7 样本建仓 10 只×100股 ≈¥27060 (国芳/美格/大族/游族/东材/远东/
      德尔/铁流/洪田/金帝); 🔴时序倒挂第 3 日: 建仓先于 pm 深度分析 14:49, 中性级 601086/002174 已入样本
      → 今日 09:30 第 7 样本 T1 卖出腿判决 (cron 链执行, 本 run 盘前仅披露)
今日快照: 情绪 80 亢奋 (55→68→80 连续第 3 日回暖) 仓位 85% (70%→85%) 涨停 84/跌停 8
baseline 自查: 今日池 11-11 涨幅 +3.21~+4.65% 全部 <5% 温和带, 无 >7% 追高标的; cold 命中披露:
      杰克科技/天奇股份 (东财键「专用设备」在 cold_sectors, 11-11 根因 E 冷启动盲区 8 板块之一;
      sina 键「其它专用机械」100% (1/1) 薄样本) — 见逐股输出
Kimi: 本机无 kimi CLI / moonshot key (连续第 28 日, 11-12 复核维持) — 由 AAna 深度评分引擎 + LLM 定性层执行
东财: 依铁律合格池 Top1 → 20261112ZZ (先例: 仅 Top1 入组); 裸日期 20261112 (gid=1976, 今晨空组) 严禁触碰;
      昨日 ZZ=1951 / PP=1966 / 20261111=1971 不动; find_group_gid 前 8 位日期匹配对 ZZ 后缀有歧义 → 创建后必须
      gid∉当日占用集 防御校验 (sync_zz_20261112.py)
"""
import sys, os, json, re, time
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import data_sources as ds
from deep_analysis_20261022 import tech_score, fund_score, val_score, rating_of

TODAY = "2026-11-12"
BASE_DATE = "2026-11-11"   # K 线末日 / 昨收基准 (11-11 周三收盘)
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
TODAY_REPORT = os.path.join(REPORT_DIR, f"{TODAY}-选股报告.md")  # 今日 08:02 盘前版
OUT_JSON = os.path.expanduser(f"~/code/AAna/data/deep_analysis_{TODAY.replace('-','')}.json")
YDAY_AM_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_20261111.json")
YDAY_PM_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_pm_20261111.json")
MK_AVG = 1.32             # 报告快照: 大盘平均涨跌 +1.32% (11-11 收盘基准)
SH_CLOSE = 0.46           # 上证 +0.46% 收 3680.64 (11-11 收盘基准)
SNAP = {"score": 80, "label": "亢奋", "zt_count": 84, "dt_count": 8, "position": 0.85}
RUN_ID = "01a1cd29-e0ba-7039-b8d6-298bc276957d"

# 行业 (双源 runtime 核验 11-12 08:3x; stat_key → rec_tuning sector_stats 114 键 428 笔) 映射
SECTOR_MAP = {
    "603990": ("医疗信息化-临床医疗信息系统 CIS/急救信息化 (医疗软件+手术机器人辅助)", "软件开发",
               [],
               None),
    "603009": ("汽车零部件-转向器齿条+滚珠丝杠 (人形机器人丝杠概念+齿条主业)", "汽车零部件",
               [],
               None),
    "603337": ("缝制设备-工业缝纫机龙头 (杰克缝纫机+成套智能装备+裁床)", "其它专用机械",
               [("纺织服装设备", "警戒邻键-纺织服装设备(0/1)")],
               "披露: 东财键「专用设备」在 cold_sectors (根因 E 冷启动盲区); sina 键其它专用机械 100% (1/1) 薄样本"),
    "002553": ("汽车零部件-滚针轴承/单向超越离合器 (机器人执行器轴承概念)", "汽车零部件",
               [("机械基础件", "邻键-机械基础件(6/6)")],
               None),
    "002979": ("工控自动化-步进伺服/运动控制龙头 (机器人+3C+激光加工控制)", "工控自动化",
               [],
               None),
    "002472": ("汽车零部件-齿轮传动龙头 (机器人 RV/谐波减速器+新能源车电驱齿轮)", "汽车零部件",
               [],
               None),
    "002009": ("智能装备-汽车自动化产线+锂电回收 (人形机器人本体/拆解装备布局)", "其它专用机械",
               [],
               "披露: 东财键「专用设备」在 cold_sectors (根因 E 冷启动盲区); sina 键其它专用机械 100% (1/1) 薄样本"),
    "000888": ("旅游-峨眉山景区 (自然景点龙头, 索道+门票+酒店一体)", None,
               [],
               "冷启动: sina「自然景点」/东财「旅游及景区」均不在板块胜率库 (114 键无旅游类键)"),
    "002911": ("燃气-佛山城市燃气 (天然气分销+延伸氢能/综合能源服务)", None,
               [("热电", "邻键-热电(1/1 薄样本)"), ("火电", "邻键-火电(2/3)")],
               "冷启动: sina「燃气」/东财「燃气Ⅱ」均不在板块胜率库"),
    "001283": ("电池-镍氢/小型锂电 (消费电池+储能, NiMH 龙头)", "储能设备",
               [],
               None),
}


def parse_top10_full(text):
    """解析 '🏆 重点关注 Top 10' 表格: 排名/名称/代码/价格/涨跌幅/技术分/综合分/软止损 (口径同 10-27~11-11)"""
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


def guard_check():
    """P0 冰点守卫 (单一真源 check_ice_point_guard)。盘前未开盘: live 源 (ths) = 11-11 收盘口径,
    以报告快照 80 亢奋为判定口径 (11-11 收盘情绪 → 11-12 盘前延续)"""
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
    return rt.get("sector_stats", {}), rt.get("overall_win_rate"), rt.get("total_records"), rt.get("generated_at")


def load_nds():
    with open(os.path.expanduser("~/code/AAna/data/next_day_strategy.json")) as f:
        return json.load(f)


def load_yday_pool(path, group_map):
    """昨日深度池 (AM/PM 两腿) 动态加载: entry=分析时点价, stop=止损, total/rating=当日深度分"""
    with open(os.path.expanduser(path)) as f:
        d = json.load(f)
    out = []
    for r in d.get("results", []):
        out.append({"code": r["code"], "name": r["name"], "total": r.get("total"),
                    "rating": r.get("rating"), "stop": r.get("stop"), "entry": r.get("price"),
                    "group": group_map.get(r["code"], "")})
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
    """腾讯实时快照: 盘前=昨收(11-11 收盘)口径。返回 {code: (现价, 涨跌幅%, 快照时间戳, 昨收)}"""
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


def review_pool(pool, title, mk_avg):
    """T+1 复核: 11-11 收盘快照验证「当日胜出(>大盘平均)+正盈利」"""
    q = tencent_quotes([r["code"] for r in pool])
    review = []
    for r in pool:
        px, chg, ts, prev = q.get(r["code"], (None, None, "", None))
        review.append({**r, "close": px, "prev_close": prev, "chg_pct": chg, "quote_ts": ts,
                       "beat_mkt": (chg is not None and chg > mk_avg),
                       "pos": (chg is not None and chg > 0),
                       "pnl_vs_entry": (round((px / r["entry"] - 1) * 100, 2) if px else None)})
    review.sort(key=lambda x: (x["chg_pct"] if x["chg_pct"] is not None else -99), reverse=True)
    print(f"\n=== {title} (11-11 收盘, 腾讯快照口径; 基准=大盘平均 {mk_avg:+.2f}%) ===")
    for i, r in enumerate(review, 1):
        ts = r['quote_ts'][:8]
        print(f"{i}. {r['code']} {r['name']} 深度{r['total']}{r['rating']}"
              f"{' [' + r['group'] + ']' if r.get('group') else ''}"
              f" | 11-11 实收 {r['chg_pct']:+.2f}% ({'✅胜大盘(' + format(mk_avg, '+.2f') + '%)' if r['beat_mkt'] else '❌弱于大盘'})"
              f"{' ✅正盈利' if r['pos'] else ' ❌负'} | vs 建仓参考价 {r['entry']} → {r['pnl_vs_entry']:+.2f}%"
              f" | 快照日 {ts}"
              f"{' 🔴破软止损' + str(r['stop']) if (r['stop'] and (r['close'] or 0) < r['stop']) else ''}")
    n_beat = sum(1 for r in review if r["beat_mkt"])
    n_pos = sum(1 for r in review if r["pos"])
    print(f"胜大盘({mk_avg:+.2f}%): {n_beat}/{len(review)} | 正盈利: {n_pos}/{len(review)}")
    return review


def main():
    print("=" * 78)
    print(f"AAna 深度分析 — {TODAY} (周四交易日盘前, 数据基准 {BASE_DATE} 收盘)")
    print(f"Run: autopilot ca411dd3 深度分析 {RUN_ID}")
    print("=" * 78)

    # ---- 报告确认 (autopilot 强制: 打印报告名称防错) ----
    sz = os.path.getsize(TODAY_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(TODAY_REPORT)))
    print(f"📄 当日报告: {TODAY_REPORT}")
    print(f"   → 存在 | 大小: {sz} 字节 | 修改: {mt} (今日 08:02 盘前版, '涨跌幅'=昨收=11-11 收盘口径)")
    text = open(TODAY_REPORT).read()
    pool = parse_top10_full(text)
    # 双重校验: 表区间内含 6 位代码的数据行原始计数 (防解析器误判, 10-28 口径)
    m = re.search(r'重点关注 Top 10(.*?)(?=\n###|\Z)', text, re.S)
    raw_rows = [l for l in (m.group(1) if m else "").split("\n")
                if l.strip().startswith("|") and re.search(r'\d{6}', l)
                and not l.strip().startswith("|:")]
    print(f"   当日 Top10 表: {len(pool)} 只 (原始数据行 {len(raw_rows)} 行) → 候选池 = {len(pool)} 只 "
          f"(连续第 3 日完整池, 情绪回暖斜率延续)")
    for p in pool:
        print(f"     #{p['rank']} {p['code']} {p['name']} ¥{p['price']} {p['chg']:+.2f}% "
              f"报告分{p['v24']} 技术分{p['tech']} 软止损{p['stop']}")
    snap_sent = (f"情绪{SNAP['score']}({SNAP['label']}) 仓位{SNAP['position']*100:.0f}% "
                 f"大盘平均{MK_AVG:+.2f}% 涨停{SNAP['zt_count']}/跌停{SNAP['dt_count']} "
                 f"上证{SH_CLOSE:+.2f}% 收3680.64 交易建议✅正常交易")
    print(f"   报告快照 (= 11-11 周三收盘口径): {snap_sent}")
    print("   链路状态: 情绪 55→68→80 连续第 3 日回暖, 仓位 70%→85%; 🔴11-11 判决: 候选池 5/10 命中均值 -0.09% "
          "(8/10 负延续, 模式①追高延续性失败), 昨 Top1 水晶光电实收 -1.54% ❌高位回吐未胜大盘; 第 6 样本判决 "
          "2胜8负 -¥91 (第 5 批盈利未延续, P1 负α假设重获支持); 昨 14:46 第 7 样本建仓 10 只≈¥27060 "
          "(🔴时序倒挂第 3 日: 建仓早于 pm 深度分析 14:49, 中性级 601086/002174 已入样本); "
          "今日 09:30 第 7 样本 T1 卖出腿判决 (cron 链), 本 run 盘前仅披露")

    sector_stats, overall_wr, n_rec, rt_gen = load_sector_stats()
    print(f"📊 板块胜率库 (rec_optimizer 口径, generated_at {rt_gen}): {len(sector_stats)} 板块 | "
          f"整体胜率 {overall_wr:.1f}% ({n_rec} 笔)")
    nds = load_nds()
    cold_l, weak_l = nds.get("cold_sectors", []), nds.get("weak_sectors", [])
    print(f"   调参披露 (next_day_strategy 11-11 16:10): v24 阈值 {nds.get('score_threshold')} "
          f"| cold_sectors {len(cold_l)} 个 ({'/'.join(cold_l)}) | weak_sectors {len(weak_l)} 个")

    live, snap = guard_check()
    print(f"🛡 P0 冰点守卫: 快照口径 情绪{snap['sentiment_score']}({snap['sentiment_label']}) "
          f"仓位{snap['position_ratio']*100:.0f}% is_ice_point={snap['is_ice_point']}")
    if snap.get("reason"):
        print(f"   短路原因: {snap['reason']}")
    if live:
        print(f"   live 口径 情绪{live['sentiment_score']}({live['sentiment_label']}) "
              f"is_ice_point={live['is_ice_point']} (ths 源盘前=11-11 收盘口径, 披露用)")
    ice = snap["is_ice_point"] and (live["is_ice_point"] if live else True)

    # ---- 昨日 (11-11) 两腿 T+1 复核 ----
    am_pool = load_yday_pool(YDAY_AM_JSON, {"002273": "20261111ZZ(gid=1951)"})
    pm_pool = load_yday_pool(YDAY_PM_JSON, {"002881": "20261111PP(gid=1966)"})
    print(f"\n=== 昨日两腿复核范围 ===\n   早盘腿: 深度池 10 只 (Top1 水晶光电 002273 → 20261111ZZ gid=1951)")
    am_rev = review_pool(am_pool, "昨早盘深度池 10 只复核 (11-11 收盘口径)", MK_AVG)
    a1 = next(r for r in am_rev if r["code"] == "002273")
    print(f"🏁 昨早 Top1 002273 水晶光电 铁律复核: 11-11 实收 {a1['chg_pct']:+.2f}% "
          f"vs 大盘 {MK_AVG:+.2f}% → 超额 {a1['chg_pct']-MK_AVG:+.2f}pp "
          f"{'✅ 当日胜出+正盈利' if (a1['beat_mkt'] and a1['pos']) else '❌ 未同时满足 (高位回吐, 20261111ZZ 组保留供跟踪)'} "
          f"(vs 入场参考 {a1['entry']} → {a1['pnl_vs_entry']:+.2f}%; 软止损 {a1['stop']} "
          f"{'🔴已破' if (a1['close'] or 0) < a1['stop'] else '未破'})")
    pm_rev = review_pool(pm_pool, "昨尾盘深度池 5 只复核 (pm 管线 day2, 质量修正口径)", MK_AVG)
    p1 = max(pm_rev, key=lambda r: r.get("total") or 0)
    print(f"🏁 昨尾盘深度分 Top1 {p1['code']} {p1['name']} 铁律复核: 11-11 实收 {p1['chg_pct']:+.2f}% "
          f"vs 大盘 {MK_AVG:+.2f}% → 超额 {p1['chg_pct']-MK_AVG:+.2f}pp "
          f"{'✅ 当日胜出+正盈利' if (p1['beat_mkt'] and p1['pos']) else '❌ 未同时满足'} "
          f"(vs 入场参考 {p1['entry']} → {p1['pnl_vs_entry']:+.2f}%; 软止损 {p1['stop']} "
          f"{'🔴已破' if (p1['close'] or 0) < p1['stop'] else '未破'}); "
          f"PP 组 gid=1966 实持美格智能 (深度分 Top1, 口径一致)")
    print("   ↳ 第 7 样本 (11-11 14:46 建仓 10 只模拟仓) 判决在今日 09:30 T1 卖出腿 (cron 链), "
          "本 run 不代跑; 尾盘深度池 5 只中美格智能入 PP 组")

    # ---- 价格真实性双重校验 (报告价 vs 腾讯快照, 盘前腿口径) ----
    print(f"\n=== 价格真实性双重校验 (报告价 vs 腾讯快照, 11-11 收盘口径) ===")
    q_pool = tencent_quotes([p["code"] for p in pool])
    n_match = 0
    for p in pool:
        px, chg, ts, prev = q_pool.get(p["code"], (None, None, "", None))
        match = (px is not None and abs(px - p["price"]) < 0.005
                 and ts[:8] == "20261111")
        n_match += bool(match)
        print(f"   {p['code']} {p['name']}: 报告 ¥{p['price']} vs 快照 ¥{px} ({ts[:8]}) "
              f"{'✅一致' if match else '⚠️不一致'}")
    print(f"   一致性: {n_match}/{len(pool)} → {'判定数据真实, 放行深度评分' if n_match == len(pool) else '存在不一致, 结果需谨慎'}")

    # ---- baseline 自查 (涨幅约束 + cold/weak 重合) ----
    chgs = [p["chg"] for p in pool]
    print(f"\n=== baseline 涨幅约束自查 ===")
    print(f"   今日池 11-11 涨幅带: +{min(chgs):.2f}% ~ +{max(chgs):.2f}% | >5% 追高标的: "
          f"{sum(1 for c in chgs if c > 5)} 只 | >7%: {sum(1 for c in chgs if c > 7)} 只 "
          f"→ {'✅ 全池温和带 (<5%), 无追高约束违例' if max(chgs) <= 5 else '⚠️ 存在追高标的, 需人工复核'}")

    # ---- 逐股深度评分 ----
    results = []
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
        sec = sector_stats.get(stat_key, {}) if stat_key else {}
        sec_wr = (f"{sec.get('win_rate'):.0f}% ({sec.get('win_count')}/{sec.get('count')})"
                  if sec else "无记录(冷启动)")
        near_wr = ""
        for nk, nd in nears:
            ns = sector_stats.get(nk, {})
            if ns:
                near_wr += f" | {nd}[{nk}] {ns.get('win_rate'):.0f}% ({ns.get('win_count')}/{ns.get('count')})"
        chg = tstat.get("chg_1d", p["chg"]) or p["chg"]
        rec = {"code": code, "name": name, "rank": p["rank"], "price": price,
               "pe_ttm": pe, "pb": pb, "mcap_yi": q.get("mcap_yi"),
               "float_mcap_yi": q.get("float_mcap_yi"), "turnover_pct": q.get("turnover_pct"),
               "vol_ratio": q.get("vol_ratio"), "v24_score": v24s, "report_tech": p["tech"],
               "ind_sina": ind_sina, "ind_em": ind_em, "cold_weak_hits": cw_hits,
               "tech_score": ts_, "fund_score": fs_, "val_score": vs_adj, "val_score_raw": vs_raw,
               "distorted": distorted, "single_quarter": (None if not sq or sq.get("error")
                                                          else {"period": sq.get("period"),
                                                                "single_q_yi": round(sq.get("single_q", 0) / 1e8, 3),
                                                                "single_q_loss": sq.get("single_q_loss")}),
               "total": total, "rating": rating, "target": target, "stop": stop,
               "tech_notes": tnotes, "fund_notes": fnotes, "val_notes": vnotes,
               "tech_stat": tstat, "fund_stat": fstat,
               "chg_pct": chg, "chg_date": tstat.get("last_date"),
               "beat_mkt": chg > MK_AVG,
               "industry": industry, "sector_stat_key": stat_key, "sector_win_rate": sec_wr,
               "sector_near": near_wr.strip(" |") if near_wr else None,
               "sector_cold_warn": cold_warn,
               "stop_broken": (stop is not None and price is not None and price < stop)}
        results.append(rec)
        print(f"  {BASE_DATE} 涨跌 {chg:+.2f}% (K线末日 {tstat.get('last_date')}, K线 {tstat.get('kline_len')} 根) "
              f"{'✅胜大盘(' + format(MK_AVG, '+.2f') + '%)' if chg > MK_AVG else '❌弱于大盘'}")
        print(f"  技术面 {ts_}/55 基本面 {fs_}/30 估值 {vs_adj}/15"
              f"{'(修正前'+str(vs_raw)+')' if distorted else ''} => {total} {rating} | 止损 {stop} "
              f"{'🔴已破' if rec['stop_broken'] else '未破'}")
        print(f"  板块: {industry} → 胜率 {sec_wr}{near_wr} "
              f"{'⚠️ ' + ' '.join(cw_hits) if cw_hits else ''} {cold_warn or ''}")
        time.sleep(0.4)

    # 铁律合成: 正盈利 + 强于大盘(胜出) + 评级≥增持(65) + 未破止损 + 守卫放行
    by_chg = sorted(results, key=lambda x: -(x["chg_pct"] or 0))
    for i, r in enumerate(by_chg, 1):
        next(r2 for r2 in results if r2["code"] == r["code"])["chg_rank"] = i
    positive = [r for r in results if (r["chg_pct"] or 0) > 0]
    eligible = [r for r in results
                if (r["chg_pct"] or 0) > 0 and r.get("beat_mkt")
                and r["total"] >= 65 and not r["stop_broken"] and not ice]
    eligible.sort(key=lambda x: (-x["total"], -x["v24_score"], -(x["chg_pct"] or 0)))
    recommend = eligible[0] if eligible else None
    results.sort(key=lambda x: (-x["total"], -x["v24_score"], -(x["chg_pct"] or 0)))

    with open(OUT_JSON, "w") as f:
        json.dump({"date": TODAY, "base_date": BASE_DATE, "report": TODAY_REPORT,
                   "report_size": sz, "report_mtime": mt,
                   "trading_day": True, "session": "pre_market",
                   "generated": time.strftime("%H:%M:%S"),
                   "sentiment_snap": SNAP, "mk_avg": MK_AVG, "sh_close_pct": SH_CLOSE,
                   "pool_size": len(pool), "guard_ice": ice,
                   "guard_reason": snap.get("reason"), "run_id": RUN_ID,
                   "overall_win_rate": overall_wr, "total_records": n_rec,
                   "sector_count": len(sector_stats), "rec_tuning_generated_at": rt_gen,
                   "price_check_match": n_match,
                   "baseline_check": {"chg_min": min(chgs), "chg_max": max(chgs),
                                      "n_gt5": sum(1 for c in chgs if c > 5),
                                      "n_gt7": sum(1 for c in chgs if c > 7)},
                   "nds_tuning": {"score_threshold": nds.get("score_threshold"),
                                  "cold_sectors": cold_l, "weak_sectors": weak_l},
                   "yesterday_review": {"am_top1": {"code": a1["code"], "name": a1["name"],
                                                    "group": "20261111ZZ(gid=1951)",
                                                    "verified_on": BASE_DATE,
                                                    "chg_pct": a1["chg_pct"], "beat_mkt": a1["beat_mkt"],
                                                    "pos": a1["pos"], "pnl_vs_entry": a1["pnl_vs_entry"]},
                                        "am_top10": {"source": "11-11 早盘深度池 10 只",
                                                     "verified_on": BASE_DATE,
                                                     "n_beat_mkt": sum(1 for r in am_rev if r["beat_mkt"]),
                                                     "n_positive": sum(1 for r in am_rev if r["pos"]),
                                                     "results": am_rev},
                                        "pm_top5": {"source": "11-11 尾盘深度池 5 只 (pm 管线 day2)",
                                                    "verified_on": BASE_DATE,
                                                    "n_beat_mkt": sum(1 for r in pm_rev if r["beat_mkt"]),
                                                    "n_positive": sum(1 for r in pm_rev if r["pos"]),
                                                    "results": pm_rev}},
                   "recommend": ({"code": recommend["code"], "name": recommend["name"],
                                  "total": recommend["total"], "rating": recommend["rating"],
                                  "chg_pct": recommend["chg_pct"],
                                  "chg_rank": recommend.get("chg_rank"),
                                  "sector_win_rate": recommend["sector_win_rate"],
                                  "industry": recommend["industry"]}
                                 if recommend else None),
                   "eligible_pool": [{"code": r["code"], "name": r["name"], "total": r["total"],
                                      "rating": r["rating"]} for r in eligible],
                   "results": results}, f, ensure_ascii=False, indent=1)

    print("\n=== 深度排名 (技术50%+基本面30%+估值20%, 含失真修正) ===")
    for i, r in enumerate(results, 1):
        pos = "✅正盈利" if (r["chg_pct"] or 0) > 0 else "❌"
        dist = " [失真修正]" if r["distorted"] else ""
        cw = f" ⚠️{'/'.join(r['cold_weak_hits'])}" if r.get("cold_weak_hits") else ""
        print(f"{i}. {r['code']} {r['name']} 深度评分 {r['total']} {r['rating']}{dist} "
              f"| {BASE_DATE} {r['chg_pct']:+.2f}% 池内#{r.get('chg_rank')} {pos} "
              f"| 板块 {r['industry']} 胜率 {r['sector_win_rate']}{cw}")
    print(f"\n正盈利: {len(positive)}/{len(results)} | 强于大盘({MK_AVG:+.2f}%): "
          f"{sum(1 for r in results if r.get('beat_mkt'))}/{len(results)}")
    print(f"铁律合格池 (≥增持65+正盈利+胜出+未破止损+守卫放行): "
          f"{[(r['code'], r['name'], r['total'], r['rating']) for r in eligible]}")
    if recommend:
        print(f"\n🏁 最值得购买: {recommend['code']} {recommend['name']} "
              f"(深度 {recommend['total']} {recommend['rating']}, "
              f"{BASE_DATE} {recommend['chg_pct']:+.2f}% 池内#{recommend.get('chg_rank')}) "
              f"→ 同步东财 {TODAY.replace('-','')}ZZ")
    else:
        if ice:
            print(f"\n🏁 0 推荐 → 不创建东财组合 {TODAY.replace('-','')}ZZ "
                  f"(P0 冰点守卫短路: 情绪{snap['sentiment_score']}{snap['sentiment_label']}/"
                  f"仓位{snap['position_ratio']*100:.0f}%/{snap.get('reason') or '⚠️停止交易'})")
        else:
            print(f"\n🏁 0 推荐 → 不创建东财组合 (无标的满足铁律)")
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()

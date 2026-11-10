#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-11-10 (周二交易日盘前 08:3x) — V 型修复兑现次日 · 候选池 8 只 · 第 5 样本判决日盘前腿
当日报告 = reports/2026-11-10-选股报告.md (11-10 08:02 盘前版, 涨跌幅=昨收 11-09 周一收盘口径)
候选池 = 当日报告 Top10 表全部 8 只 (603131 上海沪工 / 600118 中国卫星 / 601689 拓普集团 /
         603305 旭升集团 / 002351 漫步者 / 002877 智能自控 / 002420 毅昌科技 / 000700 模塑科技,
         11-09 收盘 +1.92~+4.71% 全正, 报告综合分 65x4+64x4; 与 gid=1916 (11-09 17:03 晚间链
         用 11-09 收盘数据刷新) 同池 = 动量延续口径, 11-06 同现象; 今日裸日期组 gid=1921 8 只同)
方法: 复用 deep_analysis_20261022 评分引擎 (技术50% + 基本面30% + 估值20%)
      + 估值面失真修正 v1 (10-28 PM 规则: 最新单季归母转亏 且 净利同比<-50% → PE 记 0 只留 PB)
      腾讯行情(盘前=11-09 收盘冻结口径) + 腾讯日K(120d qfq, 末日 11-09) + akshare 财务摘要
      + 东财 f127/sina 行业双源核验 + rec_tuning 板块胜率 (104 键 405 笔 49.4%, 11-09 20:00 更新)
铁律: 最值得购买者需基准交易日 11-09 当日胜出 (强于大盘平均 -0.04% 且居池内前列) + 正盈利
      + 深度评级 ≥增持(65) + 未破报告软止损 + 守卫放行
链路语境: 11-06 冰点 20 → 周末双日续 20 → 11-09 盘前三段: 盘前冰点 20 (0 推荐第 9 例) →
      09:38 回暖 58 → 14:45 守卫通过 (回暖/仓位70%) → 14:46 建仓 10 只×100股 (≈¥20196,
      第 5 个"修复放行"样本; 🔴时序倒挂: 建仓早于深度分析, 减持级宇晶与估值失真爱旭已入持仓,
      Top1 航天晨光 69.7 增持入 20261109PP gid=1911 反而未建仓) → 今日 09:32 T1 卖出腿判决
      (前 4 批 4/4 亏 -¥827, 最近批 0胜10负 — 判决由 cron 链执行, 本 run 盘前仅披露)
      今日快照情绪 55 回暖 / 仓位 50% / ✅正常交易 (仓位 70%→50% 降温一步, 非冰点)
baseline 自查 (第 5 样本透传, 昨日移交项): 今日池 11-09 涨幅 +1.92~+4.71% 全部 <5% 温和带,
      无 >7% 追高标的; cold/weak 板块重合 = runtime 双源行业命中检查 (见逐股输出)
Kimi: 本机无 kimi CLI / moonshot key (11-10 再复核: which kimi 无, env 无, ~/.kimi 不存在)
      — 连续第 26 日由 AAna 深度评分引擎 + LLM 定性层执行
东财: 依铁律合格池 Top1 → 20261110ZZ (先例: 仅 Top1 入组); 裸日期 20261110 (gid=1921, 今晨
      08:03 已持 8 只) 与 20261109 (gid=1916, 昨 17:03 晚间刷新) 严禁触碰; find_group_gid
      前 8 位日期匹配对 ZZ 后缀有歧义 → 创建后必须 gid∉当日占用集 防御校验 (sync_zz_20261110.py)
"""
import sys, os, json, re, time
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import data_sources as ds
from deep_analysis_20261022 import tech_score, fund_score, val_score, rating_of

TODAY = "2026-11-10"
BASE_DATE = "2026-11-09"   # K 线末日 / 昨收基准 (11-09 周一收盘)
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
TODAY_REPORT = os.path.join(REPORT_DIR, f"{TODAY}-选股报告.md")  # 今日 08:02 盘前版
OUT_JSON = os.path.expanduser(f"~/code/AAna/data/deep_analysis_{TODAY.replace('-','')}.json")
YDAY_PM_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_pm_20261109.json")
MK_AVG = -0.04            # 报告快照: 大盘平均涨跌 -0.04% (11-09 收盘基准)
SH_CLOSE = 0.32           # 上证 +0.32% 收 3660.79 (11-09 收盘基准)
SNAP = {"score": 55, "label": "回暖", "zt_count": 57, "dt_count": 6, "position": 0.50}
RUN_ID = "01a1c2dd-1f2e-7c6e-aca4-75ad34a889a3"

# 行业 (双源 runtime 核验; stat_key → rec_tuning sector_stats 104 键 405 笔) 映射
SECTOR_MAP = {
    "603131": ("航天军工-焊接装备+航天电子 (焊机主业 + 航天华宇军品配套)", "航空装备",
               [("其它通用机械", "警戒键-其它通用机械(cold_sectors 在列, 焊接装备若归此类)")],
               None),
    "600118": ("航天-小卫星制造总装龙头 (航天五院旗下, 卫星应用+地面测控)", "航空装备",
               [],
               None),
    "601689": ("汽车零部件-平台型 Tier1 (NVH/热管理/轻量化+机器人执行器, 特斯拉链)", "汽车零部件",
               [],
               None),
    "603305": ("汽车零部件-铝合金精密压铸 (特斯拉一体压铸链 + 新能源三电壳体)", "汽车零部件",
               [],
               None),
    "000700": ("汽车零部件-内外饰注塑模具 (改性塑料 + 北美豪车保险杠代工)", "汽车零部件",
               [("改性塑料", "邻近键-改性塑料(冷样本 0/1)")],
               None),
    "002351": ("消费电子-音频设备品牌 (音箱/耳机, 国内市占龙头)", None,
               [("电子零部件制造", "警戒键-电子零部件制造(cold_sectors 在列)"),
                ("家电零部件", "邻近键-家电零部件(1/1)")],
               None),
    "002877": ("工控-自动化控制阀 (调节阀/核电军工配套, 智能制造)", "工控自动化",
               [],
               None),
    "002420": ("显示-电视整机结构件/面板结构件 (TV 边框 + 医疗器械塑件)", "显示器件",
               [],
               None),
}

# 昨日 (11-09) 两腿: 早盘 0 推荐 (冰点第 9 例, 无复核池); 尾盘深度池 Top5 → 今日 T+1 复核
# (11-09 收盘快照 vs 大盘平均 -0.04%; entry = 尾盘选股时点价, stop = 尾盘止损价)
YDAY_AM_NOTE = "11-09 早盘 0 推荐 (冰点 20 快照+live 双口径短路, 0推荐铁律第 9 例) → 无 AM 复核池"
YDAY_PM_POOL = [
    {"code": "600501", "name": "航天晨光", "total": 69.7, "rating": "增持", "stop": 15.90, "entry": 17.12,
     "group": "20261109PP(gid=1911)"},
    {"code": "603375", "name": "盛景微", "total": 59.3, "rating": "中性", "stop": 39.92, "entry": 42.94},
    {"code": "603666", "name": "亿嘉和", "total": 55.7, "rating": "中性", "stop": 24.10, "entry": 25.99},
    {"code": "600732", "name": "爱旭股份", "total": 53.7, "rating": "中性", "stop": 12.22, "entry": 13.14},
    {"code": "002943", "name": "宇晶股份", "total": 35.9, "rating": "减持", "stop": 27.91, "entry": 30.03},
]


def parse_top10_full(text):
    """解析 '🏆 重点关注 Top 10' 表格: 排名/名称/代码/价格/涨跌幅/技术分/综合分/软止损 (口径同 10-27~11-09)"""
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
    """P0 冰点守卫 (单一真源 check_ice_point_guard)。盘前未开盘: live 源 (ths) = 11-09 收盘口径,
    以报告快照 55 回暖为判定口径 (11-09 收盘情绪 → 11-10 盘前延续)"""
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
    """腾讯实时快照: 盘前=昨收(11-09 收盘)口径。返回 {code: (现价, 涨跌幅%, 快照时间戳, 昨收)}"""
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
    """T+1 复核: 11-09 收盘快照验证「当日胜出(>大盘平均)+正盈利」"""
    q = tencent_quotes([r["code"] for r in pool])
    review = []
    for r in pool:
        px, chg, ts, prev = q.get(r["code"], (None, None, "", None))
        review.append({**r, "close": px, "prev_close": prev, "chg_pct": chg, "quote_ts": ts,
                       "beat_mkt": (chg is not None and chg > mk_avg),
                       "pos": (chg is not None and chg > 0),
                       "pnl_vs_entry": (round((px / r["entry"] - 1) * 100, 2) if px else None)})
    review.sort(key=lambda x: (x["chg_pct"] if x["chg_pct"] is not None else -99), reverse=True)
    print(f"\n=== {title} (11-09 收盘, 腾讯快照口径; 基准=大盘平均 {mk_avg:+.2f}%) ===")
    for i, r in enumerate(review, 1):
        ts = r['quote_ts'][:8]
        print(f"{i}. {r['code']} {r['name']} 深度{r['total']}{r['rating']}"
              f"{' [' + r['group'] + ']' if r.get('group') else ''}"
              f" | 11-09 实收 {r['chg_pct']:+.2f}% ({'✅胜大盘(' + format(mk_avg, '+.2f') + '%)' if r['beat_mkt'] else '❌弱于大盘'})"
              f"{' ✅正盈利' if r['pos'] else ' ❌负'} | vs 建仓参考价 {r['entry']} → {r['pnl_vs_entry']:+.2f}%"
              f" | 快照日 {ts}"
              f"{' 🔴破软止损' + str(r['stop']) if (r['stop'] and (r['close'] or 0) < r['stop']) else ''}")
    n_beat = sum(1 for r in review if r["beat_mkt"])
    n_pos = sum(1 for r in review if r["pos"])
    print(f"胜大盘({mk_avg:+.2f}%): {n_beat}/{len(review)} | 正盈利: {n_pos}/{len(review)}")
    return review


def main():
    print("=" * 78)
    print(f"AAna 深度分析 — {TODAY} (周二交易日盘前, 数据基准 {BASE_DATE} 收盘)")
    print(f"Run: autopilot ca411dd3 深度分析 {RUN_ID}")
    print("=" * 78)

    # ---- 报告确认 (autopilot 强制: 打印报告名称防错) ----
    sz = os.path.getsize(TODAY_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(TODAY_REPORT)))
    print(f"📄 当日报告: {TODAY_REPORT}")
    print(f"   → 存在 | 大小: {sz} 字节 | 修改: {mt} (今日 08:02 盘前版, '涨跌幅'=昨收=11-09 收盘口径)")
    text = open(TODAY_REPORT).read()
    pool = parse_top10_full(text)
    # 双重校验: 表区间内含 6 位代码的数据行原始计数 (防解析器误判, 10-28 口径)
    m = re.search(r'重点关注 Top 10(.*?)(?=\n###|\Z)', text, re.S)
    raw_rows = [l for l in (m.group(1) if m else "").split("\n")
                if l.strip().startswith("|") and re.search(r'\d{6}', l)
                and not l.strip().startswith("|:")]
    print(f"   当日 Top10 表: {len(pool)} 只 (原始数据行 {len(raw_rows)} 行) → 候选池 = {len(pool)} 只 "
          f"(昨早盘池 0 只 → 今日 8 只, 冰点后修复首个完整池)")
    for p in pool:
        print(f"     #{p['rank']} {p['code']} {p['name']} ¥{p['price']} {p['chg']:+.2f}% "
              f"报告分{p['v24']} 技术分{p['tech']} 软止损{p['stop']}")
    snap_sent = (f"情绪{SNAP['score']}({SNAP['label']}) 仓位{SNAP['position']*100:.0f}% "
                 f"大盘平均{MK_AVG:+.2f}% 涨停{SNAP['zt_count']}/跌停{SNAP['dt_count']} "
                 f"上证{SH_CLOSE:+.2f}% 收3660.79 交易建议✅正常交易")
    print(f"   报告快照 (= 11-09 周一收盘口径): {snap_sent}")
    print("   链路状态: V 型修复兑现次日 — 11-06 冰点 20 → 周末续 20 → 11-09 三段式修复 "
          "(盘前 20 → 09:38 回暖 58 → 14:45 守卫通过 55/仓位70%); 昨 14:46 建仓 10 只 = 第 5 个修复放行样本 "
          "(🔴时序倒挂: 建仓早于深度分析, Top1 航天晨光反而未建仓); 今日 09:32 T1 卖出腿判决 "
          "(前 4 批 4/4 亏 -¥827), 本 run 盘前仅披露; 今日快照仓位 70%→50% 降温一步非冰点")

    sector_stats, overall_wr, n_rec, rt_gen = load_sector_stats()
    print(f"📊 板块胜率库 (rec_optimizer 口径, generated_at {rt_gen}): {len(sector_stats)} 板块 | "
          f"整体胜率 {overall_wr:.1f}% ({n_rec} 笔)")
    nds = load_nds()
    cold_l, weak_l = nds.get("cold_sectors", []), nds.get("weak_sectors", [])
    print(f"   调参披露 (next_day_strategy 11-09 16:11): v24 阈值 {nds.get('score_threshold')} "
          f"| cold_sectors {len(cold_l)} 个 | weak_sectors {len(weak_l)} 个 (semi/其他家用轻工/印制电路板/"
          f"影视动漫/房地产开发/造纸)")

    live, snap = guard_check()
    print(f"🛡 P0 冰点守卫: 快照口径 情绪{snap['sentiment_score']}({snap['sentiment_label']}) "
          f"仓位{snap['position_ratio']*100:.0f}% is_ice_point={snap['is_ice_point']}")
    if snap.get("reason"):
        print(f"   短路原因: {snap['reason']}")
    if live:
        print(f"   live 口径 情绪{live['sentiment_score']}({live['sentiment_label']}) "
              f"is_ice_point={live['is_ice_point']} (ths 源盘前=11-09 收盘口径, 披露用)")
    ice = snap["is_ice_point"] and (live["is_ice_point"] if live else True)

    # ---- 昨日 (11-09) 两腿 T+1 复核 ----
    print(f"\n=== 昨日两腿复核范围 ===\n   早盘腿: {YDAY_AM_NOTE}")
    pm_rev = review_pool(YDAY_PM_POOL, "昨尾盘深度池 Top5 复核 (600501 航天晨光 → 20261109PP gid=1911)", MK_AVG)
    p1 = next(r for r in pm_rev if r["code"] == "600501")
    print(f"🏁 昨尾盘 Top1 600501 航天晨光 铁律复核: 11-09 实收 {p1['chg_pct']:+.2f}% "
          f"vs 大盘 {MK_AVG:+.2f}% → 超额 {p1['chg_pct']-MK_AVG:+.2f}pp "
          f"{'✅ 当日胜出+正盈利' if (p1['beat_mkt'] and p1['pos']) else '❌ 未同时满足'} "
          f"(vs 入场参考 {p1['entry']} → {p1['pnl_vs_entry']:+.2f}%; 软止损 {p1['stop']} "
          f"{'🔴已破' if (p1['close'] or 0) < p1['stop'] else '未破'})")
    print("   ↳ 第 5 样本 (11-09 14:46 建仓 10 只模拟仓, 含非深度过滤股) 判决在今日 09:32 T1 卖出腿 (cron 链), "
          "本 run 不代跑; 深度池 5 只中仅 Top1 入 PP 组, 其余 4 只未建仓敞口为零")

    # ---- 价格真实性双重校验 (报告价 vs 腾讯快照, 盘前腿口径) ----
    print(f"\n=== 价格真实性双重校验 (报告价 vs 腾讯快照, 11-09 收盘口径) ===")
    q_pool = tencent_quotes([p["code"] for p in pool])
    n_match = 0
    for p in pool:
        px, chg, ts, prev = q_pool.get(p["code"], (None, None, "", None))
        match = (px is not None and abs(px - p["price"]) < 0.005
                 and ts[:8] == "20261109")
        n_match += bool(match)
        print(f"   {p['code']} {p['name']}: 报告 ¥{p['price']} vs 快照 ¥{px} ({ts[:8]}) "
              f"{'✅一致' if match else '⚠️不一致'}")
    print(f"   一致性: {n_match}/{len(pool)} → {'判定数据真实, 放行深度评分' if n_match == len(pool) else '存在不一致, 结果需谨慎'}")

    # ---- baseline 自查 (第 5 样本透传: 涨幅约束 + cold/weak 重合) ----
    chgs = [p["chg"] for p in pool]
    print(f"\n=== baseline 涨幅约束自查 (第 5 样本透传项) ===")
    print(f"   今日池 11-09 涨幅带: +{min(chgs):.2f}% ~ +{max(chgs):.2f}% | >5% 追高标的: "
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
                   "yesterday_review": {"am": YDAY_AM_NOTE,
                                        "pm_top5": {"source": "11-09 尾盘深度池 Top5 (20261109PP gid=1911)",
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

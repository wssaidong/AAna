#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-11-06 (周五交易日盘前 08:3x) — 回暖延续日 · 候选池 3 只 (报告缩池)
当日报告 = reports/2026-11-06-选股报告.md (08:02 盘前版, 涨跌幅=昨收 11-05 周四收盘口径)
候选池 = 当日报告 Top10 表全部 3 只 (603258 电魂网络 / 600633 浙数文化 / 600506 统一股份,
         11-05 收盘 +4.51~+4.79%, 报告综合分 65x3; 与 11-05 晚间 selection 同池 =
         东财组 20261105(gid=1891) 现持 3 只完全一致 = 动量延续日; 昨日池 10 只 → 今日 3 只,
         选股引擎收敛)
方法: 复用 deep_analysis_20261022 评分引擎 (技术50% + 基本面30% + 估值20%)
      + 估值面失真修正 v1 (10-28 PM 规则: 最新单季归母转亏 且 净利同比<-50% → PE 记 0 只留 PB)
      腾讯行情(快照日 20261105 收盘口径) + 腾讯日K(120d qfq, 末日 11-05) + akshare 财务摘要
      + 东财 f127/sina 行业双源核验 + rec_tuning 板块胜率 (98 键 394 笔 50.76%)
铁律: 最值得购买者需基准交易日 11-05 当日胜出 (强于大盘平均 +0.61% 且居池内前列) + 正盈利
      + 深度评级 ≥增持(65) + 未破报告软止损 + 守卫放行 (10-24~11-05 口径连续)
链路语境: 11-03 冰点 35 → 11-04 V 型修复 85 亢奋 → 11-05 降温回暖 73 (上证 +0.10% 收 3689.91,
      大盘平均 +0.61%, 涨停 85/跌停 8) — 亢奋 85 隔日未塌方 (与 10-28→10-29, 11-02→11-03
      两先例不同), 但降温 12 点, 仓位 85%→70%; 今日回暖 73 ✅正常交易;
      追高风险披露: 全池 11-05 已 +4.5~4.8%, 隔日溢价不确定, 止损纪律仍为第一约束
T+1 复核 (两腿齐备, 11-05 收盘快照验证「当日胜出+正盈利」vs 大盘平均 +0.61%):
      早盘腿: 11-05 AM Top1 中电港 001287 (94.5 买入 → 东财 20261105ZZ gid=1876, 入场参考 20.75)
      尾盘腿: 11-05 PM Top5 (智度 79.5 买入 → 20261105PP gid=1886 / 澄星 76.5 / 天音 67.0 /
              惠泉 62.3 / 新宏泰 49.2)
Kimi: 本机无 kimi CLI / moonshot key (11-06 再复核: which kimi 无, env 无, ~/.kimi 不存在)
      — 连续第 22 日由 AAna 深度评分引擎 + LLM 定性层执行
胜率库: 98 键 / 394 笔 / 整体 50.76% (11-05 晚间 rec_optimizer 更新口径, 昨日 93 键/380 笔)
调参披露: next_day_strategy 11-05 回基准: 阈值 63 / cold_sectors 8 键 (啤酒/电气设备/磷化工及
      磷酸盐/铅锌/储能设备/装修装饰/交通运输/专业连锁) / weak_sectors 6 键不变 —
      昨尾盘池直接命中 3 键: 惠泉↔啤酒(cold), 新宏泰↔电气设备(cold), 天音↔专业连锁(cold);
      今日池 3 只无直接 cold/weak 命中 (影视动漫 weak 为电魂邻近键披露)
东财: 依铁律合格池 Top1 → 20261106ZZ (先例: 仅 Top1 入组); 0 合格则不建组;
      裸日期 20261106 (gid=1896, 今晨空占位组) 与 20261105 (gid=1891, 昨晚间 selection 3 只)
      严禁触碰; find_group_gid 前 8 位日期匹配对 ZZ 后缀有歧义 → 创建后必须 gid≠1896 防御校验
"""
import sys, os, json, re, time
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import data_sources as ds
from deep_analysis_20261022 import tech_score, fund_score, val_score, rating_of

TODAY = "2026-11-06"
BASE_DATE = "2026-11-05"   # K 线末日 / 昨收基准 (11-05 周四收盘)
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
TODAY_REPORT = os.path.join(REPORT_DIR, f"{TODAY}-选股报告.md")  # 周五 08:02 盘前版
OUT_JSON = os.path.expanduser(f"~/code/AAna/data/deep_analysis_{TODAY.replace('-','')}.json")
MK_AVG = 0.61             # 报告快照: 大盘平均涨跌 +0.61% (11-05 收盘基准)
SH_CLOSE = 0.10           # 上证 +0.10% 收 3689.91 (11-05 收盘基准)
SNAP = {"score": 73, "label": "回暖", "zt_count": 85, "dt_count": 8, "position": 0.70}
RUN_ID = "01a1ae43-a4b0-774b-b28c-7fe15b47a8f2"

# 行业 (sina industry_for_code + 东财 f127 双源核验, 11-06 盘前实测) → rec_tuning sector_stats (98 键 394 笔) 映射
# 603258: sina[移动互联网服务] em[游戏Ⅱ] | 600633: sina[移动互联网服务] em[游戏Ⅱ] | 600506: sina[其他种植业] em[炼化及贸易] (双源分裂)
SECTOR_MAP = {
    "603258": ("传媒-网络游戏/电子竞技 (《梦三国》IP, 电竞+AI 布局)", "移动互联网服务",
               [("传媒", "邻近键-传媒(数字娱乐)"),
                ("影视动漫", "警戒键-影视动漫(weak_sectors 在列)")],
               "⚠️ 影视动漫(游戏同属传媒娱乐链) 在 weak_sectors 6 键中; PE(TTM) -14 亏损待失真修正判定"),
    "600633": ("传媒-数字文化+互联网游戏平台 (边锋网络休闲游戏/大数据/数字文化)", "移动互联网服务",
               [("传媒", "邻近键-传媒(浙报党报数字文化)")],
               None),
    "600506": ("石化-润滑油 (统一石化重组入主, 壳遗留种植业资产)", None,
               [("chem", "邻近键-化工大类(冷样本 0/2)"),
                ("涂料油漆油墨制造", "邻近键-化学制品制造同类(1/1)")],
               "⚠️ 行业双源分裂: sina 其他种植业(壳遗留) vs 东财 炼化及贸易; 胜率库无炼化/润滑油键(冷启动); PE 167/PB 9.46 高估值"),
}

# 昨日 (11-05) 两腿深度池 — 今日 T+1 复核池 (11-05 收盘快照 vs 大盘平均 +0.61%)
YDAY_AM_TOP1 = {"code": "001287", "name": "中电港", "total": 94.5, "rating": "买入",
                "stop": 20.13, "entry": 20.75, "group": "20261105ZZ(gid=1876)"}
YDAY_PM_POOL = [
    {"code": "000676", "name": "智度股份", "total": 79.5, "rating": "买入", "stop": 6.52, "entry": 7.03,
     "group": "20261105PP(gid=1886)"},
    {"code": "600078", "name": "澄星股份", "total": 76.5, "rating": "买入", "stop": 8.82, "entry": 9.50},
    {"code": "000829", "name": "天音控股", "total": 67.0, "rating": "增持", "stop": 8.74, "entry": 9.43},
    {"code": "600573", "name": "惠泉啤酒", "total": 62.3, "rating": "中性", "stop": 11.93, "entry": 12.83},
    {"code": "603016", "name": "新宏泰", "total": 49.2, "rating": "减持", "stop": 26.58, "entry": 28.59},
]
# 11-05 晚间 NDS cold_sectors 命中 (昨尾盘池 3/5): 惠泉↔啤酒, 新宏泰↔电气设备, 天音↔专业连锁
YDAY_COLD_HIT = {"600573": "啤酒", "603016": "电气设备", "000829": "专业连锁"}


def parse_top10_full(text):
    """解析 '🏆 重点关注 Top 10' 表格: 排名/名称/代码/价格/涨跌幅/技术分/综合分/软止损 (口径同 10-27~11-05)"""
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
    """P0 冰点守卫 (单一真源 check_ice_point_guard)。盘前未开盘: live 源可能回退,
    以报告快照 73 回暖为判定口径 (11-05 收盘情绪 → 11-06 盘前延续)"""
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
    return rt.get("sector_stats", {}), rt.get("overall_win_rate"), rt.get("total_records")


def load_nds():
    with open(os.path.expanduser("~/code/AAna/data/next_day_strategy.json")) as f:
        return json.load(f)


def fetch_kline(code):
    """腾讯日K 120d qfq — fqkline qfq 端点 WAF 501 时降级 kline/kline 非复权 (10-26 PM 踩坑);
    11-04 PM 矩阵: 带参返空→3 变体降级已固化"""
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
    """腾讯实时快照: 盘前=昨收(11-05 收盘)口径。返回 {code: (现价, 涨跌幅%, 快照时间戳)}"""
    import requests
    syms = ",".join(("sh" if c.startswith(("6", "9")) else "sz") + c for c in codes)
    r = requests.get(f"https://qt.gtimg.cn/q={syms}", timeout=10,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.encoding = "gbk"
    out = {}
    for m in re.finditer(r'v_(?:sh|sz)(\d{6})="([^"]+)"', r.text):
        p = m.group(2).split("~")
        try:
            out[m.group(1)] = (float(p[3]), float(p[32]), p[30])
        except (ValueError, IndexError):
            continue
    return out


def review_pool(pool, title, mk_avg):
    """T+1 复核: 11-05 收盘快照验证「当日胜出(>大盘平均)+正盈利」"""
    q = tencent_quotes([r["code"] for r in pool])
    review = []
    for r in pool:
        px, chg, ts = q.get(r["code"], (None, None, ""))
        review.append({**r, "close": px, "chg_pct": chg, "quote_ts": ts,
                       "beat_mkt": (chg is not None and chg > mk_avg),
                       "pos": (chg is not None and chg > 0),
                       "pnl_vs_entry": (round((px / r["entry"] - 1) * 100, 2) if px else None)})
    review.sort(key=lambda x: (x["chg_pct"] if x["chg_pct"] is not None else -99), reverse=True)
    print(f"\n=== {title} (11-05 收盘, 腾讯快照口径; 基准=大盘平均 {mk_avg:+.2f}%) ===")
    for i, r in enumerate(review, 1):
        ts = r['quote_ts'][:8]
        cold = (f" [cold: {YDAY_COLD_HIT[r['code']]} 在 11-05 晚间 cold_sectors]"
                if r["code"] in YDAY_COLD_HIT else "")
        print(f"{i}. {r['code']} {r['name']} 深度{r['total']}{r['rating']} "
              f"| 11-05 实收 {r['chg_pct']:+.2f}% ({'✅胜大盘(' + format(mk_avg, '+.2f') + '%)' if r['beat_mkt'] else '❌弱于大盘'})"
              f"{' ✅正盈利' if r['pos'] else ' ❌负'} | vs 建仓参考价 {r['entry']} → {r['pnl_vs_entry']:+.2f}%"
              f" | 快照日 {ts}{cold}")
    n_beat = sum(1 for r in review if r["beat_mkt"])
    n_pos = sum(1 for r in review if r["pos"])
    print(f"胜大盘({mk_avg:+.2f}%): {n_beat}/{len(review)} | 正盈利: {n_pos}/{len(review)}")
    return review, q


def main():
    print("=" * 78)
    print(f"AAna 深度分析 — {TODAY} (周五交易日盘前, 数据基准 {BASE_DATE} 收盘)")
    print(f"Run: autopilot ca411dd3 深度分析 {RUN_ID}")
    print("=" * 78)

    # ---- 报告确认 (autopilot 强制: 打印报告名称防错) ----
    has_today = os.path.exists(TODAY_REPORT)
    sz = os.path.getsize(TODAY_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(TODAY_REPORT)))
    print(f"📄 当日报告: {TODAY_REPORT}")
    print(f"   → {'存在' if has_today else '不存在(异常)'} | 大小: {sz} 字节 | 修改: {mt} "
          f"(周五交易日 08:0x 盘前版, '涨跌幅'=昨收涨跌幅=11-05 周四收盘口径)")
    text = open(TODAY_REPORT).read()
    pool = parse_top10_full(text)
    # 双重校验: 表区间内含 6 位代码的数据行原始计数 (防解析器误判, 10-28 口径)
    m = re.search(r'重点关注 Top 10(.*?)(?=\n###|\Z)', text, re.S)
    raw_rows = [l for l in (m.group(1) if m else "").split("\n")
                if l.strip().startswith("|") and re.search(r'\d{6}', l)
                and not l.strip().startswith("|:")]
    print(f"   当日 Top10 表: {len(pool)} 只 (原始数据行 {len(raw_rows)} 行) → 候选池 = {len(pool)} 只 "
          f"(昨日 10 只 → 今日缩池, 与 11-05 晚间 selection 同池 = 东财组 20261105/gid=1891 现持 3 只一致)")
    for p in pool:
        print(f"     #{p['rank']} {p['code']} {p['name']} ¥{p['price']} {p['chg']:+.2f}% "
              f"报告分{p['v24']} 技术分{p['tech']} 软止损{p['stop']}")
    snap_sent = (f"情绪{SNAP['score']}({SNAP['label']}) 仓位{SNAP['position']*100:.0f}% "
                 f"大盘平均{MK_AVG:+.2f}% 涨停{SNAP['zt_count']}/跌停{SNAP['dt_count']} "
                 f"上证{SH_CLOSE:+.2f}% 收3689.91 交易建议✅正常交易")
    print(f"   报告快照 (= 11-05 周四收盘口径): {snap_sent}")
    print("   链路状态: 回暖延续日 — 11-03 冰点 35 → 11-04 V 型修复 85 亢奋 → 11-05 降温回暖 73 "
          "(上证 +0.10% 未现隔日塌方, 与 10-28→10-29 / 11-02→11-03 先例不同, 但降温 12 点仓位 85%→70%); "
          "追高风险披露: 全池 11-05 已 +4.5~4.8%, 隔日溢价不确定, 止损纪律第一约束")

    sector_stats, overall_wr, n_rec = load_sector_stats()
    print(f"📊 板块胜率库 (rec_optimizer 口径, 11-05 晚间更新): {len(sector_stats)} 板块 | "
          f"整体胜率 {overall_wr:.1f}% ({n_rec} 笔) [昨日 93 键/380 笔 49.5%]")
    nds = load_nds()
    print(f"   调参披露 (next_day_strategy 11-05 回基准): v24 阈值 {nds.get('score_threshold')} "
          f"| cold_sectors {len(nds.get('cold_sectors', []))} 个 (啤酒/电气设备/磷化工及磷酸盐/铅锌/储能设备/"
          f"装修装饰/交通运输/专业连锁 — 昨尾盘池直接命中 3: 惠泉↔啤酒, 新宏泰↔电气设备, 天音↔专业连锁) "
          f"| weak_sectors {len(nds.get('weak_sectors', []))} 个 (semi/其他家用轻工/印制电路板/影视动漫/"
          f"房地产开发/造纸 — 今日池邻近命中: 影视动漫↔电魂网络)")

    live, snap = guard_check()
    print(f"🛡 P0 冰点守卫: 快照口径 情绪{snap['sentiment_score']}({snap['sentiment_label']}) "
          f"仓位{snap['position_ratio']*100:.0f}% is_ice_point={snap['is_ice_point']}")
    if snap.get("reason"):
        print(f"   短路原因: {snap['reason']}")
    if live:
        print(f"   live 口径 情绪{live['sentiment_score']}({live['sentiment_label']}) "
              f"is_ice_point={live['is_ice_point']} (盘前未开盘, 披露用)")
    ice = snap["is_ice_point"]

    # ---- 昨日 (11-05) 两腿深度池 T+1 复核 (11-05 收盘, 腾讯快照) ----
    am_rev, _ = review_pool([YDAY_AM_TOP1], "昨早盘深度池 Top1 复核 (001287 中电港 → 20261105ZZ gid=1876)", MK_AVG)
    a = am_rev[0]
    print(f"🏁 昨早 Top1 001287 中电港 铁律复核: 11-05 实收 {a['chg_pct']:+.2f}% vs 大盘 {MK_AVG:+.2f}% "
          f"→ 超额 {a['chg_pct']-MK_AVG:+.2f}pp "
          f"{'✅ 当日胜出+正盈利' if (a['beat_mkt'] and a['pos']) else '❌ 未同时满足'} "
          f"(vs 入场参考 {a['entry']} → {a['pnl_vs_entry']:+.2f}%; 软止损 {a['stop']} "
          f"{'🔴已破' if (a['close'] or 0) < a['stop'] else '未破'})")
    pm_rev, q_all = review_pool(YDAY_PM_POOL, "昨尾盘深度池 Top5 复核 (000676 智度 → 20261105PP gid=1886)", MK_AVG)
    p1 = next(r for r in pm_rev if r["code"] == "000676")
    print(f"🏁 昨尾盘 Top1 000676 智度股份 铁律复核: 11-05 实收 {p1['chg_pct']:+.2f}% "
          f"vs 大盘 {MK_AVG:+.2f}% → 超额 {p1['chg_pct']-MK_AVG:+.2f}pp "
          f"{'✅ 当日胜出+正盈利' if (p1['beat_mkt'] and p1['pos']) else '❌ 未同时满足'} "
          f"(vs 入场参考 {p1['entry']} → {p1['pnl_vs_entry']:+.2f}%)")

    # ---- 价格真实性双重校验 (报告价 vs 腾讯快照, 盘前腿口径) ----
    print(f"\n=== 价格真实性双重校验 (报告价 vs 腾讯快照, 11-05 收盘口径) ===")
    q_pool = tencent_quotes([p["code"] for p in pool])
    n_match = 0
    for p in pool:
        px, chg, ts = q_pool.get(p["code"], (None, None, ""))
        match = (px is not None and abs(px - p["price"]) < 0.005
                 and ts[:8] == "20261105")
        n_match += bool(match)
        print(f"   {p['code']} {p['name']}: 报告 ¥{p['price']} vs 快照 ¥{px} ({ts[:8]}) "
              f"{'✅一致' if match else '⚠️不一致'}")
    print(f"   一致性: {n_match}/{len(pool)} → {'判定数据真实, 放行深度评分' if n_match == len(pool) else '存在不一致, 结果需谨慎'}")

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

        # 行业双源核验 (sina industry_for_code + 东财 f127)
        try:
            ind_sina = ds.industry_for_code(code)
        except Exception:
            ind_sina = None
        try:
            ind_em = ds.eastmoney_stock_info(code).get("industry") or None
        except Exception:
            ind_em = None
        print(f"  行业双源: sina[{ind_sina}] 东财f127[{ind_em}]")

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
               "ind_sina": ind_sina, "ind_em": ind_em,
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
        print(f"  板块: {industry} → 胜率 {sec_wr}{near_wr} {cold_warn or ''}")
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
                   "sector_count": len(sector_stats),
                   "price_check_match": n_match,
                   "nds_tuning": {"score_threshold": nds.get("score_threshold"),
                                  "cold_sectors": nds.get("cold_sectors"),
                                  "weak_sectors": nds.get("weak_sectors")},
                   "yesterday_review": {"am_top1": {"source": "11-05 早盘深度池 Top1 (20261105ZZ gid=1876)",
                                                    "verified_on": BASE_DATE,
                                                    "results": am_rev},
                                        "pm_top5": {"source": "11-05 尾盘深度池 Top5 (20261105PP gid=1886)",
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
        print(f"{i}. {r['code']} {r['name']} 深度评分 {r['total']} {r['rating']}{dist} "
              f"| {BASE_DATE} {r['chg_pct']:+.2f}% 池内#{r.get('chg_rank')} {pos} "
              f"| 板块 {r['industry']} 胜率 {r['sector_win_rate']} {r['sector_cold_warn'] or ''}")
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

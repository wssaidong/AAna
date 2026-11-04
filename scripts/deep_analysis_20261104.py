#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-11-04 (周三交易日盘前 08:3x) — 冰点第 1 日 (隔日塌方) · 候选池 10 只 (防御池)
当日报告 = reports/2026-11-04-选股报告.md (08:02 盘前版, 涨跌幅=昨收 11-03 周二收盘口径)
候选池 = 当日报告 Top10 表全部 10 只 (11-03 收盘 +1.64%~+1.92%, 报告综合分 65x5/64x5,
         医药×4 + 食品/银行/公用/家纺/汽零/光伏 全防御属性 — 成长杀跌日次日 screener 转向防御)
方法: 复用 deep_analysis_20261022 评分引擎 (技术50% + 基本面30% + 估值20%)
      + 估值面失真修正 v1 (10-28 PM 规则: 最新单季归母转亏 且 净利同比<-50% → PE 记 0 只留 PB)
      腾讯行情(快照日 20261103 收盘口径) + 腾讯日K(120d qfq, 末日 11-03) + akshare 财务摘要
      + 东财 f127/sina 行业双源核验 + rec_tuning 板块胜率 (93 键 380 笔 49.47%)
铁律: 最值得购买者需基准交易日 11-03 当日胜出 (强于大盘平均 -1.24% 且居池内前列) + 正盈利
      + 深度评级 ≥增持(65) + 未破报告软止损 + 守卫放行 (10-24~11-03 口径连续)
P0 冰点守卫: 报告快照情绪 35 (冰点, 仓位 20%, 涨停 52/跌停 5, ⚠️停止交易) → 预期短路;
      11-03 单日塌方 75→15→35 (亢奋第 2 日隔日即塌, 10-28 亢奋75→10-29 塌20 先例第 2 次复现),
      成长单边杀跌 (元件 -5.13%/半导体 -5.09%/电子化学品 -5.05%), 防御侧接管 (保险 +2.67%)
Kimi: 本机无 kimi CLI / moonshot key (11-04 再复核: which kimi 无, env 无, ~/.kimi 不存在)
      — 连续第 20 日由 AAna 深度评分引擎 + LLM 定性层执行
胜率库: 93 键 / 380 笔 / 整体 49.47% (b1053af 11-03 15:00 回填 13 条后口径, generated 2026-11-03T20:02)
调参披露: next_day_strategy 11-04 回基准 (根因 0 命中 → 阈值 60 / 仓位 50% / 冷板块空;
      weak_sectors 6: semi/其他家用轻工/印制电路板/影视动漫/房地产开发/造纸 — 与今日池无直接键关联)
T+1 复核: 昨 11-03 早盘深度池 Top5 (002956 西麦 85.6 买入→东财 20261103ZZ gid=1831 / 605118 力鼎
      62.7 中性 / 603160 汇顶 51.6 中性 / 000860 顺鑫 51.2 中性 / 002242 九阳 30.4 减持) 以 11-03
      收盘快照验证「当日胜出+正盈利」; 昨尾盘腿 14:45 守卫第 9 次短路 + v2.5 0 推荐 → 无尾盘池可复核
东财: 依铁律合格池 Top1 → 20261104ZZ (先例 10-27/10-29/11-03: 仅 Top1 入组); 0 合格则不建组
"""
import sys, os, json, re, time
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import data_sources as ds
from deep_analysis_20261022 import tech_score, fund_score, val_score, rating_of

TODAY = "2026-11-04"
BASE_DATE = "2026-11-03"   # K 线末日 / 昨收基准 (11-03 周二收盘)
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
TODAY_REPORT = os.path.join(REPORT_DIR, f"{TODAY}-选股报告.md")  # 周三 08:02 盘前版
OUT_JSON = os.path.expanduser(f"~/code/AAna/data/deep_analysis_{TODAY.replace('-','')}.json")
MK_AVG = -1.24          # 报告快照: 大盘平均涨跌 -1.24% (11-03 收盘基准)
SH_CLOSE = -0.82        # 上证 -0.82% 收 3608.10 (11-03 收盘基准)
SNAP = {"score": 35, "label": "冰点", "zt_count": 52, "dt_count": 5, "position": 0.20}
RUN_ID = "01a1a3f7-0284-7b13-ac2d-12c36054f4e7"

# 行业 (sina industry_for_code + 东财 f127 双源核验, 11-04 盘前实测) → rec_tuning sector_stats (93 键 380 笔) 映射
SECTOR_MAP = {
    "600732": ("电力设备-光伏设备(ABC 电池制造, sina/em 双源一致, 库无光伏设备键)", None,
               [("新能源发电", "邻近键-新能源发电(光伏产业链)")], None),
    "603233": ("医药-医药商业(华南药店连锁龙头)", "医药商业", [], None),
    "601166": ("银行-全国性股份制商业银行(em f127 银行Ⅱ)", "银行", [], None),
    "600763": ("医药-医疗服务(口腔医疗连锁, 浙江)", "医疗服务", [], None),
    "600323": ("环保-固废+供水燃气一体化(em f127 环境治理无库键, 取 sina 公用事业)", "公用事业", [], None),
    "000678": ("汽车-汽车零部件(轴承, 湖北襄阳)", "汽车零部件", [], None),
    "002293": ("轻工-家纺(床上用品龙头, sina 家纺无库键, em 服装家纺→纺织服装大类)", "纺织服装", [], None),
    "002223": ("医药-医疗器械(家用器械: 制氧机/血压计)", "医疗器械", [], None),
    "002737": ("医药-中药(儿童药/OTC, em f127 中药Ⅱ, sina 医药生物)", "中药", [], None),
    "002507": ("食品-榨菜/下饭菜(sina 食品综合 + em f127 调味发酵品Ⅱ 双键在库)", "食品综合",
               [("调味发酵品", "邻近键-em f127 调味发酵品Ⅱ口径")], None),
}

# 昨日 (11-03 08:3x) 早盘深度池 Top5 (4e27c99 口径) — 今日 T+1 复核池 (11-03 收盘快照验证)
# entry = 11-02 收盘价 (昨日分析时点现价/建仓参考); stop = 报告软止损
YDAY_AM_POOL = [
    {"code": "002956", "name": "西麦食品", "total": 85.6, "rating": "买入", "stop": 19.64, "entry": 20.25},
    {"code": "605118", "name": "力鼎光电", "total": 62.7, "rating": "中性", "stop": 36.08, "entry": 37.20},
    {"code": "603160", "name": "汇顶科技", "total": 51.6, "rating": "中性", "stop": 58.16, "entry": 59.96},
    {"code": "000860", "name": "顺鑫农业", "total": 51.2, "rating": "中性", "stop": 11.91, "entry": 12.28},
    {"code": "002242", "name": "九阳股份", "total": 30.4, "rating": "减持", "stop": 22.63, "entry": 23.33},
]


def parse_top10_full(text):
    """解析 '🏆 重点关注 Top 10' 表格: 排名/名称/代码/价格/涨跌幅/技术分/综合分/软止损 (口径同 10-27~11-03)"""
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
    以报告快照 35 冰点为判定口径 (11-03 收盘情绪 → 11-04 盘前延续)"""
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
    """腾讯实时快照: 盘前=昨收(11-03 收盘)口径。返回 {code: (现价, 涨跌幅%, 快照时间戳)}"""
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


def main():
    print("=" * 78)
    print(f"AAna 深度分析 — {TODAY} (周三交易日盘前, 数据基准 {BASE_DATE} 收盘)")
    print(f"Run: autopilot ca411dd3 深度分析 {RUN_ID}")
    print("=" * 78)

    # ---- 报告确认 (autopilot 强制: 打印报告名称防错) ----
    has_today = os.path.exists(TODAY_REPORT)
    sz = os.path.getsize(TODAY_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(TODAY_REPORT)))
    print(f"📄 当日报告: {TODAY_REPORT}")
    print(f"   → {'存在' if has_today else '不存在(异常)'} | 大小: {sz} 字节 | 修改: {mt} "
          f"(周三交易日 08:0x 盘前版, '涨跌幅'=昨收涨跌幅=11-03 周二收盘口径)")
    text = open(TODAY_REPORT).read()
    pool = parse_top10_full(text)
    # 双重校验: 表区间内含 6 位代码的数据行原始计数 (防解析器误判, 10-28 口径)
    m = re.search(r'重点关注 Top 10(.*?)(?=\n###|\Z)', text, re.S)
    raw_rows = [l for l in (m.group(1) if m else "").split("\n")
                if l.strip().startswith("|") and re.search(r'\d{6}', l)
                and not l.strip().startswith("|:")]
    print(f"   当日 Top10 表: {len(pool)} 只 (原始数据行 {len(raw_rows)} 行) → 候选池 = {len(pool)} 只")
    for p in pool:
        print(f"     #{p['rank']} {p['code']} {p['name']} ¥{p['price']} {p['chg']:+.2f}% "
              f"报告分{p['v24']} 技术分{p['tech']} 软止损{p['stop']}")
    snap_sent = (f"情绪{SNAP['score']}({SNAP['label']}) 仓位{SNAP['position']*100:.0f}% "
                 f"大盘平均{MK_AVG:+.2f}% 涨停{SNAP['zt_count']}/跌停{SNAP['dt_count']} "
                 f"上证{SH_CLOSE:+.2f}% 收3608.10 交易建议⚠️停止交易")
    print(f"   报告快照 (= 11-03 周二收盘口径): {snap_sent}")
    print("   链路状态: 冰点第 1 日 — 11-03 单日塌方 75→15→35 (亢奋第 2 日隔日即塌, 10-28→10-29 先例第 2 次复现),"
          " 成长单边杀跌 (元件 -5.13%/半导体 -5.09%), 防御侧接管; 昨三链同日空仓 (早盘 0/尾盘 v2.4 短路/v2.5 0)")

    sector_stats, overall_wr, n_rec = load_sector_stats()
    print(f"📊 板块胜率库 (rec_optimizer 口径): {len(sector_stats)} 板块 | 整体胜率 {overall_wr:.1f}% ({n_rec} 笔)")
    nds = load_nds()
    print(f"   调参披露 (next_day_strategy 11-04 回基准, 根因 0 命中): v24 阈值 {nds.get('score_threshold')} "
          f"(63→60) | 冷板块 {len(nds.get('cold_sectors', []))} 个 (空) | "
          f"weak_sectors {len(nds.get('weak_sectors', []))} 个 (semi/其他家用轻工/印制电路板/影视动漫/房地产开发/造纸 — 与今日池无直接键)")

    live, snap = guard_check()
    print(f"🛡 P0 冰点守卫: 快照口径 情绪{snap['sentiment_score']}({snap['sentiment_label']}) "
          f"仓位{snap['position_ratio']*100:.0f}% is_ice_point={snap['is_ice_point']}")
    if snap.get("reason"):
        print(f"   短路原因: {snap['reason']}")
    if live:
        print(f"   live 口径 情绪{live['sentiment_score']}({live['sentiment_label']}) "
              f"is_ice_point={live['is_ice_point']} (盘前未开盘, 披露用)")
    ice = snap["is_ice_point"]

    # ---- 昨日 (11-03) 早盘深度池 Top5 当日实现复核 (11-03 收盘, 腾讯快照) ----
    codes5 = [r["code"] for r in YDAY_AM_POOL]
    q5 = tencent_quotes(codes5)
    review = []
    for r in YDAY_AM_POOL:
        px, chg, ts = q5.get(r["code"], (None, None, ""))
        review.append({**r, "close": px, "chg_pct": chg, "quote_ts": ts,
                       "beat_mkt": (chg is not None and chg > MK_AVG),
                       "pos": (chg is not None and chg > 0),
                       "pnl_vs_entry": (round((px / r["entry"] - 1) * 100, 2) if px else None)})
    review.sort(key=lambda x: (x["chg_pct"] if x["chg_pct"] is not None else -99), reverse=True)
    print(f"\n=== 昨日早盘深度池 Top5 当日实现复核 ({BASE_DATE} 收盘, 腾讯快照口径; 快照日 20261103) ===")
    print("    (昨尾盘腿 14:45 守卫第 9 次短路 + v2.5 0 推荐 → 无尾盘池可复核 → 复核对象=早盘腿 Top5)")
    for i, r in enumerate(review, 1):
        ts = r['quote_ts'][:8]
        print(f"{i}. {r['code']} {r['name']} 深度{r['total']}{r['rating']} "
              f"| 11-03 实收 {r['chg_pct']:+.2f}% ({'✅胜大盘(-1.24%)' if r['beat_mkt'] else '❌弱于大盘'})"
              f"{' ✅正盈利' if r['pos'] else ' ❌负'} | vs 建仓参考价 {r['entry']} → {r['pnl_vs_entry']:+.2f}%"
              f" | 快照日 {ts}")
    n_beat = sum(1 for r in review if r["beat_mkt"])
    n_pos = sum(1 for r in review if r["pos"])
    ytop = next(r for r in review if r["code"] == "002956")
    print(f"胜大盘({MK_AVG:+.2f}%): {n_beat}/{len(review)} | 正盈利: {n_pos}/{len(review)}")
    print(f"🏁 昨早盘 Top1 002956 西麦食品 铁律复核: 11-03 实收 {ytop['chg_pct']:+.2f}% "
          f"vs 大盘 {MK_AVG:+.2f}% → 超额 {ytop['chg_pct']-MK_AVG:+.2f}pp "
          f"{'✅ 当日胜出+正盈利' if (ytop['beat_mkt'] and ytop['pos']) else '❌'} "
          f"(东财 20261103ZZ gid=1831; 复盘口径: 唯一命中·深度 Top1, 池内均值 -2.55% 1/5 命中)")

    # ---- 价格真实性双重校验 (报告价 vs 腾讯快照, 盘前腿口径) ----
    print(f"\n=== 价格真实性双重校验 (报告价 vs 腾讯快照, 11-03 收盘口径) ===")
    q_pool = tencent_quotes([p["code"] for p in pool])
    n_match = 0
    for p in pool:
        px, chg, ts = q_pool.get(p["code"], (None, None, ""))
        match = (px is not None and abs(px - p["price"]) < 0.005
                 and ts[:8] == "20261103")
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
              f"{'✅胜大盘(-1.24%)' if chg > MK_AVG else '❌弱于大盘'}")
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
                   "yesterday_review": {"source": "11-03 早盘深度池 Top5 (4e27c99)",
                                        "verified_on": BASE_DATE,
                                        "n_beat_mkt": n_beat, "n_positive": n_pos,
                                        "results": review},
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
                  f"仓位{snap['position_ratio']*100:.0f}%/{snap.get('reason') or '⚠️停止交易'}; "
                  f"先例 10-27/10-28/10-30/10-31 冰点短路 → 无东财污染)")
        else:
            print(f"\n🏁 0 推荐 → 不创建东财组合 (无标的满足铁律)")
    print(f"JSON: {OUT_JSON}")


if __name__ == "__main__":
    main()

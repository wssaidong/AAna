#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-11-19 (周四交易日盘前 08:3x) — 情绪 63 回暖 · 仓位 70% · 候选池 4 只
当日报告 = reports/2026-11-19-选股报告.md (11-19 08:02:07 盘前版, 涨跌幅=昨收=11-18 周三收盘口径)
候选池 = 当日报告 Top10 表全部 4 只 (600690 海尔智家 / 600483 福能股份 / 001379 腾达科技 /
         002983 芯瑞达, 11-18 收盘 +1.35~+1.92% 全正, 报告综合分 65x2+64x2;
         裸日期组 20261119 gid=2036 今晨空占位组 严禁触碰; ⚠️ 与 11-18 裸日期组 20261118
         gid=2031 持仓完全同池 4 只 — cron 11-18 早盘筛选同源, 连续性披露)
方法: 复用 deep_analysis_20261022 评分引擎 (技术50% + 基本面30% + 估值20%)
      + 估值面失真修正 v1 (10-28 PM 规则: 最新单季归母转亏 且 净利同比<-50% → PE 记 0 只留 PB)
      腾讯行情(盘前=11-18 收盘冻结口径) + 腾讯日K(120d qfq, 末日 11-18) + akshare 财务摘要
      + 东财 f127/sina 行业双源核验 + rec_tuning 板块胜率 (121 键 450 笔 50.0%, 11-18 20:00 更新)
铁律: 最值得购买者需基准交易日 11-18 当日胜出 (强于大盘平均 +0.33% 且正盈利) + 深度评级 ≥增持(65)
      + 未破报告软止损 + 守卫放行 (63 回暖/仓位 70% ≥10% → 放行)
链路语境: 11-17 尾盘腿重启 → 11-18 两腿齐发 (AM Top1 宁波银行 002142 89.0 买入 → 20261118ZZ
      gid=2016, T+0 判决今日以 11-18 收盘执行; PP 组实持鄂尔多斯 600295 gid=2026, 同判);
      今日情绪 40→63 大幅回暖 (回暖带正常交易), 池缩容 10→4 只
今日热点错位披露: 报告「热点板块」字段=「数据获取中」(热点源加载失败) + 热点主线表仍为
      「2026年4月」陈旧静态文案 (连续第 4 日) → 热点关联度无法计算, 记 0 命中并降权披露
Kimi: 本机无 kimi CLI / moonshot key (连续第 36 日) — 由 AAna 引擎 + LLM 定性层执行
东财: 依铁律合格池 Top1 → 20261119ZZ (先例: 仅 Top1 入组); 裸日期 20261119 (gid=2036 空占位) 严禁触碰;
      昨日 20261118ZZ (gid=2016) / 20261118PP (gid=2026) / 20261118 (gid=2031) 不动;
      创建后必须 gid∉当日占用集 防御校验
"""
import sys, os, json, re, time
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import data_sources as ds
from deep_analysis_20261022 import tech_score, fund_score, val_score, rating_of

TODAY = "2026-11-19"
BASE_DATE = "2026-11-18"   # K 线末日 / 昨收基准 (11-18 周三收盘)
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
TODAY_REPORT = os.path.join(REPORT_DIR, f"{TODAY}-选股报告.md")  # 今日 08:02:07 盘前版
OUT_JSON = os.path.expanduser(f"~/code/AAna/data/deep_analysis_{TODAY.replace('-', '')}.json")
YDAY_AM_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_20261118.json")
YDAY_PM_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_pm_20261118.json")
MK_AVG = 0.33             # 报告快照: 大盘平均涨跌 +0.33% (11-18 收盘基准)
SH_CLOSE = 0.09           # 上证 +0.09% 收 3587.83 (11-18 收盘基准)
SNAP = {"score": 63, "label": "回暖", "zt_count": 42, "dt_count": 4, "position": 0.70}
HOT_SECTORS = []          # 报告「热点板块」=「数据获取中」(热点源加载失败), 陈旧 4月表不采信
RUN_ID = "01a1f136-6cb9-7256-863f-96cb66d14dd7"
GROUPS_FILE = os.path.expanduser(
    "~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json")

# 行业 (双源 runtime 核验 11-19 08:3x; stat_key → rec_tuning sector_stats 121 键 450 笔) 映射
SECTOR_MAP = {
    "600690": ("家电-白电全球龙头 (冰箱/洗衣机份额全球第一+暖通+大健康产业)",
               None,
               [("小家电", "邻键-小家电(100% 6/6 非白电仅参照)")],
               "冷启动预期: 白电/家电类键不在板块胜率库 (11-18 格力同先例)"),
    "600483": ("电力-福建风电+火电+热电联产 (新能源运营商)",
               "火电", [("热电", "邻键-热电(100% 1/1 薄样本)")], None),
    "001379": ("机械基础件-高强度紧固件龙头 (风电/核电/汽车高端紧固件+出海)",
               "机械基础件",
               [("其它通用机械", "邻键-其它通用机械(100% 2/2 薄样本)"),
                ("通用机械", "邻键-通用机械(0% 0/1 薄样本)")], None),
    "002983": ("光学光电子-LED 背光模组+车载显示 (Mini LED 背光+智能座舱显示)",
               "显示器件",
               [("LED", "邻键-LED(100% 1/1 薄样本)"),
                ("光学元件", "邻键-光学元件(50% 2/4)"),
                ("电子零部件制造", "邻键-电子零部件制造(75% 3/4)")], None),
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
    """P0 冰点守卫 (单一真源 check_ice_point_guard)。盘前未开盘: live 源 (ths) = 11-18 收盘口径,
    以报告快照 63 回暖为判定口径 (11-18 收盘情绪 → 11-19 盘前延续)"""
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
    """腾讯实时快照: 盘前=昨收(11-18 收盘)口径。返回 {code: (现价, 涨跌幅%, 快照时间戳, 昨收)}"""
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
    """东财 groups.json 只读预检: 20261119* 占用 (裸日期空占位组 gid=2036 + 预期无 ZZ)。"""
    try:
        with open(GROUPS_FILE) as f:
            hist = json.load(f)
        hits = {k: v.get("gid") for k, v in hist.items() if k.startswith("20261119")}
        latest = max((int(v.get("gid", 0)) for v in hist.values()
                      if str(v.get("gid", "")).isdigit()), default=None)
        return hits, latest, len(hist)
    except Exception as e:
        return {"error": str(e)[:60]}, None, 0


def main():
    print("=" * 78)
    print(f"AAna 深度分析 — {TODAY} (周四交易日盘前, 数据基准 {BASE_DATE} 收盘)")
    print(f"Run: autopilot ca411dd3 深度分析 {RUN_ID}")
    print("=" * 78)

    # ---- 报告确认 (autopilot 强制: 打印报告名称防错) ----
    sz = os.path.getsize(TODAY_REPORT)
    mt = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(TODAY_REPORT)))
    print(f"📄 当日报告: {TODAY_REPORT}")
    print(f"   → 存在 | 大小: {sz} 字节 | 修改: {mt} (今日 08:02:07 盘前版, '涨跌幅'=昨收=11-18 收盘口径)")
    text = open(TODAY_REPORT).read()
    pool = parse_top10_full(text)
    raws = raw_row_count(text)
    print(f"   当日 Top10 表: {len(pool)} 只 (原始数据行 {len(raws)} 行) → 候选池 = {len(pool)} 只 "
          f"(标题「Top 10」实际仅 4 行, 全部进入深度评分; 与 11-18 裸日期组 20261118 gid=2031 完全同池)")
    for p in pool:
        print(f"     #{p['rank']} {p['code']} {p['name']} ¥{p['price']} {p['chg']:+.2f}% "
              f"报告分{p['v24']} 技术分{p['tech']} 软止损{p['stop']}")
    print(f"   报告快照 (= 11-18 周三收盘口径): 情绪{SNAP['score']}({SNAP['label']}) "
          f"仓位{SNAP['position']*100:.0f}% 大盘平均{MK_AVG:+.2f}% 涨停{SNAP['zt_count']}/跌停{SNAP['dt_count']} "
          f"上证{SH_CLOSE:+.2f}% 收3587.83 交易建议✅正常交易 | 热点: {('/'.join(HOT_SECTORS) or '数据获取中(缺失)')}")
    print("   ⚠️ 报告异常披露: ① 「热点板块」字段=「数据获取中」(热点源加载失败, 热点关联度无法计算); "
          "② 热点主线表标注「2026年4月」陈旧静态文案 (AI算力/人形机器人/半导体设备, 连续第 4 日同病灶); "
          "③ 基金推荐/模拟仓区块正常")
    print("   链路状态: 11-17 尾盘腿重启建仓 → 11-18 两腿齐发 (AM Top1 宁波银行 002142 89.0 买入 → "
          "20261118ZZ gid=2016; PP 组实持鄂尔多斯 600295 gid=2026) → 今日情绪 40→63 大幅回暖, "
          "池缩容 10→4 只, 全池延续温和带")

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
              f"is_ice_point={live['is_ice_point']} (ths 源盘前=11-18 收盘口径, 披露用)")
    ice = snap["is_ice_point"] and (live["is_ice_point"] if live else True)
    print(f"   判定: {'❄️ 冰点短路' if ice else '✅ 守卫放行 (63 回暖/仓位 70% ≥10%, 回暖带正常交易语境)'}")

    # ---- 昨日 (11-18) 两腿复核 (T+0 判决: 11-18 收盘口径) ----
    print(f"\n=== 昨日 (11-18) 两腿复核 (T+0 判决, 基准=大盘平均 {MK_AVG:+.2f}%, 11-18 收盘) ===")
    am_pool = load_yday_pool(YDAY_AM_JSON) if os.path.exists(YDAY_AM_JSON) else []
    pm_pool = load_yday_pool(YDAY_PM_JSON) if os.path.exists(YDAY_PM_JSON) else []
    rev_q = tencent_quotes(list(dict.fromkeys([r["code"] for r in am_pool]
                                              + [r["code"] for r in pm_pool]))) \
        if (am_pool or pm_pool) else {}

    def judge_leg(pool, tag):
        rev = []
        for r in pool:
            px, chg, ts, prev = rev_q.get(r["code"], (None, None, "", None))
            rev.append({**r, "close": px, "chg_pct": chg, "quote_ts": ts,
                        "beat_mkt": (chg is not None and chg > MK_AVG),
                        "pos": (chg is not None and chg > 0),
                        "pnl_vs_entry": (round((px / r["entry"] - 1) * 100, 2) if px else None),
                        "stop_broken": (r["stop"] is not None and px is not None and px < r["stop"])})
        rev.sort(key=lambda x: (x["chg_pct"] if x["chg_pct"] is not None else -99), reverse=True)
        for i, r in enumerate(rev, 1):
            print(f"{tag}{i}. {r['code']} {r['name']} 深度{r['total']}{r['rating']} [{r['sector']}]"
                  f" | 11-18 收盘 {r['chg_pct']:+.2f}% "
                  f"({'✅胜大盘' if r['beat_mkt'] else '❌弱于大盘'} {'✅正盈利' if r['pos'] else '❌负'})"
                  f" | vs 入场参考 ¥{r['entry']} → {r['pnl_vs_entry']:+.2f}%"
                  f"{' 🔴破软止损' + str(r['stop']) if r['stop_broken'] else ''}")
        gw = sum(1 for r in rev if r.get("beat_mkt"))
        gp = sum(1 for r in rev if r.get("pos"))
        print(f"{tag}池汇总: 胜大盘({MK_AVG:+.2f}%) {gw}/{len(rev)} | 正盈利 {gp}/{len(rev)}")
        return rev, gw, gp

    am_rev, am_gw, am_gp = [], 0, 0
    if am_pool:
        print(f"早盘腿: deep_analysis_20261118.json 池 {len(am_pool)} 只 "
              f"(Top1 宁波银行 002142 89.0 买入 → 20261118ZZ gid=2016)")
        am_rev, am_gw, am_gp = judge_leg(am_pool, "AM")
        zz = next((r for r in am_rev if r["code"] == "002142"), None)
        if zz:
            print(f"🏁 昨早盘 ZZ 实持 宁波银行 002142 T+0 判决: 11-18 收盘 {zz['chg_pct']:+.2f}% "
                  f"vs 大盘 {MK_AVG:+.2f}% → 超额 {(zz['chg_pct'] or 0)-MK_AVG:+.2f}pp "
                  f"{'✅ 当日胜出+正盈利' if (zz['beat_mkt'] and zz['pos']) else '❌ 未同时满足'} "
                  f"(vs 入场参考 ¥{zz['entry']} → {zz['pnl_vs_entry']:+.2f}%; 软止损 {zz['stop']} "
                  f"{'🔴已破' if zz['stop_broken'] else '未破'})")
    else:
        print("早盘腿: deep_analysis_20261118.json 不存在 → N/A")
    pm_rev, pm_gw, pm_gp = [], 0, 0
    if pm_pool:
        print(f"尾盘腿: deep_analysis_pm_20261118.json 池 {len(pm_pool)} 只 "
              f"(PP 组 gid=2026 实持 鄂尔多斯 600295, 入场 15.03)")
        pm_rev, pm_gw, pm_gp = judge_leg(pm_pool, "PM")
        pp = next((r for r in pm_rev if r["code"] == "600295"), None)
        if pp:
            print(f"🏁 昨尾盘 PP 实持 鄂尔多斯 600295 T+0 判决: 11-18 收盘 {pp['chg_pct']:+.2f}% "
                  f"vs 大盘 {MK_AVG:+.2f}% → 超额 {(pp['chg_pct'] or 0)-MK_AVG:+.2f}pp "
                  f"{'✅ 当日胜出+正盈利' if (pp['beat_mkt'] and pp['pos']) else '❌ 未同时满足'} "
                  f"(vs 入场参考 ¥{pp['entry']} → {pp['pnl_vs_entry']:+.2f}%; 软止损 {pp['stop']} "
                  f"{'🔴已破' if pp['stop_broken'] else '未破'})")
    else:
        print("尾盘腿: deep_analysis_pm_20261118.json 不存在 → N/A")

    # ---- 价格真实性双重校验 (报告价 vs 腾讯快照, 盘前腿口径) ----
    print(f"\n=== 价格真实性双重校验 (报告价 vs 腾讯快照, 11-18 收盘口径) ===")
    q_pool = tencent_quotes([p["code"] for p in pool])
    n_match = 0
    for p in pool:
        px, chg, ts, prev = q_pool.get(p["code"], (None, None, "", None))
        match = (px is not None and abs(px - p["price"]) < 0.005 and ts[:8] == "20261118")
        n_match += bool(match)
        print(f"   {p['code']} {p['name']}: 报告 ¥{p['price']} vs 快照 ¥{px} ({ts[:8]}) "
              f"{'✅一致' if match else '⚠️不一致'}")
    print(f"   一致性: {n_match}/{len(pool)} → {'判定数据真实, 放行深度评分' if n_match == len(pool) else '存在不一致, 结果需谨慎'}")

    # ---- baseline 自查 (涨幅约束 + 热点错位) ----
    chgs = [p["chg"] for p in pool]
    print(f"\n=== baseline 涨幅约束自查 ===")
    print(f"   今日池 11-18 涨幅带: +{min(chgs):.2f}% ~ +{max(chgs):.2f}% | >5% 追高标的: "
          f"{sum(1 for c in chgs if c > 5)} 只 | >7%: {sum(1 for c in chgs if c > 7)} 只 "
          f"→ {'✅ 全池温和带 (<5%), 无追高约束违例' if max(chgs) <= 5 else '⚠️ 存在追高标的, 需人工复核'}")
    print(f"   池 11-18 全部正盈利且胜大盘: "
          f"{'✅ ' + str(len(pool)) + '/' + str(len(pool)) + ' (vs 大盘平均 +0.33%)' if min(chgs) > 0 and min(chgs) > MK_AVG else '⚠️ 存在未胜出标的'}")

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
          f"20261119* 占用: {occ} (裸日期 gid=2036 为今晨空占位组, 严禁触碰; ZZ 预期未占用; "
          f"昨日 20261118ZZ gid=2016 / 20261118PP gid=2026 / 20261118 gid=2031 不动)")

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
                   "report_anomalies": ["「热点板块」字段=「数据获取中」(热点源加载失败, 热点关联度无法计算)",
                                        "热点主线表标注「2026年4月」陈旧静态文案 (连续第 4 日同病灶)"],
                   "overall_win_rate": overall_wr, "total_records": n_rec,
                   "sector_count": len(sector_stats), "rec_tuning_generated_at": rt_gen,
                   "nds_tuning": {"score_threshold": nds.get("score_threshold"),
                                  "cold_sectors": cold_l, "weak_sectors": weak_l},
                   "price_check_match": n_match,
                   "baseline_check": {"chg_min": min(chgs), "chg_max": max(chgs),
                                      "n_gt5": sum(1 for c in chgs if c > 5),
                                      "n_gt7": sum(1 for c in chgs if c > 7)},
                   "yesterday_review": {
                       "am_leg": {"source": "deep_analysis_20261118.json 早盘池 10 只",
                                  "zz_holding": "002142 宁波银行 89.0 买入 (20261118ZZ gid=2016)",
                                  "judged_on": BASE_DATE,
                                  "n_beat_mkt": am_gw, "n_positive": am_gp,
                                  "results": am_rev},
                       "pm_leg": {"source": "deep_analysis_pm_20261118.json 尾盘池 5 只",
                                  "pp_holding": "600295 鄂尔多斯 (20261118PP gid=2026)",
                                  "judged_on": BASE_DATE,
                                  "n_beat_mkt": pm_gw, "n_positive": pm_gp,
                                  "results": pm_rev}},
                   "recommend": ({"code": recommend["code"], "name": recommend["name"],
                                  "total": recommend["total"], "rating": recommend["rating"],
                                  "stop": recommend["stop"], "target": recommend["target"]}
                                 if recommend else None),
                   "eligible_pool": [{"code": r["code"], "name": r["name"], "total": r["total"],
                                      "rating": r["rating"]} for r in eligible],
                   "eastmoney_sync": {"action": "create_zz_if_recommend",
                                      "group_name": f"{TODAY.replace('-', '')}ZZ",
                                      "precheck_20261119_occupied": occ,
                                      "reason": (f"铁律合格池 Top1 {recommend['code']} {recommend['name']} "
                                                 f"({recommend['total']} {recommend['rating']}) → 仅 Top1 入组"
                                                 if recommend else "铁律合格池空 → 不建组")},
                   "results": results}, f, ensure_ascii=False, indent=1)

    print(f"\n=== 深度排名 (技术50%+基本面30%+估值20%) ===")
    for i, r in enumerate(results, 1):
        print(f"{i}. {r['code']} {r['name']} 综合 {r['total']} {r['rating']} "
              f"(技{r['tech_score']}/基{r['fund_score']}/估{r['val_score']}) | 11-18 实收 {r['chg_pct']:+.2f}% "
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

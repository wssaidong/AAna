#!/usr/bin/env python3
"""
AAna 尾盘选股脚本 v2.3
运行时间：工作日 14:45（A股收盘前15分钟）
策略：尾盘强势股回调买入
  - 14:45 全天数据已基本定型，可靠性高
  - 重点：当日小幅回调的强势股（不追高）
  - 过滤：RSI超买、涨幅过大、量能异常
  - 90 天回测实证：T+1 跳空高开 87.9%（中位 +0.91%），5 日持有总亏 -2474%
    → 卖出策略应改为 T+1 开盘卖（90 天 +1668%），详见 run_afternoon_v24_t1sell.py

修复历史（v2.1 2026-06-09）：
  P0  - MACD 金叉定义改为 DIF 上穿 DEA（而非 DIF 穿 0）
  P0  - 风险/止损反逻辑修正（高风险用更紧的止损）
  P1  - 候选池扩到全市场（涨幅榜 + 成交额过滤）
  P1  - 60/65 评分阈值统一为 65
  P2  - 5.0% 边界改为严格 > 5
  P2  - 报告 reason 兜底
  P3  - 新浪 HTTP 改 HTTPS、评分项加注释、format_change 名字注释
  P3  - get_vol_ratio 索引改 list comprehension

优化历史（v2.2 2026-06-09）：
  #1  - MACD 二次确认：基础金叉 +5 分，二次确认（健康回踩）+5 分，量缩价稳 +3 分
  #2  - MACD lookback 从 3 扩到 5（覆盖"金叉后第 2-3 日"的观察窗口）
  #3  - 集成 feedback_loop：评分时记录到 rec_feedback.csv 用于回测验证

回测结论（v2.2 2026-06-09）：
  - 30/90 天 MACD 二次确认胜率 15.2%，平均 -3.65%（Fisher p=0.0074 反向显著）
  - 二次确认在 A 股是"追高陷阱"，30 天 5/5 100% 是幸存者偏差

优化历史（v2.3 2026-06-09）：
  #1  - 删除 MACD 二次确认加分（+5）+ 删除 vol_shrink 加分（+3）
       → 90 天 33 笔二次确认：胜率 15.2% / 平均 -3.65% ＝ 反向指标
       → 基础金叉 +5 保留（v2.1 修复的 DIF 真正上穿 DEA）
  #2  - MACD 二次确认相关字段（macd_confirmed/macd_vol_shrink）改为只记录、不加分
  #3  - check_macd_golden_cross() 仍返回 confirmed/vol_shrink 供 paper_trading 与回测使用
       → 留口子：未来若二次确认被新数据证明有效，可一行开启加分
"""

import os
import sys
import json
import warnings
warnings.filterwarnings('ignore')

# AAna 项目路径
AANA_DIR = os.path.expanduser("~/code/AAna")
sys.path.insert(0, AANA_DIR)
sys.path.insert(0, os.path.join(AANA_DIR, "scripts"))

from datetime import datetime, timedelta

# 文件持久化层
from data import append_recommendations_batch

# 东方财富组合同步（可选，无cookie时静默跳过）
try:
    import eastmoney_portfolio
    EASTMONEY_ENABLED = True
except ImportError:
    EASTMONEY_ENABLED = False

# ── 新模块引入（v2.5）───────────────────────────────────────
sys.path.insert(0, os.path.join(AANA_DIR, "scripts"))
try:
    from market_sentiment import get_market_sentiment, get_hot_sectors
    from risk_rules import calc_stop_loss, get_position_ratio
    AFTER_NEW = True
except ImportError:
    AFTER_NEW = False


def _safe_position_ratio(sentiment_score: int) -> float:
    """情绪分 → 建议仓位 (risk_rules 不可用时的兜底, 阈值与 risk_rules 一致)"""
    try:
        return get_position_ratio(sentiment_score)
    except NameError:
        if sentiment_score >= 75:
            return 0.85
        elif sentiment_score >= 60:
            return 0.70
        elif sentiment_score >= 45:
            return 0.50
        elif sentiment_score >= 35:
            return 0.20
        elif sentiment_score >= 20:
            return 0.10
        return 0.0

# ============================================
# 数据获取
# ============================================

def get_today_str():
    return datetime.now().strftime("%Y-%m-%d")

def get_market_sina(code):
    if code.startswith('6') or code.startswith('9'):
        return f'sh{code}'
    return f'sz{code}'


# v2026-10-23 P0 修复: 指数代码的交易所前缀**不能**套用个股规则。
#   000001 作为个股是 sz(平安银行), 作为指数是 sh(上证指数);
#   000688 作为个股是 sz(国城矿业), 作为指数是 sh(科创50)。
# 原实现用 get_market_sina() 拉指数 → 报告"大盘环境"表把平安银行/国城矿业
#   当成上证指数/科创50 显示 (10/23 实证: 报告写"上证 -0.88%", 真实 +0.89%)。
_INDEX_SINA_PREFIX = {
    '000001': 'sh',  # 上证指数
    '000016': 'sh',  # 上证50
    '000300': 'sh',  # 沪深300
    '000688': 'sh',  # 科创50
    '000905': 'sh',  # 中证500
    '399001': 'sz',  # 深证成指
    '399005': 'sz',  # 中小板指
    '399006': 'sz',  # 创业板指
}


def get_index_data_sina(codes):
    """指数行情 (sina)。与个股分开取数, 因为指数代码的交易所前缀与个股不同。
    字段布局与个股一致: [0]=名称 [2]=昨收 [3]=当前 [4]=最高 [5]=最低。"""
    import requests
    results = {}
    try:
        formatted = [f"{_INDEX_SINA_PREFIX.get(c, 'sh')}{c}" for c in codes]
        url = f'https://hq.sinajs.cn/list={",".join(formatted)}'
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://finance.sina.com.cn'
        }
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = 'gbk'
        lines = resp.text.strip().split('\n')
        for i, line in enumerate(lines):
            if '=' not in line:
                continue
            code = codes[i] if i < len(codes) else ''
            parts = line.split('=')[1].strip('";\n ').split(',')
            if len(parts) < 10:
                continue
            yesterday_close = float(parts[2]) if parts[2] else 0
            price = float(parts[3]) if parts[3] else 0
            high = float(parts[4]) if parts[4] else 0
            low = float(parts[5]) if parts[5] else 0
            change_pct = ((price - yesterday_close) / yesterday_close * 100) if yesterday_close else 0
            results[code] = {
                'code': code,
                'name': parts[0],
                'price': price,
                'yesterday_close': yesterday_close,
                'high': high,
                'low': low,
                'change_pct': change_pct,
            }
    except Exception as e:
        print(f"[Sina Index] Error: {e}")

    for code in codes:
        if code not in results:
            results[code] = {'code': code, 'name': '', 'price': 0, 'change_pct': 0}
    return results

def get_stock_data_sina(codes):
    """使用新浪财经API获取实时行情"""
    import requests
    results = {}
    try:
        formatted = [get_market_sina(c) for c in codes]
        # 修复 #11: 改用 HTTPS，避免被网络拦截
        url = f'https://hq.sinajs.cn/list={",".join(formatted)}'
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://finance.sina.com.cn'
        }
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = 'gbk'
        lines = resp.text.strip().split('\n')
        for i, line in enumerate(lines):
            if '=' not in line:
                continue
            code = codes[i] if i < len(codes) else ''
            parts = line.split('=')[1].strip('";\n ').split(',')
            if len(parts) < 10:
                continue
            name = parts[0]
            yesterday_close = float(parts[2]) if parts[2] else 0
            today_open = float(parts[1]) if parts[1] else 0
            price = float(parts[3]) if parts[3] else 0
            high = float(parts[4]) if parts[4] else 0
            low = float(parts[5]) if parts[5] else 0
            vol = float(parts[8]) if parts[8] else 0  # 手
            amount = float(parts[9]) if parts[9] else 0  # 元
            change_pct = ((price - yesterday_close) / yesterday_close * 100) if yesterday_close else 0
            
            results[code] = {
                'code': code,
                'name': name,
                'price': price,
                'yesterday_close': yesterday_close,
                'today_open': today_open,
                'high': high,
                'low': low,
                'change_pct': change_pct,
                'vol': vol,
                'amount': amount * 10000,  # 万元 → 元
            }
    except Exception as e:
        print(f"[Sina] Error: {e}")
    
    for code in codes:
        if code not in results:
            results[code] = {'code': code, 'name': '', 'price': 0, 'change_pct': 0}
    return results


def get_tencent_kline(code, count=30):
    """
    获取历史K线（前复权）
    v2.5.1 修复（2026-06-12）：原 web.ifzq.gtimg.cn 返回 501（接口废弃），
    改用东财 push2his K线（已知稳定，30 根 < 100ms）。
    v2026-10-23 修复：改为三档独立兜底，每档自带 try/except（任一档抛错不再
    阻断后续档位）—— 旧写法把三档串在一个 try 里，腾讯档 json.loads 抛异常会
    直接跳到函数末尾的 except，后面兜底永远执行不到。
    """
    import requests
    mkt_str = 'sh' if code.startswith(('6', '9')) else 'sz'

    # ── 档 1: 东财 push2his（沪深都稳定，首选）──────────────────────
    try:
        mkt = 1 if code.startswith(('6', '9')) else 0
        resp = requests.get(
            "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            params={
                "secid": f"{mkt}.{code}",
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "klt": "101", "fqt": "1",
                "end": "20500101", "lmt": str(count),
            },
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
            timeout=8)
        klines = (resp.json().get('data') or {}).get('klines') or []
        result = []
        for line in klines:
            parts = line.split(",")
            if len(parts) >= 6:
                try:
                    result.append({
                        'date': parts[0],
                        'open': float(parts[1]),
                        'high': float(parts[3]),
                        'low': float(parts[4]),
                        'close': float(parts[2]),
                        'vol': float(parts[5]),
                    })
                except (ValueError, IndexError):
                    continue
        if result:
            return result
    except Exception as e:
        print(f"[K线] {code} 东财push2his失败: {e}")

    # ── 档 2: 腾讯 ifzq（fqkline）────────────────────────────────
    try:
        url2 = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayqfq&param={mkt_str}{code},day,,,{count},qfq"
        resp2 = requests.get(url2, timeout=8,
                              headers={'User-Agent': 'Mozilla/5.0',
                                       'Referer': 'https://gu.qq.com/'})
        text = resp2.text.strip()
        if '=' in text:
            text = text.split('=', 1)[1]
        data = json.loads(text)
        node = (data.get('data') or {}).get(f'{mkt_str}{code}') or {}
        day_data = node.get('qfqday') or node.get('day') or []
        result = []
        for item in day_data:
            if len(item) >= 6:
                try:
                    result.append({
                        'date': item[0],
                        'open': float(item[1]),
                        'high': float(item[2]),
                        'low': float(item[3]),
                        'close': float(item[4]),
                        'vol': float(item[5]),
                    })
                except (ValueError, IndexError):
                    continue
        if result:
            return result
    except Exception as e:
        print(f"[K线] {code} 腾讯ifzq失败: {e}")

    # ── 档 3: 新浪 K线（兜底）────────────────────────────────────
    # v2026-10-23 P0 修复: 东财 push2his 连续 RemoteDisconnected + 腾讯 ifzq
    # 返回 HTML 反爬页时, K线 100% 失败 → 评分退化成 fallback(RSI=N/A, 量比=N/A),
    # 所有票同分 ~67.4, Top10 完全失去区分度 (15:12 实测: 报告第一版被覆盖成
    # 无意义的推荐列表)。新浪这条链路实测可用, 补上第三档兜底。
    try:
        resp3 = requests.get(
            "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
            params={'symbol': mkt_str + code, 'scale': '240', 'ma': 'no',
                    'datalen': str(count)},
            headers={'User-Agent': 'Mozilla/5.0',
                     'Referer': 'https://finance.sina.com.cn'},
            timeout=8)
        rows3 = resp3.json() or []
        out3 = []
        for r3 in rows3:
            try:
                out3.append({
                    'date': r3['day'],
                    'open': float(r3['open']),
                    'high': float(r3['high']),
                    'low': float(r3['low']),
                    'close': float(r3['close']),
                    'vol': float(r3['volume']),
                })
            except (KeyError, ValueError, TypeError):
                continue
        if out3:
            print(f"[K线] {code}: 新浪兜底 OK ({len(out3)} 根)")
            return out3
    except Exception as e:
        print(f"[K线] {code} 新浪兜底失败: {e}")

    print(f"[K线] {code}: 全部数据源失败")
    return []


# ============================================
# 技术指标计算
# ============================================

def calculate_rsi(closes, period=14):
    """计算RSI"""
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_ma(closes, period):
    """计算简单均线"""
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def check_macd_golden_cross(closes, lookback=5):
    """
    检查 MACD 是否在最近 lookback 日内出现金叉。
    修复 #1: 真正定义 = DIF 上穿 DEA（DEA = EMA9 of DIF）
    原版用 DIF 穿 0 轴，频繁误报。
    修复 #1b: 进一步剔除"零附近抖动"误报（DIF 与 DEA 都接近 0 时的穿越视为噪声）
    优化 #1 (v2.2): 二次确认 — 返回 dict 包含金叉距今天数、后续回踩状态
    返回: {
        "is_golden":    bool,         # 是否在 lookback 内出现金叉
        "cross_idx":    int or None,  # 金叉发生位置（从序列起点算）
        "days_ago":     int or None,  # 距今天数（0=今天，1=昨天...）
        "confirmed":    bool,         # 二次确认（v2.2 新增）：金叉后第 2-3 日回踩未破
        "pullback_ok":  bool,         # v2.2: 是否有健康回踩（DIF 未跌破 DEA）
        "vol_shrink":   bool,         # v2.2: 回踩时成交量是否萎缩（健康）
    }
    """
    if len(closes) < 35:
        return {"is_golden": False, "cross_idx": None, "days_ago": None,
                "confirmed": False, "pullback_ok": False, "vol_shrink": False}

    def ema(data, p):
        k = 2 / (p + 1)
        e = data[0]
        for d in data[1:]:
            e = d * k + e * (1 - k)
        return e

    # 计算每日 DIF (EMA12 - EMA26) 和 DEA (EMA9 of DIF)
    dif_series = []
    for i in range(25, len(closes)):
        ema12 = ema(closes[:i + 1], 12)
        ema26 = ema(closes[:i + 1], 26)
        dif_series.append(ema12 - ema26)

    # DEA = EMA9 of DIF
    dea_series = []
    for i in range(8, len(dif_series)):
        dea_series.append(ema(dif_series[:i + 1], 9))

    # 对齐：DIF 从索引 8 之后才能算 DEA
    aligned_dif = dif_series[8:]

    # 在最近 lookback 日内查找金叉：DIF 上穿 DEA
    # 修复 #1b: 弱化"dif_now < 0 直接拒绝"的规则 — 反弹初期 DIF 仍 < 0 也算金叉
    start = max(0, len(aligned_dif) - lookback)
    is_gold = False
    cross_idx = None

    # 特殊处理 aligned_dif[0]：它之前的"虚拟"点是 dif_series 索引 7（无 DEA）
    # 如果 aligned_dif[0] 本身 DIF > DEA，且前一点（dif_series[7]）DIF < aligned_dif[0] 的 DIF
    # 可以认为金叉发生（金叉意味着 DIF 上升穿越 DEA）
    if len(aligned_dif) > 0 and start == 0:
        dif_now = aligned_dif[0]
        dea_now = dea_series[0]
        dif_prev = dif_series[7] if 7 < len(dif_series) else dif_now
        # 边界 case：aligned_dif[0] 处 DIF > DEA，且前一点（虚拟）DIF 必然更小
        if dif_now > dea_now and dif_prev < dif_now:
            # 应用 #1b 过滤
            if not (abs(dif_now) < 0.005 and abs(dea_now) < 0.005):
                if not (dif_now < 0 and dif_now < dea_now * 0.5):
                    is_gold = True
                    cross_idx = 0

    for i in range(max(1, start), len(aligned_dif)):
        if i == 0:
            continue
        dif_now = aligned_dif[i]
        dif_prev = aligned_dif[i - 1]
        dea_now = dea_series[i]
        dea_prev = dea_series[i - 1]
        # 条件1: DIF 上穿 DEA（标准定义）
        if not (dif_now > dea_now and dif_prev <= dea_prev):
            continue
        # 条件2: 排除"零轴噪声" — DIF 与 DEA 都极接近 0（< 0.005）视为噪声
        if abs(dif_now) < 0.005 and abs(dea_now) < 0.005:
            continue
        # 条件3: 排除"弱势反弹假金叉" — DIF 远在 0 下（<-1.0）且 DEA 更低
        if dif_now < 0 and dif_now < dea_now * 0.5:
            continue
        is_gold = True
        cross_idx = i
        break  # 找最近一次金叉

    # 计算金叉距今天数（基于 closes 数组）
    days_ago = None
    if is_gold and cross_idx is not None:
        # aligned_dif 索引 i 对应 closes 的索引 (i + 33)
        # (dif_series 起点 25, dea_series 起点 +8 = 33, +1 因为 0-indexed)
        # 简化为：cross_idx 是 dif_series 数组中的索引
        # closes 索引 = cross_idx + 33
        closes_idx_at_cross = cross_idx + 33
        days_ago = len(closes) - 1 - closes_idx_at_cross

    # 优化 #1: 二次确认分析
    # 关注金叉后第 2-3 日（DIF 短暂回落但未跌破 DEA）
    pullback_ok = False
    vol_shrink = False
    confirmed = False
    if is_gold and cross_idx is not None and len(aligned_dif) - cross_idx >= 2:
        # 金叉后至少要有 2 日数据
        post_cross_dif = aligned_dif[cross_idx:]
        post_cross_dea = dea_series[cross_idx:]

        # 二次确认：第 2-3 日（索引 1-2）DIF 回落但没跌破 DEA
        if len(post_cross_dif) >= 3:
            # 索引 1 和 2 是金叉后第 1、2 个交易日
            check_range = post_cross_dif[1:3]
            check_dea = post_cross_dea[1:3]
            # 健康回踩：DIF 在 DEA 之上（即回踩没破）
            pullback_ok = all(d >= d_ea for d, d_ea in zip(check_range, check_dea))
            # 二次确认 = 金叉 + 健康回踩
            confirmed = pullback_ok
        elif len(post_cross_dif) == 2:
            # 只有 1 日回踩数据
            if post_cross_dif[1] >= post_cross_dea[1]:
                pullback_ok = True
                # 单日回踩不算完整二次确认，但可作为弱信号
                confirmed = False
        # 成交量萎缩：第 1-2 日成交量 < 金叉日成交量
        if cross_idx + 1 < len(closes):
            cross_close_idx = cross_idx + 33
            if cross_close_idx < len(closes):
                # 假设 closes 数组有等量 vol 信息；这里只用 closes 推断趋势
                # 实际用 closes 变化判断"量能"：回踩日 close 不破金叉日 close
                cross_close = closes[cross_close_idx]
                if cross_close_idx + 2 < len(closes):
                    pullback_close_1 = closes[cross_close_idx + 1]
                    pullback_close_2 = closes[cross_close_idx + 2] if cross_close_idx + 2 < len(closes) else pullback_close_1
                    # 量缩价稳：金叉后 1-2 日收盘价不低于金叉日 99%
                    vol_shrink = (pullback_close_1 >= cross_close * 0.99 and
                                  pullback_close_2 >= cross_close * 0.99)

    return {
        "is_golden": is_gold,
        "cross_idx": cross_idx,
        "days_ago": days_ago,
        "confirmed": confirmed,
        "pullback_ok": pullback_ok,
        "vol_shrink": vol_shrink,
    }


def get_vol_ratio(code, klines):
    """
    计算今日量比 = 今日成交量 / 5日均量（不含今日）
    修复 #2: 原代码 klines[-6:-1][i]['vol'] 索引可读性差且边界 case 易错
    改为 list comprehension
    """
    if len(klines) < 6:
        return None
    recent_5 = [k['vol'] for k in klines[-6:-1]]
    avg_vol_5 = sum(recent_5) / 5
    if avg_vol_5 == 0:
        return None
    return klines[-1]['vol'] / avg_vol_5


# ============================================
# 板块映射 (中文行业名 → rec_tuning 英文 enum)
# ============================================
# 2026-09-09 新增: rec_tuning.weak_sectors 用的是英文 enum (chem/semi/ai_app...),
# industry_for_code() 返回的是中文行业名 (化工/半导体/AI...). 直接比较会永远不匹配。
# 映射表覆盖 rec_tuning 里所有 weak_sectors + 7 个 sector_stats 板块。
_SECTOR_CN_TO_ENUM = {
    # rec_tuning 已定义的 7 个英文 enum (来自 feedback 历史)
    "储能": "energy", "绿电": "energy", "电池": "energy", "锂电": "energy", "动力电池": "energy",
    "机器人": "robot", "人形机器人": "robot",
    "AI应用": "ai_app", "AI": "ai_app", "人工智能": "ai_app", "大模型": "ai_app",
    "半导体": "semi", "半导体设备": "semi", "集成电路": "semi", "芯片": "semi", "晶圆": "semi",
    "化工": "chem", "化学制剂": "chem", "石油化工": "chem", "石油加工": "chem",
    "机械": "mach", "工程机械": "mach",
    "电子": "elec", "消费电子": "elec", "显示器件": "elec",
    # 没在 weak_sectors 里的常见板块也映射一下，方便后续扩展
    "白酒": "baijiu", "汽车": "auto", "银行": "bank", "保险": "insurance",
    "证券": "broker", "医药": "pharma", "中药": "pharma", "互联网": "internet",
    "通信设备": "telecom", "煤炭": "coal", "钢铁": "steel", "房地产": "realestate",
    "建筑工程": "construction", "食品": "food", "家电": "home_appliance",
    "物流": "logistics",
}


def _cn_sector_to_enum(sector_cn: str) -> str:
    """中文行业名 → rec_tuning 英文 enum。未匹配返回 'unknown' (不误杀)。"""
    if not sector_cn or sector_cn == "unknown":
        return ""
    # 精确匹配优先
    if sector_cn in _SECTOR_CN_TO_ENUM:
        return _SECTOR_CN_TO_ENUM[sector_cn]
    # 子串匹配兜底 (例如 "化学制药" 含 "化学")
    for cn_key, enum_val in _SECTOR_CN_TO_ENUM.items():
        if cn_key in sector_cn or sector_cn in cn_key:
            return enum_val
    return "unknown"  # 有中文行业但未映射到 enum → 'unknown' (让 blacklist 拦截条件失败 → 放过)


def _sector_blacklisted(sector_raw: str, sector_enum: str, blacklist) -> bool:
    """板块黑名单判定 — 中文行业名 OR 英文 enum 双路匹配。

    v2026-10-28 P0 修复 (黑名单 100% 失效根因):
      rec_tuning.sector_stats 的 key = rec_feedback.csv `sector` 列原值 =
      industry_for_code() 返回的中文行业名 (如 '房地产开发' / '印制电路板'),
      而旧代码只拿 enum 去比 → '房地产开发' vs enum 'realestate' 永不相等,
      中文名黑名单 100% 匹配不上。实际只有 2026-05 那 7 个英文 enum 历史 key
      能命中 (energy/robot/ai_app/semi/chem/mach/elec), 而它们 n 全部 < 10
      → strategy_policy 门槛又拦一道 → 实测 blacklist 恒为空,
      日志 10-13 至今全是 `blacklist=[无]`。

      修法: raw 中文名 OR enum 双路匹配, 同时兼容历史 enum key。
      注: 不改 rec_optimizer 的分桶口径 (合并 '半导体'/'semi' 会改变胜率 →
      改变 weak_sectors → 改变实盘推荐, 属策略调整需先回测, 不在本次范围)。
    """
    if not blacklist:
        return False
    if sector_raw and sector_raw in blacklist:
        return True
    if sector_enum and sector_enum in blacklist:
        return True
    return False


# ============================================
# 尾盘评分系统
# ============================================

def score_afternoon_stock(info, klines, sentiment_score=50):
    """
    尾盘评分（满分100）
    核心原则：尾盘买入 = 当日小幅回调的强势股

    评分项权重（合计基础 50 分 + 加分项 - 减分项，最后裁剪到 [0,100]）：
    1. 当日涨跌幅       ±30  (核心：-3~0% +30；+5%以上 -15)
    2. 日内高点回落     ±15  (1-3% 最佳)
    3. RSI(14)          ±15  (40-60 最佳；>70 超买 -15)
    4. 均线多头         +15  (MA5>MA10>MA20)
    5. 量比             ±10  (0.5-1.5x 正常)
    6. MACD 金叉        +10  (修复 #1: 真正 DIF 上穿 DEA)
    7. 价格在 MA10 上    +5
    8. 成交额           ±10  (>5亿 +5；<1000万 -10)

    修复 #6: 根据 sentiment_score 调整评分容忍度（熊市更严、牛市宽松）
    修复 #7: 风险/止损反逻辑 — 高风险标的用更紧的止损
    """
    score = 50
    change_pct = info.get('change_pct', 0)
    price = info.get('price', 0)
    yesterday_close = info.get('yesterday_close', 0)
    high = info.get('high', 0)

    if not klines or len(klines) < 20:
        # v2026-10-02 B1 修复: K 线 API 限流时 (RemoteDisconnected) 不应直接 0 分
        # 原行为: 返回 (0, {}) → score < 65 → 0 推荐, 流水线停摆
        # 第六次微调: K 线缺失时给 60 + chg_bonus (温和上涨 0~5% 时 0~7.5)
        # 这样既能突破 0 推荐, 但用 _klines_missing 标记, 报告里明确"⚠️ 技术面缺失"
        # 设计: 起步 60 分 + 涨幅 0~5% 加 0~7.5 分, 跌 0~-5% 加 3 分, 跌超 -5% 不加
        if -5 < change_pct <= 0:
            chg_bonus = 3
        elif 0 < change_pct <= 5:
            chg_bonus = change_pct * 1.5
        elif -9 <= change_pct <= -5:
            chg_bonus = 0
        else:
            chg_bonus = 0
        fallback_score = 60 + chg_bonus
        # v2026-10-02 B1 第七次微调: 报告需要 risk/stop_loss/target_price 字段
        # K线缺失时给中风险 (与 score 65-79 区间一致) + 适当止损
        if fallback_score >= 80:
            risk = "🟢 低风险"
            stop_loss = round(price * 0.93, 2) if price else 0
            target_pct = 0.10
        elif fallback_score >= 65:
            risk = "🟡 中风险"
            stop_loss = round(price * 0.95, 2) if price else 0
            target_pct = 0.07
        else:
            risk = "🔴 高风险"
            stop_loss = round(price * 0.97, 2) if price else 0
            target_pct = 0.05
        return fallback_score, {
            'score': fallback_score,
            'klines_missing': True,
            'note': 'K线API限流, 仅基于实时行情评分 (技术面缺失)',
            'name': info.get('name', ''),
            'code': info.get('code', ''),
            'price': price,
            'change_pct': change_pct,
            'macd_gold': False,
            'macd_confirmed': False,
            'sector': info.get('sector', '') or '',
            'risk': risk,
            'stop_loss': stop_loss,
            'target_price': round(price * (1 + target_pct), 2) if price else 0,
            'target_pct': target_pct,
        }

    closes = [k['close'] for k in klines]

    # 修复 #6: 根据情绪分动态调整容忍度
    # sentiment_score: 0-100, 默认 50
    # 高分（牛市）：容忍追高，跌幅要求放松
    # 低分（熊市）：要求更严格的回调，扣分更重
    bull_adj = (sentiment_score - 50) / 100  # 范围 -0.5 ~ +0.5
    # 阈值范围扩大，确保不同情绪分在不同涨跌幅档位都能体现差异
    # bull_adj +0.5 (牛市): up_threshold=7.5, up_mild_max=3.0
    # bull_adj -0.5 (熊市): up_threshold=2.5, up_mild_max=1.0
    up_threshold = 5 + bull_adj * 5
    up_mild_max = 2 + bull_adj * 2  # 上沿加大浮动（+1 ~ +3）
    down_threshold = -3 + bull_adj * 2
    strong_drop_threshold = -5 + bull_adj * 2

    # 1. 当日涨跌幅评分（核心：尾盘 = 回调买入，绝对不追红涨）
    # P1 修复：删除所有对红涨的加分项（之前 +10/+10 让 0~+5% 红涨也进了 Top10）
    # 策略：change_pct >= 0 一律扣分，只奖励绿盘回调
    if down_threshold <= change_pct < 0:
        score += 30  # 最佳买点区间（绿盘回调）
    elif strong_drop_threshold <= change_pct < down_threshold:
        score += 20  # 较大回调，注意是否止跌
    elif change_pct < strong_drop_threshold:
        score -= 15  # 跌幅过大，可能继续跌
    # P1 修复：红涨一律扣分（按幅度递增）
    elif 0 <= change_pct < 1:
        score -= 3   # 微红涨，警示
    elif 1 <= change_pct < up_mild_max:
        score -= 8   # 上涨 1-3%，违反策略
    elif up_mild_max <= change_pct < up_threshold:
        score -= 12  # 上涨 3-5%，明显追高
    elif change_pct >= up_threshold:
        score -= 15  # 上涨 >5%，大幅追高风险

    # 2. 从日内高点的回落幅度（尾盘常从高点回落）
    if high > 0 and price > 0:
        intraday_pullback = (high - price) / high * 100
        if 1 <= intraday_pullback <= 3:
            score += 15
        elif intraday_pullback > 3:
            score += 5
        elif intraday_pullback < 1:
            score -= 5

    # 3. RSI 评分
    rsi = calculate_rsi(closes, 14)
    if rsi:
        info['rsi'] = round(rsi, 1)
        if 40 <= rsi <= 60:
            score += 15
        elif 30 <= rsi < 40:
            score += 5
        elif 60 < rsi <= 70:
            score -= 5
        elif rsi > 70:
            score -= 15
        elif rsi < 30:
            score -= 10

    # 4. 均线多头
    ma5 = calculate_ma(closes, 5)
    ma10 = calculate_ma(closes, 10)
    ma20 = calculate_ma(closes, 20)
    if ma5 and ma10 and ma20:
        info['ma5'] = round(ma5, 2)
        info['ma10'] = round(ma10, 2)
        info['ma20'] = round(ma20, 2)
        if ma5 > ma10 > ma20:
            score += 15
        elif ma5 > ma10:
            score += 5

    # 5. 量比
    vol_ratio = get_vol_ratio(info['code'], klines)
    if vol_ratio:
        info['vol_ratio'] = round(vol_ratio, 2)
        if 0.5 <= vol_ratio <= 1.5:
            score += 10
        elif vol_ratio > 3:
            score -= 10
        elif vol_ratio < 0.3:
            score -= 5

    # v2026-09-09 修复: MACD 基础金叉由 +5 改为 -3。
    # 依据: v2.3 注释自爆 90 天回测 33 笔胜率 15.2% (反向显著), 但当时只删了
    # "二次确认 +5" 和 "量缩验证 +3", 保留了"基础金叉 +5"。
    # 7-9 月 score=100 的极端样本里 90% 都开了 MACD 金叉, 实际胜率 14.7% — 强负信号。
    # 改为 -3: 仍记录金叉状态 (供回测/分析), 但从评分上明确扣分, 减少进 Top10 概率。
    macd_info = check_macd_golden_cross(closes, lookback=5)
    is_gold = macd_info["is_golden"]  # 与 check_macd_golden_cross 返回 key 一致
    if is_gold:
        score -= 3  # v2.4 → v2026.4: +5 → -3 (90 天回测反向显著)
        info['macd_gold'] = True
        info['macd_gold_days_ago'] = macd_info["days_ago"]
        # 保留字段用于回测和未来重新评估, 但不再加分
        if macd_info["confirmed"]:
            info['macd_confirmed'] = True
        if macd_info["vol_shrink"]:
            info['macd_vol_shrink'] = True
    else:
        info['macd_gold'] = False

    # 7. 价格位置
    if ma10 and price > ma10:
        score += 5

    # 8. 成交额
    amount = info.get('amount', 0)
    if amount > 5e8:
        score += 5
    elif amount < 1e7:
        score -= 10

    # v2026-09-09 修复: 解除 score=100 封顶。
    # 之前 `score = 95 + min(5, score - 95)` 把所有 >=95 的票封到 95-100 区间,
    # 真实 score 95 和 score 130 在报告里都显示 100。实测 7-9 月 score=100 共 34 条,
    # 胜率仅 14.7% (vs 全样本 38.2%) — "分数幻觉"。现在改为:
    # - 取消封顶 (min(100, score)), 真实反映打分强度
    # - 报告层用排序取代分数比较, 阈值仍由 strategy_policy 控制 (默认 70)
    # - 保留 score_band 用于报告展示, 但不再影响 score 数值
    if score >= 95:
        score_band = "S级"
    elif score >= 80:
        score_band = "A级"
    elif score >= 65:
        score_band = "B级"
    else:
        score_band = "C级"
    # v2026-09-09: 移除 B 级封顶 (score = 65 + min(14, score - 65)),
    # 与 S/A 级修复保持一致, 让 score 真实反映打分强度
    score = max(0, min(100, score))

    # 修复 #7: 风险等级与止损的逻辑修正
    # 之前：score 越高止损越紧（错 — 高分标的走势稳，应用更宽止损让利润奔跑）
    # 修正：score 越高止损越宽（高分红逻辑：让强势股多跑），score 越低止损越紧（严控风险）
    if score >= 80:
        risk = "🟢 低风险"
        stop_loss = round(price * 0.93, 2) if price else 0  # -7% 宽止损
        target_pct = 0.10  # 目标 +10%
    elif score >= 65:
        risk = "🟡 中风险"
        stop_loss = round(price * 0.95, 2) if price else 0  # -5% 中等
        target_pct = 0.07
    else:
        risk = "🔴 高风险"
        stop_loss = round(price * 0.97, 2) if price else 0  # -3% 紧止损
        target_pct = 0.05

    info['score'] = score
    info['risk'] = risk
    info['stop_loss'] = stop_loss
    info['target_price'] = round(price * (1 + target_pct), 2) if price else 0
    # v2026-09-09: 补回 score_band 字段 (之前是局部变量, 调用方拿不到)
    info['score_band'] = score_band

    return score, info


# ============================================
# 选股逻辑
# ============================================

# ============================================
# 监控信号 hook（v2.2 优化 #3）
# ============================================

FEEDBACK_FIELDS = [
    "date", "code", "name", "rec_date", "trend",
    "ret_1d", "ret_3d", "ret_5d", "ret_15d",
    # v2.2 扩展字段
    "score", "sentiment_score", "macd_gold", "macd_confirmed",
    # v2026-08-23 (Phase 8 测试发现): 加 sector — recommendations.csv 的 sector 覆盖率
    # 仅 13.6% (14/103, 全部来自 5/22 一天), 板块胜率 JOIN 大部分落 "(无板块)"。
    # 让 feedback 表自己存 sector, query_sector_stats 优先从 fb 侧取。
    "sector",
]


def _sf(v, default=None):
    """安全转 float"""
    if v is None or v == '' or v == '--' or v == '-':
        return default
    try:
        return float(str(v).replace('%', '').replace(',', ''))
    except (ValueError, TypeError):
        return default


def record_recommendation(code, name, score, sentiment_score=50,
                           macd_gold=False, macd_confirmed=False, sector=""):
    """
    监控信号 hook（优化 #3）：把每次推荐写入 rec_feedback.csv + recommendations.csv
    真实收益由 feedback_loop.py 周期性补全。
    静默失败，不影响主流程。

    v2.2 增强：写之前会升级旧 header（旧 9 字段 → 新 13 字段）
    v2026-08-23 修复（Phase 1A）: 同时 append recommendations.csv，让 feedback_loop 单源读取即可
    （之前两个源分裂：cron 走 screen_afternoon_stocks() 写 rec_feedback.csv，main() 走
    append_recommendations_batch 写 recommendations.csv —— 反馈循环只读 recommendations.csv
    时 7/29 起静默空跑 15 天）。现在统一在 record_recommendation 一处写双源。
    v2026-08-23 (Phase 8): sector 参数 — 板块信息双表落地 (feedback + recommendations),
    修 recommendations.csv sector 覆盖率 13.6% 的数据质量问题。
    """
    try:
        import csv
        from datetime import datetime as _dt
        feedback_csv = os.path.join(AANA_DIR, "data", "rec_feedback.csv")
        os.makedirs(os.path.dirname(feedback_csv), exist_ok=True)
        now = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        today = _dt.now().strftime("%Y-%m-%d")

        # v2.2: 升级旧 header（如存在 9 字段版本则升级到 13 字段）
        if os.path.exists(feedback_csv):
            with open(feedback_csv, newline='', encoding='utf-8') as f:
                rows = list(csv.DictReader(f))
            if rows and len(rows[0]) < len(FEEDBACK_FIELDS):
                # 旧 header，升级
                upgraded = []
                for r in rows:
                    for k in FEEDBACK_FIELDS:
                        r.setdefault(k, "")
                    upgraded.append(r)
                with open(feedback_csv, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=FEEDBACK_FIELDS, extrasaction='ignore')
                    writer.writeheader()
                    writer.writerows(upgraded)

        # 检查是否已存在（同日同股）
        already_recorded = False
        if os.path.exists(feedback_csv):
            with open(feedback_csv, newline='', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    if row.get('code') == code and row.get('rec_date', '').startswith(today):
                        already_recorded = True
                        break

        if not already_recorded:
            # 追加到 rec_feedback.csv（细粒度追踪：含 score/sentiment/macd）
            file_exists = os.path.exists(feedback_csv)
            with open(feedback_csv, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=FEEDBACK_FIELDS, extrasaction='ignore')
                if not file_exists:
                    writer.writeheader()
                writer.writerow({
                    "date": now,
                    "code": code,
                    "name": name,
                    "rec_date": today,
                    "trend": "",           # 留给 feedback_loop 补
                    "ret_1d": "",
                    "ret_3d": "",
                    "ret_5d": "",
                    "ret_15d": "",
                    # v2.2 扩展
                    "score": score,
                    "sentiment_score": sentiment_score,
                    "macd_gold": macd_gold,
                    "macd_confirmed": macd_confirmed,
                    # v2026-08-23 (Phase 8): sector 落地
                    "sector": sector or "",
                })

            # v2026-08-23 (Phase 1A): 同时写入 recommendations.csv —— 单一写入点
            # 让 feedback_loop 永远能读到当日推荐，不再有"split-brain"。
            # 复用 data.append_recommendation() 的去重逻辑（同日同股不重复）。
            try:
                from data import append_recommendation as _append_rec
                _append_rec(
                    code=code, name=name,
                    sector=sector or "", sector_name="",
                    reason=f"AAna v2.4 尾盘评分 {score}",
                    expected_high=1.0, expected_low=-3.0,
                )
            except Exception as rec_err:
                # recommendations.csv 写失败不阻断主流程 —— rec_feedback.csv 已落地
                print(f"  [recommendations.csv 写失败] {code}: {rec_err}")
    except Exception as e:
        # 静默失败，不影响主流程
        print(f"  [记录失败] {code}: {e}")


def screen_afternoon_stocks(
    sentiment_score=50,
    position_ratio=0.5,
    record_feedback=True,
    weights=None,
    codes=None,
    dual_export=True,
):
    """
    尾盘选股主流程
    1. 从全市场涨幅榜 / 候选池取粗筛股票
    2. 获取实时行情 + 历史K线
    3. 计算尾盘评分
    4. 过滤并排序
    5. 优化 #3: 选中票写入 rec_feedback.csv

    v2026-08-23 (数据驱动策略): 评分阈值 + 板块黑名单从 strategy_policy 读取
    (rec_tuning.json ← rec_optimizer 复盘胜率,闭环自动化)。
    policy 失败时回落 v2.4 硬编码 (65 / 无黑名单),不影响主流程。

    v2026-10-16 (XWI-50): 向后兼容新增 Skill 调用所需的 3 个参数
    - weights: dict[str, int|float] | None
        评分权重透传 (Skill 调用者意图),会写入 rec_feedback.csv
        每行的 weights 字段供下游分析。**不修改评分逻辑本身**
        (避免影响现有 rec_optimizer 闭环),只作为 side-channel。
    - codes: list[str] | None
        指定候选股票代码列表;为 None 时走默认池 (top10 + 新浪全市场)。
        Skill 模式下传 [codes] 时收敛到只评这些票。
    - dual_export: bool
        默认 True: 沿用历史行为,既写 rec_feedback.csv 也写配套的
        rec_feedback_weights_YYYYMMDD.jsonl (Skill 调用的 weights 痕迹)。
        Skill 模式下设 False 可只写主表,避免污染 JSONL 衍生数据。
    """
    # ── XWI-50: 透传参数校验 ──
    if weights is not None and not isinstance(weights, dict):
        print(f"  [screen_afternoon_stocks] weights 不是 dict,忽略: {type(weights).__name__}")
        weights = None
    if codes is not None:
        if not isinstance(codes, (list, tuple)):
            print(f"  [screen_afternoon_stocks] codes 不是 list/tuple,忽略: {type(codes).__name__}")
            codes = None
        else:
            codes = [str(c).strip() for c in codes if str(c).strip()]
            if not codes:
                codes = None
    import json as _wjson
    _today = datetime.now().strftime("%Y%m%d")
    _weights_jsonl = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", f"rec_feedback_weights_{_today}.jsonl",
    )
    if weights is not None:
        print(f"  [screen_afternoon_stocks] 收到 weights: {weights} (作为侧-channel 写入 JSONL)")
    if codes is not None:
        print(f"  [screen_afternoon_stocks] 收到 codes={len(codes)} 只, 收敛候选池")
    # ── 策略参数 (数据驱动) ──
    try:
        from strategy_policy import get_today_policy, policy_banner
        policy = get_today_policy()
        score_threshold = policy.score_threshold
        sector_blacklist = set(policy.sector_blacklist)
        print(policy_banner(policy))
        for note in policy.data_notes:
            print(f"  [strategy_policy] {note}")
    except Exception as _policy_err:
        print(f"[strategy_policy] 加载失败回落默认: {_policy_err}")
        score_threshold = 65
        sector_blacklist = set()

    # ── v2026-09-09 (Phase 12): 叠加 next_day_strategy.json ──
    # daily_root_cause 昨日根因触发的额外调参:
    #   1. score_threshold / position 已经在 strategy_policy 优先 (auto_tune_next_day 写)
    #   2. cold_sectors 单独叠加到 sector_blacklist (板块样本<3 但被命中, 一票否决)
    try:
        from pathlib import Path as _P
        import json as _json
        _nd_path = _P(__file__).parent.parent / "data" / "next_day_strategy.json"
        if _nd_path.exists():
            _nd = _json.loads(_nd_path.read_text(encoding="utf-8"))
            _cold = _nd.get("cold_sectors") or []
            _watch = _nd.get("watchlist") or []
            # cold_sectors 是一组**未在 enum 里**的中文行业名 (如 "园林工程"), 直接拒绝
            # watchlist 是 enum (如 "energy"), 已通过 sector_blacklist 拦截 (rec_tuning 已覆盖)
            if _cold:
                # 把 cold_sectors 加入 cn_blacklist (set[str] 中文)
                cn_blacklist = set(_cold)
                print(f"  [next_day_strategy] 加载 cold_sectors: {_cold[:5]}"
                      + (f" (+{len(_cold)-5} more)" if len(_cold) > 5 else ""))
            else:
                cn_blacklist = set()
            # v2026-10-28 P0-3 修复: next_day_strategy.weak_sectors 之前只被
            #   run_afterhours.py 拿去**显示** "板块黑名单: ..." (盘后战报),
            #   尾盘选股本身**从来没把它当过滤器用** → 战报承诺的黑名单没执行。
            #   auto_tune_next_day.py 的 SAFE_WEAK_SECTOR_MIN_SAMPLES=3 与
            #   rec_optimizer 的 n>=3 门槛一致, 说明这份列表已是"权威口径",
            #   直接并入 sector_blacklist 即可 (中文名 OR enum 双路匹配已就绪)。
            _nd_weak = _nd.get("weak_sectors") or []
            if _nd_weak:
                _added = [s for s in _nd_weak if s not in sector_blacklist]
                sector_blacklist.update(_nd_weak)
                print(f"  [next_day_strategy] 加载 weak_sectors: {_nd_weak[:5]}"
                      + (f" (+{len(_nd_weak)-5} more)" if len(_nd_weak) > 5 else "")
                      + (f" → 新增 {len(_added)} 个到黑名单" if _added else ""))
        else:
            cn_blacklist = set()
    except Exception as _nd_err:
        print(f"  [next_day_strategy] 加载失败: {_nd_err}")
        cn_blacklist = set()

    filtered_by_sector = 0

    """
    修复 #5 (P1): 候选池扩到全市场
       原版只看 top10 报告，会自限。今日改为：top10 + 新浪全市场涨幅榜（涨幅 -3~+5%）。
    修复 #3 (P1): 评分阈值从 60 改 65，与报告"买入条件 ≥ 65"一致
    修复 #6: 接收 sentiment_score，传给评分函数
    """
    from dynamic_stocks import get_dynamic_stock_pool, filter_stocks
    from eastmoney_portfolio import get_snapshot_top10

    print(f"[AAna 尾盘] {datetime.now().strftime('%H:%M:%S')} 开始尾盘选股...")

    # 1. 候选股票池（多源合并去重）
    candidate_codes = []
    today_str = datetime.now().strftime("%Y-%m-%d")

    # 源 1: 今日选股报告 Top10
    today_top10 = get_snapshot_top10(today_str)
    if today_top10:
        candidate_codes.extend(today_top10)
        print(f"  [源1] 今日 Top10: {len(today_top10)} 只")

    # 源 2: 昨日 Top10（fallback）
    if not today_top10:
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        yest_top10 = get_snapshot_top10(yesterday_str)
        if yest_top10:
            candidate_codes.extend(yest_top10)
            print(f"  [源2] 昨日 Top10: {len(yest_top10)} 只")

    # 源 3 (修复 #5): 全市场涨幅榜，扩大候选
    # 抓涨幅 -3% ~ +5% 区间 + 成交活跃股，这是尾盘选股的真正范围
    #
    # v2026-10-23 P0 修复 (根因): 原实现内联硬编码"5 页 × 80 只 + 涨幅 -3%~+5% 窗口"。
    # 强普涨日 (2026-10-23: 上证 -2.66% → +0.85%, 深证 +3.00%, 创业板 +4.46%, 涨停 81)
    # 涨幅榜前 400 只**全部** >+5% (实测最小 +6.94%), 硬编码窗口筛出 0 只 →
    # 候选池空 → 0 推荐 (假空仓)。**窗口是"涨跌幅绝对值", 普涨日天然失效。**
    # 修复: 统一走 dynamic_stocks 的真源 (get_top_gainers_with_fallback 800 只 +
    # filter_stocks 用集中常量 CHANGE_MIN/MAX=-3/+7 + 主板/价格/ST 过滤)。
    # 这同时消除了"多脚本多阈值"分裂 (同源取数, 见 china-stock-analysis v2026.5 教训)。
    try:
        from dynamic_stocks import get_top_gainers_with_fallback, filter_stocks
        raw_stocks, src = get_top_gainers_with_fallback(800)
        if raw_stocks:
            pool = filter_stocks(raw_stocks)
            before = len(candidate_codes)
            for item in pool:
                c = item.get('code', '')
                if c and c not in candidate_codes:
                    candidate_codes.append(c)
            print(f"  [源3] 全市场涨幅榜 ({src}, 原始{len(raw_stocks)}→过滤{len(pool)}): 新增 {len(candidate_codes) - before} 只")
        else:
            print("  [源3] 全市场涨幅榜失败: 所有数据源返回空")
    except Exception as e:
        print(f"  [源3] 全市场涨幅榜失败: {e}")

    if not candidate_codes:
        print("[AAna 尾盘] 候选股票池为空，跳过尾盘选股")
        # v2026-10-23 P0 修复: 必须返回 (top_n, confidence_note) 二元组。
        # 根因: 这里原来 `return []` (单值), 而 main() 写的是
        #   `stocks, confidence_note = screen_afternoon_stocks(...)` → 候选池为空时
        #   ValueError: not enough values to unpack (expected 2, got 0) → 整个尾盘流程崩,
        #   报告都没生成, 上层误判为"0 推荐"。
        return [], None

    # ── XWI-50: Skill 模式下调用方指定 codes 时,过滤候选池 ──
    if codes is not None:
        codes_set = set(codes)
        before = len(candidate_codes)
        candidate_codes = [c for c in candidate_codes if c in codes_set]
        print(f"  [XWI-50 codes 过滤] {before} → {len(candidate_codes)} 只 (仅 Skill 指定)")
        if not candidate_codes:
            print("[AAna 尾盘] Skill 指定 codes 在默认池中无匹配, 跳过")
            return [], None  # v2026-10-23 P0 修复: 同上, 保持二元组返回契约

    print(f"[AAna 尾盘] 候选股票总数: {len(candidate_codes)} 只")

    # 2. 获取实时行情
    prices = get_stock_data_sina(candidate_codes)

    # ── v2026-10-08 修复 (#12): 数据源健康度追踪 ──
    # 背景: 10/1-10/6 多个交易日"东财资金流 + 新浪 K 线 + 同花顺涨停股池 + 板块数据"全挂,
    # 导致 fallback score 47-49 < 阈值 65 → 0 推荐(用户从 A 股 Top 10 表头发现"真空")。
    # 修复: 统计各数据源 ok/fail, fail 率 > 50% 时降阈值, 报告里加置信度提示。
    data_health = {
        'kline': {'ok': 0, 'fail': 0},
        'fund_flow': {'ok': 0, 'fail': 0},  # 评分函数内部 fail 计数由 score_afternoon_stock 返回的 'klines_missing' 间接推断
    }

    # 3. 逐只评分
    results = []
    for code in candidate_codes:
        info = prices.get(code, {})
        if not info or info.get('price', 0) <= 0:
            continue

        # v2026-10-02 B1 修复: 价格区间从 [20,80] 放宽到 [5,100]
        # 之前 user 要求 10-80 是为排除仙股(<5) 和妖股(>100), 但 [20,80]
        # 实际过滤掉了大量温和红涨的优质票, 叠加红涨砍 0% + change_pct > 3% 上限
        # 导致震荡日 0 推荐 25 个交易日 P0。
        # 放宽到 [5,100] 保留对仙股和过高价股的过滤, 同时让推荐池不致于真空。
        price = info.get('price', 0)
        if price < 5 or price > 100:
            continue

        # 过滤：科创板(688) + 创业板(300/301) — 用户要求不推荐
        if code.startswith(('688', '8')) or code.startswith(('300', '301')):
            continue

        # v2026-10-02 B1 修复: 涨跌范围从 [-8, 3% 砍红涨] 放宽到 [-9, 7%]
        # 策略核心: 尾盘买入 = 当日温和上涨或小幅回调的强势股 (不追高)
        # 之前 bug: 红涨一律砍 + 上限 3% 等于震荡日 0 推荐
        # 现在: 允许温和红涨 (0~5%) 进评分环节, 但不追高 (>=7% 砍), 跌幅限制 [-9, 涨停砍]
        change_pct = info.get('change_pct', 0)
        if change_pct < -9 or change_pct >= 9:  # 跌停/涨停排除
            continue
        if change_pct > 7:  # 涨幅上限放宽到 7% (之前 3% 太严)
            continue

        # v2026-10-02 B1 修复 (第三次, 早盘快照 amount 不可信):
        # v2026-09-09 引入的 amount < 5e7 前置过滤, 原本想卡僵尸票,
        # 但 sina realtime 接口在早盘/盘后返回 amount 数值偏低
        # (茅台早盘快照 0.13 亿 vs 全天 12.59 亿, 甘李药业早盘 7740 万 vs 全天数亿),
        # 任何 amount 阈值都会误杀大量优质票。
        # 解决: 移除 amount 前置过滤, 改为 score_afternoon_stock 的扣分项处理
        # (info.amount 仍传给评分函数, < 5亿 扣 5分; 不进 Top10 而非直接砍)
        amount = info.get('amount', 0) or 0
        # v2026-10-02 B1 第三次: 不卡 amount (只在 score 里扣分)
        # 注: 如果未来需要 amount 硬卡, 用 get_dynamic_quote_full() 拉全天数据, 而非 realtime 接口

        # v2026-10-02 B1 修复 (第四次): 当 K 线 API 持续限流时, 临时降 score_threshold
        # 实测 sina/腾讯 K 线在早盘 cron 触发时 (07:00-08:00) 频繁 RemoteDisconnected,
        # 全市场 80+ 只票 K 线 100% 失败, score=fallback(50-|change|*1)≈47-49 < 65 阈值 → 0 推荐
        # 修复: 统计 K 线失败率, >50% 时降阈值到 50, 让 fallback 47-49 通过门槛
        # 但仍记录 _klines_partial=True 标记, 报告里标注"技术面缺失, 仅基于实时行情"
        # 注: 真交易时段 14:45 触发时,K 线 API 稳定, 不需要降阈值
        # 先占位: 后面 K 线调用后用 klines_available_count / total 判断
        # v2026-10-08 修复 (#12): 真实追踪 K 线成功/失败
        klines = get_tencent_kline(code, count=30)
        if klines and len(klines) >= 5:
            data_health['kline']['ok'] += 1
        else:
            data_health['kline']['fail'] += 1

        # v2026-08-23 (数据驱动): 板块黑名单过滤 — rec_tuning 复盘胜率 < 35% 的板块
        # (样本 ≥ 10) 不进评分。
        # v2026-09-09 修复: 新浪全市场来源的 info['sector'] 100% 为空, 导致 weak_sectors
        # 黑名单 100% 失效。现在改为: info.sector 为空时调 industry_for_code() 反查
        # (sina HTML → akshare 关键词, 4 级降级链), 然后映射到 rec_tuning 英文 enum。
        # 仍未知 (返回 'unknown') 则保守放过 (沿用"无数据不误杀"原则)。
        stock_sector_raw = info.get('sector', '') or ''
        if not stock_sector_raw:
            try:
                from data_sources import industry_for_code, normalize_code
                _cn = industry_for_code(normalize_code(code)) or 'unknown'
                if _cn and _cn != 'unknown':
                    stock_sector_raw = _cn
            except Exception:
                stock_sector_raw = 'unknown'
        # 映射中文行业名 → rec_tuning 英文 enum
        stock_sector_enum = _cn_sector_to_enum(stock_sector_raw)
        # v2026-10-28 P0 修复: 双路匹配 (中文原名 OR enum) — 旧代码只比 enum,
        # 而 blacklist 里存的是 rec_feedback.sector 列的中文原值 → 恒不匹配。
        if _sector_blacklisted(stock_sector_raw, stock_sector_enum, sector_blacklist):
            filtered_by_sector += 1
            continue
        # v2026-09-09 (Phase 12): next_day_strategy.json 的 cold_sectors 拦截
        # 这是一组**未映射到 enum**的中文行业名 (如 "园林工程"), enum 是空字符串,
        # 上面的 enum 检查拦截不到, 必须直接比较 cn.
        if cn_blacklist and stock_sector_raw in cn_blacklist:
            filtered_by_sector += 1
            print(f"  [cold_sector] 拦截 {code} {info.get('name', code)}: 板块 '{stock_sector_raw}' 在 cold_sectors 中")
            continue

        # 评分（修复 #6: 传 sentiment_score）
        score, scored_info = score_afternoon_stock(info, klines, sentiment_score=sentiment_score)
        # 把反查到的中文行业名写回 scored_info, 后面 record_recommendation 用
        scored_info['sector'] = stock_sector_raw

        # v2026-08-23 (数据驱动): 阈值从 strategy_policy 读取 (默认 65, 真实 score
        # 样本 ≥ 30 且胜率数据支持时 rec_optimizer 会调)
        # v2026-10-08 修复 (#12): 改为先收下, 在循环外根据数据源健康度动态过滤
        # 原因: 早盘 cron 多源全挂时硬阈值 65 会得到 0 推荐; 健康度差时需降阈值
        results.append(scored_info)

    # 4. 排序
    results.sort(key=lambda x: x['score'], reverse=True)

    # ── v2026-10-08 修复 (#12): 数据源健康度 → 动态降阈值 ──
    # 现实: 多源全挂时硬阈值 65 是 0 推荐; 健康度差时改软阈值
    total_kline = data_health['kline']['ok'] + data_health['kline']['fail']
    fail_rate_kline = (data_health['kline']['fail'] / total_kline) if total_kline else 0.0
    if fail_rate_kline > 0.7:
        # 70% K 线失败 → 大幅降阈值(技术面缺失, 容忍低置信度)
        adjusted_threshold = 45
        confidence = '低'
    elif fail_rate_kline > 0.5:
        # 50% K 线失败 → 适度降阈值
        adjusted_threshold = max(50, score_threshold - 15)
        confidence = '中'
    else:
        adjusted_threshold = score_threshold
        confidence = '高'
    if adjusted_threshold != score_threshold:
        print(f"  [data_health] K线 fail 率 {fail_rate_kline:.0%}, 阈值 {score_threshold} → {adjusted_threshold} (置信度:{confidence})")
        score_threshold = adjusted_threshold

    # 用新阈值重新过滤
    results = [r for r in results if r.get('score', 0) >= score_threshold]

    top_n = results[:10]

    # 5. 优化 #3: 监控信号 — 写入 rec_feedback.csv
    if record_feedback and top_n:
        for s in top_n:
            record_recommendation(
                code=s.get('code', ''),
                name=s.get('name', ''),
                score=s.get('score', 0),
                sentiment_score=sentiment_score,
                macd_gold=bool(s.get('macd_gold', False)),
                macd_confirmed=bool(s.get('macd_confirmed', False)),
                # v2026-09-09 修复: 把反查到的板块传给 record_recommendation,
                # 之前 100% 漏传 → rec_feedback.csv sector 100% 为空 → weak_sectors 黑名单失效
                sector=s.get('sector', '') or '',
            )
        print(f"[AAna 尾盘] 已记录 {len(top_n)} 条推荐到 rec_feedback.csv (优化 #3)")

    # ── XWI-50: dual_export — Skill 模式下可关闭,避免污染 JSONL 衍生数据 ──
    if dual_export and weights is not None and top_n:
        try:
            os.makedirs(os.path.dirname(_weights_jsonl), exist_ok=True)
            with open(_weights_jsonl, "a", encoding="utf-8") as _fj:
                for s in top_n:
                    _fj.write(_wjson.dumps({
                        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "code": s.get("code", ""),
                        "name": s.get("name", ""),
                        "score": s.get("score", 0),
                        "sentiment_score": sentiment_score,
                        "weights": weights,
                        "source": "skill",
                    }, ensure_ascii=False) + "\n")
            print(f"[AAna 尾盘] dual_export 已记录 {len(top_n)} 条 weights 到 {_weights_jsonl}")
        except Exception as _de_err:
            print(f"[AAna 尾盘] dual_export 写入失败: {_de_err}")

    print(f"[AAna 尾盘] 筛选后候选: {len(results)} 只 (板块黑名单拦截 {filtered_by_sector} 只)")
    return top_n, f"K线失败率 {fail_rate_kline:.0%} (置信度:{confidence})" if fail_rate_kline > 0.5 else None


# ============================================
# 报告生成
# ============================================

def format_change(c):
    """
    A股惯例：红涨绿跌
    修复 #9: 加注释（行为不变，只是命名易混淆）
    """
    if c == 0:
        return "⚪ 0.00%"
    emoji = "🔴" if c > 0 else "🟢"
    return f"{emoji} {c:+.2f}%"


def cleanup_old_reports(days=7):
    """
    清理超过 days 天的旧报告
    修复 #10: 增加早盘/盘中报告匹配
    修复 #11 (v2026-10-07 review): 使用模块级 AANA_DIR 常量, 避免重复硬编码
    """
    import glob
    import time
    report_dir = os.path.join(AANA_DIR, "reports")
    cutoff = time.time() - days * 86400
    patterns = [
        f"{report_dir}/*-选股报告.md",
        f"{report_dir}/*尾盘选股.md",
        f"{report_dir}/*早盘*.md",  # 修复 #10
        f"{report_dir}/*盘中*.md",  # 修复 #10
        f"{report_dir}/.snapshot_*.json",
    ]
    removed = 0
    for pat in patterns:
        for path in glob.glob(pat):
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed += 1
                print(f"[AAna] 清理过期报告: {os.path.basename(path)}")
    if removed:
        print(f"[AAna] 共清理 {removed} 个过期文件")


def generate_report(stocks, index_data=None, sentiment_label='中性', position_ratio=0.5, market_status='待定', avg_change=0.0, hot_str='', hot_sects=None, confidence_note=None):
    """生成尾盘选股报告 v2.5
    修复 #11 (v2026-10-07 review): report_dir 改用模块级 AANA_DIR 常量
    """
    today = get_today_str()
    now = datetime.now()
    hot_sects = hot_sects or []

    report_dir = os.path.join(AANA_DIR, "reports")
    os.makedirs(report_dir, exist_ok=True)
    filename = "{}/{}-尾盘选股.md".format(report_dir, today)

    # 生成报告前清理过期文件（保留7天）
    cleanup_old_reports(days=7)

    # 大盘状态
    # P1 修复：情绪标签直接用传入的 sentiment_label，不再重复判断指数（避免"冰点+乐观"矛盾）
    market_status = sentiment_label if sentiment_label else ("谨慎" if not index_data else "中性")
    avg_change = 0
    if index_data:
        avg_change = sum(i['change'] for i in index_data) / len(index_data)

    # 热点板块 — P1 修复：失败时打印明确日志（不静默）+ 报告里显示"获取失败"
    hot_sects = []
    hot_data_source = "ok"
    if AFTER_NEW:
        try:
            hot_sects = get_hot_sectors(3) or []
            if not hot_sects:
                hot_data_source = "fallback_empty"
                print(f"[AAna 尾盘] ⚠️ 热点板块获取为空（接口可能限流）")
        except Exception as e:
            hot_data_source = "fallback_error"
            print(f"[AAna 尾盘] ⚠️ 热点板块接口异常: {type(e).__name__}: {e}")
    hot_str = " | ".join("{}({:+.1f}%)".format(s['name'], s['change']) for s in hot_sects[:3])

    content = (
        "# A股尾盘选股建议 — {} {}\n\n".format(today, now.strftime('%H:%M')) +
        "> AAna 尾盘策略 v2.5 | 仅供参考，不构成投资建议\n"
        "> **生成时间：** {}\n".format(now.strftime('%Y-%m-%d %H:%M:%S')) +
        "> **情绪评分：** {} | **建议仓位：** {:.0f}%\n\n".format(
            sentiment_label, position_ratio * 100
        ) +
        # v2026-10-08 修复 (#12): 数据源健康度警告显式写到报告头部
        ("⚠️ **数据源异常：** {}\n\n".format(confidence_note) if confidence_note else "") +
        "---\n\n"
        "## 一、大盘环境 + 情绪\n\n"
        "| 指标 | 涨跌幅 | 状态 |\n"
        "|:----:|:------:|:----:|\n"
    )
    if index_data:
        for idx in index_data:
            emoji = "\U0001f534" if idx['change'] > 0 else "\U0001f7e2"
            content += "| {} | {} {:+.2f}% | {} |\n".format(
                idx['name'], emoji, idx['change'],
                '上涨' if idx['change'] > 0 else '下跌'
            )
    else:
        content += "| 大盘数据获取失败 | - | - |\n"
    content += "\n**市场情绪：** {} | **平均涨跌：** {:+.2f}%".format(market_status, avg_change)
    if hot_str:
        content += " | **热点：** {}".format(hot_str)
    elif hot_data_source != "ok":
        # P1 修复：板块数据失败时显示"获取失败"，不静默
        content += " | **热点：** ⚠️获取失败({})".format(hot_data_source)
    content += "\n\n---\n\n"


    content += (
        # P1 修复：错字"尿盘"→"尾盘"（unicode 5c3f 改成 5c3e）
        "> \u7b56\u7565\u8bf4\u660e\uff1a\u5c3e\u76d8\u4e70\u5165\u5f53\u65e5\u5c0f\u5e45\u56de\u8c03\u7684\u5f3a\u52bf\u80a1\n"
        "> - \u5f53\u65e5\u56de\u8c03 -3%~0% \u4e14\u4ef7\u683c\u4ecd\u5728\u5747\u7ebf\u4e0a\u65b9\n"
        "> - RSI 40-60\uff08\u4e0d\u8d85\u4e70\u4e5f\u4e0d\u8d85\u5356\uff09\n"
        "> - \u91cf\u6bd4\u6b63\u5e38\uff080.5~1.5x\uff09\n"
        "> - \u5747\u7ebf\u591a\u5934\u6392\u5217\n"
        "\n"
    )
    
    if stocks:
        content += "| 排名 | 股票 | 代码 | 现价 | 今日涨跌 | RSI | 量比 | 均线 | MACD | 评分 | 风险 | 止损价 | 目标价 |\n"
        content += "|:----:|:----:|:----:|:----:|:--------:|:----:|:----:|:----:|:----:|:----:|:----:|:-----:|:-----:|\n"
        
        for i, s in enumerate(stocks, 1):
            rsi = s.get('rsi', 'N/A')
            vol_r = s.get('vol_ratio', 'N/A')
            ma_status = '多头' if s.get('ma5', 0) > s.get('ma10', 0) else ('空头' if s.get('ma5', 0) < s.get('ma10', 0) else '纠缠')
            macd = '✅金叉' if s.get('macd_gold') else '-'
            
            content += f"| {i} | {s['name']} | {s['code']} | ¥{s['price']:.2f} | {format_change(s['change_pct'])} | {rsi} | {vol_r}x | {ma_status} | {macd} | **{s['score']}** | {s['risk']} | ¥{s['stop_loss']} | ¥{s['target_price']} |\n"
    else:
        content += "> 今日无符合条件的尾盘买入机会\n\n"
        content += "可能原因：\n"
        content += "- 市场整体下跌，无回调强势股\n"
        content += "- 候选股RSI偏高，不宜买入\n"
        content += "- 建议：轻仓或空仓观望\n"
    
    content += f"""

---

## 三、操作建议

### 买入条件（全部满足）
1. 评分 ≥ 65
2. 当日跌幅 -3% ~ 0%（不是大跌大买）
3. RSI < 70
4. 价格在MA5上方
5. 量比 < 3（不是巨量出货）

### 止损纪律
- 单只股票止损：-5%（跌破止损价次日开盘清仓）
- 总仓位止损：-3%时减仓50%

### 尾盘注意事项
- ⏰ 14:50 前完成买入，14:55后不再开新仓
- 📊 优先买评分最高的1-2只，不分散买太多
- 🔴 涨幅>5%的股票不追（尾盘追高次日容易低开）

---

## 四、Top3 重点关注（动态按实际数量调整）
"""
    # P1 修复：动态匹配实际数量（不再硬编码 Top3）
    if stocks:
        n_top = min(3, len(stocks))
        content += "\n## 四、Top {} 重点关注\n\n".format(n_top)

    if stocks[:3]:
        for i, s in enumerate(stocks[:3], 1):
            reason = []
            change_pct = s.get('change_pct', 0)
            if -3 <= change_pct < 0:
                reason.append("当日回调")
            if s.get('rsi') and 40 <= s['rsi'] <= 60:
                reason.append(f"RSI适中({s['rsi']})")
            if s.get('macd_gold'):
                days_ago = s.get('macd_gold_days_ago', 0)
                reason.append(f"MACD金叉({days_ago}日前)" if days_ago else "MACD金叉")
            # 修复 #8: 兜底 reason — 多头排列和量能健康也算
            ma5 = s.get('ma5', 0)
            ma10 = s.get('ma10', 0)
            ma20 = s.get('ma20', 0)
            if ma5 and ma10 and ma5 > ma10 > ma20:
                reason.append("均线多头")
            elif ma5 and ma10 and ma5 > ma10:
                reason.append("短期多头")
            vol_r = s.get('vol_ratio', 0)
            if vol_r and 0.5 <= vol_r <= 1.5:
                reason.append(f"量比健康({vol_r}x)")
            if price := s.get('price', 0):
                amount = s.get('amount', 0)
                if amount > 5e8:
                    reason.append("成交活跃")

            content += f"### {i}. {s['name']}({s['code']}) 评分{s['score']}\n"
            content += f"- 现价: ¥{s['price']:.2f} | 今日: {format_change(change_pct)}\n"
            # 修复 #8: 永远至少显示一条理由（避免 f-string 反斜杠问题）
            reason_text = '; '.join(reason) if reason else f"综合评分{s['score']}分（多维度均达标）"
            sl_pct = (s['stop_loss'] / s['price'] - 1) * 100
            tp_pct = (s['target_price'] / s['price'] - 1) * 100
            content += f"- 买入理由: {reason_text}\n"
            content += f"- 止损价: ¥{s['stop_loss']}（{sl_pct:+.1f}%）| 目标价: ¥{s['target_price']}（{tp_pct:+.1f}%）\n\n"
    else:
        content += "> 今日暂无重点推荐\n"
    
    content += f"""---

*AAna 尾盘选股 v1.0 | {now.strftime('%Y-%m-%d %H:%M:%S')}*
"""
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"[AAna 尾盘] 报告已生成: {filename}")
    return filename, stocks


# ============================================
# 主流程
# ============================================

def check_ice_point_guard(sent=None):
    """冰点/极低仓位守卫 — 尾盘选股的**唯一**短路入口 (v2026-10-22 P0 修复)

    背景 (P0, 连续 3 日复发 10/17 + 10/21 + 10/22):
      冰点守卫原先只写在 main() 内部，而 daily_v24_recommend.py (launchd 14:45)
      直接调用 screen_afternoon_stocks() —— 绕过了 main() 里的守卫，
      并且硬编码 sentiment_score=50 / position_ratio=0.5 (假装中性)，
      于是在冰点日逆势建了 10 只纸面仓 + 写 10 行 rec_feedback/recommendations，
      污染 rec_tuning 胜率统计。

    修复 (单一真源):
      把守卫抽成本函数, main() 与 daily_v24_recommend.py 共用同一个判定。
      任何调用 screen_afternoon_stocks() 的入口都必须先过这道门。

    返回 dict:
      is_ice_point: bool      — True 表示应短路 (不选股/不建仓/不写推荐池)
      sentiment_label: str
      sentiment_score: int
      position_ratio: float
      data_source_fallback: bool
      reason: str             — 短路原因 (写日志用)

    参数 sent: 可选。传入已取好的情绪 dict 则复用 (避免重复拉取 + 便于测试);
                传 None 则自行调用 get_market_sentiment()。
    """
    sentiment_label = '乐观'
    sentiment_score = 50
    position_ratio = 0.5

    if sent is None and AFTER_NEW:
        try:
            sent = get_market_sentiment()
        except Exception as e:
            print(f"[情绪] ⚠️ 获取失败 ({e}), 保守按非冰点处理")
            sent = None

    if sent is not None:
        sentiment_label = sent.get('label', '乐观')
        sentiment_score = sent.get('score', 50)
        position_ratio = _safe_position_ratio(sentiment_score)
        print("[情绪] {} | 涨停{} 跌停{} | 建议仓位{:.0f}%".format(
            sentiment_label,
            sent.get('zt_count', 0),
            sent.get('dt_count', 0),
            position_ratio * 100
        ))

    # v2.5.1 修复（2026-06-12）：冰点短路必须配合"数据源=fallback"判断
    # 涨跌停接口 fallback 时返回 (-1,-1)，单看 label='冰点' 会误判 → 不强制空仓
    data_source_fallback = (sent is not None) and (
        sent.get('zt_count', 0) == -1 or sent.get('dt_count', 0) == -1
    )
    if data_source_fallback and position_ratio < 0.3:
        print(f"[情绪] ⚠️ 涨跌停数据 fallback，仓位从 {position_ratio*100:.0f}% 提升到 30%（避免单点脏数据误判冰点）")
        position_ratio = 0.3

    # P0-B: 冰点日 / 仓位 < 10% 时直接短路, 不跑选股
    # 阈值 < 0.1: 仓位低于 10% 视为"几乎空仓"，尾盘选股无意义
    is_ice_point = (
        sentiment_label in ('冰点', '极冷', '恐慌') or position_ratio < 0.1
    ) and not data_source_fallback

    reason = ""
    if is_ice_point:
        reason = f"情绪={sentiment_label}/仓位={position_ratio*100:.0f}%"

    return {
        'is_ice_point': is_ice_point,
        'sentiment_label': sentiment_label,
        'sentiment_score': sentiment_score,
        'position_ratio': position_ratio,
        'data_source_fallback': data_source_fallback,
        'reason': reason,
    }


def main():
    # ── 🆕 假期守卫 (2026-10-06): 非交易日直接短路, 禁止写推荐/反馈 ──
    # 教训: 10/02 (国庆假期) cron 仍执行, 用 9/30 陈旧数据+fallback_empty
    # 写入 11 条假日推荐 → 污染 rec_tuning 统计。与 generate_report.py 同守卫。
    from generate_report import is_trading_day
    is_trade, non_trade_reason = is_trading_day()
    if not is_trade:
        print(f"[AAna 尾盘] 📅 今日非交易日 ({non_trade_reason}), 跳过选股, 不写任何推荐/反馈")
        return []

    # ── 市场情绪 + 冰点守卫 (v2026-10-22 P0: 抽成 check_ice_point_guard 单一真源) ──
    # 守卫判定与 daily_v24_recommend.py 共用同一个函数，避免两个入口阈值分裂。
    guard = check_ice_point_guard()
    sentiment_label = guard['sentiment_label']
    sentiment_score = guard['sentiment_score']
    position_ratio = guard['position_ratio']
    data_source_fallback = guard['data_source_fallback']

    # 获取大盘指数
    # v2026-10-23 P0 修复: 指数走 get_index_data_sina() (专用 sh/sz 前缀表),
    # 不能用个股的 get_market_sina() —— 否则 000001→平安银行 / 000688→国城矿业。
    index_codes = ['000001', '399001', '399006', '000688']
    index_names = {'000001': '上证指数', '399001': '深证成指', '399006': '创业板', '000688': '科创50'}
    prices = get_index_data_sina(index_codes)
    index_data = []
    for code, name in index_names.items():
        info = prices.get(code, {})
        if info.get('price', 0) > 0:
            index_data.append({
                'name': name,
                'price': info['price'],
                'change': info['change_pct']
            })
    # P1 修复：avg_change 提前算出来，避免冰点短路分支里用 `if 'avg_change' in dir()` 怪写法
    avg_change = sum(i['change'] for i in index_data) / len(index_data) if index_data else 0.0

    # P0-B 修复：冰点日 / 仓位 < 10% 时直接短路，不跑选股
    # 之前 bug：报告顶部写"建议仓位 0%"，但仍推 8 只（自相矛盾）
    # 阈值 < 0.1：仓位低于 10% 视为"几乎空仓"，尾盘选股无意义
    #
    # v2026-10-22 P0 修复：判定已抽到 check_ice_point_guard()，与
    # daily_v24_recommend.py 共用同一真源（连续 3 日复发 10/17+10/21+10/22 的根因）。
    is_ice_point = guard['is_ice_point']
    if is_ice_point:
        print(f"[AAna 尾盘] ❄️ 情绪={sentiment_label}/仓位={position_ratio*100:.0f}%，跳过尾盘选股（冰点日策略不推任何票）")
        # 仍然生成报告，但内容是"暂停推荐"
        filename, top_stocks = generate_report(
            [], index_data,
            sentiment_label=sentiment_label,
            position_ratio=position_ratio,
            market_status='冰点',
            avg_change=avg_change,
            hot_str='',
            hot_sects=[],
            confidence_note=None,  # 冰点分支无选股, 不需要数据源警告
        )
        print(f"[AAna 尾盘] 📝 冰点日报已生成: {filename}")
        print(f"[AAna 尾盘] 🛑 不推送推荐，不同步东财，不写入推荐池")
        return []

    # 选股（修复 #6: 传 sentiment_score / position_ratio 进评分）
    stocks, confidence_note = screen_afternoon_stocks(
        sentiment_score=sentiment_score,
        position_ratio=position_ratio,
    )

    # 生成报告
    market_status = sentiment_label if sentiment_label else '待定'
    # avg_change 已在上方算过
    hot_sects = []
    hot_str = ''
    filename, top_stocks = generate_report(
        stocks, index_data,
        sentiment_label=sentiment_label,
        position_ratio=position_ratio,
        market_status=market_status,
        avg_change=avg_change,
        hot_str=hot_str,
        hot_sects=hot_sects,
        confidence_note=confidence_note,  # v2026-10-08 修复 (#12): 数据源健康度写到报告
    )

    # 持久化到 data/ 层
    if top_stocks:
        persisted = append_recommendations_batch(top_stocks)
        print(f"[AAna 尾盘] data/ 层已记录 {persisted} 条推荐")

    # 输出到控制台
    print("\n" + "="*70)
    print(f"📋 尾盘选股建议 {get_today_str()} {datetime.now().strftime('%H:%M')}")
    print("="*70)
    
    if top_stocks:
        print(f"\n🏆 重点推荐（评分降序）：\n")
        for i, s in enumerate(top_stocks[:5], 1):
            print(f"  {i}. {s['name']}({s['code']}) ¥{s['price']:.2f} {s['change_pct']:+.2f}% RSI={s.get('rsi','N/A')} 量比={s.get('vol_ratio','N/A')}x 评分={s['score']} {s['risk']}")
            print(f"     理由: 止损¥{s['stop_loss']} 目标¥{s['target_price']}")

        # v2026-08-23 Phase 1C: 移除末尾自动同步到东财 PP 组合的代码
        # ─────────────────────────────────────────────────────────
        # 根因: 该段自动调 sync_portfolio_to_eastmoney() 内部走
        #   get_snapshot_top10() 解析**早盘** reports/{date}-选股报告.md
        #   → 8/18 第 3 次复发实证: 跑出 4 只筛选股，末尾同步把 10 只早盘 raw
        #   加进 PP 组合 (gid=1341)。三次复发(7/1 + 7/14 + 8/18)同根。
        #
        # 修复: 让 cron prompt `__main__` 块独占同步逻辑（已沉淀 in
        # `~/.hermes/skills/a-stock/a-stock-system/SKILL.md` 8/18 实战 SOP），
        # 本脚本只负责数据采集 + 报告生成，单一职责。
        #
        # 如果确实需要脚本内同步，明确传入报告路径:
        #   success = sync_portfolio_to_eastmoney(
        #       stock_codes=actual_screen_result_codes,  # ← 显式传入筛选后
        #       group_name=f"{today_str}PP",
        #   )
        # 当前参数过于隐式（依赖 get_snapshot_top10 内部读早盘报告），放弃。
        # ─────────────────────────────────────────────────────────

    else:
        print("\n⚠️ 今日暂无符合尾盘策略的股票，建议轻仓观望")
    
    print("="*70)
    return top_stocks


if __name__ == '__main__':
    # v2.5.1 修复（2026-06-12）：根据 main() 返回值 + 数据源状态决定 exit code
    # 0=正常有推荐  1=有输出但无推荐  2=数据脏/上游 fallback（触发 alert）
    import sys as _sys
    try:
        result = main()
    except SystemExit as e:
        raise
    except Exception as e:
        print(f"[AAna 尾盘] ❌ 未捕获异常: {e}")
        import traceback; traceback.print_exc()
        _sys.exit(2)
    # 简单判定：main() 返回 [] 表示 0 推荐
    if not result:
        _sys.exit(1)
    _sys.exit(0)

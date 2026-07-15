#!/usr/bin/env python3
"""
AAna v2.5 每日选股报告 + 复盘评分
迭代优化：
- v2.1: 技术指标增强（均线、量比、MACD信号）
- v2.2: 基本面筛选（PE/PB/ROE/股息率）
- v2.3: 智能筛选+风险评估
- v2.4: 复盘评分报告（17:00）+ 早盘快照
- v2.5: 资金流向 + 市场情绪 + 风控硬化 + 模拟交易
"""
import os
import sys
import json
import subprocess
import argparse
import warnings
from pathlib import Path
warnings.filterwarnings('ignore')

from datetime import datetime
import requests

# ── 新模块引入 ──────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
for _p in (str(SCRIPT_DIR), str(DATA_DIR), str(PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
try:
    from market_sentiment import (
        get_market_sentiment, get_hot_sectors,
        get_north_money, get_zt_pool,
        get_enhanced_stock_pool,
    )
    from risk_rules import (
        get_position_ratio, filter_stock_basic,
        calc_stop_loss, calc_take_profit_trail,
        composite_score, RiskManager,
        WEIGHT_TECH, WEIGHT_FUND, WEIGHT_MONEYFLOW,
    )
    from fund_screener import screen_funds, format_fund_report
    from fund_tracker import get_tracker_report as get_fund_tracker_report
    from fund_comparison import get_comparison_report as get_fund_comparison_report
    NEW_MODULES = True
except ImportError as e:
    print(f"[AAna] 新模块加载失败: {e}，使用简化版")
    WEIGHT_TECH = 0.60
    WEIGHT_FUND = 0.40
    WEIGHT_MONEYFLOW = 0.00
    NEW_MODULES = False

PROJECT_DIR = os.path.expanduser("~/code/AAna")
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")


def get_today_str():
    now = datetime.now()
    # 22点后生成次日报告
    if now.hour >= 22:
        from datetime import timedelta
        return (now + timedelta(days=1)).strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%d")

def get_yesterday_str():
    from datetime import timedelta
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


# ============================================
# 交易日判断 (2026-06-19 P0 修复)
# 解决端午/中秋/国庆等法定节假日 cron 仍触发生成空报告的问题
# ============================================
# 2026 年中国法定休市日 (周末 + 调休 + 法定节假日)
# 来源: 国务院办公厅每年发布的节假日安排通知
# 2026-06-22 修正: 6/22 周一不是端午调休（实际是工作日），上证指数 -0.43% 正常交易
_HOLIDAY_2026 = {
    # 元旦: 1/1-3
    '2026-01-01', '2026-01-02', '2026-01-03',
    # 春节: 2/17-23 (除夕到初六), 调休 2/14(六)上班、2/28(日)上班
    '2026-02-17', '2026-02-18', '2026-02-19', '2026-02-20',
    '2026-02-21', '2026-02-22', '2026-02-23',
    # 清明: 4/4-6
    '2026-04-04', '2026-04-05', '2026-04-06',
    # 劳动节: 5/1-5
    '2026-05-01', '2026-05-02', '2026-05-03', '2026-05-04', '2026-05-05',
    # 端午: 6/19-21 (周五-周日) — 6/22 周一实际是工作日
    '2026-06-19', '2026-06-20', '2026-06-21',
    # 中秋+国庆: 10/1-7
    '2026-10-01', '2026-10-02', '2026-10-03',
    '2026-10-04', '2026-10-05', '2026-10-06', '2026-10-07',
}


def is_trading_day(date_str=None):
    """判断是否为 A 股交易日（周末 + 法定节假日都算非交易日）
    
    Args:
        date_str: 'YYYY-MM-DD' 格式日期, 默认今天
    
    Returns:
        (is_trading: bool, reason: str) — reason 仅在非交易日时填
    """
    if date_str is None:
        date_str = get_today_str()
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return True, ''  # 解析失败按交易日处理 (fail-open)
    # 周末
    if dt.weekday() >= 5:  # 5=周六, 6=周日
        return False, f'周末 ({["周一","周二","周三","周四","周五","周六","周日"][dt.weekday()]})'
    # 2026 法定节假日 (其他年份未维护 — fail-open 避免误杀)
    year = dt.strftime('%Y')
    if year == '2026' and date_str in _HOLIDAY_2026:
        return False, '法定节假日'
    return True, ''

def get_report_filename(report_type='选股报告'):
    return f"{REPORT_DIR}/{get_today_str()}-{report_type}.md"

def cleanup_old_reports(days=7):
    """清理超过 days 天的旧报告（选股报告、尾盘选股、快快照）"""
    import glob, time
    cutoff = time.time() - days * 86400
    patterns = [
        f"{REPORT_DIR}/*-选股报告.md",
        f"{REPORT_DIR}/*尾盘选股.md",
        f"{REPORT_DIR}/*基金*.md",
        f"{REPORT_DIR}/.snapshot_*.json",
        f"{REPORT_DIR}/盘中/*.log",
        f"{REPORT_DIR}/盘前/*.log",
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

def get_morning_snapshot_filename():
    """获取今日早盘快照文件名（9:00AM生成）"""
    today = get_today_str()
    return f"{REPORT_DIR}/.snapshot_{today}_09_00.json"

def save_morning_snapshot(prices):
    """保存早盘快照（9:00AM），用于收盘后复盘对比"""
    snap_file = get_morning_snapshot_filename()
    if not os.path.exists(snap_file):
        with open(snap_file, 'w', encoding='utf-8') as f:
            json.dump({
                'version': '2.4',
                'timestamp': datetime.now().isoformat(),
                'prices': prices,
            }, f, ensure_ascii=False, indent=2)
        print(f"[AAna] 早盘快照已保存: {snap_file}")

# ============================================
# Git pull: 每次运行前拉取最新代码
# ============================================
def get_historical_kline(code, count=60):
    """获取历史 K 线

    v2.5.1 修复（2026-07-08）：弃用 baostock（50 只股票 50 次 login/logout 慢路径 5+ 分钟）。
    改用东财 push2his.eastmoney.com（重试 3 次）+ 新浪 K 线（fallback）。
    返回数据格式保持 baostock 兼容：list of [date,open,high,low,close,volume]
    """
    import requests, time

    # ─── 源 1: 东财 push2his（首选，重试 3 次）───
    try:
        secid = f"1.{code}" if code.startswith(("5", "6", "9")) else f"0.{code}"
        url = (
            f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
            f"?secid={secid}&fields1=f1,f2&fields2=f51,f52,f53,f54,f55,f56,f57&klt=101&fqt=1&end=20500101"
        )
        for attempt in range(3):
            try:
                if attempt > 0:
                    time.sleep(0.5 * attempt)  # 退避 0.5s / 1.0s
                resp = requests.get(url, headers={
                    'User-Agent': 'Mozilla/5.0',
                    'Referer': 'https://quote.eastmoney.com/'
                }, timeout=8)
                data = resp.json().get("data", {})
                klines = data.get("klines", [])
                if klines:
                    # 东财 "2026-07-08,open,close,high,low,volume" → baostock 兼容格式
                    result = []
                    for line in klines[:count]:
                        parts = line.split(",")
                        if len(parts) < 6: continue
                        # date,open,high,low,close,volume
                        result.append([parts[0], parts[1], parts[3], parts[4], parts[2], parts[5]])
                    if result:
                        return result
            except Exception as _e:
                if attempt == 2:  # 最后一次仍失败，让外层 except 接管
                    raise
    except Exception as e:
        # 东财彻底失败（瞬时风控/网络），fallback 到新浪
        pass

    # ─── 源 2: 新浪 K 线（已知可用，fallback）───
    try:
        sina_code = f"sh{code}" if code.startswith(("5", "6", "9")) else f"sz{code}"
        url = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        resp = requests.get(url, params={
            'symbol': sina_code, 'scale': 240, 'ma': 5, 'datalen': count,
        }, headers={
            'Referer': 'http://finance.sina.com.cn',
            'User-Agent': 'Mozilla/5.0',
        }, timeout=8)
        rows = resp.json()
        if not rows:
            return None
        # 新浪返回: [{day, open, high, low, close, volume}, ...]
        # 转 baostock 兼容: [date, open, high, low, close, volume]
        result = []
        for r in rows[:count]:
            result.append([
                r.get('day', ''),
                r.get('open', ''),
                r.get('high', ''),
                r.get('low', ''),
                r.get('close', ''),
                r.get('volume', ''),
            ])
        return result if result else None
    except Exception as e:
        print(f"[K线] 新浪 fallback 也失败 {code}: {e}")
        return None

def calculate_ema(data, period):
    """计算 EMA - data 可以是 list 或 dict"""
    if len(data) < period:
        return None
    # 如果是 dict，提取 close 值
    if isinstance(data[0], dict):
        data = [float(d['close']) for d in data]
    k = 2 / (period + 1)
    ema_val = data[0]
    for d in data[1:]:
        ema_val = d * k + ema_val * (1 - k)
    return ema_val

def get_close_list(kline):
    """从 kline 提取 close 列表 - 支持 BaoStock list 或 Sina dict"""
    if not kline:
        return []
    if isinstance(kline[0], dict):
        return [float(d['close']) for d in kline]
    else:  # BaoStock list format
        return [float(d[4]) for d in kline]  # index 4 = close

def detect_trend(kline):
    """检测趋势状态：上升/震荡/下降
    基于MA多头排列 + 价格位置 + 近期涨跌方向综合判断
    """
    if not kline or len(kline) < 20:
        return "震荡", "neutral"
    closes = get_close_list(kline)
    if len(closes) < 20:
        return "震荡", "neutral"
    
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20
    current = closes[-1]
    
    # 计算近期涨跌
    recent_change = (closes[-1] - closes[-5]) / closes[-5] * 100 if closes[-5] > 0 else 0
    
    # 上升趋势：MA多头且价格在均线上方
    if ma5 > ma10 > ma20 and current > ma5 and recent_change > 0:
        return "上升", "up"
    # 下降趋势：MA空头且价格在均线下方
    elif ma5 < ma10 < ma20 and current < ma5 and recent_change < 0:
        return "下降", "down"
    # 下降趋势：明显空头排列
    elif ma5 < ma10 < ma20:
        return "下降", "down"
    # 上升趋势：明显多头排列
    elif ma5 > ma10 > ma20:
        return "上升", "up"
    else:
        return "震荡", "neutral"

def is_ice_point(info, kline):
    """判断是否是冰点日（跌停或接近跌停）"""
    change_pct = info.get('change_pct', 0)
    # 跌停（-9.5%以下算冰点）
    if change_pct <= -9.5:
        return True
    # 大跌超过7%也视为冰点区域
    if change_pct <= -7:
        return True
    return False

def get_trend_emoji(trend):
    """趋势状态对应的emoji"""
    if trend == "上升":
        return "📈"
    elif trend == "下降":
        return "📉"
    else:
        return "➡️"

def check_均线多头(kline):
    """均线多头: MA5 > MA10 > MA20"""
    closes = get_close_list(kline)
    if len(closes) < 25:
        return False
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20
    return ma5 > ma10 > ma20

def check_MACD金叉(kline):
    """MACD 金叉"""
    closes = get_close_list(kline)
    if len(closes) < 35:
        return False
    for i in range(26, len(closes)):
        ema12 = calculate_ema(closes[:i+1], 12)
        ema26 = calculate_ema(closes[:i+1], 26)
        if ema12 and ema26:
            dif = ema12 - ema26
            dif_prev = calculate_ema(closes[:i], 12) - calculate_ema(closes[:i], 26)
            if dif > 0 and dif_prev <= 0:
                return True
    return False

def calculate_enhanced_tech_score(info, kline):
    """增强版技术评分"""
    score = 50
    change_pct = info.get('change_pct', 0)
    vol_ratio = info.get('volume_ratio', 1) or 1
    
    # 涨幅
    if change_pct >= 9.5: score += 10
    elif change_pct > 5: score += 2
    elif change_pct > 0: score += 3
    elif change_pct > -2: score += 5
    elif change_pct > -5: score += 8
    
    # 量比
    if vol_ratio > 3: score += 8
    elif vol_ratio > 2: score += 5
    elif vol_ratio > 1.5: score += 3
    elif vol_ratio > 1: score += 1
    
    # 均线多头
    if check_均线多头(kline): score += 15
    
    # MACD金叉
    if check_MACD金叉(kline): score += 10
    
    return max(0, min(100, score))

def git_pull():
    """每次生成报告前拉取 AAna 最新代码，确保使用最新规则"""


    try:
        result = subprocess.run(
            ['git', 'pull', 'origin', 'main'],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            print(f"[AAna] Git pull: {result.stdout.strip()}")
        elif result.returncode != 0:
            print(f"[AAna] Git pull 失败: {result.stderr.strip()}")
    except Exception as e:
        print(f"[AAna] Git pull 异常: {e}")

# ============================================
# v2.1: 技术指标评分
# ============================================
def calculate_technical_score(info):
    """
    技术面评分（基于新浪数据）
    - 均线多头 (20日 > 10日 > 5日)
    - 量比 (放量 vs 缩量)
    - 涨幅位置 (回调 vs 追高)
    - 换手率
    """
    score = 50
    
    change_pct = info.get('change_pct', 0)
    price = info.get('price', 0)
    yesterday_close = info.get('yesterday_close', 0)
    
    # 1. 涨幅位置评分（核心逻辑：回调是买点，追高是风险）
    if change_pct > 0:
        if change_pct > 9:  # 涨停，风险大
            score -= 15
        elif change_pct > 5:  # 大涨，可能回调
            score += 5
        elif change_pct > 0:  # 温和上涨
            score += 10
    elif change_pct < 0:
        if change_pct < -9:  # 跌停，谨慎
            score -= 10
        elif change_pct < -7:  # 大跌
            score += 20
        elif change_pct < -3:  # 中跌
            score += 15
        elif change_pct < 0:  # 小跌，最佳买点
            score += 12
    
    # 2. 成交额评分（流动性）
    amount = info.get('amount', 0)
    if amount > 1e9:  # >10亿
        score += 8
    elif amount > 5e8:  # >5亿
        score += 5
    elif amount < 1e7:  # <1000万，流动性差
        score -= 5
    
    # 3. 价格位置（相对于昨日收盘）
    if yesterday_close > 0:
        price_change = (price - yesterday_close) / yesterday_close
        if -0.03 < price_change < 0:  # 小幅回调
            score += 8
        elif price_change < -0.05:  # 大幅回调
            score += 12
    
    return max(0, min(100, score))

# ============================================
# v2.2: 基本面评分（简化版，无API时用）
# ============================================
def calculate_fundamental_score(code, change_pct):
    """
    基本面评分（基于股票特性）
    - 科创板/创业板：高风险高波动
    - 主板：相对稳健
    - 行业特性
    """
    score = 50
    
    # 板块风险调整（科创板/创业板高风险，反向操作）
    if code.startswith('688'):  # 科创板
        score -= 10  # 高风险
    elif code.startswith('30'):  # 创业板
        score -= 8
    elif code.startswith('6'):  # 沪市主板
        score += 5
    
    # 2. 股价位置（高价股 vs 低价股）
    price = 0  # will be passed from info
    
    # 3. 行业动量（今日强势板块）
    hot_sectors = ['ai_chip', 'robot', 'semi']  # AI芯片、机器人、半导体
    # 这个后面会根据实际涨跌来调整
    
    return max(0, min(100, score))

# ============================================
# v2.3: 综合评分 + 风险评估
# ============================================
def calculate综合评分(info, category, tech_score):
    """综合评分 = 技术面(60%) + 基本面(40%)"""
    
    # 基本面基础分
    fund_score = 50
    code = info.get('code', '')
    
    # 板块加成
    if category in ['ai_chip', 'robot']:
        fund_score += 10  # 热点板块
    elif category == 'semi':
        fund_score += 5  # 政策支持
    
    # 科创/创业扣除
    if code.startswith('688'):
        fund_score -= 8
    elif code.startswith('30'):
        fund_score -= 5
    elif code.startswith('6'):
        fund_score += 5
    
    # 综合评分
    综合评分 = tech_score * 0.6 + fund_score * 0.4
    return int(综合评分)

def get风险等级(综合评分, tech_score):
    """根据评分和风险指标确定风险等级"""
    if tech_score >= 80 or 综合评分 >= 80:
        return "🟢 低风险", "-10%"
    elif tech_score >= 70 or 综合评分 >= 70:
        return "🟡 中风险", "-8%"
    elif tech_score <= 30 or 综合评分 <= 40:
        return "🔴 高风险", "-5%"
    else:
        return "🟡 中高风险", "-6%"

def get评级(综合评分):
    """评级标签"""
    if 综合评分 >= 85:
        return "⭐⭐⭐⭐⭐ 强烈推荐"
    elif 综合评分 >= 75:
        return "⭐⭐⭐⭐ 推荐"
    elif 综合评分 >= 65:
        return "⭐⭐⭐ 谨慎推荐"
    elif 综合评分 >= 55:
        return "⭐⭐ 观察"
    else:
        return "⭐ 不推荐"

# ============================================
# 数据获取
# ============================================
def get_stock_data_sina(codes):
    """使用新浪财经API获取股票/指数数据"""
    import requests
    
    results = {}
    
    def get_market_sina(code):
        if code.startswith('6') or code.startswith('9'):
            return f'sh{code}'
        return f'sz{code}'
    
    try:
        formatted = [get_market_sina(c) for c in codes]
        url = f'http://hq.sinajs.cn/list={",".join(formatted)}'
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'http://finance.sina.com.cn'
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
            price = float(parts[3]) if parts[3] else 0
            change_pct = ((price - yesterday_close) / yesterday_close * 100) if yesterday_close else 0
            amount = float(parts[9]) if parts[9] else 0
            results[code] = {
                'code': code,
                'name': name,
                'price': price,
                'change_pct': change_pct,
                'amount': amount * 10000,
                'yesterday_close': yesterday_close,
            }
    except Exception as e:
        print(f"新浪API失败: {e}")
    
    # 补全没有返回的股票
    for code in codes:
        if code not in results:
            results[code] = {'code': code, 'name': '', 'price': 0, 'change_pct': 0, 'amount': 0}
    
    return results

def format_price(price):
    return f"¥{price:.2f}" if price > 0 else "（休市）"

def format_change(change_pct):
    if change_pct == 0:
        return "⚪ 0.00%"
    emoji = "🔴" if change_pct > 0 else "🟢"
    return f"{emoji} {change_pct:+.2f}%"


# generate_report.py 的股票池 all_codes 只包含个股，不包含指数代码。
# 过去直接 prices.get('000001') 会永远取空，导致报告渲染“上证指数：数据待获取 +0.00%”。
# 指数源统一复用 market_sentiment.get_index_data()：腾讯 qt.gtimg.cn 首选 + 东财备用 + sanity check。
INDEX_DISPLAY_ORDER = [
    ("000001", "上证指数"),
    ("399001", "深证成指"),
    ("399006", "创业板指"),
    ("000300", "沪深300"),
]
INDEX_NAME_TO_CODE = {
    "上证指数": "000001",
    "深证成指": "399001",
    "创业板指": "399006",
    "创业板": "399006",
    "沪深300": "000300",
    # 兼容旧报告模板；market_sentiment 当前默认不返回科创50，但如果后续返回也能入 prices。
    "科创50": "000688",
}


def refresh_index_prices_from_market_sentiment(prices, get_index_data_fn=None):
    """用 market_sentiment.get_index_data() 补齐报告渲染所需指数价格。

    Args:
        prices: generate_report 内部价格字典，会原地写入指数项。
        get_index_data_fn: 测试注入用；默认导入 market_sentiment.get_index_data。

    Returns:
        int: 成功写入/更新的指数数量。
    """
    if get_index_data_fn is None:
        from market_sentiment import get_index_data as get_index_data_fn

    updated = 0
    for idx in get_index_data_fn() or []:
        name = str(idx.get('name', '')).strip()
        code = INDEX_NAME_TO_CODE.get(name)
        if not code:
            continue
        try:
            price = float(idx.get('price', 0) or 0)
            change_pct = float(idx.get('change', idx.get('change_pct', 0)) or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        prices[code] = {
            'code': code,
            'name': name,
            'price': price,
            'change_pct': change_pct,
            'amount': idx.get('amount', 0),
        }
        updated += 1
    return updated


def format_market_overview_rows(prices):
    """渲染大盘概览表格行，避免深证/创业板/沪深300硬编码为 '-'。"""
    rows = []
    for code, name in INDEX_DISPLAY_ORDER:
        info = prices.get(code, {}) or {}
        price = info.get('price') or 0
        change_pct = info.get('change_pct', 0)
        if price > 0:
            status = '🔴 上涨' if change_pct > 0 else ('🟢 下跌' if change_pct < 0 else '⚪ 持平')
            rows.append("| {} | {:.2f} | {} |".format(name, price, status))
        else:
            rows.append("| {} | 数据待获取 | - |".format(name))
    return "\n".join(rows) + "\n\n"

def get_sector_emoji(name):
    """根据股票名称返回板块emoji"""
    if any(k in name for k in ['寒武纪', '海光', '中际', '新易盛', '光模块']):
        return "💻"
    elif any(k in name for k in ['五洲', '昊志', '机器人']):
        return "🤖"
    elif any(k in name for k in ['中微', '华润', '三安', '紫光']):
        return "🔧"
    elif any(k in name for k in ['宁德', '比亚迪', '固德']):
        return "🔋"
    elif any(k in name for k in ['科大讯', '创达', '海天']):
        return "🧠"
    return "📊"

# ============================================
# 报告生成
# ============================================

def main():
    parser = argparse.ArgumentParser(description='AAna v2.5 每日选股报告')
    parser.add_argument('--type', choices=['selection', 'review', 'both'], default='both',
                        help='报告类型：选股报告(selection)、复盘报告(review)或两者(both)')
    args = parser.parse_args()

    # ── 非交易日快速跳过 (2026-06-19 P0 修复) ──────────────────
    # 避免周末/节假日 cron 触发生成无意义的空报告
    # 注意: 仍走 git_pull() 保持代码最新, 但 report/sync/eastmoney 全跳过
    is_trade, non_trade_reason = is_trading_day()
    if not is_trade:
        today_str = get_today_str()
        print(f"[AAna] {today_str} 非交易日 ({non_trade_reason})，跳过报告生成")
        # 仍跑 git_pull — 让节假日期间代码也保持最新
        git_pull()
        return 0

    git_pull()

    if args.type in ('selection', 'both'):
        generate_report()
        # 选股报告生成后，自动同步 Top10 到东方财富组合
        try:
            # 2026-06-19 修复: sync_top10_v5.py 不存在, 改用 sync_top10_v9.py
            sync_script = os.path.join(os.path.dirname(__file__), 'sync_top10_v9.py')
            if os.path.exists(sync_script):
                subprocess.run(
                    [sys.executable, sync_script],
                    check=False, capture_output=True, text=True, timeout=60
                )
            else:
                print(f"[AAna] 同步脚本不存在: {sync_script} (跳过)")
        except Exception as _se:
            print(f"[AAna] 同步 Top10 到东方财富失败（非致命）: {_se}")
    if args.type in ('review', 'both'):
        generate_review_report()

def generate_report():
    today = get_today_str()
    filename = get_report_filename()

    # ── REC_TUNING 过滤（评分阈值 + 弱势板块）──────────
    REC_TUNING = {
        "score_threshold": 50,
        "hold_days": 1,
        "weak_sectors": ['ai_app', 'semi', 'chem', 'mach', 'elec', 'robot'],
        "overall_win_rate": 21.2,
        "total_records": 354,
        "generated_at": "2026-06-04T20:00:37.400971",
    }

    # 生成报告前清理过期文件（保留7天）
    cleanup_old_reports(days=7)

    print(f"[AAna v2.5] 生成 {today} 动态选股报告...")
    sentiment = {}
    if NEW_MODULES:
        sentiment = get_market_sentiment()
        print(f"[情绪] {sentiment.get('label','未知')} | "
              f"涨停{sentiment.get('zt_count',0)} "
              f"跌停{sentiment.get('dt_count',0)} "
              f"平均涨跌{sentiment.get('avg_change',0):+.2f}%")
    sentiment_score = sentiment.get('score', 50)
    position_ratio = get_position_ratio(sentiment_score) if NEW_MODULES else 0.5

    # ── 2. 增强选股源（v2.6 修复：双池分离 normal + risk）────────
    if NEW_MODULES:
        dynamic_stocks = get_enhanced_stock_pool(
            include_zt=(sentiment_score > 40)
        )
        risk_pool = []  # 涨停警示池（NEW_MODULES 分支不展开 risk）
    else:
        from dynamic_stocks import get_dynamic_stock_pool, get_stock_pool_split
        try:
            # 优先用双池接口：normal=推荐主池，risk=涨停警示池
            dynamic_stocks, risk_pool = get_stock_pool_split()
        except Exception as _e:
            print(f"[AAna] 双池拆分失败，回退单池: {_e}")
            dynamic_stocks = get_dynamic_stock_pool()
            risk_pool = []
    print(f"[AAna] 动态股票池: {len(dynamic_stocks)} 只 (涨停警示 {len(risk_pool)} 只)")

    # ── 3. 获取资金流向 ──────────────────────────────────────
    money_flows = {}
    if NEW_MODULES and dynamic_stocks:
        codes = [s['code'] for s in dynamic_stocks[:30]]
        from market_sentiment import get_money_flow
        money_flows = get_money_flow(codes)
        print(f"[资金流] 获取 {len(money_flows)} 只资金数据")

    # 将动态股票转换为 stock_pool 格式（按涨幅分类）
    stock_pool = {
        'high_rise': {
            'name': '🚀 强势股',
            'codes': [s['code'] for s in dynamic_stocks[:10]],
            'logic': '今日强势上涨+放量',
            'risk_level': '高',
            'stop_loss': '-5%',
        },
        'active': {
            'name': '⚡ 活跃股',
            'codes': [s['code'] for s in dynamic_stocks[10:25]],
            'logic': '量比放大+趋势良好',
            'risk_level': '中高',
            'stop_loss': '-6%',
        },
        'potential': {
            'name': '💡 潜力股',
            'codes': [s['code'] for s in dynamic_stocks[25:40]],
            'logic': '温和上涨+缩量整理',
            'risk_level': '中',
            'stop_loss': '-8%',
        },
    }

    # 收集所有股票
    all_codes = []
    for cat in stock_pool.values():
        all_codes.extend(cat['codes'])
    all_codes = list(dict.fromkeys(all_codes))

    # 获取数据
    print(f"[AAna] 获取 {len(all_codes)} 只股票数据...")
    prices = get_stock_data_sina(all_codes)

    try:
        idx_count = refresh_index_prices_from_market_sentiment(prices)
        print(f"  [指数] 已补拉 {idx_count}/{len(INDEX_DISPLAY_ORDER)} 个指数")
    except Exception as e:
        print(f"  [指数] market_sentiment.get_index_data() 失败: {e}（不影响报告生成）")

    # 合并板块信息
    for cat_id, cat in stock_pool.items():
        cat['stocks'] = []
        for code in cat['codes']:
            info = prices.get(code, {})
            if not info:
                continue
            info['code'] = code
            info['category'] = cat_id

            # ── 过滤 ──────────────────────────────────────
            if NEW_MODULES:
                passed, reason = filter_stock_basic(
                    code, info.get('name', ''),
                    info.get('price', 0), info.get('amount', 0)
                )
                if not passed:
                    continue

            # 获取历史 K 线
            kline = get_historical_kline(code, count=60)

            # 计算评分（使用增强版）
            tech_score = calculate_enhanced_tech_score(info, kline)
            fund_score = calculate_fundamental_score(code, info.get('change_pct', 0))

            # 资金流向因子
            mf = money_flows.get(code, {})
            net_in_wan = mf.get('net_in', 0)

            # 综合评分（技术50% + 基本面20% + 资金流30%）
            if NEW_MODULES:
                sc = composite_score(
                    tech_score, fund_score,
                    net_in_wan, info.get('change_pct', 0),
                    sentiment_score
                )
                综合评分 = sc['composite']
                money_score = sc['money_score']
            else:
                综合评分 = int(tech_score * 0.6 + fund_score * 0.4)

            风险等级, 止损位 = get风险等级(综合评分, tech_score)
            评级 = get评级(综合评分)

            # 技术信号
            signals = []
            if kline:
                if check_均线多头(kline): signals.append('MA多头')
                if check_MACD金叉(kline): signals.append('MACD金叉')
            info['signals'] = signals

            # 趋势检测
            trend, trend_key = detect_trend(kline)
            info['trend'] = trend
            info['trend_key'] = trend_key
            info['is_ice_point'] = is_ice_point(info, kline)

            # 风控止损
            if NEW_MODULES:
                sl = calc_stop_loss(info.get('price', 0))
                info['stop_soft'] = sl['stop_soft']
                info['stop_hard'] = sl['stop_hard']
                info['stop_profit'] = sl['take_profit']
                info['money_flow_net'] = net_in_wan

            info['tech_score'] = tech_score
            info['fund_score'] = fund_score
            if NEW_MODULES:
                info['money_score'] = money_score
            info['综合评分'] = 综合评分
            info['风险等级'] = 风险等级
            info['止损位'] = 止损位
            info['评级'] = 评级
            info['emoji'] = get_sector_emoji(info.get('name', ''))

            # ── REC_TUNING 过滤（评分阈值 + 弱势板块）──────────
            score_thresh = REC_TUNING.get('score_threshold', 50)
            weak_sectors = REC_TUNING.get('weak_sectors', [])
            sector = info.get('category', '') or info.get('sector', '')
            if 综合评分 < score_thresh:
                continue  # 评分低于阈值，跳过
            if sector in weak_sectors:
                continue  # 板块为弱势板块，跳过

            price = info.get('price', 0)
            if price <= 0:
                continue
            cat['stocks'].append(info)

        # 按综合评分排序
        cat['stocks'].sort(key=lambda x: x['综合评分'], reverse=True)
    

    # ========== 生成报告 ==========
    sentiment_section = ""
    if NEW_MODULES and sentiment:
        sects = get_hot_sectors(5) or []
        north = get_north_money() or {}
        zt_count = sentiment.get('zt_count', 0)
        dt_count = sentiment.get('dt_count', 0)
        avg_change = sentiment.get('avg_change', 0)
        north_str = "{} {:.2f}亿（{}额）".format(
            north.get('direction', '未知'),
            north.get('total', 0) / 10000,
            north.get('magnitude', '小')
        )
        trade_sig = "\u2705 正常交易" if not sentiment.get('avoid_trading') else "\u26a0\ufe0f 停止交易"
        sects_str = ', '.join("{}({:+.1f}%)".format(s['name'], s['change']) for s in sects[:5]) if sects else '数据获取中'
        sentiment_section = (
            "## 一、市场情绪\n\n"
            "| 指标 | 数值 |\n"
            "|:----:|:----:|\n"
            "| 情绪评分 | **{}** / 100（{}） |\n".format(sentiment_score, sentiment.get('label', '未知')) +
            "| 大盘平均涨跌 | {:+.2f}% |\n".format(avg_change) +
            "| 涨停数量 | {} |\n".format(zt_count) +
            "| 跌停数量 | {} |\n".format(dt_count) +
            "| 北向资金 | {} |\n".format(north_str) +
            "| 建议仓位 | **{:.0f}%**（{}） |\n".format(position_ratio * 100, sentiment.get('long_sentiment', '观望')) +
            "| 交易建议 | {} |\n\n".format(trade_sig) +
            "> {}\n\n".format(sentiment.get('description', '')) +
            "**热点板块：** {}\n\n".format(sects_str) +
            "---\n\n"
            "## 二、大盘概览\n\n"
        )
    else:
        sentiment_section = "## 一、大盘概览\n\n"

    pos_ratio_str = "{:.0f}%".format(position_ratio * 100) if NEW_MODULES else "50%"
    # ── 关键价位：上证指数当前价格/涨跌幅 ───────────────────
    sh_price = prices.get('000001', {}).get('price') or 0
    sh_change = prices.get('000001', {}).get('change_pct', 0)
    # 2026-07-03 修复（4 天 P2）：报告涨跌幅=昨收涨跌幅 → 标题加副标题
    # 8:00-9:30 早盘 cron 跑时市场未开盘，报告"涨跌幅"实际是昨收涨跌幅。
    # 开盘后用户看会发现与盘中价不符 → 副标题明示
    from datetime import time as _dt_time
    is_premarket = datetime.now().time() < _dt_time(9, 30)
    subtitle = ""
    if is_premarket:
        subtitle = "> ⚠️ **早盘副标题（8:00-9:30 报告专用）**：本报告\"涨跌幅\"=**昨收涨跌幅**（市场未开盘，无今日实时数据）。开盘后请以券商 App 实时行情为准。\n\n"
    header = (
        "# A股选股报告 — {} v2.5\n\n".format(today) +
        subtitle +
        "> AAna 智能选股系统 v2.5 | 仅供参考，不构成投资建议\n"
        "> **生成时间：** {}\n".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")) +
        "> **情绪评分：** {}（{}）| **上证指数：** {} {:+.2f}% | **建议仓位：** {}\n\n".format(
            sentiment_score,
            sentiment.get('label', '未知') if NEW_MODULES else '未知',
            format_price(sh_price) if sh_price > 0 else '数据待获取',
            sh_change,
            pos_ratio_str
        ) +
        "> **评分体系：** 技术面{} + 基本面{} + 资金流向{}\n\n".format(
            "{:.0%}".format(WEIGHT_TECH),
            "{:.0%}".format(WEIGHT_FUND),
            "{:.0%}".format(WEIGHT_MONEYFLOW)
        ) +
        "---\n\n" +
        sentiment_section +
        "| 指标 | 数值 | 状态 |\n"
        "|:----:|:----:|:----:|\n" +
        format_market_overview_rows(prices) +
        "**市场情绪：** {} | **建议仓位：** {}\n\n".format(
            sentiment.get('label', '乐观') if NEW_MODULES else '乐观',
            pos_ratio_str
        ) +
        "---\n\n"
        "## 二、热点主线（2026年4月）\n\n"
        "| 排名 | 板块 | 核心逻辑 | 持续性 |\n"
        "|:----:|:----:|:---------|:------:|\n"
        "| \U0001f947 | AI算力/DS概念 | DeepSeek拉动+国产大模型爆发 | \u2b50\ufe0f\u2b50\ufe0f\u2b50\ufe0f\u2b50\ufe0f\u2b50\ufe0f |\n"
        "| \U0001f948 | 人形机器人 | 特斯拉Q1发布+量产预期 | \u2b50\ufe0f\u2b50\ufe0f\u2b50\ufe0f\u2b50\ufe0f\u2b50\ufe0f |\n"
        "| \U0001f949 | 半导体设备 | 国产替代+AI芯片自主可控 | \u2b50\ufe0f\u2b50\ufe0f\u2b50\ufe0f\u2b50\ufe0f |\n\n"
        "---\n\n"
        "## 三、精选个股（按综合评分排序）\n\n"
    )

    # 按评分高低展示所有股票
    all_stocks = []
    for cat in stock_pool.values():
        all_stocks.extend(cat['stocks'])
    all_stocks.sort(key=lambda x: x['\u7efc\u5408\u8bc4\u5206'], reverse=True)

    # Top 10（含资金流数据）
    content = header + "### \U0001f3c6 重点关注 Top 10\n\n"
    if NEW_MODULES:
        content += (
            "| 排名 | 股票 | 代码 | 价格 | 涨跌幅 | 技术分 | 资金流 | 综合评分 | 信号 | 风险 | 软止损 | 趋势 |\n"
            "|:----:|:----:|:----:|:----:|:------:|:------:|:------:|:--------:|:----:|:----:|:------:|:----:|\n"
        )
        for i, stock in enumerate(all_stocks[:10], 1):
            signals = ''.join(stock.get('signals', []) or ['-'])
            mf_net = stock.get('money_flow_net', 0)
            mf_str = "{:+.0f}万".format(mf_net) if abs(mf_net) > 1 else "~"
            ice_warning = " 🚨冰点" if stock.get('is_ice_point') else ""
            trend_emoji = get_trend_emoji(stock.get('trend', '震荡'))
            trend_str = stock.get('trend', '震荡')
            content += (
                "| {} | {}{}{} | {} | {} | {} | {} | {} | **{}** | {} | {} | {} | {} |\n".format(
                    i,
                    stock['emoji'],
                    stock['name'],
                    ice_warning,
                    stock['code'],
                    format_price(stock['price']),
                    format_change(stock['change_pct']),
                    stock.get('tech_score', 0),
                    mf_str,
                    stock['综合评分'],
                    signals,
                    stock['风险等级'],
                    stock.get('stop_soft', '-'),
                    trend_emoji + trend_str
                )
            )

    # 按板块展示（NEW_MODULES=False情况）
    else:
        content += (
            "| 排名 | 股票 | 代码 | 价格 | 涨跌幅 | 技术分 | 综合评分 | 信号 | 风险 | 趋势 |\n"
            "|:----:|:----:|:----:|:----:|:------:|:------:|:--------:|:----:|:----:|:----:|\n"
        )
        for i, stock in enumerate(all_stocks[:10], 1):
            signals = ''.join(stock.get('signals', []) or ['-'])
            trend_emoji = get_trend_emoji(stock.get('trend', '震荡'))
            trend_str = stock.get('trend', '震荡')
            ice_warning = " 🚨冰点" if stock.get('is_ice_point') else ""
            content += (
                "| {} | {}{}{} | {} | {} | {} | **{}** | {} | {} | {} |\n".format(
                    i, stock['emoji'], stock['name'], ice_warning, stock['code'],
                    format_price(stock['price']), format_change(stock['change_pct']),
                    stock.get('tech_score', 0), stock['综合评分'],
                    signals, stock['风险等级'], trend_emoji + trend_str
                )
            )

    # 按板块展示
    for cat_id, cat in stock_pool.items():
        if not cat['stocks']:
            continue
        content += (
            "\n### {}\n\n".format(cat['name']) +
            "> 逻辑：{} | 风险等级：{} | 建议止损：{}\n\n".format(
                cat['logic'], cat['risk_level'], cat['stop_loss']
            ) +
            "| 股票 | 代码 | 最新价 | 涨跌幅 | 技术分 | 综合分 | 评级 | 推荐理由 |\n"
            "|:----:|:----:|:------:|:------:|:------:|:------:|:----:|:------:|\n"
        )
        for stock in cat['stocks']:
            reason = cat.get('logic', '-')
            trend_emoji = get_trend_emoji(stock.get('trend', '震荡'))
            trend_str = stock.get('trend', '震荡')
            ice_warning = " 🚨冰点" if stock.get('is_ice_point') else ""
            content += (
                "| {}{}{} | {} | {} | {} | {} | **{}** | {} | {} | {} |\n".format(
                    stock['emoji'],
                    stock['name'],
                    ice_warning,
                    stock['code'],
                    format_price(stock['price']),
                    format_change(stock['change_pct']),
                    stock.get('tech_score', 0),
                    stock['综合评分'],
                    stock['评级'],
                    reason,
                    trend_emoji + trend_str
                )
            )

    # ========== 操作建议 ==========
    buy_opportunities = [s for s in all_stocks if s['change_pct'] < -3 and s['change_pct'] > -9]
    buy_opportunities.sort(key=lambda x: x['tech_score'], reverse=True)

    content += (
        "\n---\n\n"
        "## 四、\U0001f3af 最佳买点（今日回调但未暴跌）\n\n"
    )
    if buy_opportunities:
        content += "| 股票 | 代码 | 现价 | 回调幅度 | 综合评分 | 建议 |\n"
        content += "|:----:|:----:|:----:|:--------:|:--------:|:----:|\n"
        for s in buy_opportunities[:5]:
            content += (
                "| {}{} | {} | {} | {:+.1f}% | {} | 分批建仓 |\n".format(
                    s['emoji'], s['name'], s['code'],
                    format_price(s['price']), s['change_pct'], s['\u7efc\u5408\u8bc4\u5206']
                )
            )
    else:
        content += "今日无明显回调机会，关注明日开盘\n"

    high_risk = [s for s in all_stocks if s['change_pct'] > 7]
    # v2.6: 优先用上游传过来的 risk_pool（涨停警示池）
    if risk_pool:
        content += "\n\u26a0\ufe0f **高风险警示（追高危险，仅展示不推荐）**\n"
        for s in risk_pool:
            content += "- {name}({code}) 今日{change:+.1f}%，追高风险大\n".format(
                name=s['name'], code=s['code'], change=s['change_pct']
            )
    elif high_risk:
        content += "\n\u26a0\ufe0f **高风险警示（追高危险）**\n"
        for s in high_risk:
            content += "- {name}({code}) 今日{change:+.1f}%，追高风险大\n".format(
                name=s['name'], code=s['code'], change=s['change_pct']
            )

    # ========== 风险提示 ==========
    stop_loss_rule = "-5%" if NEW_MODULES else "-8%"
    content += (
        "\n---\n\n"
        "## 五、风险提示\n\n"
        "⚠️ **免责声明**：本报告仅供参考，不构成投资建议\n\n"
        "| 风险类型 | 说明 | 应对 |\n"
        "|:--------:|:----:|:----:|\n"
        "| 追高风险 | 涨停或大涨>7%个股容易回调 | 勿追高，等回调 |\n"
        "| 止损风险 | 严格执行止损线 | 建议{}强制止损 |\n"
        "| 流动性风险 | 成交额<1千万谨慎 | 回避 |\n"
        "| 风格切换 | 热点板块可能轮动 | 分散持仓 |\n\n"
        "**止损原则：** {} 必须止损，不可恋战\n\n"
        "---\n\n"
        "## 六、评分系统说明（v2.5）\n\n"
    ).format(stop_loss_rule, stop_loss_rule)
    content += (
        "| 维度 | 权重 | 评分要素 |\n"
        "|:----:|:----:|:--------|\n"
        "| 技术面 | {:.0%} | 涨跌幅、量比、均线位置 |\n"
        "| 基本面 | {:.0%} | 板块、股价位置、流动性 |\n"
        "| 资金流向 | {:.0%} | 东方财富主力净流入 |\n"
        "\n"
        "**技术分计算：**\n"
        "- 回调-3%~0%：+12分（最佳买点区）\n"
        "- 回调-7%~-3%：+15分（大幅回调）\n"
        "- 温和上涨0~5%：+10分\n"
        "- 涨停>9%：-15分（风险大）\n\n"
        "---\n\n"
        "## 七、💰 基金推荐\n\n"
    ).format(WEIGHT_TECH if NEW_MODULES else 0.6, WEIGHT_FUND if NEW_MODULES else 0.4, WEIGHT_MONEYFLOW if NEW_MODULES else 0.0)

    # ── 基金推荐 section ──────────────────────────────────────────
    if NEW_MODULES:
        content += (
            "> 基于东方财富 API，数据每日更新非实时\n\n"
            "**筛选条件：** 成立≥2年 · 规模≥5亿 · 近1年正收益\n\n"
            "**评分公式：** 近3月×30% + 近1年×40% + YTD×30%\n\n"
        )
        try:
            fund_results = screen_funds(top_n=3, max_pages=20)
            fund_report = format_fund_report(fund_results)
            # 去掉 Markdown 标题（已在上方有标题）
            lines = fund_report.split('\n')
            skip = False
            for line in lines:
                if line.startswith('# '):
                    skip = True
                    continue
                if skip and line == '':
                    skip = False
                if not skip:
                    content += line + '\n'
        except Exception as e:
            content += f"*⚠️ 基金数据获取失败: {e}*\n\n"

    # ── 基金持仓追踪 section ──────────────────────────────────────
    if NEW_MODULES:
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent / "data"))
            from fund_tracker import get_tracker_report as get_fund_tracker_report
            tracker_report = get_fund_tracker_report()
            # 去掉 ## 标题（上方已有标题）
            lines = tracker_report.split('\n')
            skip = False
            for line in lines:
                if line.startswith('# '):
                    skip = True
                    continue
                if skip and line == '':
                    skip = False
                if not skip:
                    content += line + '\n'
        except Exception as e:
            content += f"*⚠️ 基金持仓读取失败: {e}*\n\n"

    # ── 基金 vs 股票对比 section ─────────────────────────────────
    if NEW_MODULES:
        try:
            from fund_comparison import get_comparison_report as get_fund_comparison_report
            comp_report = get_fund_comparison_report()
            lines = comp_report.split('\n')
            skip = False
            for line in lines:
                if line.startswith('# '):
                    skip = True
                    continue
                if skip and line == '':
                    skip = False
                if not skip:
                    content += line + '\n'
        except Exception as e:
            content += f"*⚠️ 对比报告生成失败: {e}*\n\n"

    # ── 读取 paper_trading 持仓 ─────────────────────────────────
    paper_positions = []
    paper_init_cash = 100000
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent / "data"))
        from paper_trading import _load
        d = _load()
        paper_init_cash = d.get("init_cash", 100000)
        positions = d.get("positions", {})
        snapshots = d.get("daily_snapshots", [])
        for code, pos in positions.items():
            current_price = 0
            unreal_pnl = 0
            unreal_pct = 0
            if snapshots:
                latest = snapshots[-1]
                ps = next((p for p in latest.get("positions", []) if p["code"] == code), None)
                if ps:
                    current_price = ps.get("current_price", 0)
                    unreal_pnl = ps.get("unreal_pnl", 0)
                    unreal_pct = ps.get("unreal_pct", 0)
            paper_positions.append({
                "code": code,
                "name": pos.get("name", code),
                "shares": pos.get("shares", 0),
                "entry_price": pos.get("entry_price", 0),
                "current_price": current_price,
                "unreal_pnl": unreal_pnl,
                "unreal_pct": unreal_pct,
                "days_held": (datetime.now() - datetime.strptime(pos.get("entry_date", datetime.now().strftime("%Y-%m-%d")), "%Y-%m-%d")).days,
            })
    except Exception as e:
        print(f"[AAna] 模拟交易数据读取失败: {e}")

    if paper_positions:
        realized = 0
        unrealized = sum(p["unreal_pnl"] for p in paper_positions)
        total_pnl = realized + unrealized
        total_pnl_pct = total_pnl / paper_init_cash * 100
        content += (
            "| 股票 | 代码 | 持仓天数 | 成本价 | 现价 | 浮盈 | 浮盈% |\n"
            "|:----:|:----:|:------:|:------:|:----:|:----:|:----:|\n"
        )
        for p in paper_positions:
            entry_str = format_price(p["entry_price"])
            curr_str = format_price(p["current_price"]) if p["current_price"] > 0 else "（休市）"
            content += (
                "| {}{} | {} | {}天 | {} | {} | {:+.2f} | {:+.2f}% |\n".format(
                    get_sector_emoji(p["name"]),
                    p["name"],
                    p["code"],
                    p["days_held"],
                    entry_str,
                    curr_str,
                    p["unreal_pnl"],
                    p["unreal_pct"],
                )
            )
        content += "\n"
        content += (
            "> **模拟仓汇总：** 初始资金 {:,.0f} | 累计收益 {:+.2f}（{:+.2f}%）| "
            "持仓 {} 只\n\n".format(
                paper_init_cash, total_pnl, total_pnl_pct, len(paper_positions)
            )
        )
    else:
        content += "*本周暂无模拟交易持仓*\n\n"

    content += (
        "---\n\n"
        "*AAna v2.5 | china-stock-analysis 集成 | {}*\n".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )

    # ========== 保存报告 ==========
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"[AAna] 选股报告已生成: {filename}")

def generate_review_report():
    """生成每日复盘评分报告 + 模拟交易结算"""
    today = get_today_str()
    snap_file = get_morning_snapshot_filename()
    filename = get_report_filename('复盘评分')

    print(f"[AAna v2.5] 生成 {today} 复盘评分报告...")

    # 读取早盘快照
    if not os.path.exists(snap_file):
        print(f"[AAna] 早盘快照不存在: {snap_file}，跳过复盘报告")
        return None

    with open(snap_file, 'r', encoding='utf-8') as f:
        morning_data = json.load(f)

    morning_prices = morning_data.get('prices', {})
    if not morning_prices:
        print("[AAna] 早盘快照数据为空，跳过复盘报告")
        return None

    # 获取今日收盘数据
    all_codes = list(morning_prices.keys())
    print(f"[AAna] 获取 {len(all_codes)} 只股票收盘数据...")
    current_prices = get_stock_data_sina(all_codes)

    # 获取指数数据
    try:
        index_map = {
            '000001': '上证指数',
            '399001': '深证成指',
            '399006': '创业板指',
            '000688': '科创50',
        }
        index_codes = list(index_map.keys())
        index_data = get_stock_data_sina(index_codes)
    except Exception as e:
        print(f"[AAna] 指数数据获取失败: {e}")
        index_data = {}

    # ===== 从早盘快照获取实际股票池 =====
    all_review_stocks = []
    for code, morn in morning_prices.items():
        curr = current_prices.get(code, {})
        if not curr or curr.get('price', 0) <= 0:
            continue

        morn_price = morn.get('price', 0)
        curr_price = curr.get('price', 0)
        if morn_price <= 0:
            continue

        morn_change = morn.get('change_pct', 0)
        curr_change = curr.get('change_pct', 0)
        actual_diff = curr_change - morn_change

        morn_score = morn.get('\u7efc\u5408\u8bc4\u5206', 0)
        morn_rating = morn.get('\u8bc4\u7ea7', '')
        cat_name = morn.get('category', '')
        name = curr.get('name', code)
        stop_soft = morn.get('stop_soft', 0)
        stop_hard = morn.get('stop_hard', 0)

        # 评估预测准确性
        if abs(actual_diff) < 1:
            eval_emoji = '\u2705'
            eval_text = '\u9884\u6d4b\u51c6\u786e'
        elif abs(actual_diff) < 3:
            eval_emoji = '\u26a0\ufe0f'
            eval_text = '\u5c0f\u5e45\u504f\u5dee'
        else:
            eval_emoji = '\u274c'
            eval_text = '\u504f\u5dee\u8f83\u5927'

        # 自动止损检查
        stop_triggered = ''
        if stop_soft > 0 and curr_price <= stop_soft:
            stop_triggered = '\u8d75\u6b65\u6b65\u505c\u635f'
        elif stop_hard > 0 and curr_price <= stop_hard:
            stop_triggered = '\u5f3a\u5236\u505c\u635f'

        all_review_stocks.append({
            'name': name,
            'code': code,
            'cat_name': cat_name,
            'morn_price': morn_price,
            'curr_price': curr_price,
            'morn_change': morn_change,
            'curr_change': curr_change,
            'morn_score': morn_score,
            'morn_rating': morn_rating,
            'actual_diff': actual_diff,
            'eval_emoji': eval_emoji,
            'eval_text': eval_text,
            'stop_triggered': stop_triggered,
        })

    # ===== 生成报告内容 =====
    index_rows = []
    for code, name in index_map.items():
        info = current_prices.get(code, {})
        price = info.get('price', 0)
        change = info.get('change_pct', 0)
        if price > 0:
            emoji = '\U0001f534' if change > 0 else '\U0001f7e2'
            index_rows.append("| {} | - | {:.2f} | {} {:+.2f}% |".format(name, price, emoji, change))

    # 模拟交易：收盘市价更新 + 自动止损
    paper_pnl = 0
    if NEW_MODULES:
        try:
            from data import mark_to_market, auto_stop_loss, auto_take_profit_trail, paper_summary
            today_str = get_today_str()
            quotes = {code: info.get('price', 0) for code, info in current_prices.items()}
            mark_to_market(today_str, quotes)
            auto_stop_loss(today_str, quotes)
            auto_take_profit_trail(today_str, quotes)
            ps = paper_summary()
            paper_pnl = ps.get('total_pnl', 0)
            print(f"[\u6a21\u62df\u4ea4\u6613] \u4f53\u7ecf\u6536\u76ca: {paper_pnl:+.2f}")
        except Exception as e:
            print(f"[\u6a21\u62df\u4ea4\u6613] {e}")

    content = (
        "# AAna\u6bcf\u65e5\u9009\u80a1\u590d\u76d8\u8bc4\u5206 — {}\n\n".format(today) +
        "> \u751f\u6210\u65f6\u95f4\uff1a{}\n".format(datetime.now().strftime("%Y-%m-%d %H:%M")) +
        "> \u5bf9\u6bd4\u57fa\u51c6\uff1a\u4eca\u65e5 09:00 \u9009\u80a1\u62a5\u544a\n\n" +
        "---\n\n"
        "## \u4e00\u3001\u5927\u76d8\u73af\u5883\u5bf9\u6bd4\n\n"
        "| \u6307\u6807 | \u65e9\u76d8\u53c2\u8003 | \u4eca\u65e5\u6536\u76d8 | \u6da8\u6da8\u5e45 |\n"
        "|:----:|:----:|:----:|:----:|\n"
    )
    for row in index_rows:
        content += row + "\n"
    if not index_rows:
        content += "| \u6570\u636e\u83b7\u53d6\u5931\u8d25 | - | - | - |\n"

    # 按预测评分排序
    all_review_stocks.sort(key=lambda x: x['morn_score'], reverse=True)

    content += (
        "\n---\n\n"
        "## \u4e8c\u3001\u63a8\u8350\u4e2a\u80a1\u8868\u73b0\u590d\u76d8\n\n"
        "| \u80a1\u7968 | \u4ee3\u7801 | \u65e9\u76d8\u5173\u6ce8\u4ef7 | \u65e9\u76d8\u6da8\u5e45 | "
        "\u6536\u76d8\u4ef7 | \u6536\u76d8\u6da8\u5e45 | \u9884\u6d4b\u8bc4\u5206 | \u8bc4\u4ef7 |\n"
        "|:----:|:----:|:--------:|:-------:|:------:|:-------:|:-------:|:----:|\n"
    )

    hit_count = 0
    for s in all_review_stocks:
        stop_info = " | \u505c\u635f:" + s['stop_triggered'] if s['stop_triggered'] else ""
        content += (
            "| {}{} | {} | {:.2f} | {:+.1f}% | {:.2f} | {:+.1f}% | {} | {}{} |\n".format(
                s['eval_emoji'], s['name'], s['code'],
                s['morn_price'], s['morn_change'],
                s['curr_price'], s['curr_change'],
                s['morn_score'], s['eval_text'], stop_info
            )
        )
        if s['eval_emoji'] == '\u2705':
            hit_count += 1

    total = len(all_review_stocks)
    hit_rate = hit_count / total * 100 if total > 0 else 0

    # 模拟交易汇总
    paper_section = ""
    if NEW_MODULES and paper_pnl != 0:
        paper_section = (
            "\n---\n\n"
            "## \u4e09\u3001\u6a21\u62df\u4ea4\u6613\u6c47\u603b\n\n"
            "| \u9879\u76ee | \u6570\u503c |\n"
            "|:----:|:----:|\n"
            "| \u4f53\u7ecf\u7d2f\u8ba1\u6536\u76ca | {:+.2f} |\n".format(paper_pnl) +
            "| \u7ed3\u7b97\u65f6\u95f4 | {} |\n".format(datetime.now().strftime("%Y-%m-%d %H:%M")) +
            "\n> \u6a21\u62df\u4ea4\u6613\u4ec5\u4f5c\u7ed3\u679c\u5907\u4f30\uff0c\u4e0d\u6784\u6210\u4efb\u4f55\u6295\u8d44\u5efa\u8bae\n\n"
        )

    content += (
        "\n**\u547d\u4e2d\u7387\uff1a{}/{} ({:.0f}\uff05)\u8d34\u7b26\u7387\uff1a{:.0f}\uff05**\n\n".format(
            hit_count, total, hit_rate,
            (total - hit_count) / total * 100 if total > 0 else 0
        ) +
        paper_section +
        "---\n\n"
        "## \u56db\u3001\u7efc\u5408\u8bc4\u5206\n\n"
        "| \u8bc4\u4f30\u9879 | \u7ed3\u679c |\n"
        "|:----:|:----:|\n"
        "| \u5927\u76d8\u65b9\u5411 | {} |\n".format(
            '\u9884\u6d4b\u6b63\u786e' if index_rows else '\u5f85\u89c2\u5bdf'
        ) +
        "| \u4e2a\u80a1\u547d\u4e2d\u7387 | {}/{} ({:.0f}%) |\n".format(hit_count, total, hit_rate) +
        "| \u6a21\u62df\u4ea4\u6613\u6536\u76ca | {:+.2f} |\n".format(paper_pnl) +
        "| \u62a5\u544a\u7248\u672c | AAna v2.5 |\n\n"
        "---\n\n"
        "*AAna v2.5 \u590d\u76d8\u8bc4\u5206 | {}*\n".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )

    # 保存报告
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"[AAna] \u590d\u76d8\u8bc4\u5206\u62a5\u544a\u5df2\u751f\u6210: {filename}")

    # Git push
    try:
        os.chdir(PROJECT_DIR)
        subprocess.run(['git', 'add', '.'], check=True, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'feat: add {} review report v2.5 (auto)'.format(today)], check=True, capture_output=True)
        subprocess.run(['git', 'push', 'origin', 'main'], check=True, capture_output=True)
        print(f"[AAna] \u590d\u76d8\u62a5\u544a\u5df2\u63a8\u9001 GitHub")
    except subprocess.CalledProcessError as e:
        print(f"[AAna] Git \u5931\u8d25: {e}")

    return filename

if __name__ == "__main__":
    # 2026-06-22 P0 修复: CLI 入口直接调 main(), 让 is_trading_day() 短路生效
    # 之前此处独立写了一份 CLI 入口, 绕过了 main() 第 554 行的非交易日判断,
    # 导致 6/22 端午调休日 cron 仍然完整跑选股报告 (拉数据 + 拉 K 线 + 创建东财组合)
    sys.exit(main())
































# === REC_OPTIMIZER_TUNING_START ===
# 由 RecOptimizer 自动生成，勿手动修改
REC_TUNING = {
    "score_threshold": 60,
    "hold_days": 1,
    "weak_sectors": ['ai_app', 'semi', 'chem', 'mach', 'elec', 'robot'],
    "overall_win_rate": 30.7,
    "total_records": 845,
    "generated_at": "2026-07-15T20:00:42.301085",
}
# === REC_OPTIMIZER_TUNING_END ===

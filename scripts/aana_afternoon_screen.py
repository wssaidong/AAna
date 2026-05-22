#!/usr/bin/env python3
"""
AAna 尾盘选股脚本 v1.0
运行时间：工作日 14:45（A股收盘前15分钟）
策略：尾盘强势股回调买入
  - 14:45 全天数据已基本定型，可靠性高
  - 重点：当日小幅回调的强势股（不追高）
  - 过滤：RSI超买、涨幅过大、量能异常
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

# ============================================
# 数据获取
# ============================================

def get_today_str():
    return datetime.now().strftime("%Y-%m-%d")

def get_market_sina(code):
    if code.startswith('6') or code.startswith('9'):
        return f'sh{code}'
    return f'sz{code}'

def get_stock_data_sina(codes):
    """使用新浪财经API获取实时行情"""
    import requests
    results = {}
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
    """获取腾讯历史K线（前复权）"""
    import requests
    try:
        mkt = 'sh' if code.startswith(('6', '9')) else 'sz'
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayhfq&param={mkt}{code},day,,,{count},qfq"
        resp = requests.get(url, timeout=10)
        text = resp.text.strip()
        # 格式: var kline_dayhfq={...}
        if '=' in text:
            text = text.split('=', 1)[1]
        data = json.loads(text)
        
        # 取日K数据
        day_data = data.get('data', {}).get(f'{mkt}{code}', {}).get('qfqday', [])
        if not day_data:
            day_data = data.get('data', {}).get(f'{mkt}{code}', {}).get('day', [])
        
        # 转换为 [{date, open, high, low, close, vol}, ...]
        result = []
        for item in day_data:
            if len(item) >= 6:
                result.append({
                    'date': item[0],
                    'open': float(item[1]),
                    'high': float(item[2]),
                    'low': float(item[3]),
                    'close': float(item[4]),
                    'vol': float(item[5]),
                })
        return result
    except Exception as e:
        print(f"[Tencent K线] {code}: {e}")
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


def check_macd_golden_cross(closes):
    """检查MACD是否金叉（近3日内）"""
    if len(closes) < 35:
        return False
    
    def ema(data, p):
        k = 2 / (p + 1)
        e = data[0]
        for d in data[1:]:
            e = d * k + e * (1 - k)
        return e
    
    for i in range(26, len(closes)):
        ema12 = ema(closes[:i+1], 12)
        ema26 = ema(closes[:i+1], 26)
        dif = ema12 - ema26
        
        ema12_prev = ema(closes[:i], 12)
        ema26_prev = ema(closes[:i], 26)
        dif_prev = ema12_prev - ema26_prev
        
        if dif > 0 and dif_prev <= 0:
            return True  # 金叉
    return False


def get_vol_ratio(code, klines):
    """计算今日量比（今日成交量 / 5日均量）"""
    if len(klines) < 6:
        return None
    today_vol = klines[-1]['vol']
    avg_vol_5 = sum(klines[-6:-1][i]['vol'] for i in range(5)) / 5
    if avg_vol_5 == 0:
        return None
    return today_vol / avg_vol_5


# ============================================
# 尾盘评分系统
# ============================================

def score_afternoon_stock(info, klines):
    """
    尾盘评分（满分100）
    核心原则：尾盘买入 = 当日小幅回调的强势股
    """
    score = 50
    change_pct = info.get('change_pct', 0)
    price = info.get('price', 0)
    yesterday_close = info.get('yesterday_close', 0)
    high = info.get('high', 0)
    low = info.get('low', 0)
    
    if not klines or len(klines) < 20:
        return 0, {}
    
    closes = [k['close'] for k in klines]
    vols = [k['vol'] for k in klines]
    
    # 1. 当日涨跌幅评分（核心：回调是买点）
    # 尾盘策略：最好是小幅下跌（-3%~0%），涨幅过大不追
    if -3 <= change_pct < 0:
        score += 30  # 最佳买点区间
    elif -5 <= change_pct < -3:
        score += 20  # 较大回调，注意是否止跌
    elif 0 <= change_pct < 2:
        score += 10  # 小幅上涨，可接受
    elif change_pct < -5:
        score -= 15  # 跌幅过大，可能继续跌
    elif 2 <= change_pct < 5:
        score -= 5   # 涨幅偏大，不追高
    elif change_pct >= 5:
        score -= 15  # 涨幅过大，尾盘追高风险大（次日容易低开）
    
    # 2. 从日内高点的回落幅度（尾盘常从高点回落）
    if high > 0 and price > 0:
        intraday_pullback = (high - price) / high * 100
        # 理想情况：从高点回落 1-3%（说明有回调但没崩）
        if 1 <= intraday_pullback <= 3:
            score += 15
        elif intraday_pullback > 3:
            score += 5  # 回落较大，可能蓄势
        elif intraday_pullback < 1:
            score -= 5  # 一直高位，尾盘追高风险大
    
    # 3. RSI 评分
    rsi = calculate_rsi(closes, 14)
    if rsi:
        info['rsi'] = round(rsi, 1)
        if 40 <= rsi <= 60:
            score += 15  # 最佳区间（不超买也不超卖）
        elif 30 <= rsi < 40:
            score += 5   # 接近超卖，可能有机会
        elif 60 < rsi <= 70:
            score -= 5   # 偏热，小心
        elif rsi > 70:
            score -= 15  # 超买，不追
        elif rsi < 30:
            score -= 10  # 超卖，可能还在跌
    
    # 4. 均线多头
    ma5 = calculate_ma(closes, 5)
    ma10 = calculate_ma(closes, 10)
    ma20 = calculate_ma(closes, 20)
    if ma5 and ma10 and ma20:
        info['ma5'] = round(ma5, 2)
        info['ma10'] = round(ma10, 2)
        info['ma20'] = round(ma20, 2)
        if ma5 > ma10 > ma20:
            score += 15  # 均线多头
        elif ma5 > ma10:
            score += 5   # 短期多头
    
    # 5. 量比
    vol_ratio = get_vol_ratio(info['code'], klines)
    if vol_ratio:
        info['vol_ratio'] = round(vol_ratio, 2)
        if 0.5 <= vol_ratio <= 1.5:
            score += 10  # 量能正常
        elif vol_ratio > 3:
            score -= 10  # 巨量，可能出货
        elif vol_ratio < 0.3:
            score -= 5   # 极度缩量
    
    # 6. MACD金叉
    if check_macd_golden_cross(closes):
        score += 10
        info['macd_gold'] = True
    
    # 7. 价格位置（在均线上的位置）
    if ma10 and price > ma10:
        score += 5
    
    # 8. 成交额（流动性）
    amount = info.get('amount', 0)
    if amount > 5e8:
        score += 5
    elif amount < 1e7:
        score -= 10
    
    score = max(0, min(100, score))
    
    # 风险评估
    if score >= 80:
        risk = "🟢 低风险"
        stop_loss = round(price * 0.96, 2) if price else 0
    elif score >= 65:
        risk = "🟡 中风险"
        stop_loss = round(price * 0.95, 2) if price else 0
    else:
        risk = "🔴 高风险"
        stop_loss = round(price * 0.93, 2) if price else 0
    
    info['score'] = score
    info['risk'] = risk
    info['stop_loss'] = stop_loss
    info['target_price'] = round(price * 1.05, 2) if price else 0  # 目标+5%
    
    return score, info


# ============================================
# 选股逻辑
# ============================================

def screen_afternoon_stocks():
    """
    尾盘选股主流程
    1. 从新浪获取涨幅榜股票池
    2. 获取实时行情 + 历史K线
    3. 计算尾盘评分
    4. 过滤并排序
    """
    from dynamic_stocks import get_dynamic_stock_pool, filter_stocks
    
    print(f"[AAna 尾盘] {datetime.now().strftime('%H:%M:%S')} 开始尾盘选股...")
    
    # 1. 获取候选股票池（优先用今日选股报告 Top10，次用昨日快照）
    candidate_codes = []
    from eastmoney_portfolio import get_snapshot_top10

    # 尝试今日选股报告（盘中版，已含技术评分）
    today_str = datetime.now().strftime("%Y-%m-%d")
    candidate_codes = get_snapshot_top10(today_str)

    # 如果今日报告为空（数据源失败），尝试昨日快照
    if not candidate_codes:
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        candidate_codes = get_snapshot_top10(yesterday_str)

    if not candidate_codes:
        print("[AAna 尾盘] 候选股票池为空，跳过尾盘选股")
        return []

    print(f"[AAna 尾盘] 候选股票: {candidate_codes}")

    # 2. 获取实时行情
    prices = get_stock_data_sina(candidate_codes)

    # 3. 逐只评分
    results = []
    for code in candidate_codes:
        info = prices.get(code, {})
        if not info or info.get('price', 0) <= 0:
            continue

        # 过滤：价格区间
        price = info.get('price', 0)
        if price < 20 or price > 80:
            continue

        # 过滤：科创板(688) + 创业板(300/301) — 用户要求不推荐
        if code.startswith(('688', '8')) or code.startswith(('300', '301')):
            continue

        # 过滤：涨跌范围（尾盘只买小幅回调或微涨，不追高）
        change_pct = info.get('change_pct', 0)
        if change_pct < -8 or change_pct > 9:  # 跌停/涨停排除
            continue
        if change_pct > 5:  # 尾盘策略：涨幅>5%不追高
            continue

        # 获取K线（30天）
        klines = get_tencent_kline(code, count=30)

        # 评分
        score, scored_info = score_afternoon_stock(info, klines)

        if score >= 60:  # 只保留60分以上的
            results.append(scored_info)

    # 4. 排序
    results.sort(key=lambda x: x['score'], reverse=True)
    
    print(f"[AAna 尾盘] 筛选后候选: {len(results)} 只")
    return results[:10]


# ============================================
# 报告生成
# ============================================

def format_change(c):
    if c == 0:
        return "⚪ 0.00%"
    emoji = "🔴" if c > 0 else "🟢"
    return f"{emoji} {c:+.2f}%"


def generate_report(stocks, index_data=None):
    """生成尾盘选股报告"""
    today = get_today_str()
    now = datetime.now()
    
    report_dir = os.path.expanduser("~/code/AAna/reports")
    os.makedirs(report_dir, exist_ok=True)
    filename = f"{report_dir}/{today}-尾盘选股.md"
    
    # 大盘状态
    market_status = "乐观" if index_data and any(i['change'] > 0 for i in index_data) else "谨慎"
    avg_change = 0
    if index_data:
        avg_change = sum(i['change'] for i in index_data) / len(index_data)
    
    content = f"""# A股尾盘选股建议 — {today} {now.strftime('%H:%M')}

> AAna 尾盘策略 v1.0 | 仅供参考，不构成投资建议
> **生成时间：** {now.strftime('%Y-%m-%d %H:%M:%S')}（收盘前15分钟）

---

## 一、大盘环境

"""
    if index_data:
        content += "| 指数 | 涨跌幅 | 状态 |\n|:----:|:------:|:----:|\n"
        for idx in index_data:
            emoji = "🔴" if idx['change'] > 0 else "🟢"
            content += f"| {idx['name']} | {emoji} {idx['change']:+.2f}% | {'上涨' if idx['change'] > 0 else '下跌'} |\n"
    else:
        content += "> 大盘数据获取失败\n"
    
    content += f"""
**市场情绪：** {market_status} | **平均涨跌：** {avg_change:+.2f}%

---

## 二、尾盘买入信号（14:45）

> 策略说明：尾盘买入选当日小幅回调的强势股
> - 当日回调 -3%~0% 且价格仍在均线上方
> - RSI 40-60（不超买也不超卖）
> - 量比正常（0.5~1.5x）
> - 均线多头排列

"""
    
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

## 四、Top 3 重点关注

"""
    
    if stocks[:3]:
        for i, s in enumerate(stocks[:3], 1):
            reason = []
            change_pct = s.get('change_pct', 0)
            if -3 <= change_pct < 0:
                reason.append("当日回调")
            if s.get('rsi') and 40 <= s['rsi'] <= 60:
                reason.append(f"RSI适中({s['rsi']})")
            if s.get('macd_gold'):
                reason.append("MACD金叉")
            if s.get('ma5', 0) > s.get('ma10', 0):
                reason.append("均线多头")
            
            content += f"### {i}. {s['name']}({s['code']}) 评分{s['score']}\n"
            content += f"- 现价: ¥{s['price']:.2f} | 今日: {format_change(change_pct)}\n"
            content += f"- 买入理由: {', '.join(reason) if reason else '综合评分高'}\n"
            content += f"- 止损价: ¥{s['stop_loss']}（-5%）| 目标价: ¥{s['target_price']}（+5%）\n\n"
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

def main():
    # 获取大盘指数
    index_codes = ['000001', '399001', '399006', '000688']
    index_names = {'000001': '上证指数', '399001': '深证成指', '399006': '创业板', '000688': '科创50'}
    prices = get_stock_data_sina(index_codes)
    index_data = []
    for code, name in index_names.items():
        info = prices.get(code, {})
        if info.get('price', 0) > 0:
            index_data.append({
                'name': name,
                'price': info['price'],
                'change': info['change_pct']
            })
    
    # 选股
    stocks = screen_afternoon_stocks()
    
    # 生成报告
    filename, top_stocks = generate_report(stocks, index_data)

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

        # 同步到东方财富组合（改用每日报告 Top10 精选个股）
        if EASTMONEY_ENABLED:
            try:
                from eastmoney_portfolio import get_snapshot_top10, sync_portfolio_to_eastmoney
                today_str = datetime.now().strftime("%Y%m%d")
                today_date = datetime.now().strftime("%Y-%m-%d")
                codes = get_snapshot_top10(today_date)
                if codes:
                    success = sync_portfolio_to_eastmoney(codes, group_name=today_str)
                    if success:
                        print(f"\n✅ 已同步 Top10 精选到东方财富组合")
                else:
                    print(f"\n⚠️ 快照无数据，跳过东方财富同步")
            except Exception as e:
                print(f"\n⚠️ 东方财富同步失败: {e}")
    else:
        print("\n⚠️ 今日暂无符合尾盘策略的股票，建议轻仓观望")
    
    print("="*70)
    return top_stocks


if __name__ == '__main__':
    main()

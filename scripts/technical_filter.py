#!/usr/bin/env python3
"""
AAna v2.4 增强版技术指标模块
支持 MACD 金叉、均线多头、K 线形态等
数据来源：新浪财经历史 K 线
"""
import requests
import json
from datetime import datetime

def get_historical_kline(code, count=60):
    """获取新浪财经历史 K 线"""
    try:
        # code格式: sh600000 或 sz000001
        url = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        params = {
            'symbol': code,
            'scale': 240,   # 日K
            'ma': 5,        # 5日均线
            'datalen': count,
        }
        headers = {
            'Referer': 'http://finance.sina.com.cn',
            'User-Agent': 'Mozilla/5.0',
        }
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        return resp.json()
    except Exception as e:
        return None

def calculate_ema(data, period):
    """计算 EMA"""
    if len(data) < period:
        return None
    k = 2 / (period + 1)
    ema_val = data[0]
    for d in data[1:]:
        ema_val = d * k + ema_val * (1 - k)
    return ema_val

def calculate_macd(prices, fast=12, slow=26, signal=9):
    """计算 MACD 指标"""
    if len(prices) < slow + signal:
        return None, None, None
    
    ema_fast = calculate_ema(prices, fast)
    ema_slow = calculate_ema(prices, slow)
    
    if ema_fast is None or ema_slow is None:
        return None, None, None
    
    dif = ema_fast - ema_slow
    # Signal 线用 DIF 的 EMA
    # 简化：直接用 DIF 代替，后续优化
    dea = dif
    macd_hist = 2 * (dif - dea)
    
    return dif, dea, macd_hist

def check_均线多头(kline_data):
    """检查均线多头排列 (MA5 > MA10 > MA20)"""
    if len(kline_data) < 25:
        return False
    
    closes = [float(d['close']) for d in kline_data]
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else ma10
    
    return ma5 > ma10 > ma20

def check_MACD金叉(kline_data):
    """检查 MACD 金叉（DIF 上穿 DEA，即 MACD 柱由负转正）"""
    if len(kline_data) < 35:
        return False
    
    closes = [float(d['close']) for d in kline_data]
    macd_hist_list = []
    
    for i in range(26, len(closes)):
        _, _, hist = calculate_macd(closes[:i+1])
        if hist is not None:
            macd_hist_list.append(hist)
    
    if len(macd_hist_list) < 3:
        return False
    
    # 金叉：MACD 柱由负转正
    return macd_hist_list[-1] > 0 and macd_hist_list[-2] <= 0

def check_放量(kline_data, current_vol=None):
    """检查是否放量（今日成交量 > 5日均量）"""
    if len(kline_data) < 5:
        return False
    
    volumes = [float(d.get('volume', 0)) for d in kline_data]
    avg_vol = sum(volumes[-5:]) / 5
    
    # 如果传入当前成交量，用当前；否则用最后一条
    vol = current_vol if current_vol else volumes[-1]
    
    return vol > avg_vol * 1.5

def calculate_technical_score_enhanced(code, stock_info, kline_data=None):
    """
    增强版技术评分 (0-100)
    考虑：均线多头、MACD 金叉、量比、涨幅
    
    stock_info: 当日行情数据 {price, change_pct, volume, volume_ratio}
    kline_data: 历史 K 线数据（可选）
    """
    score = 50  # 基础分
    
    change_pct = stock_info.get('change_pct', 0)
    volume_ratio = stock_info.get('volume_ratio', 1) or 1
    current_vol = stock_info.get('volume', 0)
    
    # 1. 涨幅评分 (核心：回调是买点，追高谨慎)
    if change_pct >= 9.5:  # 涨停
        score += 10
    elif change_pct > 7:
        score += 5
    elif change_pct > 5:
        score += 2
    elif change_pct > 3:
        score += 0
    elif change_pct > 0:
        score += 3
    elif change_pct > -2:
        score += 5  # 小跌，回调是买点
    elif change_pct > -5:
        score += 8  # 中跌，可能超卖
    else:
        score += 5  # 大跌，谨慎
    
    # 2. 量比评分
    if volume_ratio > 5:
        score += 10
    elif volume_ratio > 3:
        score += 7
    elif volume_ratio > 2:
        score += 5
    elif volume_ratio > 1.5:
        score += 3
    elif volume_ratio > 1:
        score += 1
    
    # 3. 均线多头 (+15分)
    if kline_data and check_均线多头(kline_data):
        score += 15
    
    # 4. MACD 金叉 (+10分)
    if kline_data and check_MACD金叉(kline_data):
        score += 10
    
    # 5. 放量 (+5分)
    if kline_data and check_放量(kline_data, current_vol):
        score += 5
    
    # 6. K 线形态分析
    if kline_data and len(kline_data) >= 2:
        closes = [float(d['close']) for d in kline_data]
        latest_close = closes[-1]
        latest_open = float(kline_data[-1].get('open', latest_close))
        latest_high = float(kline_data[-1].get('high', latest_close))
        latest_low = float(kline_data[-1].get('low', latest_close))
        
        # 锤子线（长下影线）形态
        body = abs(latest_close - latest_open)
        lower_shadow = min(latest_open, latest_close) - latest_low
        upper_shadow = latest_high - max(latest_open, latest_close)
        
        if lower_shadow > body * 2 and upper_shadow < body:
            score += 5  # 锤子线，看涨信号
        
        # 放量上涨
        if change_pct > 0 and volume_ratio > 2:
            score += 3
    
    return max(0, min(100, score))

def get_stock_with_enhanced_score(code, stock_info):
    """
    获取股票增强评分
    """
    # 获取历史 K 线
    sina_code = f"sh{code}" if code.startswith('6') else f"sz{code}"
    kline = get_historical_kline(sina_code, count=60)
    
    # 计算增强评分
    score = calculate_technical_score_enhanced(code, stock_info, kline)
    
    return {
        'code': code,
        'score': score,
        'kline': kline is not None,
    }

if __name__ == '__main__':
    # 测试
    test_info = {
        'change_pct': 2.5,
        'volume_ratio': 2.3,
        'volume': 7500000,
    }
    score = calculate_technical_score_enhanced('688256', test_info)
    print(f"技术评分: {score}")
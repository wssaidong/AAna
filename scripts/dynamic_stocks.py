#!/usr/bin/env python3
"""
AAna v2.5 动态选股模块
使用新浪财经 API 获取实时行情，筛选符合条件的股票
"""
import requests
import json
import pandas as pd
from datetime import datetime

def get_sina_top_gainers(num=200):
    """从新浪财经获取A股涨幅榜"""
    url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'http://finance.sina.com.cn'}
    
    all_stocks = []
    for page in range(1, 6):  # 5 pages = 200 stocks
        params = {
            'page': page, 'num': 40, 'sort': 'changepercent', 'asc': 0,
            'node': 'hs_a', 'symbol': '', '_s_r_a': 'page'
        }
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            data = json.loads(resp.text)
            if not data:
                break
            all_stocks.extend(data)
        except Exception as e:
            print(f"[Sina] Page {page} failed: {e}")
            break
    
    return all_stocks

def filter_stocks(raw_stocks):
    """过滤股票：价格20-80元、涨幅0-9.8%、排除ST/新股"""
    filtered = []
    for s in raw_stocks:
        code = s.get('code', '')
        name = s.get('name', '')
        price = float(s.get('trade', 0))
        change_pct = float(s.get('changepercent', 0))
        
        # 排除新股、北交所、ST
        if code.startswith(('N', 'C', 'n', 'c', 'bj', '8', '9')):
            continue
        if name.startswith(('N', 'C', 'n', 'c', '*', 'S')):
            continue
        # 价格/涨幅过滤
        if price < 20 or price > 80:
            continue
        if change_pct < 0 or change_pct > 9.8:
            continue
        
        # 获取量比（需要单独查询）
        vol_ratio = float(s.get('volume', 0))  # Sina doesn't have volume ratio in this API
        
        filtered.append({
            'code': str(code).zfill(6),
            'name': name,
            'price': price,
            'change_pct': change_pct,
            'vol_ratio': vol_ratio,
        })
    
    # 按涨幅排序
    filtered.sort(key=lambda x: x['change_pct'], reverse=True)
    return filtered

def get_dynamic_stock_pool():
    """
    主函数：从新浪获取动态股票池
    返回最多50只符合条件的股票
    """
    print("[AAna] 从新浪财经获取动态股票池...")
    
    try:
        raw_stocks = get_sina_top_gainers(200)
        print(f"[AAna] 获取原始数据: {len(raw_stocks)} 只")
        
        if not raw_stocks:
            return []
        
        filtered = filter_stocks(raw_stocks)
        print(f"[AAna] 筛选后: {len(filtered)} 只")
        
        # 返回 Top 50
        return filtered[:50]
        
    except Exception as e:
        print(f"[AAna] 获取失败: {e}")
        return []

if __name__ == '__main__':
    stocks = get_dynamic_stock_pool()
    if stocks:
        print(f"\n动态选股 Top 20:")
        for i, s in enumerate(stocks[:20], 1):
            print(f"  {i}. {s['name']}({s['code']}): ¥{s['price']:.2f} {s['change_pct']:+.2f}%")
    else:
        print("未能获取动态股票池")
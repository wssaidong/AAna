#!/usr/bin/env python3
"""
AAna v2.4 动态选股模块
从东方财富爬取热门板块成分股
"""
import requests
import json
import re
from datetime import datetime

# 东方财富热门板块配置
SECTOR_KEYWORDS = {
    'AI算力': ['AI', '算力', 'DeepSeek', '大模型', '智能'],
    '人形机器人': ['机器人', '智能制造', 'Tesla', '特斯拉'],
    '半导体': ['半导体', '芯片', '集成电路', '光刻'],
    '新能源车': ['新能源车', '锂电池', '储能', '电动车'],
    'AI应用': ['AI应用', '端侧AI', '智能驾驶', 'AI软件'],
}

def get_eastmoney_headers():
    """获取东方财富请求头"""
    return {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer': 'https://quote.eastmoney.com/',
        'Accept': 'application/json, text/plain, */*',
    }

def get_hot_sectors():
    """获取东方财富热门板块（A股涨幅榜）"""
    try:
        url = "https://44.push2.eastmoney.com/api/qt/clist/get"
        params = {
            'pn': 1,
            'pz': 50,
            'po': 1,
            'np': 1,
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': 2,
            'invt': 2,
            'fid': 'f3',
            'fs': 'm:0+t:6,m:0+t:80,m:0+t:81,m:1+t:2,m:1+t:23',
            'fields': 'f2,f3,f4,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f22,f11,f62',
        }
        resp = requests.get(url, params=params, headers=get_eastmoney_headers(), timeout=10)
        data = resp.json()
        sectors = []
        for item in data.get('data', {}).get('diff', []):
            name = item.get('f14', '')
            code = item.get('f12', '')
            change_pct = item.get('f3', 0)
            volume_ratio = item.get('f62', 0)
            sectors.append({
                'name': name,
                'code': code,
                'change_pct': change_pct,
                'volume_ratio': volume_ratio,
            })
        return sectors
    except Exception as e:
        print(f"[AAna] 爬取东方财富板块失败: {e}")
        return []

def get_stock_by_keyword(keyword, limit=20):
    """按关键词搜索股票"""
    try:
        url = "https://searchapi.eastmoney.com/api/suggest/get"
        params = {
            'input': keyword,
            'type': '14',
            'token': 'D43BF722C8E33BDC906FB84D85E326E8',
            'count': limit,
        }
        resp = requests.get(url, params=params, headers=get_eastmoney_headers(), timeout=10)
        data = resp.json()
        stocks = []
        for item in data.get('QuotationCodeTable', {}).get('Data', []):
            stocks.append({
                'code': item.get('Code', ''),
                'name': item.get('Name', ''),
            })
        return stocks
    except Exception as e:
        print(f"[AAna] 搜索股票失败: {e}")
        return []

def filter_sectors_by_keyword(sectors, keywords):
    """根据关键词过滤板块"""
    filtered = []
    for s in sectors:
        name = s['name']
        for kw in keywords:
            if kw.lower() in name.lower():
                filtered.append(s)
                break
    return filtered

def get_dynamic_stock_pool():
    """获取动态股票池"""
    print("[AAna] 正在爬取东方财富热门板块...")
    hot_sectors = get_hot_sectors()
    
    if not hot_sectors:
        print("[AAna] 未能获取热门板块，使用备用方案")
        return None
    
    # 打印热门板块
    print(f"[AAna] 获取到 {len(hot_sectors)} 个热门板块")
    for s in hot_sectors[:10]:
        print(f"  {s['name']}: {s['change_pct']}%")
    
    # 根据关键词匹配目标板块
    target_sectors = []
    for category, keywords in SECTOR_KEYWORDS.items():
        matched = filter_sectors_by_keyword(hot_sectors, keywords)
        for s in matched:
            s['category'] = category
            target_sectors.append(s)
    
    print(f"[AAna] 匹配到 {len(target_sectors)} 个目标板块")
    
    # 按关键词搜索股票作为成分股
    all_stocks = {}
    stock_codes = set()
    
    for category, keywords in SECTOR_KEYWORDS.items():
        for kw in keywords:
            stocks = get_stock_by_keyword(kw, limit=10)
            for s in stocks:
                if s['code'] not in stock_codes:
                    stock_codes.add(s['code'])
                    s['category'] = category
                    all_stocks[s['code']] = s
    
    print(f"[AAna] 动态股票池共 {len(all_stocks)} 只")
    return list(all_stocks.values())

if __name__ == '__main__':
    stocks = get_dynamic_stock_pool()
    if stocks:
        print(f"\n获取到 {len(stocks)} 只股票")
        for s in stocks[:10]:
            print(f"  {s.get('name','未知')}({s['code']}): {s.get('category','未知')}")
    else:
        print("未能获取股票池")
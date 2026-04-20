#!/usr/bin/env python3
"""
AAna v2.4 动态选股 - 直接从东方财富获取股票池
"""
import requests
import json

def get_eastmoney_headers():
    return {
        'User-Agent': 'Mozilla/5.0',
        'Referer': 'https://quote.eastmoney.com/',
    }

def fetch_dynamic_stocks(page=1, pages=5):
    """从东方财富获取动态股票池"""
    all_stocks = []
    
    for p in range(1, pages + 1):
        url = "https://44.push2.eastmoney.com/api/qt/clist/get"
        params = {
            'pn': p,
            'pz': 200,
            'po': 1,
            'np': 1,
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': 2,
            'invt': 2,
            'fid': 'f3',
            'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',  # 沪深主板+创业板+科创板
            'fields': 'f2,f3,f12,f14,f62,f204',
        }
        
        try:
            resp = requests.get(url, params=params, headers=get_eastmoney_headers(), timeout=10)
            data = resp.json()
            items = data.get('data', {}).get('diff', [])
            if not items:
                break
            all_stocks.extend(items)
        except Exception as e:
            print(f"[AAna] 东方财富API失败: {e}")
            break
    
    return all_stocks

def filter_stocks(items):
    """过滤符合条件的股票"""
    filtered = []
    for item in items:
        code = str(item.get('f12', ''))
        price = item.get('f2', 0)
        change = item.get('f3', 0)
        vol_ratio = item.get('f62', 0) or 0
        
        # 排除ST、新股、价格异常
        if code.startswith(('8', '9')):
            continue
        if price < 20 or price > 80:
            continue
        # 只选涨幅 0-9% (排除涨停)
        if change <= 0 or change >= 9.8:
            continue
        # 量比 > 1.5
        if vol_ratio < 1.5:
            continue
        
        filtered.append({
            'code': code,
            'name': item.get('f14', ''),
            'price': price,
            'change_pct': change,
            'vol_ratio': vol_ratio,
            'turnover': item.get('f204', 0) or 0,
        })
    
    return filtered

def get_dynamic_stock_pool():
    """获取动态股票池"""
    print("[AAna] 从东方财富获取动态股票池...")
    items = fetch_dynamic_stocks(pages=5)
    print(f"[AAna] 获取到 {len(items)} 只候选股票")
    
    filtered = filter_stocks(items)
    print(f"[AAna] 动态筛选后: {len(filtered)} 只")
    
    # 按涨幅排序
    filtered.sort(key=lambda x: x['change_pct'], reverse=True)
    
    return filtered[:50]  # 最多50只

if __name__ == '__main__':
    stocks = get_dynamic_stock_pool()
    print(f"\n动态选股池: {len(stocks)} 只")
    for s in stocks[:10]:
        print(f"  {s['name']}({s['code']}): ¥{s['price']} {s['change_pct']}%")
    
    # 保存
    with open('dynamic_stocks.json', 'w') as f:
        json.dump(stocks, f, ensure_ascii=False, indent=2)
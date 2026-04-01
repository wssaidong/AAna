#!/usr/bin/env python3
"""
AAna 实时行情获取脚本
使用新浪财经API获取实时股价
"""

import requests
import json
import time
import warnings
warnings.filterwarnings('ignore')

def get_realtime_data(stock_codes_with_names):
    """
    获取实时行情
    stock_codes_with_names: [(code, name), ...]
    返回: [{code, name, price, change_pct, yesterday_close, amount}, ...]
    """
    if not stock_codes_with_names:
        return []
    
    # 转换代码格式: 上海sh, 深圳sz
    def format_code(code):
        if code.startswith('6') or code.startswith('9'):
            return f'sh{code}'
        elif code.startswith('00') or code.startswith('30') or code.startswith('8'):
            return f'sz{code}'
        else:
            return f'sz{code}'
    
    formatted = [format_code(c) for c, _ in stock_codes_with_names]
    url = 'http://hq.sinajs.cn/list=' + ','.join(formatted)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer': 'http://finance.sina.com.cn'
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = 'gbk'
        
        results = []
        lines = resp.text.strip().split('\n')
        
        for i, line in enumerate(lines):
            if '=' not in line:
                continue
            
            code = stock_codes_with_names[i][0] if i < len(stock_codes_with_names) else ''
            name = stock_codes_with_names[i][1] if i < len(stock_codes_with_names) else ''
            
            parts = line.split('=')[1].strip('";\n ').split(',')
            
            if len(parts) < 10:
                continue
            
            # 格式: 名称,今开,昨收,当前价,最高,最低,...
            yesterday_close = float(parts[2]) if parts[2] else 0
            price = float(parts[3]) if parts[3] else 0
            open_price = float(parts[1]) if parts[1] else 0
            high = float(parts[4]) if parts[4] else 0
            low = float(parts[5]) if parts[5] else 0
            amount = float(parts[9]) if parts[9] else 0  # 成交额(万元)
            volume = int(parts[8]) if parts[8] else 0  # 成交量(手)
            
            change = price - yesterday_close
            change_pct = (change / yesterday_close * 100) if yesterday_close else 0
            
            results.append({
                'code': code,
                'name': name,
                'price': price,
                'yesterday_close': yesterday_close,
                'open': open_price,
                'high': high,
                'low': low,
                'change': change,
                'change_pct': change_pct,
                'volume': volume,
                'amount': amount,  # 万元
                'update_time': parts[30] + ' ' + parts[31] if len(parts) > 31 else '',
            })
        
        return results
    
    except Exception as e:
        print(f"获取数据失败: {e}")
        return []

def get_index_data():
    """获取大盘指数"""
    indices = [
        ('sh000001', '上证指数'),
        ('sz399001', '深证成指'),
        ('sz399006', '创业板指'),
        ('sh000688', '科创50'),
    ]
    
    url = 'http://hq.sinajs.cn/list=' + ','.join([x[0] for x in indices])
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Referer': 'http://finance.sina.com.cn'
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = 'gbk'
        
        results = {}
        for i, line in enumerate(resp.text.strip().split('\n')):
            if '=' not in line:
                continue
            parts = line.split('=')[1].strip('";\n ').split(',')
            if len(parts) < 6:
                continue
            
            name = indices[i][1] if i < len(indices) else ''
            price = float(parts[3]) if parts[3] else 0
            yesterday_close = float(parts[2]) if parts[2] else 0
            change_pct = ((price - yesterday_close) / yesterday_close * 100) if yesterday_close else 0
            
            results[name] = {
                'price': price,
                'yesterday_close': yesterday_close,
                'change_pct': change_pct,
            }
        
        return results
    
    except Exception as e:
        print(f"获取指数失败: {e}")
        return {}

def format_amount(amount_wan):
    """格式化成交额"""
    if amount_wan >= 10000:
        return f"{amount_wan/10000:.2f}亿"
    else:
        return f"{amount_wan:.2f}万"

def main():
    print("=" * 60)
    print("AAna 实时行情获取")
    print("=" * 60)
    
    # 重点关注股票
    focus_stocks = [
        ('603667', '五洲新春'),
        ('300352', '科大国创'),
        ('300503', '昊志机电'),
        ('688256', '寒武纪'),
        ('688041', '海光信息'),
        ('300308', '中际旭创'),
        ('300502', '新易盛'),
        ('688012', '中微公司'),
        ('688396', '华润微'),
        ('600703', '三安光电'),
        ('002049', '紫光国微'),
        ('688475', '源杰科技'),
        ('300496', '中科创达'),
        ('688787', '海天瑞声'),
    ]
    
    # 获取指数
    print("\n【大盘指数】")
    indices = get_index_data()
    for name, data in indices.items():
        pct = data['change_pct']
        emoji = "🔴" if pct > 0 else "🟢" if pct < 0 else "⚪"
        print(f"{emoji} {name}: {data['price']:.2f} ({pct:+.2f}%)")
    
    # 获取股票
    print("\n【重点股票】")
    stocks = get_realtime_data(focus_stocks)
    
    trading_stocks = [s for s in stocks if s['price'] > 0]
    halted_stocks = [s for s in stocks if s['price'] == 0]
    
    if trading_stocks:
        print("\n📈 正常交易:")
        for s in trading_stocks:
            pct = s['change_pct']
            emoji = "🔴" if pct > 0 else "🟢" if pct < 0 else "⚪"
            print(f"  {emoji} {s['name']}({s['code']}): {s['price']:.2f}元 ({pct:+.2f}%) 成交额:{format_amount(s['amount'])}")
    
    if halted_stocks:
        print("\n⏸️ 停牌/休市(昨收价):")
        for s in halted_stocks:
            print(f"  ⚪ {s['name']}({s['code']}): {s['yesterday_close']:.2f}元 (未交易)")
    
    # 保存结果
    output = {
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'indices': indices,
        'stocks': stocks,
    }
    
    with open('/Users/cai/code/AAna/scripts/stock_data.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 数据已保存到 scripts/stock_data.json")
    return output

if __name__ == "__main__":
    main()

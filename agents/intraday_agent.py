#!/usr/bin/env python3
"""
AAna 盘中子Agent (常驻版)
工作时间：09:30 - 15:00
任务：
  - 09:30-15:00 实时监控
  - 11:28 午盘总结
  - 14:40 尾盘分析
"""
import os
import sys
import time
import warnings
warnings.filterwarnings('ignore')

sys.path.insert(0, os.path.expanduser('~/code/AAna'))

from datetime import datetime
from agents.config import (
    PROJECT_DIR, STOCK_POOL, INDEX_CODES, get_today_str, get_time_str,
    is_trading_day
)
from agents.data_utils import (
    get_stock_data_sina, get_all_codes, get_sector_emoji,
    format_price, format_change, save_state, load_state,
    git_commit_and_push, save_report
)

LOG_FILE = os.path.expanduser('~/code/AAna/reports/盘中/intraday.log')

def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')

def real_time_monitor():
    """实时监控（09:30-15:00定时检查）"""
    log("="*50)
    log("👁️ 盘中实时监控")
    
    all_codes = get_all_codes()
    prices = get_stock_data_sina(all_codes)
    
    # 检查指数
    index_changes = {}
    for code, name in INDEX_CODES.items():
        info = prices.get(code, {})
        if info.get('price', 0) > 0:
            index_changes[code] = info['change_pct']
    
    # 大盘状态
    if index_changes:
        avg_change = sum(index_changes.values()) / len(index_changes)
        if avg_change > 2:
            status = "🔥 强势上涨"
        elif avg_change > 0.5:
            status = "📈 温和上涨"
        elif avg_change > -0.5:
            status = "➡️ 震荡整理"
        elif avg_change > -2:
            status = "📉 温和下跌"
        else:
            status = "❄️ 大幅下跌"
    else:
        status = "⚠️ 数据异常"
        avg_change = 0
    
    # 个股异动检测
    alerts = []
    for cat_id, cat in STOCK_POOL.items():
        for code in cat['codes']:
            info = prices.get(code, {})
            if info.get('price', 0) > 0:
                change = info['change_pct']
                
                # 异动条件
                if change > 9:
                    alerts.append({
                        'type': 'limit_up',
                        'name': info['name'],
                        'code': code,
                        'change': change,
                        'category': cat['name'],
                        'msg': '涨停！注意获利了结风险'
                    })
                elif change < -9:
                    alerts.append({
                        'type': 'limit_down',
                        'name': info['name'],
                        'code': code,
                        'change': change,
                        'category': cat['name'],
                        'msg': '跌停！谨慎抄底'
                    })
                elif change > 7:
                    alerts.append({
                        'type': 'surge',
                        'name': info['name'],
                        'code': code,
                        'change': change,
                        'category': cat['name'],
                        'msg': '大涨，追高谨慎'
                    })
                elif change < -7:
                    alerts.append({
                        'type': 'drop',
                        'name': info['name'],
                        'code': code,
                        'change': change,
                        'category': cat['name'],
                        'msg': '大跌，留意止损'
                    })
    
    # 按异动程度排序
    alerts.sort(key=lambda x: abs(x['change']), reverse=True)
    
    log(f"大盘状态: {status} (平均 {avg_change:+.2f}%)")
    log(f"异动股票: {len(alerts)} 只")
    
    for alert in alerts[:5]:
        log(f"  {alert['name']}({alert['code']}): {alert['change']:+.2f}% - {alert['msg']}")
    
    # 保存监控状态
    save_state('intraday_monitor', {
        'timestamp': datetime.now().isoformat(),
        'status': status,
        'avg_change': avg_change,
        'index_changes': index_changes,
        'alerts': alerts
    })
    
    return {
        'status': status,
        'alerts': alerts,
        'avg_change': avg_change
    }

def midday_summary():
    """11:28 午盘总结"""
    log("="*50)
    log("📋 11:28 午盘总结")
    
    today = get_today_str()
    all_codes = get_all_codes()
    prices = get_stock_data_sina(all_codes)
    
    # 加载早盘简报数据
    morning_state = load_state('premarket_briefing')
    sentiment = morning_state['data']['sentiment'] if morning_state else "未知"
    
    # 加载竞价数据
    quote_state = load_state('competitive_quote')
    
    # 指数表现
    index_data = []
    for code, name in INDEX_CODES.items():
        info = prices.get(code, {})
        if info.get('price', 0) > 0:
            index_data.append({
                'name': name,
                'price': info['price'],
                'change': info['change_pct']
            })
    
    # 板块表现排行
    sector_perf = []
    for cat_id, cat in STOCK_POOL.items():
        changes = []
        for code in cat['codes']:
            info = prices.get(code, {})
            if info.get('price', 0) > 0:
                changes.append(info['change_pct'])
        
        if changes:
            avg_change = sum(changes) / len(changes)
            sector_perf.append({
                'name': cat['name'],
                'avg_change': avg_change,
                'logic': cat['logic'],
                'count': len(changes)
            })
    
    sector_perf.sort(key=lambda x: x['avg_change'], reverse=True)
    
    # 热门股票
    hot_stocks = []
    for cat_id, cat in STOCK_POOL.items():
        for code in cat['codes']:
            info = prices.get(code, {})
            if info.get('price', 0) > 0:
                hot_stocks.append({
                    'name': info['name'],
                    'code': code,
                    'category': cat['name'],
                    'change': info['change_pct'],
                    'price': info['price']
                })
    
    hot_stocks.sort(key=lambda x: x['change'], reverse=True)
    
    # 下午操作建议
    if index_data:
        avg_change = sum(i['change'] for i in index_data) / len(index_data)
        if avg_change > 1.5:
            afternoon_advice = "**强势市场：** 可继续持有或逢低加仓"
        elif avg_change > 0:
            afternoon_advice = "**震荡市场：** 高抛低吸，控制仓位"
        else:
            afternoon_advice = "**弱势市场：** 谨慎操作，观望为主"
    else:
        afternoon_advice = "**等待数据确认**"
    
    # 生成午盘总结
    content = f"""# A股午盘总结 — {today} 11:28

> 📋 盘中子Agent | 生成时间: {datetime.now().strftime('%H:%M:%S')}

---

## 一、上午盘面回顾

**早盘情绪:** {sentiment}

### 指数表现

"""
    
    for idx in index_data:
        emoji = "🔴" if idx['change'] > 0 else "🟢"
        content += f"| {idx['name']} | {format_price(idx['price'])} | {emoji} {idx['change']:+.2f}% |\n"
    
    content += f"""

### 板块排行（上午）

| 板块 | 平均涨幅 | 逻辑 |
|:----:|:--------:|:-----|
"""
    
    for s in sector_perf:
        emoji = "🔴" if s['avg_change'] > 0 else "🟢"
        content += f"| {s['name']} | {emoji} {s['avg_change']:+.2f}% | {s['logic']} |\n"
    
    content += f"""

---

## 二、个股表现

### 涨幅榜 Top 5

| 股票 | 代码 | 板块 | 涨幅 |
|:----:|:----:|:----:|:----:|
"""
    
    for s in hot_stocks[:5]:
        emoji = "🔴" if s['change'] > 0 else "🟢"
        content += f"| {get_sector_emoji(s['name'])}{s['name']} | {s['code']} | {s['category']} | {emoji} {s['change']:+.2f}% |\n"
    
    content += f"""

### 跌幅榜 Top 5

"""
    
    for s in hot_stocks[-5:]:
        emoji = "🟢" if s['change'] < 0 else "🔴"
        content += f"| {get_sector_emoji(s['name'])}{s['name']} | {s['code']} | {s['category']} | {emoji} {s['change']:+.2f}% |\n"
    
    content += f"""

---

## 三、下午操作建议

{afternoon_advice}

**注意事项：**
- 下午开盘(13:00)可能有惯性波动
- 14:30后谨慎追涨杀跌
- 14:40关注尾盘异动

---

## 四、下午时间线

| 时间 | 事项 |
|:----:|:----:|
| 13:00 | 下午开盘 |
| 14:40 | 📊 尾盘分析 |
| 15:00 | 🔵 收盘 |
| 21:30 | 🌙 复盘开始 |

---

*📋 AAna 午盘总结 v1.0 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
    
    filepath = save_report('午盘总结', content)
    git_commit_and_push(f"feat: add {today} midday summary (auto)")
    
    return filepath

def afternoon_analysis():
    """14:40 尾盘分析"""
    log("="*50)
    log("📊 14:45 尾盘推荐")
    
    today = get_today_str()
    all_codes = get_all_codes()
    prices = get_stock_data_sina(all_codes)
    
    # 指数表现
    index_data = []
    for code, name in INDEX_CODES.items():
        info = prices.get(code, {})
        if info.get('price', 0) > 0:
            index_data.append({
                'name': name,
                'price': info['price'],
                'change': info['change_pct']
            })
    
    avg_change = sum(i['change'] for i in index_data) / len(index_data) if index_data else 0
    
    # 判断尾盘走势
    if avg_change > 1.5:
        trend = "📈 尾盘强势拉升"
        analysis = "主力做多意愿强，明日可能延续"
    elif avg_change > 0.5:
        trend = "📈 尾盘小幅上涨"
        analysis = "平稳收官，明日震荡概率大"
    elif avg_change > -0.5:
        trend = "➡️ 尾盘横盘整理"
        analysis = "多空平衡，明日方向待定"
    elif avg_change > -1.5:
        trend = "📉 尾盘小幅回落"
        analysis = "部分资金撤离，明日谨慎"
    else:
        trend = "📉 尾盘大幅杀跌"
        analysis = "主力出逃迹象，明日注意风险"
    
    # 板块表现
    sector_perf = []
    for cat_id, cat in STOCK_POOL.items():
        changes = []
        for code in cat['codes']:
            info = prices.get(code, {})
            if info.get('price', 0) > 0:
                changes.append(info['change_pct'])
        
        if changes:
            avg_change_s = sum(changes) / len(changes)
            sector_perf.append({
                'name': cat['name'],
                'avg_change': avg_change_s,
                'logic': cat['logic']
            })
    
    sector_perf.sort(key=lambda x: x['avg_change'], reverse=True)
    
    # 强势股：涨幅>2% 且强于大盘
    strong_stocks = []
    # 超跌股：跌幅>4% 且弱于大盘（相对超跌）
    pullback_stocks = []
    
    for cat_id, cat in STOCK_POOL.items():
        for code in cat['codes']:
            info = prices.get(code, {})
            if info.get('price', 0) > 0:
                change = info['change_pct']
                rel_change = change - avg_change  # 相对大盘强弱
                if change > 2 and rel_change > 1:
                    strong_stocks.append({
                        'name': info['name'],
                        'code': code,
                        'category': cat['name'],
                        'change': change,
                        'rel_change': rel_change,
                        'price': info['price'],
                        'stop_loss': cat['stop_loss'],
                        'risk': cat['risk_level'],
                        'logic': cat['logic'],
                    })
                elif change < -4 and rel_change < -2:
                    pullback_stocks.append({
                        'name': info['name'],
                        'code': code,
                        'category': cat['name'],
                        'change': change,
                        'rel_change': rel_change,
                        'price': info['price'],
                        'stop_loss': cat['stop_loss'],
                        'risk': cat['risk_level'],
                        'logic': cat['logic'],
                    })
    
    strong_stocks.sort(key=lambda x: x['change'], reverse=True)
    pullback_stocks.sort(key=lambda x: x['change'])  # 跌幅大的排前面
    
    # 明日操作建议
    if avg_change > 1:
        tomorrow_advice = "**积极信号：** 明日可适度加仓，重点关注今日强势板块"
    elif avg_change > 0:
        tomorrow_advice = "**中性偏暖：** 明日震荡为主，逢低布局"
    else:
        tomorrow_advice = "**谨慎信号：** 明日观望为主，等待企稳"
    
    # 生成尾盘分析（含推荐）
    content = f"""# A股尾盘推荐 — {today} 14:45

> 📊 盘中子Agent | 生成时间: {datetime.now().strftime('%H:%M:%S')}

---

## 一、尾盘走势分析

**指数表现：**

"""
    
    for idx in index_data:
        emoji = "🔴" if idx['change'] > 0 else "🟢"
        content += f"| {idx['name']} | {format_price(idx['price'])} | {emoji} {idx['change']:+.2f}% |\n"
    
    content += f"""

**尾盘特征:** {trend}
**分析判断:** {analysis}

---

## 二、板块表现（收盘）

| 板块 | 收盘涨幅 | 评价 |
|:----:|:--------:|:----:|
"""
    
    for s in sector_perf:
        emoji = "🔴" if s['avg_change'] > 0 else "🟢"
        tag = "今日强势" if s['avg_change'] > 2 else ("今日弱势" if s['avg_change'] < -2 else "平稳")
        content += f"| {s['name']} | {emoji} {s['avg_change']:+.2f}% | {tag} |\n"
    
    content += f"""

## 三、尾盘股票推荐

"""
    
    if strong_stocks:
        content += "**🚀 强势股（涨幅>2%且强于大盘）**\n"
        content += "| 股票 | 代码 | 涨跌幅 | 强弱 | 板块 | 止损 |\n"
        content += "|:----:|:----:|:--------:|:----:|:----:|:----:|\n"
        for s in strong_stocks[:8]:
            emoji = "🔴"
            content += f"| {get_sector_emoji(s['name'])}{s['name']} | {s['code']} | {emoji} {s['change']:+.2f}% | {s['rel_change']:+.2f}% | {s['category']} | {s['stop_loss']} |\n"
        content += "\n"
    
    if pullback_stocks:
        content += "**📉 超跌关注（跌幅>4%且弱于大盘）**\n"
        content += "| 股票 | 代码 | 涨跌幅 | 强弱 | 板块 | 止损 |\n"
        content += "|:----:|:----:|:--------:|:----:|:----:|:----:|\n"
        for s in pullback_stocks[:8]:
            emoji = "🟢"
            content += f"| {get_sector_emoji(s['name'])}{s['name']} | {s['code']} | {emoji} {s['change']:+.2f}% | {s['rel_change']:+.2f}% | {s['category']} | {s['stop_loss']} |\n"
        content += "\n"
    
    if not strong_stocks and not pullback_stocks:
        content += "今日无符合条件个股（涨跌幅未达到筛选标准）\n"
    
    content += f"""

---

## 四、明日操作建议

{tomorrow_advice}

**今日复盘要点：**
- 收盘仓位建议：{'50-70%' if avg_change > 0 else '30-50%'}
- 明日关注板块：{sector_perf[0]['name'] if sector_perf else '待定'}
- 风险提示：严格止损

---

## 五、收盘时间线

| 时间 | 状态 |
|:----:|:----:|
| 14:40 | ✅ 尾盘分析完成 |
| 15:00 | 🔵 收盘 |
| 15:00-21:30 | 盘后数据处理 |
| 21:30 | 🌙 复盘开始 |

---

*📊 AAna 尾盘分析 v1.0 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
    
    filepath = save_report('尾盘分析', content)
    
    # 保存收盘快照
    save_state('close_snapshot', {
        'timestamp': datetime.now().isoformat(),
        'index_data': index_data,
        'sector_perf': sector_perf,
        'strong_stocks': strong_stocks,
        'pullback_stocks': pullback_stocks,
        'trend': trend
    })
    
    git_commit_and_push(f"feat: add {today} afternoon analysis (auto)")
    
    return filepath

def run():
    """主运行函数"""
    log("👁️ 盘中子Agent 启动")
    
    if not is_trading_day():
        log("今日非交易日，退出")
        return
    
    current_time = datetime.now()
    hour = current_time.hour
    minute = current_time.minute
    
    if hour == 11 and minute == 28:
        midday_summary()
    elif hour == 14 and minute == 45:
        afternoon_analysis()
    elif 9 <= hour < 15:
        # 盘中每个30分钟监控一次
        if minute % 30 == 0:
            real_time_monitor()
    else:
        log(f"当前时间 {hour}:{minute:02d} 无需执行任务")

if __name__ == "__main__":
    run()

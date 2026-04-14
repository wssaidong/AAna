#!/usr/bin/env python3
"""
AAna 盘前子Agent (常驻版)
工作时间：07:00 - 09:28
任务：
  - 07:00 健康检测
  - 08:25 系统自检
  - 08:30 盘前简报
  - 09:28 竞价推送
"""
import os
import sys
import time
import warnings
warnings.filterwarnings('ignore')

# 添加项目路径
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

LOG_FILE = os.path.expanduser('~/code/AAna/reports/盘前/premarket.log')

def log(msg):
    """日志记录"""
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')

def health_check():
    """07:00 健康检测"""
    log("="*50)
    log("🦞 盘前Agent 启动 - 健康检测")
    
    checks = []
    
    # 1. 系统检查
    try:
        import requests
        resp = requests.get('http://hq.sinajs.cn/list=sh000001', timeout=5)
        checks.append(('新浪API', '✅ 正常' if resp.status_code == 200 else '❌ 异常'))
    except Exception as e:
        checks.append(('新浪API', f'❌ 失败: {e}'))
    
    # 2. Git 检查
    try:
        os.chdir(PROJECT_DIR)
        import subprocess
        result = subprocess.run(['git', 'status'], capture_output=True, text=True)
        checks.append(('Git', '✅ 正常' if result.returncode == 0 else '❌ 异常'))
    except Exception as e:
        checks.append(('Git', f'❌ 失败: {e}'))
    
    # 3. 目录检查
    dirs_ok = all(os.path.isdir(os.path.expanduser(p)) for p in ['~/code/AAna', '~/code/AAna/reports'])
    checks.append(('目录结构', '✅ 正常' if dirs_ok else '❌ 缺失'))
    
    # 4. 股票池检查
    all_codes = get_all_codes()
    checks.append(('股票池', f'✅ {len(all_codes)} 只'))
    
    log("健康检测结果:")
    for name, status in checks:
        log(f"  {name}: {status}")
    
    return all('✅' in s for _, s in checks)

def system_self_check():
    """08:25 系统自检"""
    log("="*50)
    log("🔧 08:25 系统自检")
    
    # 获取最新数据
    all_codes = get_all_codes()
    log(f"获取 {len(all_codes)} 只股票数据...")
    
    prices = get_stock_data_sina(all_codes)
    
    # 检查指数
    index_status = []
    for code, name in INDEX_CODES.items():
        info = prices.get(code, {})
        price = info.get('price', 0)
        change = info.get('change_pct', 0)
        if price > 0:
            status = f"{format_price(price)} {format_change(change)}"
        else:
            status = "❌ 数据异常"
        index_status.append(f"{name}: {status}")
        log(f"  {name}: {status}")
    
    # 检查热门股票
    stock_status = []
    for cat_id, cat in STOCK_POOL.items():
        for code in cat['codes'][:2]:  # 每类取2只
            info = prices.get(code, {})
            if info.get('price', 0) > 0:
                stock_status.append(f"{info.get('name', code)}: {format_change(info.get('change_pct', 0))}")
    
    log(f"股票数据: {len([p for p in prices.values() if p.get('price', 0) > 0])}/{len(all_codes)} 只有效")
    
    # 保存自检状态
    save_state('premarket_selfcheck', {
        'indexes': index_status,
        'sample_stocks': stock_status[:10],
        'total_stocks': len(all_codes),
        'valid_stocks': len([p for p in prices.values() if p.get('price', 0) > 0])
    })
    
    return True

def pre_market_briefing():
    """08:30 盘前简报"""
    log("="*50)
    log("📋 08:30 盘前简报生成")
    
    today = get_today_str()
    all_codes = get_all_codes()
    prices = get_stock_data_sina(all_codes)
    
    # 大盘概览
    index_data = []
    for code, name in INDEX_CODES.items():
        info = prices.get(code, {})
        if info.get('price', 0) > 0:
            index_data.append({
                'name': name,
                'price': info['price'],
                'change': info['change_pct']
            })
    
    # 市场情绪判断
    if index_data:
        avg_change = sum(i['change'] for i in index_data) / len(index_data)
        if avg_change > 1:
            sentiment = "🔥 乐观"
            advice = "积极布局，注意追高风险"
        elif avg_change > 0:
            sentiment = "📈 偏暖"
            advice = "谨慎乐观，控制仓位"
        elif avg_change > -1:
            sentiment = "🌧️ 偏弱"
            advice = "防御为主，等待机会"
        else:
            sentiment = "❄️ 悲观"
            advice = "轻仓或空仓，谨慎操作"
    else:
        sentiment = "⚠️ 数据异常"
        advice = "等待数据确认"
        avg_change = 0
    
    # 热点板块
    hot_sectors = []
    for cat_id, cat in STOCK_POOL.items():
        stocks_data = []
        for code in cat['codes']:
            info = prices.get(code, {})
            if info.get('price', 0) > 0:
                stocks_data.append(info)
        
        if stocks_data:
            avg_change = sum(s['change_pct'] for s in stocks_data) / len(stocks_data)
            hot_sectors.append({
                'name': cat['name'],
                'logic': cat['logic'],
                'avg_change': avg_change,
                'stocks': len(stocks_data)
            })
    
    # 按涨幅排序
    hot_sectors.sort(key=lambda x: x['avg_change'], reverse=True)
    
    # 生成简报
    content = f"""# A股盘前简报 — {today} 08:30

> 🦞 盘前子Agent | 生成时间: {datetime.now().strftime('%H:%M:%S')}

---

## 一、大盘概览

"""
    
    for idx in index_data:
        emoji = "🔴" if idx['change'] > 0 else "🟢"
        content += f"| {idx['name']} | {format_price(idx['price'])} | {emoji} {idx['change']:+.2f}% |\n"
    
    content += f"""
**市场情绪:** {sentiment}
**操作建议:** {advice}

---

## 二、热点板块（按涨幅排序）

"""
    
    for i, sector in enumerate(hot_sectors[:3], 1):
        emoji = "🔴" if sector['avg_change'] > 0 else "🟢"
        content += f"### 🥇 {sector['name']} {emoji} {sector['avg_change']:+.2f}%\n"
        content += f"> {sector['logic']}\n\n"
    
    content += f"""| 板块 | 今日均涨幅 | 关注逻辑 |
|:----:|:----------:|:--------|
"""
    
    for sector in hot_sectors:
        emoji = "🔴" if sector['avg_change'] > 0 else "🟢"
        content += f"| {sector['name']} | {emoji} {sector['avg_change']:+.2f}% | {sector['logic']} |\n"
    
    content += f"""

---

## 三、操作建议

{'**积极信号：** 可适当布局核心标的' if avg_change > 0 else '**注意风险：** 等待市场企稳'}

**重点关注：**
"""
    
    # 推荐关注
    for sector in hot_sectors[:2]:
        for code in STOCK_POOL_inv.get(sector['name'], []):
            info = prices.get(code, {})
            if info.get('price', 0) > 0 and -3 <= info['change_pct'] <= 5:
                content += f"- {get_sector_emoji(info['name'])}{info['name']}({code}) {format_change(info['change_pct'])}\n"
    
    content += f"""

---

## 四、今日关注时间点

| 时间 | 任务 |
|:----:|:----:|
| 09:15 | 集合竞价开始 |
| 09:25 | 竞价确认 |
| 09:28 | 🎯 竞价推送 |
| 09:30 | 开盘交易 |
| 11:28 | 午盘总结 |
| 14:40 | 尾盘分析 |
| 15:00 | 收盘 |
| 21:30 | 复盘开始 |

---

*🦞 AAna 盘前简报 v1.0 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
    
    # 临时：创建反向映射
    global STOCK_POOL_inv
    STOCK_POOL_inv = {}
    for cat_id, cat in STOCK_POOL.items():
        for code in cat['codes']:
            STOCK_POOL_inv.setdefault(cat['name'], []).append(code)
    
    filepath = save_report('早盘简报', content)
    
    # 保存状态
    save_state('premarket_briefing', {
        'sentiment': sentiment,
        'advice': advice,
        'hot_sectors': [(s['name'], s['avg_change']) for s in hot_sectors],
        'avg_index_change': avg_change
    })
    
    # Git
    git_commit_and_push(f"feat: add {today} pre-market briefing (auto)")
    
    return filepath

def competitive_quote_push():
    """09:28 竞价推送"""
    log("="*50)
    log("🎯 09:28 竞价推送")
    
    today = get_today_str()
    all_codes = get_all_codes()
    prices = get_stock_data_sina(all_codes)
    
    # 竞价阶段重点股票
    focus_stocks = []
    
    for cat_id, cat in STOCK_POOL.items():
        for code in cat['codes']:
            info = prices.get(code, {})
            if info.get('price', 0) > 0:
                change = info['change_pct']
                # 竞价阶段：涨幅适中（-3%~5%）的股票
                if -3 <= change <= 5:
                    focus_stocks.append({
                        'name': info['name'],
                        'code': code,
                        'category': cat['name'],
                        'price': info['price'],
                        'change': change,
                        'amount': info.get('amount', 0),
                        'logic': cat['logic'],
                        'stop_loss': cat['stop_loss']
                    })
    
    # 按涨幅排序
    focus_stocks.sort(key=lambda x: x['change'], reverse=True)
    
    # 生成竞价推送
    content = f"""# A股竞价推送 — {today} 09:28

> 🎯 竞价子Agent | 生成时间: {datetime.now().strftime('%H:%M:%S')}

---

## ⚠️ 竞价阶段 - 重点关注

**开盘前注意事项：**
- 竞价阶段涨跌超过5%的股票谨慎追入
- 优先选择竞价涨幅在-3%~3%之间的标的
- 关注成交额放量情况

---

## 🎯 竞价精选

| 股票 | 代码 | 板块 | 昨收 | 竞价涨幅 | 建议 |
|:----:|:----:|:----:|:----:|:--------:|:----:|
"""
    
    for s in focus_stocks[:10]:
        emoji = "🔴" if s['change'] > 0 else "🟢"
        if s['change'] > 3:
            tag = "⚠️ 追高风险"
        elif s['change'] < -3:
            tag = "🔥 回调机会"
        else:
            tag = "✅ 关注"
        
        content += f"| {get_sector_emoji(s['name'])}{s['name']} | {s['code']} | {s['category']} | {format_price(s['price'])} | {emoji} {s['change']:+.2f}% | {tag} |\n"
    
    content += f"""

## 📋 操作计划

"""
    
    # 找最佳买点
    buy_candidates = [s for s in focus_stocks if -3 <= s['change'] <= 1]
    if buy_candidates:
        content += "**建议关注（回调到位）：**\n"
        for s in buy_candidates[:5]:
            content += f"- {get_sector_emoji(s['name'])}{s['name']}({s['code']}) {s['change']:+.2f}% | {s['logic']} | 止损: {s['stop_loss']}\n"
    
    # 高风险警示
    high_risk = [s for s in focus_stocks if s['change'] > 5]
    if high_risk:
        content += "\n**⚠️ 高风险警示（谨慎）：**\n"
        for s in high_risk:
            content += f"- {s['name']}({s['code']}) {s['change']:+.2f}%\n"
    
    content += f"""

---

## 🕘 今日时间线

| 时间 | 状态 |
|:----:|:----:|
| 09:28 | ✅ 竞价确认 |
| 09:30 | 🔴 开盘 |
| 11:28 | 📋 午盘总结 |
| 14:40 | 📊 尾盘分析 |
| 15:00 | 🔵 收盘 |

---

*🎯 AAna 竞价推送 v1.0 | 仅供参考，不构成投资建议*
"""
    
    filepath = save_report('竞价推送', content)
    
    # 保存竞价快照
    save_state('competitive_quote', {
        'timestamp': datetime.now().isoformat(),
        'stocks': focus_stocks,
        'buy_candidates': buy_candidates[:5] if buy_candidates else []
    })
    
    git_commit_and_push(f"feat: add {today} competitive quote push (auto)")
    
    return filepath


def run():
    """主运行函数"""
    log("🦞 盘前子Agent 启动")
    
    if not is_trading_day():
        log("今日非交易日，退出")
        return
    
    # 根据时间执行不同任务
    current_time = datetime.now()
    hour = current_time.hour
    minute = current_time.minute
    
    if hour == 7 and minute == 0:
        health_check()
    elif hour == 8 and minute == 25:
        system_self_check()
    elif hour == 8 and minute == 30:
        pre_market_briefing()
    elif hour == 9 and minute == 28:
        competitive_quote_push()
    else:
        log(f"当前时间 {hour}:{minute:02d} 无需执行任务")


if __name__ == "__main__":
    run()

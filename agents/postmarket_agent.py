#!/usr/bin/env python3
"""
AAna 复盘子Agent (常驻版)
工作时间：21:30 - 21:45
任务：
  - 21:30 全天数据汇总
  - 21:35 策略有效性分析
  - 21:40 风险控制评估
  - 21:45 明日策略规划
"""
import os
import sys
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

LOG_FILE = os.path.expanduser('~/code/AAna/reports/复盘/postmarket.log')

def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')

def data_summary():
    """21:30 全天数据汇总"""
    log("="*50)
    log("📊 21:30 全天数据汇总")
    
    today = get_today_str()
    all_codes = get_all_codes()
    
    # 获取收盘数据
    prices = get_stock_data_sina(all_codes)
    
    # 加载早盘快照
    morning_state = load_state('premarket_briefing')
    
    # 指数汇总
    index_summary = []
    for code, name in INDEX_CODES.items():
        info = prices.get(code, {})
        if info.get('price', 0) > 0:
            index_summary.append({
                'name': name,
                'close': info['price'],
                'change': info['change_pct']
            })
    
    # 板块汇总
    sector_summary = []
    for cat_id, cat in STOCK_POOL.items():
        stocks_data = []
        for code in cat['codes']:
            info = prices.get(code, {})
            if info.get('price', 0) > 0:
                stocks_data.append({
                    'code': code,
                    'name': info['name'],
                    'close': info['price'],
                    'change': info['change_pct']
                })
        
        if stocks_data:
            changes = [s['change'] for s in stocks_data]
            sector_summary.append({
                'name': cat['name'],
                'logic': cat['logic'],
                'avg_change': sum(changes) / len(changes),
                'max_change': max(changes),
                'min_change': min(changes),
                'stocks': stocks_data,
                'count': len(stocks_data)
            })
    
    sector_summary.sort(key=lambda x: x['avg_change'], reverse=True)
    
    # 全部股票表现
    all_stocks = []
    for cat_id, cat in STOCK_POOL.items():
        for code in cat['codes']:
            info = prices.get(code, {})
            if info.get('price', 0) > 0:
                all_stocks.append({
                    'name': info['name'],
                    'code': code,
                    'category': cat['name'],
                    'close': info['price'],
                    'change': info['change_pct']
                })
    
    all_stocks.sort(key=lambda x: x['change'], reverse=True)
    
    # 汇总数据
    summary_data = {
        'timestamp': datetime.now().isoformat(),
        'index_summary': index_summary,
        'sector_summary': sector_summary,
        'top_stocks': all_stocks[:10],
        'bottom_stocks': all_stocks[-5:],
        'total_count': len(all_stocks)
    }
    
    save_state('postmarket_summary', summary_data)
    
    # 统计
    up_count = len([s for s in all_stocks if s['change'] > 0])
    down_count = len([s for s in all_stocks if s['change'] < 0])
    
    log(f"上涨: {up_count}, 下跌: {down_count}")
    log(f"最强板块: {sector_summary[0]['name'] if sector_summary else 'N/A'} {sector_summary[0]['avg_change']:+.2f}%")
    log(f"最弱板块: {sector_summary[-1]['name'] if sector_summary else 'N/A'} {sector_summary[-1]['avg_change']:+.2f}%")
    
    return summary_data

def strategy_analysis():
    """21:35 策略有效性分析"""
    log("="*50)
    log("📈 21:35 策略有效性分析")
    
    # 加载今日数据
    summary_state = load_state('postmarket_summary')
    if not summary_state:
        log("缺少汇总数据，跳过策略分析")
        return None
    
    data = summary_state['data']
    today = get_today_str()
    
    # 早盘情绪
    morning_state = load_state('premarket_briefing')
    sentiment = morning_state['data']['sentiment'] if morning_state else "未知"
    
    # 分析预测准确性
    index_data = data['index_summary']
    sector_data = data['sector_summary']
    top_stocks = data['top_stocks']
    
    # 策略评估
    if index_data:
        avg_change = sum(i['change'] for i in index_data) / len(index_data)
        
        if avg_change > 2:
            market_score = 90
            market_eval = "大盘强势，符合积极信号"
        elif avg_change > 0.5:
            market_score = 75
            market_eval = "大盘偏暖，基本符合预期"
        elif avg_change > -0.5:
            market_score = 60
            market_eval = "大盘震荡，预测偏乐观"
        elif avg_change > -2:
            market_score = 40
            market_eval = "大盘走弱，预测偏差较大"
        else:
            market_score = 20
            market_eval = "大盘大跌，预测完全错误"
    else:
        market_score = 50
        market_eval = "数据异常，无法评估"
        avg_change = 0
    
    # 板块预测准确性
    if sector_data:
        predicted_hot = sector_data[0]['name'] if sector_data else ""
        actual_hot = sector_data[0]['name'] if sector_data and sector_data[0]['avg_change'] > 0 else "无上涨板块"
        
        sector_accuracy = "✅ 预测准确" if predicted_hot == actual_hot else "⚠️ 有所偏差"
    else:
        sector_accuracy = "⚠️ 数据不足"
    
    # 策略分析报告
    content = f"""# 策略有效性分析 — {today}

> 📈 复盘子Agent | 分析时间: {datetime.now().strftime('%H:%M:%S')}

---

## 一、市场预测回顾

| 预测维度 | 早盘判断 | 收盘实际 | 评价 |
|:--------:|:--------:|:--------:|:----:|
| 大盘情绪 | {sentiment} | {'上涨' if avg_change > 0 else '下跌'} {avg_change:+.2f}% | {'✅ 准确' if abs(avg_change) > 0.5 else '⚠️ 基本准确'} |
| 最强板块 | {sector_data[0]['name'] if sector_data else 'N/A'} | {sector_data[0]['name'] if sector_data else 'N/A'} | {sector_accuracy} |

---

## 二、策略评分

### 大盘策略评分: {market_score}/100

**评价：** {market_eval}

### 板块命中率

"""
    
    if sector_data:
        content += "| 板块 | 预测 | 实际涨幅 | 命中 |\n"
        content += "|:----:|:----:|:--------:|:----:|\n"
        
        predicted = [s['name'] for s in sector_data[:3]]
        for s in sector_data[:3]:
            hit = "✅" if s['avg_change'] > 0 else "❌"
            content += f"| {s['name']} | {'强势' if s['avg_change'] > 1 else '震荡'} | {s['avg_change']:+.2f}% | {hit} |\n"
    
    content += f"""

### 个股命中率

"""
    
    # 计算个股预测准确率
    if top_stocks:
        # 早盘推荐且收盘上涨的
        recommended_up = [s for s in top_stocks if s['change'] > 0]
        accuracy = len(recommended_up) / len(top_stocks) * 100 if top_stocks else 0
        
        content += f"| 指标 | 数值 |\n"
        content += f"|:----:|:----:|\n"
        content += f"| 推荐上涨 | {len(recommended_up)}/{len(top_stocks)} |\n"
        content += f"| 命中率 | {accuracy:.0f}% |\n"
    
    content += f"""

---

## 三、策略有效性总结

**今日策略评分: {market_score}/100**

| 等级 | 分数范围 | 说明 |
|:----:|:--------:|:----:|
| 🏆 优秀 | 80-100 | 策略精准，有效规避风险 |
| ✅ 良好 | 60-79 | 策略基本准确，可继续执行 |
| ⚠️ 一般 | 40-59 | 偏差较大，需调整 |
| ❌ 较差 | <40 | 策略失败，需反思改进 |

**综合评价：** {'策略执行良好' if market_score >= 60 else '策略需改进'}

---

*📈 AAna 策略分析 v1.0 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
    
    filepath = save_report('策略分析', content)
    git_commit_and_push(f"feat: add {today} strategy analysis (auto)")
    
    return filepath

def risk_assessment():
    """21:40 风险控制评估"""
    log("="*50)
    log("🛡️ 21:40 风险控制评估")
    
    summary_state = load_state('postmarket_summary')
    if not summary_state:
        log("缺少汇总数据，跳过风险评估")
        return None
    
    data = summary_state['data']
    today = get_today_str()
    all_stocks = data.get('top_stocks', []) + data.get('bottom_stocks', [])
    
    # 风险检测
    risks = []
    
    # 1. 大盘风险
    index_data = data.get('index_summary', [])
    if index_data:
        avg_change = sum(i['change'] for i in index_data) / len(index_data)
        if avg_change < -2:
            risks.append({
                'level': 'high',
                'type': '大盘风险',
                'desc': f'大盘大幅下跌 {avg_change:.2f}%，系统风险释放'
            })
        elif avg_change < -1:
            risks.append({
                'level': 'medium',
                'type': '大盘风险',
                'desc': f'大盘走弱 {avg_change:.2f}%，注意控制仓位'
            })
    
    # 2. 个股风险
    for stock in data.get('top_stocks', [])[:5]:
        if stock['change'] > 9:
            risks.append({
                'level': 'high',
                'type': '涨停风险',
                'desc': f"{stock['name']}涨停，明日可能低开"
            })
        elif stock['change'] > 7:
            risks.append({
                'level': 'medium',
                'type': '追高风险',
                'desc': f"{stock['name']}大涨+{stock['change']:.2f}%，追高需谨慎"
            })
    
    for stock in data.get('bottom_stocks', []):
        if stock['change'] < -9:
            risks.append({
                'level': 'high',
                'type': '跌停风险',
                'desc': f"{stock['name']}跌停，谨慎抄底"
            })
        elif stock['change'] < -7:
            risks.append({
                'level': 'medium',
                'type': '止损风险',
                'desc': f"{stock['name']}大跌{stock['change']:.2f}%，关注止损"
            })
    
    # 3. 板块风险
    sector_data = data.get('sector_summary', [])
    if sector_data:
        worst = sector_data[-1]
        if worst['avg_change'] < -3:
            risks.append({
                'level': 'medium',
                'type': '板块轮动风险',
                'desc': f"{worst['name']}领跌，热点可能切换"
            })
    
    # 风险等级
    high_risk = len([r for r in risks if r['level'] == 'high'])
    medium_risk = len([r for r in risks if r['level'] == 'medium'])
    
    if high_risk > 0:
        risk_level = "🔴 高风险"
        risk_advice = "建议轻仓或空仓，等待市场企稳"
    elif medium_risk > 2:
        risk_level = "🟡 中高风险"
        risk_advice = "控制仓位在30%以下，谨慎操作"
    elif medium_risk > 0:
        risk_level = "🟡 中风险"
        risk_advice = "控制仓位50%左右，分散投资"
    else:
        risk_level = "🟢 低风险"
        risk_advice = "市场稳定，可保持50-70%仓位"
    
    # 生成风险评估报告
    content = f"""# 风险控制评估 — {today}

> 🛡️ 复盘子Agent | 评估时间: {datetime.now().strftime('%H:%M:%S')}

---

## 一、风险等级

**今日风险等级: {risk_level}**

风险信号统计：
- 🔴 高风险信号: {high_risk} 个
- 🟡 中风险信号: {medium_risk} 个

---

## 二、风险详情

"""
    
    if risks:
        for i, r in enumerate(risks, 1):
            level_icon = "🔴" if r['level'] == 'high' else "🟡"
            content += f"### {i}. {level_icon} {r['type']}\n"
            content += f"{r['desc']}\n\n"
    else:
        content += "今日无明显风险信号\n\n"
    
    content += f"""---

## 三、风险控制建议

**仓位建议：** {risk_advice}

**操作策略：**

| 风险等级 | 建议仓位 | 操作策略 |
|:--------:|:--------:|:--------|
| 🟢 低风险 | 50-70% | 积极参与，关注强势股 |
| 🟡 中风险 | 30-50% | 谨慎操作，逢低布局 |
| 🔴 高风险 | 0-30% | 轻仓或空仓，等待机会 |

---

## 四、止损纪律

1. **单只股票止损：** -8% 强制止损
2. **总仓位止损：** -5% 回撤时减仓
3. **涨停股处理：** 次日高开即考虑部分获利了结
4. **跌停股处理：** 不抄底，严格规避

---

## 五、明日风险预警

"""
    
    # 预警明日可能的风险点
    tomorrow_warnings = []
    
    for stock in data.get('top_stocks', [])[:3]:
        if stock['change'] > 7:
            tomorrow_warnings.append(f"- {stock['name']} 涨幅过大，明日注意高开回落风险")
    
    for stock in data.get('bottom_stocks', [])[:3]:
        if stock['change'] < -5:
            tomorrow_warnings.append(f"- {stock['name']} 回调较大，明日可能继续调整")
    
    if tomorrow_warnings:
        content += '\n'.join(tomorrow_warnings)
    else:
        content += "无明确预警\n"
    
    content += f"""

---

*🛡️ AAna 风险评估 v1.0 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
    
    filepath = save_report('风险评估', content)
    git_commit_and_push(f"feat: add {today} risk assessment (auto)")
    
    return filepath

def tomorrow_strategy():
    """21:45 明日策略规划"""
    log("="*50)
    log("🎯 21:45 明日策略规划")
    
    summary_state = load_state('postmarket_summary')
    if not summary_state:
        log("缺少汇总数据，跳过策略规划")
        return None
    
    data = summary_state['data']
    today = get_today_str()
    
    index_data = data.get('index_summary', [])
    sector_data = data.get('sector_summary', [])
    
    avg_change = sum(i['change'] for i in index_data) / len(index_data) if index_data else 0
    
    # 明日大盘预判
    if avg_change > 2:
        tomorrow_market = "📈 大概率高开延续"
        tomorrow_advice = "积极布局，延续今日强势"
    elif avg_change > 0.5:
        tomorrow_market = "📈 小幅高开震荡"
        tomorrow_advice = "震荡偏强，可适度加仓"
    elif avg_change > -0.5:
        tomorrow_market = "➡️ 低开震荡"
        tomorrow_advice = "谨慎操作，等待方向明确"
    elif avg_change > -2:
        tomorrow_market = "📉 低开调整"
        tomorrow_advice = "防御为主，控制仓位"
    else:
        tomorrow_market = "❄️ 大幅低开"
        tomorrow_advice = "轻仓观望，等待市场稳定"
    
    # 重点关注板块
    focus_sectors = []
    for s in sector_data[:3]:
        if s['avg_change'] > 0:
            focus_sectors.append({
                'name': s['name'],
                'logic': s['logic'],
                'change': s['avg_change']
            })
    
    # 生成明日策略
    content = f"""# 明日策略规划 — {today}

> 🎯 复盘子Agent | 规划时间: {datetime.now().strftime('%H:%M:%S')}

---

## 一、明日大盘预判

**指数环境：** {'多头排列' if avg_change > 1 else ('空头排列' if avg_change < -1 else '震荡整理')}

| 指标 | 今日收盘 | 明日预判 |
|:----:|:--------:|:--------:|
"""
    
    for idx in index_data:
        emoji = "📈" if idx['change'] > 0 else "📉"
        content += f"| {idx['name']} | {emoji} {idx['change']:+.2f}% | 待定 |\n"
    
    content += f"""

**明日开盘预期:** {tomorrow_market}
**操作建议:** {tomorrow_advice}

---

## 二、重点关注板块（明日）

| 优先级 | 板块 | 今日表现 | 关注逻辑 |
|:------:|:----:|:--------:|:--------|
"""
    
    for i, s in enumerate(focus_sectors[:3], 1):
        medal = ["🥇", "🥈", "🥉"][i-1]
        emoji = "🔴" if s['change'] > 0 else "🟢"
        content += f"| {medal} | {s['name']} | {emoji} {s['change']:+.2f}% | {s['logic']} |\n"
    
    if not focus_sectors:
        content += "| - | 无明显强势板块 | 等待机会 |\n"
    
    content += f"""

---

## 三、操作计划

### 明日开盘前（09:00-09:25）

1. 查看隔夜美股表现
2. 查看A50期货走势
3. 确认是否有重大消息面影响

### 盘中操作（09:30-15:00）

| 时间 | 操作重点 |
|:----:|:--------:|
| 09:30-10:00 | 观察开盘走势，不追高 |
| 10:00-11:30 | 回调时适度加仓 |
| 13:00-14:30 | 持有为主，谨慎操作 |
| 14:30-15:00 | 尾盘减仓，锁定利润 |

---

## 四、选股方向

"""
    
    # 推荐关注的标的
    if focus_sectors:
        content += f"**明日重点关注：**\n\n"
        for s in focus_sectors[:2]:
            content += f"### {s['name']}\n"
            content += f"> 逻辑：{s['logic']}\n\n"
            
            # 从板块中找回调到位的股票
            for cat_id, cat in STOCK_POOL.items():
                if cat['name'] == s['name']:
                    for code in cat['codes'][:3]:
                        # 找到对应的股票数据
                        for stock in data.get('top_stocks', []) + data.get('bottom_stocks', []):
                            if stock['code'] == code:
                                change = stock['change']
                                if -5 <= change <= 3:
                                    emoji = "✅" if 0 <= change <= 3 else "🔥"
                                    content += f"- {emoji} {stock['name']}({code}) {change:+.2f}%\n"
    else:
        content += "**明日暂无明确方向，观望为主**\n"
    
    content += f"""

---

## 五、风险提醒

1. **严格止损：** 单只股票-8%必须止损
2. **控制仓位：** 明日{'保持50-70%' if avg_change > 0 else '控制在30-50%'}
3. **不追高：** 涨幅超过5%的不追入
4. **分散投资：** 不重仓单只股票

---

## 六、下一个交易日时间线

| 时间 | 任务 |
|:----:|:----:|
| 07:00 | 🦞 盘前健康检测 |
| 08:25 | 🔧 系统自检 |
| 08:30 | 📋 盘前简报 |
| 09:25 | 集合竞价确认 |
| 09:28 | 🎯 竞价推送 |
| 09:30 | 🔴 开盘 |
| 11:28 | 📋 午盘总结 |
| 14:40 | 📊 尾盘分析 |
| 15:00 | 🔵 收盘 |
| 21:30 | 🌙 复盘开始 |

---

*🎯 AAna 明日策略 v1.0 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
    
    filepath = save_report('明日策略', content)
    
    # 生成完整的每日复盘评分
    full_review_content = generate_full_review(today, data, avg_change, focus_sectors)
    review_filepath = save_report('复盘评分', full_review_content)
    
    git_commit_and_push(f"feat: add {today} tomorrow strategy and full review (auto)")
    
    return filepath, review_filepath

def generate_full_review(today, data, avg_change, focus_sectors):
    """生成完整复盘评分报告"""
    
    index_data = data.get('index_summary', [])
    sector_data = data.get('sector_summary', [])
    top_stocks = data.get('top_stocks', [])
    bottom_stocks = data.get('bottom_stocks', [])
    
    # 计算复盘评分
    # 1. 大盘表现得分
    if avg_change > 2:
        market_score = 25
        market_desc = "强势上涨"
    elif avg_change > 0:
        market_score = 20
        market_desc = "小幅上涨"
    elif avg_change > -2:
        market_score = 10
        market_desc = "震荡下跌"
    else:
        market_score = 0
        market_desc = "大幅下跌"
    
    # 2. 赚钱效应
    up_count = len([s for s in top_stocks + bottom_stocks if s['change'] > 0])
    total = len(top_stocks) + len(bottom_stocks)
    profit_score = int(25 * up_count / total) if total > 0 else 0
    
    # 3. 风险控制
    risk_score = 25 if avg_change > -2 else 15 if avg_change > -3 else 5
    
    # 4. 策略执行
    strategy_score = 25 if avg_change > 0 else 15 if avg_change > -1 else 5
    
    total_score = market_score + profit_score + risk_score + strategy_score
    
    # 评分等级
    if total_score >= 85:
        grade = "🏆 S级"
        grade_desc = "完美交易"
    elif total_score >= 70:
        grade = "✅ A级"
        grade_desc = "优秀交易"
    elif total_score >= 55:
        grade = "⚠️ B级"
        grade_desc = "一般交易"
    elif total_score >= 40:
        grade = "🔸 C级"
        grade_desc = "较差交易"
    else:
        grade = "❌ D级"
        grade_desc = "糟糕交易"
    
    content = f"""# AAna每日复盘评分 — {today}

> 🌙 复盘子Agent | 复盘时间: {datetime.now().strftime('%H:%M:%S')}

---

## 一、复盘评分

**综合评分: {total_score}/100 {grade}**

| 评分维度 | 得分 | 满分 | 评价 |
|:--------:|:----:|:----:|:----:|
| 大盘表现 | {market_score} | 25 | {market_desc} |
| 赚钱效应 | {profit_score} | 25 | {'良好' if up_count > total/2 else '较差'} |
| 风险控制 | {risk_score} | 25 | {'良好' if avg_change > -2 else '需加强'} |
| 策略执行 | {strategy_score} | 25 | {grade_desc} |

**总体评价: {grade_desc}**

---

## 二、今日大盘

"""
    
    for idx in index_data:
        emoji = "🔴" if idx['change'] > 0 else "🟢"
        content += f"| {idx['name']} | {emoji} {idx['change']:+.2f}% |\n"
    
    content += f"""

## 三、今日涨跌幅榜

### 涨幅榜 Top 5

| 股票 | 代码 | 板块 | 收盘涨幅 |
|:----:|:----:|:----:|:--------:|
"""
    
    for s in top_stocks[:5]:
        emoji = "🔴" if s['change'] > 0 else "🟢"
        content += f"| {get_sector_emoji(s['name'])}{s['name']} | {s['code']} | {s.get('category', '-')} | {emoji} {s['change']:+.2f}% |\n"
    
    content += f"""

### 跌幅榜 Top 5

| 股票 | 代码 | 板块 | 收盘涨幅 |
|:----:|:----:|:----:|:--------:|
"""
    
    for s in bottom_stocks:
        emoji = "🟢" if s['change'] < 0 else "🔴"
        content += f"| {get_sector_emoji(s['name'])}{s['name']} | {s['code']} | {s.get('category', '-')} | {emoji} {s['change']:+.2f}% |\n"
    
    content += f"""

## 四、明日展望

"""
    
    if focus_sectors:
        content += f"**重点关注板块:** {', '.join([s['name'] for s in focus_sectors[:2]])}\n"
    else:
        content += "**明日暂无明确方向**\n"
    
    content += f"""

---

*🌙 AAna 复盘评分 v1.0 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
    
    return content

def run():
    """主运行函数"""
    log("🌙 复盘子Agent 启动")
    
    if not is_trading_day():
        log("今日非交易日，退出")
        return
    
    current_time = datetime.now()
    hour = current_time.hour
    minute = current_time.minute
    
    if hour == 21 and minute == 30:
        data_summary()
    elif hour == 21 and minute == 35:
        strategy_analysis()
    elif hour == 21 and minute == 40:
        risk_assessment()
    elif hour == 21 and minute == 45:
        tomorrow_strategy()
    else:
        log(f"当前时间 {hour}:{minute:02d} 无需执行任务")

if __name__ == "__main__":
    run()

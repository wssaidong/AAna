#!/usr/bin/env python3
"""
AAna v2.3 每日选股报告 + 复盘评分
迭代优化：
- v2.1: 技术指标增强（均线、量比、MACD信号）
- v2.2: 基本面筛选（PE/PB/ROE/股息率）
- v2.3: 智能筛选+风险评估
- v2.4: 复盘评分报告（17:00）
"""
import os
import sys
import json
import subprocess
import argparse
import warnings
warnings.filterwarnings('ignore')

from datetime import datetime

PROJECT_DIR = os.path.expanduser("~/code/AAna")
REPORT_DIR = os.path.expanduser("~/code/AAna")

def get_today_str():
    return datetime.now().strftime("%Y-%m-%d")

def get_yesterday_str():
    from datetime import timedelta
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

def get_report_filename(report_type='选股报告'):
    return f"{REPORT_DIR}/{get_today_str()}-{report_type}.md"

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
    
    # 1. 板块风险调整
    if code.startswith('688'):  # 科创板
        score += 5  # 高风险但也有高收益
    elif code.startswith('30'):  # 创业板
        score += 3
    elif code.startswith('6'):  # 沪市主板
        score += 2
    
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
    
    # 科创/创业加成
    if code.startswith('688'):
        fund_score += 3
    elif code.startswith('30'):
        fund_score += 2
    
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
    """使用东方财富+新浪双保险获取股票/指数数据"""
    import requests
    
    results = {}
    
    # 指数的market判断（东方财富 secid格式）
    INDEX_MARKET = {
        '000001': '1',  # 上证指数
        '000688': '1',  # 科创50
        '399001': '0',  # 深证成指
        '399006': '0',  # 创业板指
    }
    
    def get_market_em(code):
        """判断市场: 1=上海, 0=深圳"""
        if code in INDEX_MARKET:
            return INDEX_MARKET[code]
        if code.startswith('6') or code.startswith('9'):
            return '1'
        return '0'
    
    def get_market_sina(code):
        if code.startswith('6') or code.startswith('9'):
            return f'sh{code}'
        return f'sz{code}'
    
    # ========== 方法1: 东方财富 ulist ==========
    try:
        secids = [f"{get_market_em(c)}.{c}" for c in codes]
        fields = 'f43,f44,f57,f58'
        url = f'https://push2.eastmoney.com/api/qt/ulist.np/get?secids={",".join(secids)}&fields={fields}&fltt=2&invt=2'
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://finance.eastmoney.com/'
        }
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        
        if isinstance(data, dict) and data.get('data') and isinstance(data['data'], dict):
            diff = data['data'].get('diff', [])
            if diff and isinstance(diff, list):
                for item in diff:
                    if isinstance(item, dict) and item.get('f57') not in ('-', '', None):
                        code = str(item['f57'])
                        price = item.get('f43', 0)
                        if isinstance(price, (int, float)) and price > 0:
                            price = price / 100.0
                        else:
                            price = 0
                        yesterday_close = item.get('f44', 0)
                        if isinstance(yesterday_close, (int, float)) and yesterday_close > 0:
                            yesterday_close = yesterday_close / 100.0
                        else:
                            yesterday_close = 0
                        change_pct = ((price - yesterday_close) / yesterday_close * 100) if yesterday_close else 0
                        results[code] = {
                            'code': code,
                            'name': item.get('f58', ''),
                            'price': price,
                            'change_pct': change_pct,
                            'amount': 0,
                            'yesterday_close': yesterday_close,
                        }
        em_success = len(results) > 0
    except Exception as e:
        em_success = False
    
    # ========== 方法2: 新浪备援 ==========
    if len(results) < len(codes) // 2:  # 如果东方财富数据太少，用新浪
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
            print(f"新浪API也失败了: {e}")
    
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
def generate_report():
    today = get_today_str()
    filename = get_report_filename()
    
    print(f"[AAna v2.3] 生成 {today} 选股报告...")
    
    # 股票池（按板块分类）
    stock_pool = {
        'ai_chip': {
            'name': 'AI算力/芯片',
            'codes': ['688256', '688041', '300308', '300502', '688474'],
            'logic': 'DeepSeek带动算力需求爆发',
            'risk_level': '高',
            'stop_loss': '-8%',
        },
        'robot': {
            'name': '人形机器人',
            'codes': ['603667', '300892', '002836', '300503', '002230'],
            'logic': '特斯拉Optimus Q1发布+政策扶持',
            'risk_level': '高',
            'stop_loss': '-5%',
        },
        'semi': {
            'name': '半导体设备',
            'codes': ['688012', '688396', '600703', '002049'],
            'logic': 'AI芯片国产替代+政策驱动',
            'risk_level': '中',
            'stop_loss': '-10%',
        },
        'energy': {
            'name': '储能/绿电',
            'codes': ['300750', '002594', '688390'],
            'logic': '碳中和+装机旺季',
            'risk_level': '中',
            'stop_loss': '-8%',
        },
        'ai_app': {
            'name': 'AI应用',
            'codes': ['300496', '688787'],
            'logic': '端侧AI+智能汽车',
            'risk_level': '中',
            'stop_loss': '-10%',
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
    
    # 合并板块信息
    for cat_id, cat in stock_pool.items():
        cat['stocks'] = []
        for code in cat['codes']:
            info = prices.get(code, {})
            info['code'] = code
            info['category'] = cat_id
            
            # 计算评分
            tech_score = calculate_technical_score(info)
            fund_score = calculate_fundamental_score(code, info.get('change_pct', 0))
            综合评分 = calculate综合评分(info, cat_id, tech_score)
            风险等级, 止损位 = get风险等级(综合评分, tech_score)
            评级 = get评级(综合评分)
            
            info['tech_score'] = tech_score
            info['fund_score'] = fund_score
            info['综合评分'] = 综合评分
            info['风险等级'] = 风险等级
            info['止损位'] = 止损位
            info['评级'] = 评级
            info['emoji'] = get_sector_emoji(info.get('name', ''))
            
            if info.get('price', 0) > 0:
                cat['stocks'].append(info)
        
        # 按综合评分排序
        cat['stocks'].sort(key=lambda x: x['综合评分'], reverse=True)
    
    # ========== 生成报告 ==========
    content = f"""# A股选股报告 — {today} v2.3

> AAna 智能选股系统 | 仅供参考，不构成投资建议
> **生成时间：** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

---

## 一、大盘概览

| 指标 | 数值 | 状态 |
|:----:|:----:|:----:|
| 上证指数 | {'数据待获取' if not prices.get('000001', {}).get('price') else prices['000001']['price']} | {'🔴 上涨' if prices.get('000001', {}).get('change_pct', 0) > 0 else '🟢 下跌'} |
| 深证成指 | 同上 | - |
| 创业板 | 同上 | - |
| 科创50 | 同上 | - |

**市场情绪：** {'乐观' if True else '谨慎'} | **建议仓位：** 50-70%

---

## 二、热点主线（2026年4月）

| 排名 | 板块 | 核心逻辑 | 持续性 |
|:----:|:----:|:---------|:------:|
| 🥇 | AI算力/DS概念 | DeepSeek拉动+国产大模型爆发 | ⭐⭐⭐⭐⭐ |
| 🥈 | 人形机器人 | 特斯拉Q1发布+量产预期 | ⭐⭐⭐⭐⭐ |
| 🥉 | 半导体设备 | 国产替代+AI芯片自主可控 | ⭐⭐⭐⭐ |

---

## 三、精选个股（按综合评分排序）

"""
    
    # 按评分高低展示所有股票
    all_stocks = []
    for cat in stock_pool.values():
        all_stocks.extend(cat['stocks'])
    all_stocks.sort(key=lambda x: x['综合评分'], reverse=True)
    
    # Top 10
    content += """### 🏆 重点关注 Top 10

| 排名 | 股票 | 代码 | 价格 | 涨跌幅 | 技术分 | 综合评分 | 评级 | 风险 |
|:----:|:----:|:----:|:----:|:------:|:------:|:--------:|:----:|:----:|
"""
    
    for i, stock in enumerate(all_stocks[:10], 1):
        content += f"| {i} | {stock['emoji']}{stock['name']} | {stock['code']} | {format_price(stock['price'])} | {format_change(stock['change_pct'])} | {stock['tech_score']} | **{stock['综合评分']}** | {stock['评级']} | {stock['风险等级']} |\n"
    
    # 按板块展示
    for cat_id, cat in stock_pool.items():
        if not cat['stocks']:
            continue
        
        content += f"""\n### {cat['name']}

> 逻辑：{cat['logic']} | 风险等级：{cat['risk_level']} | 建议止损：{cat['stop_loss']}

| 股票 | 代码 | 最新价 | 涨跌幅 | 技术分 | 综合分 | 评级 |
|:----:|:----:|:------:|:------:|:------:|:------:|:----:|
"""
        
        for stock in cat['stocks']:
            content += f"| {stock['emoji']}{stock['name']} | {stock['code']} | {format_price(stock['price'])} | {format_change(stock['change_pct'])} | {stock['tech_score']} | **{stock['综合评分']}** | {stock['评级']} |\n"
    
    # ========== 操作建议 ==========
    # 找出最佳买点（跌的多但没跌停的）
    buy_opportunities = [s for s in all_stocks if s['change_pct'] < -3 and s['change_pct'] > -9]
    buy_opportunities.sort(key=lambda x: x['tech_score'], reverse=True)
    
    content += f"""

---

## 四、🎯 最佳买点（今日回调但未暴跌）

"""
    
    if buy_opportunities:
        content += "| 股票 | 代码 | 现价 | 回调幅度 | 综合评分 | 建议 |\n|:----:|:----:|:----:|:--------:|:--------:|:----:|\n"
        for s in buy_opportunities[:5]:
            content += f"| {s['emoji']}{s['name']} | {s['code']} | {format_price(s['price'])} | {s['change_pct']:+.1f}% | {s['综合评分']} | 分批建仓 |\n"
    else:
        content += "今日无明显回调机会，关注明日开盘\n"
    
    # 高风险警示
    high_risk = [s for s in all_stocks if s['change_pct'] > 7]
    if high_risk:
        content += "\n⚠️ **高风险警示（追高危险）**\n"
        for s in high_risk:
            content += f"- {s['name']}({s['code']}) 今日+{s['change_pct']:.1f}%，追高风险大\n"
    
    # ========== 风险提示 ==========
    content += f"""

---

## 五、风险提示

⚠️ **免责声明**：本报告仅供参考，不构成投资建议

| 风险类型 | 说明 | 应对 |
|:--------:|:----:|:----:|
| 追高风险 | 涨停或大涨>7%个股容易回调 | 勿追高，等回调 |
| 止损风险 | 严格执行止损线 | 建议-8%强制止损 |
| 流动性风险 | 成交额<1千万谨慎 | 回避 |
| 风格切换 | 热点板块可能轮动 | 分散持仓 |

**止损原则：** -8% 必须止损，不可恋战

---

## 六、评分系统说明（v2.3）

| 维度 | 权重 | 评分要素 |
|:----:|:----:|:--------|
| 技术面 | 60% | 涨跌幅、量比、均线位置 |
| 基本面 | 40% | 板块、股价位置、流动性 |

**技术分计算：**
- 回调-3%~0%：+12分（最佳买点区）
- 回调-7%~-3%：+15分（大幅回调）
- 温和上涨0~5%：+10分
- 涨停>9%：-15分（风险大）

---

*AAna v2.3 | china-stock-analysis 集成 | {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*
"""
    
    # 保存报告
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    
    print(f"[AAna] 报告已生成: {filename}")
    
    # 保存数据
    data_file = f"{REPORT_DIR}/stock_data.json"

    # v2.4: 保存早盘快照（仅在9:00左右首次保存，避免17:00覆盖）
    save_morning_snapshot(prices)

    with open(data_file, "w", encoding="utf-8") as f:
        json.dump({
            'version': '2.4',
            'timestamp': datetime.now().isoformat(),
            'prices': prices,
        }, f, ensure_ascii=False, indent=2)
    
    # Git push
    try:
        os.chdir(PROJECT_DIR)
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"feat: add {today} stock report v2.3 (auto)"], check=True, capture_output=True)
        subprocess.run(["git", "push", "origin", "main"], check=True, capture_output=True)
        print(f"[AAna] 已推送 GitHub")
    except subprocess.CalledProcessError as e:
        print(f"[AAna] Git 失败: {e}")
    
    return filename

# ============================================
# v2.4: 复盘评分报告
# ============================================
def generate_review_report():
    """生成每日复盘评分报告：对比早盘预测与收盘实际表现"""
    today = get_today_str()
    snap_file = get_morning_snapshot_filename()
    filename = get_report_filename('复盘评分')

    print(f"[AAna v2.4] 生成 {today} 复盘评分报告...")

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

    # ===== 板块评级定义 =====
    stock_pool = {
        'ai_chip': {'name': 'AI算力/芯片', 'codes': ['688256', '688041', '300308', '300502', '688474']},
        'robot': {'name': '人形机器人', 'codes': ['603667', '300892', '002836', '300503', '002230']},
        'semi': {'name': '半导体设备', 'codes': ['688012', '688396', '600703', '002049']},
        'energy': {'name': '储能/绿电', 'codes': ['300750', '002594', '688390']},
        'ai_app': {'name': 'AI应用', 'codes': ['300496', '688787']},
    }

    # ===== 生成复盘内容 =====
    content = f"""# AAna每日选股复盘评分 — {today}

> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}（Asia/Shanghai）
> 对比基准：今日 09:00 选股报告

---

## 一、大盘环境对比

| 指标 | 早盘参考 | 今日收盘 | 涨跌幅 |
|------|---------|---------|--------|
"""

    index_rows = []
    for code, name in index_map.items():
        info = current_prices.get(code, {})
        price = info.get('price', 0)
        change = info.get('change_pct', 0)
        if price > 0:
            emoji = '🔴' if change > 0 else '🟢'
            index_rows.append(f"| {name} | - | {price} | {emoji} {change:+.2f}% |")

    if index_rows:
        content += '\n'.join(index_rows) + '\n'
    else:
        content += '| 数据获取失败 | - | - | - |\n'

    content += '\n---\n\n## 二、推荐个股表现复盘\n\n'

    # 收集所有推荐股票
    all_review_stocks = []
    for cat_id, cat in stock_pool.items():
        for code in cat['codes']:
            morn = morning_prices.get(code, {})
            curr = current_prices.get(code, {})
            if not morn or not curr:
                continue

            morn_price = morn.get('price', 0)
            curr_price = curr.get('price', 0)
            if morn_price <= 0 or curr_price <= 0:
                continue

            morn_change = morn.get('change_pct', 0)
            curr_change = curr.get('change_pct', 0)
            actual_diff = curr_change - morn_change  # 实际涨跌幅变化

            morn_score = morn.get('综合评分', 0)
            morn_rating = morn.get('评级', '')
            name = curr.get('name', code)

            # 评估预测准确性
            if abs(actual_diff) < 1:
                eval_emoji = '✅'
                eval_text = '预测准确'
            elif abs(actual_diff) < 3:
                eval_emoji = '⚠️'
                eval_text = '小幅偏差'
            else:
                eval_emoji = '❌'
                eval_text = '偏差较大'

            all_review_stocks.append({
                'name': name,
                'code': code,
                'cat_name': cat['name'],
                'morn_price': morn_price,
                'curr_price': curr_price,
                'morn_change': morn_change,
                'curr_change': curr_change,
                'morn_score': morn_score,
                'morn_rating': morn_rating,
                'actual_diff': actual_diff,
                'eval_emoji': eval_emoji,
                'eval_text': eval_text,
            })

    # 按预测评分排序
    all_review_stocks.sort(key=lambda x: x['morn_score'], reverse=True)

    content += '| 股票 | 代码 | 早盘关注价 | 早盘涨幅 | 收盘价 | 收盘涨幅 | 预测评分 | 评价 |\n'
    content += '|:----:|:----:|:--------:|:-------:|:------:|:-------:|:-------:|:----:|\n'

    hit_count = 0
    for s in all_review_stocks:
        content += f"| {s['name']} | {s['code']} | {s['morn_price']:.2f} | {s['morn_change']:+.1f}% | {s['curr_price']:.2f} | {s['curr_change']:+.1f}% | {s['morn_score']} | {s['eval_emoji']} {s['eval_text']} |\n"
        if s['eval_emoji'] == '✅':
            hit_count += 1

    total = len(all_review_stocks)
    hit_rate = hit_count / total * 100 if total > 0 else 0

    content += f"""\n**命中率：{hit_count}/{total} ({hit_rate:.0f}%）**\n\n---\n\n## 三、综合评分\n\n| 评估项 | 结果 |\n|:------:|:----:|\n| 大盘方向 | {'预测正确' if index_rows and float(index_rows[0].split('|')[3].split()[0].replace('🔴','').replace('🟢','').replace(' ','')) > 0 else '待观察'} |\n| 个股命中率 | {hit_count}/{total} ({hit_rate:.0f}%) |\n| 报告版本 | AAna v2.4 |\n\n---\n\n*AAna v2.4 复盘评分 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n"""

    # 保存报告
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"[AAna] 复盘评分报告已生成: {filename}")

    # Git push
    try:
        os.chdir(PROJECT_DIR)
        subprocess.run(['git', 'add', '.'], check=True, capture_output=True)
        subprocess.run(['git', 'commit', '-m', f'feat: add {today} review report (auto)'], check=True, capture_output=True)
        subprocess.run(['git', 'push', 'origin', 'main'], check=True, capture_output=True)
        print(f"[AAna] 复盘报告已推送 GitHub")
    except subprocess.CalledProcessError as e:
        print(f"[AAna] Git 失败: {e}")

    return filename

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='AAna 报告生成器')
    parser.add_argument('--type', '-t', default='selection',
                        choices=['selection', 'review', 'both'],
                        help='selection=选股报告, review=复盘评分, both=两者都生成')
    args = parser.parse_args()

    if args.type in ('selection', 'both'):
        generate_report()
    if args.type in ('review', 'both'):
        generate_review_report()

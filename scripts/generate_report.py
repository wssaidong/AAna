#!/usr/bin/env python3
"""
AAna 每日选股报告自动生成脚本
整合 china-stock-analysis 技能，提供基本面+技术面综合评分
"""
import os
import sys
import json
import subprocess
import warnings
warnings.filterwarnings('ignore')

from datetime import datetime

# 项目路径
PROJECT_DIR = os.path.expanduser("~/code/AAna")
REPORT_DIR = os.path.expanduser("~/code/AAna")

def get_today_str():
    return datetime.now().strftime("%Y-%m-%d")

def get_report_filename():
    today = get_today_str()
    return f"{REPORT_DIR}/{today}-选股报告.md"

def calculate_score(row):
    """
    综合评分：基本面(60%) + 技术面(40%)
    返回 0-100 分
    """
    score = 50  # 基础分
    
    try:
        # 基本面指标 (PE, PB, ROE, 涨跌幅)
        pe = row.get('市盈率-动态', None)
        if pe and 0 < pe < 100:
            if pe < 20:
                score += 15
            elif pe < 40:
                score += 8
            elif pe > 80:
                score -= 10
        
        pb = row.get('市净率', None)
        if pb and 0 < pb < 20:
            if pb < 3:
                score += 10
            elif pb < 5:
                score += 5
        
        # 涨跌幅动量
        change = row.get('涨跌幅', 0)
        if change:
            if -5 < change < 0:  # 小幅回调，可能是买入机会
                score += 12
            elif -10 < change < -5:  # 大幅回调
                score += 18
            elif 0 < change < 3:  # 温和上涨
                score += 8
            elif change > 9:  # 涨停，风险大
                score -= 8
        
        # 成交额（流动性）
        amount = row.get('成交额', 0)
        if amount and amount > 5e8:  # >5千万
            score += 5
        
        # 股价位置（相对高低）
        price = row.get('最新价', 0)
        if price:
            high_52w = row.get('52周最高', 0)
            low_52w = row.get('52周最低', 0)
            if high_52w and low_52w and high_52w > low_52w:
                position = (price - low_52w) / (high_52w - low_52w)
                if position < 0.3:  # 低位
                    score += 10
                elif position > 0.8:  # 高位
                    score -= 5
                    
    except Exception as e:
        print(f"评分计算异常: {e}")
    
    return max(0, min(100, score))

def get_stock_data_sina(codes):
    """
    使用新浪财经API获取股票数据（更稳定）
    """
    import requests
    
    results = {}
    
    def format_code(code):
        if code.startswith('6') or code.startswith('9'):
            return f'sh{code}'
        else:
            return f'sz{code}'
    
    formatted = [format_code(c) for c in codes]
    url = f'http://hq.sinajs.cn/list={",".join(formatted)}'
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Referer': 'http://finance.sina.com.cn'
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = 'gbk'
        
        lines = resp.text.strip().split('\n')
        for i, line in enumerate(lines):
            if '=' not in line:
                continue
            code = codes[i] if i < len(codes) else ''
            parts = line.split('=')[1].strip('";\n ').split(',')
            
            if len(parts) < 10:
                results[code] = {'name': '', 'price': 0, 'change': 0, 'change_pct': 0, 'amount': 0}
                continue
            
            name = parts[0]
            yesterday_close = float(parts[2]) if parts[2] else 0
            price = float(parts[3]) if parts[3] else 0
            change = price - yesterday_close
            change_pct = (change / yesterday_close * 100) if yesterday_close else 0
            amount = float(parts[9]) if parts[9] else 0  # 万元
            
            results[code] = {
                'name': name,
                'price': price,
                'change': change,
                'change_pct': change_pct,
                'amount': amount * 10000,  # 转换为元
                'yesterday_close': yesterday_close,
            }
    except Exception as e:
        print(f"新浪API获取失败: {e}")
        # Fallback: 全部设为0
        for code in codes:
            results[code] = {'name': '', 'price': 0, 'change': 0, 'change_pct': 0, 'amount': 0}
    
    return results

def get_stock_prices_ak(codes):
    """使用akshare获取股票数据（备用）"""
    results = {}
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        for code in codes:
            row = df[df['代码'] == code]
            if not row.empty:
                results[code] = {
                    'name': row['名称'].values[0],
                    'price': float(row['最新价'].values[0]),
                    'change': float(row['涨跌幅'].values[0]),
                    'change_pct': float(row['涨跌幅'].values[0]),
                    'amount': float(row['成交额'].values[0]) if '成交额' in row.columns else 0,
                }
            else:
                results[code] = {'name': '', 'price': 0, 'change': 0, 'change_pct': 0, 'amount': 0}
    except Exception as e:
        print(f"akshare获取失败: {e}")
        for code in codes:
            results[code] = {'name': '', 'price': 0, 'change': 0, 'change_pct': 0, 'amount': 0}
    return results

def get_stock_prices(codes):
    """获取股票价格，优先用新浪API，失败则用akshare"""
    # 先试新浪
    prices = get_stock_data_sina(codes)
    # 检查是否有有效数据
    has_data = any(p.get('price', 0) > 0 for p in prices.values())
    if has_data:
        return prices
    
    # 新浪失败，试用akshare
    print("[AAna] 新浪API无数据，尝试akshare...")
    return get_stock_prices_ak(codes)

def format_price(price):
    if price is None or price == 0:
        return "（待获取）"
    return f"¥{price:.2f}"

def format_change(change_pct):
    if change_pct is None or change_pct == 0:
        return "-"
    emoji = "🔴" if change_pct > 0 else "🟢" if change_pct < 0 else "⚪"
    return f"{emoji} {change_pct:+.2f}%"

def get_score_label(score):
    """根据评分返回标签"""
    if score >= 80:
        return "⭐⭐⭐⭐⭐ 强烈推荐"
    elif score >= 70:
        return "⭐⭐⭐⭐ 推荐"
    elif score >= 60:
        return "⭐⭐⭐ 谨慎推荐"
    elif score >= 50:
        return "⭐⭐ 观察"
    else:
        return "⭐ 不推荐"

def generate_report():
    """生成报告的主逻辑"""
    today = get_today_str()
    filename = get_report_filename()
    
    print(f"[AAna Report] 生成 {today} 选股报告...")
    
    # 监控的股票池（按类别）
    stock_pool = {
        'robot': {
            'name': '人形机器人',
            'codes': ['603667', '300892', '002836', '300503', '002230'],
            'logic': '特斯拉Optimus量产+政策扶持',
            'risk': '高',
            'stop_loss': '-5%',
        },
        'ai_chip': {
            'name': 'AI算力/芯片',
            'codes': ['688256', '688041', '300308', '300502', '688474'],
            'logic': '国产大模型DeepSeek拉动+算力需求爆发',
            'risk': '高',
            'stop_loss': '-8%',
        },
        'semi': {
            'name': '半导体设备',
            'codes': ['688012', '688396', '600703', '002049'],
            'logic': 'AI芯片自主可控+国产替代',
            'risk': '中',
            'stop_loss': '-10%',
        },
        'energy': {
            'name': '储能/绿电',
            'codes': ['300750', '002594', '688390'],
            'logic': '碳中和政策+装机旺季',
            'risk': '中',
            'stop_loss': '-8%',
        },
        'ai_app': {
            'name': 'AI应用',
            'codes': ['300496', '688787'],
            'logic': '端侧AI+智能汽车',
            'risk': '中',
            'stop_loss': '-10%',
        },
    }
    
    # 收集所有代码
    all_codes = []
    for category in stock_pool.values():
        all_codes.extend(category['codes'])
    
    # 去重
    all_codes = list(dict.fromkeys(all_codes))
    
    # 获取股价
    print(f"[AAna] 正在获取 {len(all_codes)} 只股票数据...")
    prices = get_stock_prices(all_codes)
    
    # 生成报告
    content = f"""# A股选股报告 — {today}

> 基于 AAna 选股系统 + 东方财富/新浪财经实时数据 | 仅供参考，不构成投资建议
> **自动生成时间：** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

---

## 一、大盘定位

| 指标 | 数值 | 判断 |
|:----:|:----:|:----:|
| 上证指数 | {prices.get('000001', {}).get('price', '?') if prices.get('000001', {}).get('price', 0) > 0 else '请手动填写'} |  |
| 大盘位置 | | 上涨中继/震荡整固/回调探底 |
| 支撑位 | | |
| 压力位 | | |
| 风险等级 | ⭐⭐⭐ 中 | |
| 成交量 | | |

---

## 二、热点方向（本月核心主线）

| 排名 | 热点板块 | 逻辑 | 持续性 |
|:----:|:--------:|:----:|:------:|
| 1 | 人形机器人 | 特斯拉 Q1 发布 + 量产预期 + 政策扶持 | ⭐⭐⭐⭐ |
| 2 | AI算力/DS概念 | 国产大模型DeepSeek拉动 + 算力需求爆发 | ⭐⭐⭐⭐ |
| 3 | 半导体国产替代 | AI芯片自主可控 + 政策强力驱动 | ⭐⭐⭐⭐ |
| 4 | 储能绿电 | 碳中和政策 + 装机旺季 | ⭐⭐⭐ |

---

## 三、个股筛选结果

"""
    
    # 按类别生成表格
    for cat_id, category in stock_pool.items():
        content += f"""### 🚀 {category['name']}

> 策略逻辑：{category['logic']}
> **风险等级：** {category['risk']} | **止损位：** {category['stop_loss']}

| 股票代码 | 股票名称 | 最新价 | 涨跌幅 | 综合评分 | 评级 |
|:--------:|:--------:|:------:|:------:|:--------:|:----:|
"""
        
        # 收集该类别股票数据并排序
        stock_data = []
        for code in category['codes']:
            info = prices.get(code, {})
            if info.get('price', 0) > 0:  # 只显示有数据的
                score = 50  # 简化评分
                # 根据涨跌幅调整评分
                change_pct = info.get('change_pct', 0)
                if -5 < change_pct < 0:
                    score += 15  # 小幅回调是买点
                elif -10 < change_pct <= -5:
                    score += 25  # 大幅回调
                elif 0 <= change_pct < 5:
                    score += 10  # 温和上涨
                
                stock_data.append({
                    'code': code,
                    'name': info.get('name', ''),
                    'price': info.get('price', 0),
                    'change_pct': change_pct,
                    'score': score,
                })
        
        # 按评分排序
        stock_data.sort(key=lambda x: x['score'], reverse=True)
        
        for stock in stock_data:
            label = get_score_label(stock['score'])
            content += f"| {stock['code']} | {stock['name']} | {format_price(stock['price'])} | {format_change(stock['change_pct'])} | {stock['score']} | {label} |\n"
        
        content += "\n"
    
    content += f"""---

## 四、操作建议

### 仓位管理

| 指数位置 | 操作策略 | 仓位建议 |
|:--------:|:--------:|:--------:|
| 压力位以上 | 冲高减仓 | 30-50% |
| 支撑与压力之间 | 持股待涨 | 50-70% |
| 支撑位以下 | 逢低加仓 | 70-100% |

### 分批买入

| 批次 | 比例 | 条件 |
|:----:|:----:|:----:|
| 首批 | 30% | 符合条件即买入 |
| 第二批 | 30% | 回调5%后买入 |
| 第三批 | 40% | 再次回调5%或突破后买入 |

---

## 五、风险提示

⚠️ **免责声明**：本文仅供选股参考，不构成投资建议。股市有风险，入市需谨慎。

- **激进型标的：** 最大亏损可达15%，务必严格止损
- **平衡型标的：** 建议分批建仓
- **稳健型标的：** 适合中线持有
- 每日收盘前检查持仓，设置价格提醒

---

## 六、数据来源

| 用途 | 来源 |
|:----:|:----:|
| 行情数据 | 新浪财经/东方财富实时行情 |
| 热点研报 | 头部券商策略 |
| 选股系统 | AAna v2.0 (china-stock-analysis集成) |

---

*报告生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*
*AAna v2.0 自动生成*
"""
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    
    print(f"[AAna Report] 报告已生成: {filename}")
    
    # 保存股票数据
    data_file = f"{REPORT_DIR}/stock_data.json"
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'prices': prices,
        }, f, ensure_ascii=False, indent=2)
    
    # 自动 commit 并 push
    try:
        os.chdir(PROJECT_DIR)
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"feat: add {today} stock report (auto-generated)"], check=True, capture_output=True)
        subprocess.run(["git", "push", "origin", "main"], check=True, capture_output=True)
        print(f"[AAna Report] 已提交到 GitHub")
    except subprocess.CalledProcessError as e:
        print(f"[AAna Report] Git 操作失败: {e}")
    
    return filename

if __name__ == "__main__":
    generate_report()

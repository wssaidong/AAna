#!/usr/bin/env python3
"""
AAna 每日选股报告自动生成脚本
每天定时运行，从东方财富获取股价数据，生成选股报告
"""
import os
import sys
import json
import subprocess
from datetime import datetime

# 项目路径
PROJECT_DIR = os.path.expanduser("~/code/AAna")
REPORT_DIR = os.path.expanduser("~/code/AAna")

def get_today_str():
    return datetime.now().strftime("%Y-%m-%d")

def get_report_filename():
    today = get_today_str()
    return f"{REPORT_DIR}/{today}-选股报告.md"

def get_stock_price(code):
    """获取单个股票的最新价格"""
    try:
        import akshare as ak
        # 东方财富实时行情
        df = ak.stock_zh_a_spot_em()
        row = df[df['代码'] == code]
        if not row.empty:
            price = row['最新价'].values[0]
            change = row['涨跌幅'].values[0]
            return price, change
    except Exception as e:
        print(f"[AAna] 获取 {code} 股价失败: {e}")
    return None, None

def get_stock_prices(codes):
    """批量获取股票价格"""
    results = {}
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        for code in codes:
            row = df[df['代码'] == code]
            if not row.empty:
                results[code] = {
                    'name': row['名称'].values[0],
                    'price': row['最新价'].values[0],
                    'change': row['涨跌幅'].values[0],
                    'volume': row['成交额'].values[0],
                }
            else:
                results[code] = {'name': '', 'price': None, 'change': None, 'volume': None}
    except Exception as e:
        print(f"[AAna] 批量获取股价失败: {e}")
        # 返回空结果
        for code in codes:
            results[code] = {'name': '', 'price': None, 'change': None, 'volume': None}
    return results

def format_price(price):
    """格式化股价"""
    if price is None:
        return "（待获取）"
    return f"¥{price:.2f}"

def format_change(change):
    """格式化涨跌幅"""
    if change is None:
        return "-"
    return f"{change:+.2f}%"

def generate_report():
    """生成报告的主逻辑"""
    today = get_today_str()
    filename = get_report_filename()
    
    print(f"[AAna Report] 生成 {today} 选股报告...")
    
    # 监控的股票池（按类别）
    stock_pool = {
        'robot': ['603667', '300892', '002836', '300503', '002230'],  # 人形机器人
        'ai_chip': ['688256', '688041', '300308', '300502', '688474'],  # AI算力
        'semi': ['688012', '688396', '600703', '002049'],  # 半导体
        'energy': ['300750', '002594', '688390'],  # 储能
        'ai_app': ['300496', '688787'],  # AI应用
    }
    
    all_codes = []
    for codes in stock_pool.values():
        all_codes.extend(codes)
    
    # 尝试获取股价
    print(f"[AAna] 正在获取 {len(all_codes)} 只股票的实时数据...")
    prices = get_stock_prices(all_codes)
    
    # 生成报告内容
    content = f"""# A股选股报告 — {today}

> 基于 AAna 选股模板 + 东方财富实时数据 | 仅供参考，不构成投资建议
> **自动生成时间：** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

---

## 一、大盘定位（请手动填写）

| 指标 | 数值 | 判断 |
|:----:|:----:|:----:|
| 上证指数 | | |
| 大盘位置 | | 上涨中继/震荡整固/回调探底 |
| 支撑位 | | |
| 压力位 | | |
| 风险等级 | ⭐⭐⭐ 中 | |
| 成交量(亿) | | |

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

> ⚠️ 股价数据取自东方财富实时行情，实际价格请以操盘软件为准

### 🚀 3.1 激进型（热点追涨）— 人形机器人

> 策略指标：#3 放量突破 + #6 事件驱动 + #8 均线多头
> **风险等级：** 高 | **止损位：** -5%

| 股票代码 | 股票名称 | 收盘价 | 涨跌幅 | 买入逻辑 | 对应指标 |
|:--------:|:--------:|:------:|:------:|:--------:|:--------:|
"""
    
    # 人形机器人
    for code in stock_pool['robot']:
        info = prices.get(code, {})
        name = info.get('name', '')
        price = format_price(info.get('price'))
        change = format_change(info.get('change'))
        content += f"| {code} | {name} | {price} | {change} | 特斯拉Optimus供应链 | #3 #6 |\n"
    
    content += """
---

### 📈 3.2 平衡型（趋势波段）— AI算力产业链

> 策略指标：#9 中市值温和上涨 + #12 金叉+低估值
> **风险等级：** 中 | **止损位：** -8%

| 股票代码 | 股票名称 | 收盘价 | 涨跌幅 | 买入逻辑 | 对应指标 |
|:--------:|:--------:|:------:|:------:|:--------:|:--------:|
"""
    
    # AI算力
    for code in stock_pool['ai_chip']:
        info = prices.get(code, {})
        name = info.get('name', '')
        price = format_price(info.get('price'))
        change = format_change(info.get('change'))
        content += f"| {code} | {name} | {price} | {change} | 国产AI芯片龙头+算力自主可控 | #12 |\n"
    
    content += """
---

### 💎 3.3 稳健型（回调低吸）— 半导体设备

> 策略指标：#14 大市值稳健 + #17 基本面+下跌
> **风险等级：** 低 | **止损位：** -10%

| 股票代码 | 股票名称 | 收盘价 | 涨跌幅 | 买入逻辑 | 对应指标 |
|:--------:|:--------:|:------:|:------:|:--------:|:--------:|
"""
    
    # 半导体
    for code in stock_pool['semi']:
        info = prices.get(code, {})
        name = info.get('name', '')
        price = format_price(info.get('price'))
        change = format_change(info.get('change'))
        content += f"| {code} | {name} | {price} | {change} | 半导体设备龙头+业绩稳健 | #14 |\n"
    
    content += """
---

### 🔥 3.4 短线热门（概念炒作）— 储能/绿电 + AI应用

#### 储能概念

| 股票代码 | 股票名称 | 收盘价 | 涨跌幅 | 细分领域 | 备注 |
|:--------:|:--------:|:------:|:------:|:--------:|:------:|
"""
    
    # 储能
    for code in stock_pool['energy']:
        info = prices.get(code, {})
        name = info.get('name', '')
        price = format_price(info.get('price'))
        change = format_change(info.get('change'))
        content += f"| {code} | {name} | {price} | {change} | 储能龙头 | 行业绝对龙头 |\n"
    
    content += """
#### AI应用端

| 股票代码 | 股票名称 | 收盘价 | 涨跌幅 | 细分领域 | 备注 |
|:--------:|:--------:|:------:|:------:|:--------:|:------:|
"""
    
    # AI应用
    for code in stock_pool['ai_app']:
        info = prices.get(code, {})
        name = info.get('name', '')
        price = format_price(info.get('price'))
        change = format_change(info.get('change'))
        content += f"| {code} | {name} | {price} | {change} | AI应用 | 端侧AI+智能汽车 |\n"
    
    content += f"""
---

## 四、操作建议

### 仓位管理

| 指数位置 | 操作策略 | 仓位建议 |
|:--------:|:--------:|:--------:|
| 压力位(3450)以上 | 冲高减仓 | 30-50% |
| 支撑与压力之间 | 持股待涨 | 50-70% |
| 支撑位(3280)以下 | 逢低加仓 | 70-100% |

### 分批买入

| 批次 | 比例 | 条件 |
|:----:|:----:|:----:|
| 首批 | 30% | 符合条件即买入 |
| 第二批 | 30% | 回调5%后买入 |
| 第三批 | 40% | 再次回调5%或突破后买入 |

---

## 五、风险提示

⚠️ **免责声明**：本文仅供选股参考，不构成投资建议。股市有风险，入市需谨慎。

- **激进型标的：** 最大亏损可达15%，务必严格止损（-5%）
- **平衡型标的：** 建议分批建仓（-8%止损）
- **稳健型标的：** 适合中线持有（-10%止损）
- 每日收盘前检查持仓，设置价格提醒

---

## 六、数据来源

| 用途 | 来源 |
|:----:|:----:|
| 行情数据 | 东方财富实时行情 |
| 热点研报 | 中信证券/浦银安盛/头部券商策略 |
| 板块资金 | 同花顺/东方财富 |

---

*报告生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*
*AAna v1.0 自动生成*
"""
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    
    print(f"[AAna Report] 报告已生成: {filename}")
    
    # 自动 commit 并 push
    try:
        os.chdir(PROJECT_DIR)
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", f"feat: add {today} stock report (auto-generated)"], check=True)
        subprocess.run(["git", "push", "origin", "main"], check=True)
        print(f"[AAna Report] 已提交到 GitHub")
    except subprocess.CalledProcessError as e:
        print(f"[AAna Report] Git 操作失败: {e}")
    
    return filename

if __name__ == "__main__":
    generate_report()

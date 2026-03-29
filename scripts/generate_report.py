#!/usr/bin/env python3
"""
AAna 每日选股报告自动生成脚本
每天定时运行，从东方财富/雪球获取股价数据，生成选股报告
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

def run_script():
    """生成报告的主逻辑"""
    today = get_today_str()
    filename = get_report_filename()
    
    print(f"[AAna Report] 生成 {today} 选股报告...")
    
    # 这里可以加入获取实时股价数据的逻辑
    # 目前生成基础模板报告
    content = f"""# A股选股报告 — {today}

> 基于 AAna 选股模板生成 | 仅供参考，不构成投资建议
> **自动生成时间：** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

---

## 一，大盘定位（请手动填写）

| 指标 | 数值 | 判断 |
|:----:|:----:|:----:|
| 上证指数 | | |
| 大盘位置 | | 上涨中继/震荡整固/回调探底 |
| 支撑位 | | |
| 压力位 | | |
| 风险等级 | ⭐⭐⭐ 中 | |
| 成交量(亿) | | |

---

## 二、热点方向（请手动填写）

| 排名 | 热点板块 | 逻辑 | 持续性 |
|:----:|:--------:|:----:|:------:|
| 1 | | | ⭐⭐⭐⭐ |
| 2 | | | ⭐⭐⭐⭐ |
| 3 | | | ⭐⭐⭐ |

---

## 三、选股区域（请根据当天行情手动筛选）

> 建议参考：AAna/docs/stock.md 中的17条选股指标进行筛选

### 🚀 激进型（热点追涨）
| 股票代码 | 股票名称 | 股价 | 买入逻辑 |
|:--------:|:--------:|:----:|:--------:|
| | | | |

### 📈 平衡型（趋势波段）
| 股票代码 | 股票名称 | 股价 | 买入逻辑 |
|:--------:|:--------:|:----:|:--------:|
| | | | |

### 💎 稳健型（回调低吸）
| 股票代码 | 股票名称 | 股价 | 买入逻辑 |
|:--------:|:--------:|:----:|:--------:|
| | | | |

---

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
| 第二批 | 30% | 回測5%后买入 |
| 第三批 | 40% | 再次回调5%或突破后买入 |

---

## 五、风险提示

⚠️ **免责声明**：本文仅供选股参考，不构成投资建议。股市有风险，入市需谨慎。

---

## 六、数据来源

| 用途 | 来源 |
|:----:|:----:|
| 行情数据 | 东方财富/腾讯财经 |
| 热点研报 | 各大券商晨会策略 |

---

*报告由 AAna 自动生成*
*模板版本：AAna v1.0*
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
    run_script()

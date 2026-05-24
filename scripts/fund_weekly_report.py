#!/usr/bin/env python3
"""
AAna 基金周报生成脚本（独立运行）
每周日20:00自动推送飞书
数据来源: 东方财富 fund.eastmoney.com
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fund_screener import screen_funds, format_fund_report
from datetime import datetime

def main():
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"[AAna Fund] 基金周报生成中... {today}")

    results = screen_funds(top_n=5, max_pages=20)
    report = format_fund_report(results)

    # 保存到 reports 目录
    out_dir = os.path.expanduser("~/code/AAna/reports")
    os.makedirs(out_dir, exist_ok=True)
    out_path = f"{out_dir}/{today}-基金周报.md"

    with open(out_path, 'w') as f:
        f.write(report)

    print(f"[AAna Fund] 报告已保存: {out_path}")
    print(report)
    return report

if __name__ == '__main__':
    main()
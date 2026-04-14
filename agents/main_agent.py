#!/usr/bin/env python3
"""
AAna 主Agent (总调度)
负责任务分发和状态管理
"""
import os
import sys
import warnings
warnings.filterwarnings('ignore')

sys.path.insert(0, os.path.expanduser('~/code/AAna'))

from datetime import datetime
from agents.config import get_today_str, is_trading_day
from agents.data_utils import git_commit_and_push

LOG_FILE = os.path.expanduser('~/code/AAna/reports/main_agent.log')

def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')

def run():
    """主Agent入口"""
    log("🦞 AAna 主Agent 启动")
    
    if not is_trading_day():
        log("今日非交易日，退出")
        return
    
    today = get_today_str()
    hour = datetime.now().hour
    
    log(f"今日日期: {today}")
    log(f"当前小时: {hour}")
    
    # 根据时间触发不同子Agent
    if hour < 9 or (hour == 9 and datetime.now().minute < 30):
        # 盘前阶段
        log("盘前阶段，触发盘前子Agent")
        from agents.premarket_agent import run as premarket_run
        premarket_run()
    elif hour < 15:
        # 盘中阶段
        log("盘中阶段，触发盘中子Agent")
        from agents.intraday_agent import run as intraday_run
        intraday_run()
    elif hour >= 21:
        # 复盘阶段
        log("复盘阶段，触发复盘子Agent")
        from agents.postmarket_agent import run as postmarket_run
        postmarket_run()
    else:
        log("非活跃时段，无需执行")

if __name__ == "__main__":
    run()

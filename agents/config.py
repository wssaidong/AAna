"""
AAna 四层Agent架构 - 配置文件
"""
import os
from datetime import datetime

# 项目路径
PROJECT_DIR = os.path.expanduser("~/code/AAna")
REPORTS_DIR = os.path.expanduser("~/code/AAna/reports")
STATE_DIR = os.path.expanduser("~/code/AAna/state")

# 股票池（按板块分类）
STOCK_POOL = {
    'ai_chip': {
        'name': 'AI算力/芯片',
        'codes': ['300308', '300502', '300223', '300604'],
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
        'codes': ['600703', '002049', '600584'],
        'logic': 'AI芯片国产替代+政策驱动',
        'risk_level': '中',
        'stop_loss': '-10%',
    },
    'energy': {
        'name': '储能/绿电',
        'codes': ['300750', '002594', '002459'],
        'logic': '碳中和+装机旺季',
        'risk_level': '中',
        'stop_loss': '-8%',
    },
    'ai_app': {
        'name': 'AI应用',
        'codes': ['300496', '002415'],
        'logic': '端侧AI+智能汽车',
        'risk_level': '中',
        'stop_loss': '-10%',
    },
}

# 指数列表
INDEX_CODES = {
    '000001': '上证指数',
    '399001': '深证成指',
    '399006': '创业板指',
    '000688': '科创50',
}

# 交易时间
TRADING_HOURS = {
    'pre_market': {'start': '07:00', 'end': '09:28'},
    'session': {'start': '09:30', 'end': '11:30'},
    'afternoon': {'start': '13:00', 'end': '15:00'},
    'post_market': {'start': '15:00', 'end': '21:30'},
}

def get_today_str():
    return datetime.now().strftime("%Y-%m-%d")

def get_date_str():
    return datetime.now().strftime("%Y%m%d")

def get_time_str():
    return datetime.now().strftime("%H:%M:%S")

def is_trading_day():
    """简单判断是否是交易日（周一到周五）"""
    weekday = datetime.now().weekday()
    return weekday < 5  # 0=周一, 4=周五

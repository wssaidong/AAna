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
# ⚠️ 仅含主板（沪市600/601/603/605 + 深市000/002/003），禁止创业板(300/301)和科创板(688)
STOCK_POOL = {
    'ai_chip': {
        'name': 'AI算力/芯片',
        'codes': ['603986', '002230', '002049', '002415'],  # 替换为合规主板
        'logic': 'DeepSeek带动算力需求爆发',
        'risk_level': '高',
        'stop_loss': '-8%',
    },
    'robot': {
        'name': '人形机器人',
        'codes': ['603667', '002836', '002230', '600745'],  # 全主板
        'logic': '特斯拉Optimus Q1发布+政策扶持',
        'risk_level': '高',
        'stop_loss': '-5%',
    },
    'semi': {
        'name': '半导体设备',
        'codes': ['600703', '002049', '600584'],  # 全主板
        'logic': 'AI芯片国产替代+政策驱动',
        'risk_level': '中',
        'stop_loss': '-10%',
    },
    'energy': {
        'name': '储能/绿电',
        'codes': ['002594', '002459', '600900'],  # 全主板（宁德时代已移除）
        'logic': '碳中和+装机旺季',
        'risk_level': '中',
        'stop_loss': '-8%',
    },
    'ai_app': {
        'name': 'AI应用',
        'codes': ['002415', '600570'],  # 全主板（中科创达已移除）
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

# 重点关注行业板块（用于盘前行业排名监控）
INDUSTRY_WATCH = {
    '涨幅榜TOP5': 5,   # 触发强势信号阈值
    '跌幅榜TOP5': 5,   # 触发风险预警阈值
    '关注板块': [       # 重点跟综板块
        '人工智能',
        '半导体',
        '机器人概念',
        '新能源汽车',
        '光伏设备',
        '军工',
    ],
}

# 北向资金监控阈值（单位：亿元）
NORTHBOUND_THRESHOLDS = {
    '单日大幅流入预警': 50,    # >50亿视为强势信号
    '单日大幅流出预警': -50,   # <-50亿视为风险信号
    '持续流入追踪': 100,       # 3日累计流入预警
    '持续流出追踪': -100,      # 3日累计流出预警
}

# 涨跌停监控（用于日内 Agent 异动检测）
LIMIT_UP_CONFIG = {
    '强势拉升阈值': 7.0,   # >7% 强势拉升
    '接近涨停阈值': 9.0,   # >9% 接近涨停
    '涨停确认': 9.9,       # >=9.9% 确认涨停
}
LIMIT_DOWN_CONFIG = {
    '走弱阈值': -7.0,      # <-7% 走弱
    '接近跌停阈值': -9.0,  # <-9% 接近跌停
    '跌停确认': -9.9,      # <=-9.9% 确认跌停
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
    """简单判断是否是交易日（周一到周五）
    注意：此函数不校验节假日（如春节、国庆等），仅基于星期判断。
    实际生产环境应调用 akshare 的 is_trading_day() 或接入交易日历API获取准确结果。
    节假日包括但不限于：元旦、春节、清明、劳动节、端午、中秋、国庆等法定假日。
    建议使用 akshare.is_trading_day() 或维护一份准确的交易日历表。
    """
    weekday = datetime.now().weekday()
    return weekday < 5  # 0=周一, 4=周五

"""
AAna Agent System - 共享工具
"""
import os
import json
import subprocess
import warnings
warnings.filterwarnings('ignore')

from datetime import datetime
from .config import PROJECT_DIR, get_today_str, get_time_str

# ============================================
# 数据获取
# ============================================
def get_stock_data_sina(codes):
    """使用新浪财经API获取股票数据"""
    import requests
    
    results = {}
    
    def format_code(code):
        if code.startswith('6') or code.startswith('9'):
            return f'sh{code}'
        return f'sz{code}'
    
    if not codes:
        return results
    
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
                results[code] = {'code': code, 'name': '', 'price': 0, 'change_pct': 0, 'amount': 0}
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
        print(f"[data_utils] 新浪API失败: {e}")
        for code in codes:
            results[code] = {'code': code, 'name': '', 'price': 0, 'change_pct': 0, 'amount': 0}
    
    return results


def get_all_codes():
    """获取所有监控的股票代码"""
    from .config import STOCK_POOL, INDEX_CODES
    
    codes = list(INDEX_CODES.keys())
    for cat in STOCK_POOL.values():
        codes.extend(cat['codes'])
    return list(dict.fromkeys(codes))


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


def format_price(price):
    return f"¥{price:.2f}" if price > 0 else "（休市）"


def format_change(change_pct):
    if change_pct == 0:
        return "⚪ 0.00%"
    emoji = "🔴" if change_pct > 0 else "🟢"
    return f"{emoji} {change_pct:+.2f}%"


# ============================================
# 状态管理
# ============================================
def save_state(state_name, data):
    """保存状态到文件"""
    from .config import STATE_DIR
    os.makedirs(STATE_DIR, exist_ok=True)
    filepath = os.path.join(STATE_DIR, f"{state_name}_{get_today_str()}.json")
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'data': data
        }, f, ensure_ascii=False, indent=2)
    return filepath


def load_state(state_name):
    """加载今日状态"""
    from .config import STATE_DIR
    filepath = os.path.join(STATE_DIR, f"{state_name}_{get_today_str()}.json")
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


# ============================================
# Git 操作
# ============================================
def git_commit_and_push(message, filepath=None):
    """Git 提交并推送"""
    try:
        os.chdir(PROJECT_DIR)
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", message], check=True, capture_output=True)
        subprocess.run(["git", "push", "origin", "main"], check=True, capture_output=True)
        print(f"[git] 已推送: {message}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[git] 失败: {e}")
        return False


# ============================================
# 报告保存
# ============================================
def save_report(report_type, content):
    """保存报告到文件"""
    from .config import REPORTS_DIR
    today = get_today_str()
    time_str = get_time_str().replace(':', '')[:-2]  # HHMM
    
    if report_type == '早盘简报':
        subdir = os.path.join(REPORTS_DIR, '盘前')
        filename = f"{today}_{time_str}_早盘简报.md"
    elif report_type == '竞价推送':
        subdir = os.path.join(REPORTS_DIR, '竞价')
        filename = f"{today}_09{25}_竞价推送.md"
    elif report_type == '午盘总结':
        subdir = os.path.join(REPORTS_DIR, '盘中')
        filename = f"{today}_11{28}_午盘总结.md"
    elif report_type == '尾盘分析':
        subdir = os.path.join(REPORTS_DIR, '盘中')
        filename = f"{today}_14_45_尾盘推荐.md"
    elif report_type == '复盘评分':
        subdir = os.path.join(REPORTS_DIR, '复盘')
        filename = f"{today}_21{45}_复盘评分.md"
    elif report_type == '明日策略':
        subdir = os.path.join(REPORTS_DIR, '复盘')
        filename = f"{today}_21{45}_明日策略.md"
    else:
        subdir = REPORTS_DIR
        filename = f"{today}_{report_type}.md"
    
    os.makedirs(subdir, exist_ok=True)
    filepath = os.path.join(subdir, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"[report] 已保存: {filepath}")
    return filepath

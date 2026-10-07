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
    """
    使用新浪财经API获取股票数据（已修正字段索引）。
    返回字段：code, name, price(=昨收), yesterday_close(=今开), change_pct, amount
    """
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

    def safe_float(val):
        if not val or val == '--' or val == '-':
            return 0.0
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0

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
            price = safe_float(parts[2])        # parts[2] = 当前价格/今收
            yesterday_close = safe_float(parts[1])  # parts[1] = 昨日收盘
            if price > 0 and yesterday_close > 0:
                change_pct = round((price - yesterday_close) / yesterday_close * 100, 2)
            else:
                change_pct = 0
            amount = safe_float(parts[9]) * 10000

            results[code] = {
                'code': code,
                'name': name,
                'price': price,
                'change_pct': change_pct,
                'amount': amount,
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
# v2026-10-04 评审修复 (P0 B1): 改为白名单路径 + push 前数量守卫
# 旧版用 `git add .` 等价 `git add -A`,会 stage 工作区所有变化(新增/修改/删除),
# 包括: 删除 reports/*.md、修改 scripts/*.py、改 .gitignore、改 pyproject.toml 等
# 已被多个 cron agent(premarket/intraday/postmarket)调用,风险敞口大。
# 新版:
#   - 只 stage 白名单路径(reports/ + data/ + state/)— cron 产出物
#   - 绝不 stage scripts/ tests/ config/ strategies/ analysis_tools/ .venv/ docs/
#     references/ backtest/ prompts/ pyproject.toml uv.lock
#   - commit 前统计 stage 后的 diff,删除文件数 > DELETE_GUARD 报警并取消 push
#   - 接口签名保持兼容 (message, filepath=None), 老调用无需改
DELETE_GUARD = 50  # 单次 commit 删除文件超过此数 → 取消 push 报警
GIT_STAGE_ALLOWLIST = ("reports/", "data/", "state/")

def git_commit_and_push(message, filepath=None):
    """Git 提交并推送（白名单 + 数量守卫）

    v2026-10-04 修复: 替换原 `git add .` 全量 stage,改为只 stage reports/data/state
    三类路径;commit 前检查删除文件数,超阈值则拒绝 push。
    """
    try:
        os.chdir(PROJECT_DIR)
        # 1) 只 stage 白名单路径(精确目录,避免误伤根目录文件)
        for path in GIT_STAGE_ALLOWLIST:
            subprocess.run(
                ["git", "add", "--", path],
                check=True, capture_output=True,
            )
        # 2) 删除文件也需 stage(否则 git rm 才能让 index 知道)
        #    用 `git add -u` 仅更新已 tracked 文件的删除/修改 — 配合上面 -- 限定范围
        #    注意: `git add -u` 不带路径会作用于整个工作区,但带路径只作用于路径下,
        #    所以我们对每个白名单路径都跑一次 `git add -u -- <path>`。
        for path in GIT_STAGE_ALLOWLIST:
            subprocess.run(
                ["git", "add", "-u", "--", path],
                check=True, capture_output=True,
            )
        # 4) commit 前检查删除数量(数量守卫)
        staged_diff = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=D"],
            check=True, capture_output=True, text=True,
        ).stdout
        deletions = [l for l in staged_diff.splitlines() if l.strip()]
        if len(deletions) > DELETE_GUARD:
            print(
                f"[git] ⚠️ 守卫触发: 本次 stage 含 {len(deletions)} 个删除 "
                f"(>{DELETE_GUARD} 阈值),取消 commit 防止误删\n"
                f"  删除文件示例:\n    " + "\n    ".join(deletions[:10])
            )
            subprocess.run(["git", "reset"], capture_output=True)
            return False
        # 5) 如果 stage 后没有任何变化 → 跳过 commit(避免空 commit)
        staged_any = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        if not staged_any:
            print(f"[git] 无变化, 跳过 commit: {message}")
            return True
        # 6) 实际 commit + push
        subprocess.run(["git", "commit", "-m", message], check=True, capture_output=True)
        subprocess.run(["git", "push", "origin", "main"], check=True, capture_output=True)
        print(f"[git] 已推送: {message} (staged={len(staged_any.splitlines())} files)")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[git] 失败: {e}")
        try:
            subprocess.run(["git", "reset"], capture_output=True)
        except Exception:
            pass
        return False


# ============================================
# 报告保存
# ============================================
def save_report(report_type, content):
    """保存报告到文件，按日期和Agent职责分类
    结构: reports/YYYY-MM-DD/{phase}/{time}_{type}.md
    - 盘前(07:00-09:28): 早盘简报、竞价推送  → reports/YYYY-MM-DD/盘前/
    - 盘中(09:30-15:00): 午盘总结、尾盘推荐  → reports/YYYY-MM-DD/盘中/
    - 复盘(21:00-21:45): 复盘评分、明日策略、策略分析、风险评估 → reports/YYYY-MM-DD/复盘/
    - 竞价(09:15-09:25): 竞价推送(冗余保留) → reports/YYYY-MM-DD/竞价/
    """
    from .config import REPORTS_DIR
    today = get_today_str()
    time_str = get_time_str().replace(':', '')[:-2]  # HHMM

    # 按报告类型映射到 phase 子目录
    phase_map = {
        '早盘简报':    '盘前',
        '竞价推送':    '竞价',
        '午盘总结':    '盘中',
        '尾盘推荐':    '盘中',
        '尾盘分析':    '盘中',
        '复盘评分':    '复盘',
        '明日策略':    '复盘',
        '策略分析':    '复盘',
        '风险评估':    '复盘',
    }
    phase = phase_map.get(report_type, '杂项')

    # 构建路径: reports/YYYY-MM-DD/{phase}/
    day_dir = os.path.join(REPORTS_DIR, today)
    subdir = os.path.join(day_dir, phase)
    os.makedirs(subdir, exist_ok=True)

    # 文件名保留时间戳便于追溯
    filename = f"{today}_{time_str}_{report_type}.md"
    filepath = os.path.join(subdir, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"[report] 已保存: {filepath}")
    return filepath

# ============================================
# 增强行情（腾讯+同花顺热点）
# ============================================
def get_enhanced_quotes(codes):
    """
    融合腾讯行情（含PE/PB/市值/涨跌停）和新浪实时价格。
    返回: {code: {name, price, change_pct, pe_ttm, pb, mcap_yi, limit_up, limit_down, ...}}
    零 akshare 依赖，直接 HTTP 调用。
    """
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'analysis_tools'))
    try:
        from analysis_tools.data_sources import get_enhanced_quotes as _ds_quotes
        return _ds_quotes(codes)
    except Exception as e:
        print(f"[data_utils] get_enhanced_quotes 失败: {e}")
        return {}


def get_ths_hot(date_str=None):
    """
    同花顺当日强势股 + 题材归因。
    返回: {stocks: [{code, name, reason, zhangfu, huanshou, tags}, ...], total, tag_freq}
    """
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'analysis_tools'))
    try:
        from analysis_tools.data_sources import ths_hot_reason
        return ths_hot_reason(date_str)
    except Exception as e:
        print(f"[data_utils] get_ths_hot 失败: {e}")
        return {"stocks": [], "total": 0, "tag_freq": {}}


def get_industry_ranking(top_n=20):
    """
    东财行业板块涨跌幅排名。
    返回: {top: [...], bottom: [...], total: int}
    """
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'analysis_tools'))
    try:
        from analysis_tools.data_sources import industry_comparison
        return industry_comparison(top_n)
    except Exception as e:
        print(f"[data_utils] get_industry_ranking 失败: {e}")
        return {"top": [], "bottom": [], "total": 0}


# ============================================
# 腾讯财经数据源（备用）
# ============================================
def get_stock_data_tencent(codes):
    """使用腾讯财经API获取股票数据（备用）"""
    import requests
    
    results = {}
    
    def format_code(code):
        if code.startswith('6') or code.startswith('9'):
            return f'sh{code}'
        return f'sz{code}'
    
    if not codes:
        return results
    
    formatted = [format_code(c) for c in codes]
    url = f'https://qt.gtimg.cn/q={",".join(formatted)}'
    
    try:
        resp = requests.get(url, headers={'Referer': 'https://finance.qq.com'}, timeout=10)
        resp.encoding = 'gbk'
        
        lines = resp.text.strip().split('\n')
        for i, line in enumerate(lines):
            if '"' not in line:
                continue
            code = codes[i] if i < len(codes) else ''
            parts = line.split('"')[1].split('~')
            
            if len(parts) < 33:
                results[code] = {'code': code, 'name': '', 'price': 0, 'change_pct': 0, 'amount': 0}
                continue
            
            name = parts[1]
            price = float(parts[3]) if parts[3] else 0
            yesterday_close = float(parts[4]) if parts[4] else 0
            change_pct = float(parts[32]) if parts[32] else 0
            change_amt = float(parts[31]) if parts[31] else 0
            vol = float(parts[36]) if parts[36] else 0
            amount = float(parts[37]) if parts[37] else 0
            high = float(parts[33]) if parts[33] else 0
            low = float(parts[34]) if parts[34] else 0
            date_str = parts[30] if len(parts) > 30 else ''
            
            results[code] = {
                'code': code,
                'name': name,
                'price': price,
                'yesterday_close': yesterday_close,
                'change_pct': change_pct,
                'change_amt': change_amt,
                'vol': vol,
                'amount': amount * 10000,
                'high': high,
                'low': low,
                'date': date_str,
            }
    except Exception as e:
        print(f"[data_utils] 腾讯API失败: {e}")
        for code in codes:
            results[code] = {'code': code, 'name': '', 'price': 0, 'change_pct': 0, 'amount': 0}
    
    return results

"""
scripts/sync_top10_v9.py — 手动工具:把最近一份 `*选股报告.md` 的 Top10 同步到东财 today 组合

v2026-08-23 Phase 1C: 移除脚本末尾的"再调一次 sync_portfolio_to_eastmoney([])"。
  原代码会在 add_stocks() 后又跑 cleanup,踩 8/13 L410 BUG(已有 stocks 被清空)。
  现简化为纯"提取 Top10 + 同步",不做 cleanup。
  cleanup 现在由 `scripts/eastmoney_cleanup.py` 独立脚本负责(待补)。
"""
import os
import re
import sys
from datetime import datetime

REPORT_DIR = os.path.expanduser('~/code/AAna/reports')
SCRIPTS_DIR = os.path.expanduser('~/code/AAna/scripts')


def extract_top10(report_path):
    if not os.path.exists(report_path):
        return []
    with open(report_path, encoding='utf-8') as f:
        content = f.read()
    section = re.search(r'## 三、精选个股.*?(?=^---)', content, re.DOTALL | re.MULTILINE)
    if section:
        rows = re.findall(r'\|\s*(\d+)\s*\|\s*[^|]*\|\s*(\d{6})\s*\|', section.group(0))
        return [code for _, code in rows[:10]]
    rows = re.findall(r'\|\s*\d+\s*\|\s*[^|]*\|\s*(\d{6})\s*\|', content)
    return rows[:10]


def main():
    files = sorted([f for f in os.listdir(REPORT_DIR) if f.endswith('-选股报告.md')])
    if not files:
        print('no report files found')
        return
    latest = files[-1]
    print('最新报告:', latest)
    codes = extract_top10(os.path.join(REPORT_DIR, latest))
    print('Top10 codes:', codes)
    if not codes:
        return
    sys.path.insert(0, SCRIPTS_DIR)
    try:
        import eastmoney_portfolio
        today_str = datetime.now().strftime('%Y%m%d')
        gid = eastmoney_portfolio.get_or_create_group(today_str)
        if gid is None:
            print('[Eastmoney] get_or_create_group returned None, exiting')
            return
        added_count = eastmoney_portfolio.add_stocks(gid, codes)
        print('东方财富同步: gid=', gid, '成功=', added_count, '总共尝试=', len(codes))
    except Exception as e:
        import traceback
        print('东方财富同步跳过:', e)
        traceback.print_exc()
    print('早盘推荐股票已同步东方财富:', codes)


if __name__ == '__main__':
    main()

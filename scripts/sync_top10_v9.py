import os
import re
import sys
from datetime import datetime

REPORT_DIR = os.path.expanduser('~/code/AAna/reports')
SCRIPTS_DIR = os.path.expanduser('~/code/AAna/scripts')


def extract_top10(report_path):
  if not os.path.exists(report_path):
    return []
  f = open(report_path, encoding='utf-8')
  content = f.read()
  f.close()
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
    eastmoney_portfolio.sync_portfolio_to_eastmoney([])
  except Exception as e:
    import traceback
    print('东方财富同步跳过:', e)
    traceback.print_exc()
  print('早盘推荐股票已同步东方财富:', codes)


if __name__ == '__main__':
  main()

import os, re, sys
from datetime import datetime

report_dir = os.path.expanduser("~/code/AAna/reports")
report_files = sorted([f for f in os.listdir(report_dir) if f.endswith("-选股报告.md")])
latest = report_files[-1] if report_files else None
print("最新报告:", latest)

codes = []
if latest:
 fp = os.path.join(report_dir, latest)
 with open(fp, encoding="utf-8") as f:
 content = f.read()
 section_match = re.search(r"## 三、精选个股.*?(?=^---)", content, re.DOTALL | re.MULTILINE)
 if section_match:
 sec = section_match.group(0)
 rows = re.findall(r"\|\s*(\d+)\s*\|\s*[^|]*\|\s*(\d{6})\s*\|", sec)
 codes = [c[1] for c in rows[:10]]
 print("从精选个股章节提取 Top10:", codes)
 else:
 rows = re.findall(r"\|\s*\d+\s*\|\s*[^|]*\|\s*(\d{6})\s*\|", content)
 codes = rows[:10]
 print("fallback Top10:", codes)

if codes:
 sys.path.insert(0, os.path.expanduser("~/code/AAna/scripts"))
 try:
 import eastmoney_portfolio
 today_str = datetime.now().strftime("%Y%m%d")
 group_name = today_str
 gid = eastmoney_portfolio.get_or_create_group(group_name)
 result = eastmoney_portfolio.add_stocks(gid, codes)
 print("东方财富同步结果: gid=", gid, "添加=", result.get("added",0), "跳过=", result.get("skipped",0), "总数=", len(codes))
 eastmoney_portfolio.sync_portfolio_to_eastmoney([])
 except Exception as e:
 import traceback
 print("东方财富同步跳过:", e)
 traceback.print_exc()

print("早盘推荐股票已同步东方财富:", codes)

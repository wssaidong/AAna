#!/usr/bin/env python3
"""清理 recommendations.csv 中的创业板/科创板记录.

修复 #11 (v2026-10-07 review): 路径改用 __file__ 相对定位, 不再硬编码 /Users/cai/...
"""
import csv
import os

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "recommendations.csv")
with open(path, newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

print(f"清理前: {len(rows)} 条记录")
print("创业板/科创板记录:")
blocked = [r for r in rows if r["code"].startswith(("300","301","688"))]
for r in blocked:
    print(f"  {r['date']} {r['code']} {r['name']}")

# 过滤掉创业板和科创板
clean = [r for r in rows if not r["code"].startswith(("300","301","688"))]
print(f"\n清理后: {len(clean)} 条记录（删除了 {len(blocked)} 条）")

# 写回
fields = ["date","code","name","sector","sector_name","reason","expected_high","expected_low","actual_change","hit","created_at"]
with open(path, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    w.writerows(clean)
print("已写入 recommendations.csv")
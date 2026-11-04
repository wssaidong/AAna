#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描东财服务端 gid 范围, 列出今日 (20261104) 有更新的组 + 股票明细。
用途: 确认 launchd daily_v24_recommend (14:45) 是否已建 20261104PP, 并区分早盘组 20261104。
"""
import sys
sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import eastmoney_portfolio as ep

DATE = "20261104"
lo, hi = 1780, 1930
found = []
for g in range(lo, hi):
    try:
        r, _ = ep.api_call(ep.mkurl('gstkinfos', g=g), max_retries=0)
    except Exception:
        continue
    if r.get('state') != 0:
        continue
    stks = r.get('data', {}).get('stkinfolist', [])
    if not stks:
        continue
    ut = str(stks[0].get('updatetime', ''))
    if ut[:8] == DATE:
        codes = [s.get('c', '?') for s in stks]
        found.append((g, ut, len(codes), codes))
        print(f"gid={g} updatetime={ut} n={len(codes)} codes={codes}")

print("\n=== 今日有更新的组 ===")
for g, ut, n, codes in found:
    print(f"gid={g}  n={n}  {codes}")
if not found:
    print("(无)")

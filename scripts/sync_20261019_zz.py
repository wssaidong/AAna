#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同步 10/19 深度分析 Top 2 → 东方财富组合 20261019ZZ
沿用 9/15-10/18 autopilot 沉淀:
- 组合名 YYYYMMDDZZ (纯数字字母, 9/20 验证 + 沿用)
- Top 1: 002270 华明装备 (深度评分 77.0 买入, 10-16 +4.09% 正盈利)
- Top 2: 603101 汇嘉时代 (深度评分 76.8 买入, 10-16 +3.99% 正盈利)
"""
import sys, json, os
from pathlib import Path
sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import eastmoney_portfolio as ep

NAME = '20261019ZZ'
CODES = ['002270', '603101']

# 1) 预检:清僵尸缓存 (8/5-8/14 SOP)
grp_file = os.path.expanduser('~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json')
with open(grp_file) as f:
    groups = json.load(f)

if NAME in groups:
    print(f"⚠️  清理 {NAME} 缓存: gid={groups[NAME].get('gid')} stocks={groups[NAME].get('stocks')}")
    del groups[NAME]
    with open(grp_file, 'w') as f:
        json.dump(groups, f, ensure_ascii=False, indent=2)

# 2) 创建新组合 (用 create_group 而非 get_or_create_group 避免扫描副作用)
print(f"\n[1/4] 创建组合 {NAME}...")
gid = ep.create_group(NAME)
print(f"  新 gid: {gid}")

if gid is None:
    print("❌ create_group 返回 None — 检查 cookie")
    sys.exit(1)

# 3) 添加 Top 2 股票
print(f"\n[2/4] 添加 Top 2 股票: {CODES}")
added = ep.add_stocks(gid, CODES)
print(f"  add_stocks 返回: {added} (int)")

# 4) 验证 — 用 gstkinfos (唯一可靠验证方式)
print(f"\n[3/4] 验证 (gstkinfos)...")
r, _ = ep.api_call(ep.mkurl('gstkinfos', g=gid))
got = [s['security'].split('$')[1] for s in r['data']['stkinfolist']]
print(f"  gid={gid} 实际含 {len(got)} 只: {got}")

assert set(CODES) == set(got), f"同步不完整! 期望 {CODES}, 实际 {got}"

# 5) 更新 groups.json 缓存
print(f"\n[4/4] 更新 groups.json 缓存...")
groups[NAME] = {
    'gid': str(gid),
    'date': '2026-10-19',
    'stocks': CODES,
    'type': 'deep_analysis_zz',
    'report': '2026-10-19-选股报告.md (Top10 空) + 基准 2026-10-16-选股报告.md',
    'top1': '002270 华明装备 (深度 77.0 买入, 10-16 +4.09%)',
    'top2': '603101 汇嘉时代 (深度 76.8 买入, 10-16 +3.99%)',
    'ts': '2026-10-19T08:42:00',
    'note': '10/19 周一交易日盘前 (第4次验证), 当日报告 Top10 空 → 候选池沿用 10-16 报告, Top2 与 10-17/10-18 ZZ 一致',
}
with open(grp_file, 'w') as f:
    json.dump(groups, f, ensure_ascii=False, indent=2)

print(f"\n✅ 同步完成! 组合 {NAME} (gid={gid}) 含 {len(got)} 只: {got}")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同步 10/21 深度分析推荐股 → 东方财富组合 20261021ZZ
沿用 9/15-10/20 autopilot 沉淀:
- 组合名 YYYYMMDDZZ (纯数字字母)
- Top 1: 002956 西麦食品 (深度评分 92.0 买入, 10-20 +4.53% 全池最高胜出)
- Top 2: 002917 金奥博 (深度评分 68.0 增持, 10-20 +4.09% 正盈利)
- 不同步: 001233 海安集团 (63.0 中性, 净利 -46% 不达推荐级)
"""
import sys, json, os
sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import eastmoney_portfolio as ep

NAME = '20261021ZZ'
CODES = ['002956', '002917']

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

# 3) 添加推荐股
print(f"\n[2/4] 添加股票: {CODES}")
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
    'date': '2026-10-21',
    'stocks': CODES,
    'type': 'deep_analysis_zz',
    'report': '2026-10-21-选股报告.md (Top10 仅 3 只, 当日池第 2 日)',
    'top1': '002956 西麦食品 (深度 92.0 买入, 10-20 +4.53% 全池最高胜出)',
    'top2': '002917 金奥博 (深度 68.0 增持, 10-20 +4.09%)',
    'ts': '2026-10-21T08:40:00',
    'note': '10/21 周三交易日盘前, 候选池 3 只 (10-20 十只缩容); 中性 001233 海安集团不同步; akshare 基本面恢复, 西麦 76→92 (净利 +82%)',
}
with open(grp_file, 'w') as f:
    json.dump(groups, f, ensure_ascii=False, indent=2)

print(f"\n✅ 同步完成! 组合 {NAME} (gid={gid}) 含 {len(got)} 只: {got}")

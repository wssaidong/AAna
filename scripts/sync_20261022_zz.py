#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同步 10/22 深度分析推荐股 → 东方财富组合 20261022ZZ
沿用 9/15-10/21 autopilot 沉淀:
- 组合名 YYYYMMDDZZ (纯数字字母)
- Top 1: 603992 松霖科技 (深度评分 78.0 买入, 10-21 +1.79% 正盈利居前列; 净利+66%/营收+44% 全池唯一双增长)
- 不同步: 000028 国药一致 (64.5 中性, 基本面 0/30 三弱, 差 0.5 分达增持线)
- 不同步: 603466 风语筑 (63.3 中性, PE 负异常 + 换手 19.94% 博弈盘, 报告 Top10#1 被深度分析降级)
"""
import sys, json, os
sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import eastmoney_portfolio as ep

NAME = '20261022ZZ'
CODES = ['603992']

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
    'date': '2026-10-22',
    'stocks': CODES,
    'type': 'deep_analysis_zz',
    'report': '2026-10-22-选股报告.md (Top10 仅 3 只, 当日池第 3 日, 情绪冰点 35 停止交易)',
    'top1': '603992 松霖科技 (深度 78.0 买入, 10-21 +1.79% 正盈利, 净利+66%/营收+44%)',
    'excluded': '000028 国药一致 (64.5 中性, PE11/PB0.65 深价值但基本面三弱) / 603466 风语筑 (63.3 中性, PE 负异常+换手 19.9%)',
    'ts': '2026-10-22T08:42:00',
    'note': '10/22 周四交易日盘前, 候选池 3 只; 仅 1 只达增持级 (10-21 为 2 只); 板块胜率库 10-22 去重后 285 笔 39.6%',
}
with open(grp_file, 'w') as f:
    json.dump(groups, f, ensure_ascii=False, indent=2)

print(f"\n✅ 同步完成! 组合 {NAME} (gid={gid}) 含 {len(got)} 只: {got}")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同步 10/26 深度分析推荐股 → 东方财富组合 20261026ZZ
沿用 9/15-10/25 autopilot 沉淀:
- 组合名 YYYYMMDDZZ (纯数字字母)
- Top 1: 002956 西麦食品 (深度评分 92.0 买入, 10-23 +4.73% 池内第一胜出+正盈利; ROE 13.4%/净利+71.6%/营收+21.7%)
- 不同步: 002351 漫步者 (69.5 增持, 财务刷新后升入合格池但居第 2) / 600592 龙溪股份 (66.0 增持但基本面 0/30, 概念驱动), 均列观察
- 守卫: 10-26 报告快照情绪 90 亢奋 (盘前 live 源未开盘回退, 快照口径) → 放行建组
- 10-25 组 20261025ZZ (gid=1746) 同标的, 本日为复验后第 3 组; 10-26 周一为 10-23 池首个可执行交易日
"""
import sys, json, os
sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import eastmoney_portfolio as ep

NAME = '20261026ZZ'
CODES = ['002956']

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
    'date': '2026-10-26',
    'stocks': CODES,
    'type': 'deep_analysis_zz',
    'report': '2026-10-26-选股报告.md (08:02 盘前版, Top10 与 10-23 池一致, 情绪 90 亢奋)',
    'top1': '002956 西麦食品 (深度 92.0 买入, 10-23 +4.73% 池内#1 胜出+正盈利, ROE 13.4%/净利+71.6%/营收+21.7%, 技术 55/55 满分)',
    'excluded': '002351 漫步者 (69.5 增持, 财务刷新 ROE 11.1%/净利+13% 升入合格池第 2, 列观察) / 600592 龙溪股份 (66.0 增持, 技术 55/55 但基本面 0/30 净利-18%/营收-19%, 概念驱动列观察) / 其余 7 只中性或减持',
    'ts': '2026-10-26T08:40:00',
    'note': '10/26 周一交易日盘前 (10-23 池首个可执行日), 第三次独立复验 Top1 不变; 守卫放行链路恢复第 3 组; 板块胜率库 67 键 293 笔 39.9%, 食品综合 50% (1/2)',
}
with open(grp_file, 'w') as f:
    json.dump(groups, f, ensure_ascii=False, indent=2)

print(f"\n✅ 同步完成! 组合 {NAME} (gid={gid}) 含 {len(got)} 只: {got}")

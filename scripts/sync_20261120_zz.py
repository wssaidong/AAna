#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同步 11/20 深度分析推荐股 → 东方财富组合 20261120ZZ
沿用 9/15-11/18 autopilot 沉淀 (先例: 仅铁律合格池 Top1 入组):
- 组合名 YYYYMMDDZZ (标准命名, 幂等路径)
- Top 1: 002415 海康威视 (深度评分 89.0 买入, 11-19 收盘 +1.19% 胜大盘(-0.44%)+正盈利;
  技55/基23(全池最高)/估12; 板块[计算机设备]胜率 100% 2/2; 软止损 34.64 未破)
- 并列 89.0 的 002142 宁波银行以基准日涨幅 (+0.48% < +1.19%) 落后, 且已实持于
  20261118ZZ (gid=2016), 不重复入组
- 不同步: 600312 平高电气 79.6 / 603288 海天味业 77.0 / 601166 兴业银行 77.0 等 (Top1 单票先例)
- 裸日期组 20261120 (gid=2046 空占位) 严禁触碰; 昨日 20261119 (gid=2041) /
  20261118ZZ (gid=2016) / 20261118PP (gid=2026) / 20261118 (gid=2031) 不动
"""
import sys, json, os
sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import eastmoney_portfolio as ep

NAME = '20261120ZZ'
CODES = ['002415']
FORBIDDEN_GID = 2046  # 裸日期组 20261120 空占位, 防御校验

# 1) 预检: 清僵尸缓存 (8/5-8/14 SOP) + 占用确认
grp_file = os.path.expanduser('~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json')
with open(grp_file) as f:
    groups = json.load(f)
occ = {k: v.get('gid') for k, v in groups.items() if k.startswith('20261120')}
print(f"预检 20261120* 占用: {occ}")
assert '20261120ZZ' not in groups or not groups['20261120ZZ'].get('gid'), \
    f"20261120ZZ 已在缓存: {groups.get('20261120ZZ')} — 疑似重复建组, 人工确认后再跑"
if NAME in groups:
    print(f"⚠️ 清理 {NAME} 僵尸缓存: {groups[NAME]}")
    del groups[NAME]

# 2) 创建组合 (用 create_group 避免扫描副作用)
print(f"\n[1/4] 创建组合 {NAME}...")
gid = ep.create_group(NAME)
print(f"  新 gid: {gid}")
if gid is None:
    print("❌ create_group 返回 None — 检查 cookie")
    sys.exit(1)
if str(gid) == str(FORBIDDEN_GID):
    print(f"❌ 防御校验失败: gid={gid} 撞裸日期组 20261120 — 终止")
    sys.exit(1)

# 3) 添加推荐股
print(f"\n[2/4] 添加股票: {CODES}")
added = ep.add_stocks(gid, CODES)
print(f"  add_stocks 返回: {added}")

# 4) 验证 — 用 gstkinfos (唯一可靠验证方式)
print(f"\n[3/4] 验证 (gstkinfos)...")
r, _ = ep.api_call(ep.mkurl('gstkinfos', g=gid))
got = [s['security'].split('$')[1] for s in r['data']['stkinfolist']]
print(f"  gid={gid} 实际含 {len(got)} 只: {got}")
assert set(CODES) == set(got), f"同步不完整! 期望 {CODES}, 实际 {got}"
assert str(gid) not in {str(v) for v in occ.values()}, f"gid={gid} 撞当日占用集 {occ}"

# 5) 更新 groups.json 缓存
print(f"\n[4/4] 更新 groups.json 缓存...")
groups[NAME] = {
    'gid': str(gid),
    'date': '2026-11-20',
    'stocks': CODES,
    'type': 'deep_analysis_zz',
    'report': '2026-11-20-选股报告.md (Top10 全 10 只入池, 情绪 45 分歧, 仓位 50%)',
    'top1': '002415 海康威视 (深度 89.0 买入, 11-19 收盘 +1.19% 胜大盘+正盈利, 技55/基23/估12, 计算机设备胜率 100% 2/2)',
    'excluded': '002142 宁波银行 (并列 89.0 但基准日涨幅 +0.48% 落后且已实持 20261118ZZ gid=2016) / '
                '600312 平高电气 79.6 / 603288 海天味业 77.0 / 601166 兴业银行 77.0 (Top1 单票先例)',
    'ts': '2026-11-20T08:45:00',
    'note': '11/20 周五交易日盘前, 候选池 10 只 (11-19 的 2.5 倍); 铁律合格池 8 只; 热点字段连续第 5 日缺失',
}
with open(grp_file, 'w') as f:
    json.dump(groups, f, ensure_ascii=False, indent=2)

print(f"\n✅ 同步完成! 组合 {NAME} (gid={gid}) 含 {len(got)} 只: {got}")

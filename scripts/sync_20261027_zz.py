#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同步 10/27 深度分析推荐股 → 东方财富组合 20261027ZZ
沿用 9/15-10/26 autopilot 沉淀:
- 组合名 YYYYMMDDZZ (纯数字字母)
- Top 1: 603883 老百姓 (深度评分 75.4 买入, 池内唯一买入级; 10-26 +1.89% 正盈利+胜大盘-0.69%;
  全池唯一财务三项全正 ROE 9.1%/净利+17%/营收+4%; PE 23.5/PB 1.66 估值满分 15/15; 医药商业板块胜率 100% (2/2))
- 不同步: 601857 中国石油 (71.4 增持, 涨幅池内#1 但技术 40/55 偏弱) / 603707 健友股份 (70.0 增持, 技术 55/55 满分
  但净利 -34% 技术/基本面背离) / 002265 建设工业 (68.4, PE 63.6) / 603882 金域医学 (65.0, PE 145), 均列观察
- 守卫: 10-27 报告快照情绪 45 分歧 (仓位 50% ≥10%, 非冰点标签) → 放行建组
- 全新池: 与 10-26 池 0 重合 (10-26 池 10-23 基准; 10-27 池 10-26 基准)
"""
import sys, json, os
sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import eastmoney_portfolio as ep

NAME = '20261027ZZ'
CODES = ['603883']

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
    'date': '2026-10-27',
    'stocks': CODES,
    'type': 'deep_analysis_zz',
    'report': '2026-10-27-选股报告.md (08:02 盘前版, 全新池 8 只, 情绪 45 分歧)',
    'top1': '603883 老百姓 (深度 75.4 买入, 池内唯一买入级; 10-26 +1.89% 正盈利+胜大盘-0.69% 超额+2.58pp; 全池唯一财务三项全正 ROE 9.1%/净利+17%/营收+4%; PE 23.5/PB 1.66 估值满分; 医药商业板块胜率 100% (2/2))',
    'excluded': '601857 中国石油 (71.4 增持, 涨幅池内#1 +4.94% 但技术 40/55) / 603707 健友股份 (70.0, 技术 55/55 满分但净利-34% 背离) / 002265 建设工业 (68.4, PE 63.6 低基数+322%) / 603882 金域医学 (65.0, PE 145) / 其余 3 只中性或减持',
    'ts': '2026-10-27T09:00:00',
    'note': '10/27 周二交易日盘前, 全新池 (与 10-26 池 0 重合); 守卫放行 (45 分歧非冰点); 板块胜率库 69 键 295 笔 39.7%, 医药商业 100% (2/2); 涨幅池内#8 评分优先先例 (10-24~26)',
}
with open(grp_file, 'w') as f:
    json.dump(groups, f, ensure_ascii=False, indent=2)

print(f"\n✅ 同步完成! 组合 {NAME} (gid={gid}) 含 {len(got)} 只: {got}")

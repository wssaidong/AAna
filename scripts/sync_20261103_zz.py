#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同步 11/03 深度分析推荐股 → 东方财富组合 20261103ZZ
沿用 9/15-10/29 autopilot 沉淀:
- 组合名 YYYYMMDDZZ (纯数字字母, 幂等命名)
- Top 1: 002956 西麦食品 (深度评分 85.6 买入, 池内唯一买入级/唯一铁律合格; 11-02 +6.69% 正盈利
  胜大盘均 +1.34% 超额 +5.35pp 池内#2; 基本面 26/30 池内唯一三项全正 ROE 13.4%/净利+71.6%/营收+21.7%;
  PE 23.8 合理 PB 3.67; 食品综合板块胜率 80% (4/5) 池内唯一样本≥5且≥80%; 软止损 19.64 未破)
- 不同步: 605118 力鼎光电 (62.7 中性, 涨幅池内#1 +6.99% 但 PE 51/PB 9.1 + RSI 76 超买) / 603160 汇顶科技
  (51.6 中性, 净利 -47% 双负) / 000860 顺鑫农业 (51.2 中性, 估值失真修正) / 002242 九阳股份 (30.4 减持,
  60日 +158% 严重透支), 均列观察
- 守卫: 11-03 报告快照情绪 75 亢奋 (仓位 85%, 快照与 live 双口径一致) → 放行建组
- 全新池: 与昨 11-02 早盘组 20261102 gid=1816 6 只 0 重合
"""
import sys, json, os
sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import eastmoney_portfolio as ep

NAME = '20261103ZZ'
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
    'date': '2026-11-03',
    'stocks': CODES,
    'type': 'deep_analysis_zz',
    'report': '2026-11-03-选股报告.md (08:03 盘前版, 全新池 5 只, 情绪 75 亢奋, 冰点解除后首个有效早盘池)',
    'top1': '002956 西麦食品 (深度 85.6 买入, 池内唯一买入级/唯一铁律合格; 11-02 +6.69% 正盈利胜大盘+1.34%超额+5.35pp池内#2; 基本面26/30唯一三项全正ROE13.4%/净利+71.6%/营收+21.7%; PE23.8合理; 食品综合板块胜率80%(4/5)唯一样本≥5且≥80%; 软止损19.64未破)',
    'excluded': '605118 力鼎光电 (62.7 中性, 涨幅#1 +6.99% 但 PE51/PB9.1+RSI76超买) / 603160 汇顶科技 (51.6 中性, 净利-47%双负) / 000860 顺鑫农业 (51.2 中性, 估值失真修正单季-2.35亿转亏) / 002242 九阳股份 (30.4 减持, 60日+158%严重透支, 连续第2次减持级)',
    'ts': '2026-11-03T08:50:00',
    'note': '11/03 周二交易日盘前, 全新池 (与 11-02 早盘组 0 重合); 守卫放行 (75 亢奋快照+live双口径); 板块胜率库 87 键 367 笔 49.9% (f45355a 修复后); next_day_strategy 11-03 调参生效 (阈值63/冷板块含光学元件·电子); 评分优先先例 (10-24 起) — 涨幅#1 力鼎 62.7 落选, 涨幅#2 西麦 85.6 入选',
}
with open(grp_file, 'w') as f:
    json.dump(groups, f, ensure_ascii=False, indent=2)

print(f"\n✅ 同步完成! 组合 {NAME} (gid={gid}) 含 {len(got)} 只: {got}")

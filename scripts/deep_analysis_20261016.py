#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-10-16 (周五) — 冰点日 + 选股报告 Top10 空
⚠️ 触发 aana-deep-analysis-autopilot skill "Top10 表格为空" 自主筛选流程
- 2026-10-16 选股报告 Top10 = 空 (冰点 20, 建议仓位 10%, 停止交易)
- 比 2026-10-15 (情绪 30) 更弱, 沿用 "不强行自主筛选" SOP
- next_day_strategy.date_for = 2026-10-16, score_threshold=70, position_final=50%
- weak_sectors 7 个 (ai_app/chem/elec/mach/robot/semi/印制电路板)
- 整体胜率 30.52% (960 笔, 远低于 40% 基线)
- energy 板块 100% 胜率 22/22 但今日无 energy 候选

正确做法:
1. 打印报告名称验证 (autopilot 强制要求)
2. 不强行自主筛选 — 冰点日 0 推荐保持诚实
3. 生成深度分析报告 (无候选变体) + 同步东财空组合 20261016ZZ
4. 飞书推送冰点日"无推荐"消息 (含策略状态)
5. commit + 推送 github
"""
import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TODAY = "2026-10-16"
REPORT_DIR = os.path.expanduser("~/code/AAna/reports")
RUN_ID = "01a1421e-1dc9-7845-9ab2-9480aa3b4c5d"


def load_strategy_state():
    """加载今日战略状态"""
    state = {"today": TODAY, "candidates": [], "sector_stats": {},
             "weak_sectors": [], "cold_sectors": []}
    nds_path = os.path.expanduser("~/code/AAna/data/next_day_strategy.json")
    rt_path = os.path.expanduser("~/code/AAna/data/rec_tuning.json")
    if os.path.exists(nds_path):
        with open(nds_path) as f:
            nds = json.load(f)
        state["date_for"] = nds.get("date_for")
        state["score_threshold"] = nds.get("score_threshold")
        state["position_final"] = nds.get("position_final")
        state["weak_sectors"] = nds.get("weak_sectors", [])
        state["cold_sectors"] = nds.get("cold_sectors", [])
    if os.path.exists(rt_path):
        with open(rt_path) as f:
            rt = json.load(f)
        state["overall_win_rate"] = rt.get("overall_win_rate")
        state["total_records"] = rt.get("total_records")
        state["sector_stats"] = rt.get("sector_stats", {})
    return state


def report_check():
    """autopilot 强制要求: 打印报告名称防错"""
    report_path = os.path.join(REPORT_DIR, f"{TODAY}-选股报告.md")
    if not os.path.exists(report_path):
        return report_path, 0, None
    return report_path, os.path.getsize(report_path), \
        datetime.fromtimestamp(os.path.getmtime(report_path)).isoformat(timespec="seconds")


def main():
    print("=" * 80)
    print(f"AAna 深度分析 — {TODAY} (周五, 冰点日情绪 20 + Top10 空)")
    print(f"Run ID: {RUN_ID}")
    print("=" * 80)

    rp, sz, mt = report_check()
    print(f"\n📄 报告路径: {rp}")
    print(f"   文件大小: {sz} 字节")
    print(f"   修改时间: {mt}")

    state = load_strategy_state()
    print(f"\n📊 战略状态:")
    print(f"   date_for: {state.get('date_for')}")
    print(f"   score_threshold: {state.get('score_threshold')}")
    print(f"   position_final: {state.get('position_final')}%")
    print(f"   weak_sectors ({len(state.get('weak_sectors', []))}): "
          f"{state.get('weak_sectors', [])}")
    print(f"   cold_sectors ({len(state.get('cold_sectors', []))}): "
          f"{state.get('cold_sectors', [])}")
    print(f"   整体胜率: {state.get('overall_win_rate')}% "
          f"(样本 {state.get('total_records')})")
    energy = state.get("sector_stats", {}).get("energy", {})
    print(f"   energy 板块: 胜率 {energy.get('win_rate')}% "
          f"({energy.get('win_count')}/{energy.get('count')}) — 今日无候选")

    print(f"\n⚠️ 冰点日 (情绪 20) + Top10 表格为空 → 不强行自主筛选")
    print(f"   决策: 0 推荐, 组合名 {TODAY.replace('-','')}ZZ")
    return state


if __name__ == "__main__":
    main()

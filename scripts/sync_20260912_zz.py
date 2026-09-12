#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同步 Top 3 到东方财富组合 20260912ZZ
"""
import sys
import os
import json

sys.path.insert(0, "/Users/cai/code/AAna/scripts")
import eastmoney_portfolio as ep

TODAY = "20260912"
PORTFOLIO_NAME = f"{TODAY}ZZ"
TOP3 = ["600900", "600887", "600345"]  # 长江电力 / 伊利股份 / 长江通信

GROUPS_PATH = os.path.expanduser("~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json")

def main():
    print(f"\n{'='*70}")
    print(f"同步 Top 3 → 东方财富组合 {PORTFOLIO_NAME}")
    print(f"Top 3: {TOP3}")
    print(f"{'='*70}")

    # Step 1: 清僵尸缓存 (7/7 SOP + 7/8 SOP)
    try:
        with open(GROUPS_PATH) as f:
            groups = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        groups = {}

    if PORTFOLIO_NAME in groups and not groups[PORTFOLIO_NAME].get("stocks"):
        print(f"[Step 1] 清僵尸缓存: {PORTFOLIO_NAME} -> {groups[PORTFOLIO_NAME]}")
        del groups[PORTFOLIO_NAME]
        with open(GROUPS_PATH, "w") as f:
            json.dump(groups, f, ensure_ascii=False, indent=2)
    elif PORTFOLIO_NAME in groups:
        print(f"[Step 1] 检测到已存在条目: {PORTFOLIO_NAME} -> {groups[PORTFOLIO_NAME]}")
        print(f"  → 验证 gid 有效性...")

    # Step 2: 创建组合
    print(f"\n[Step 2] 创建组合 {PORTFOLIO_NAME}...")
    gid = ep.create_group(PORTFOLIO_NAME)
    if gid is None:
        print(f"❌ 创建失败 (gid=None)")
        return False
    print(f"  ✅ gid = {gid}")

    # Step 3: 添加股票
    print(f"\n[Step 3] 添加 Top 3: {TOP3}")
    added = ep.add_stocks(gid, TOP3)
    print(f"  ✅ add_stocks 返回: {added} (int, 添加成功的股票数)")

    # Step 4: 用 gstkinfos 验证 (唯一可靠验证方式)
    print(f"\n[Step 4] 用 gstkinfos 验证...")
    r, _ = ep.api_call(ep.mkurl('gstkinfos', g=gid))
    if r.get('state') == 0:
        stkinfolist = r.get('data', {}).get('stkinfolist', [])
        actual_codes = [s['security'].split('$')[1] for s in stkinfolist]
        print(f"  ✅ 服务端实际含 {len(actual_codes)} 只: {actual_codes}")
        if set(TOP3) == set(actual_codes):
            print(f"  ✅✅ 服务端股票集 == 输入 Top 3, 完全匹配")
        else:
            missing = set(TOP3) - set(actual_codes)
            extra = set(actual_codes) - set(TOP3)
            print(f"  ❌ 集合不一致: 缺失={missing}, 多余={extra}")
            return False
    else:
        print(f"  ❌ gstkinfos 返回 state={r.get('state')}: {r.get('message')}")
        return False

    # Step 5: 写回缓存
    print(f"\n[Step 5] 写回 groups.json...")
    groups[PORTFOLIO_NAME] = {
        "gid": str(gid),
        "date": TODAY,
        "stocks": TOP3,
        "type": "deep_analysis_zz",
        "report": "2026-09-11-选股报告.md",
        "ts": __import__('datetime').datetime.now().isoformat(timespec='seconds')
    }
    with open(GROUPS_PATH, "w") as f:
        json.dump(groups, f, ensure_ascii=False, indent=2)
    print(f"  ✅ groups.json 已更新")

    print(f"\n{'='*70}")
    print(f"✅✅✅ 同步成功! {PORTFOLIO_NAME} (gid={gid}) 含 {len(TOP3)} 只: {TOP3}")
    print(f"{'='*70}")
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

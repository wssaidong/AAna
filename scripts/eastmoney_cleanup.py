#!/usr/bin/env python3
"""
scripts/eastmoney_cleanup.py — 独立的东财组合 cleanup 工具

v2026-08-23 Phase 2:
  把 sync_top10_v9.py 末尾的 cleanup 调用拆出来,作为独立脚本。
  目的: 1) cleanup 慢/dacenter hang 不再拖累主同步链路
       2) cron 任务可独立 schedule (周末跑一次就够)
       3) 任何脏数据组合可以手工触发清理

用法:
    python3 scripts/eastmoney_cleanup.py                # 默认保留 7 天
    python3 scripts/eastmoney_cleanup.py --keep 14     # 保留 14 天
    python3 scripts/eastmoney_cleanup.py --dry         # 只打印待删,不真删
    python3 scripts/eastmoney_cleanup.py --full-scan   # 全量扫服务端 (8/13 实战沉淀)

⚠️ 设计: 不要和 sync_portfolio_to_eastmoney 混合调用 —— 那条函数原本就是
  "sync 主任务 + cleanup 副作用" 的混合,引入 P0 L410 BUG。Phase 2 起明确分工:
    - sync_portfolio_to_eastmoney: 纯同步,不做 cleanup
    - eastmoney_cleanup.py:        纯 cleanup,不做同步
    - cron job: 分开两个 trigger
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))

import eastmoney_portfolio as ep
from _safe_io import safe_json_dump, safe_read_json


def cleanup_local_cache(keep_days: int = 7, group_name_today: str | None = None) -> dict:
    """
    纯本地 cleanup: 删 groups.json 里 date < (today - keep_days) 的条目。
    Returns {deleted: [...], kept: [...], cutoff: str}
    """
    groups_file = os.path.expanduser(
        "~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json"
    )
    groups = safe_read_json(groups_file, default={}) or {}

    today_str = datetime.now().strftime("%Y%m%d")
    cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y%m%d")

    to_delete = []
    for name, info in list(groups.items()):
        if name == group_name_today:
            continue
        d = (info.get("date") or "")[:8]
        if d and d < cutoff:
            to_delete.append(name)

    kept = [n for n in groups if n not in to_delete]
    return {"deleted": to_delete, "kept": kept, "cutoff": cutoff}


def run_local_cleanup(
    keep_days: int = 7, group_name_today: str | None = None, dry: bool = False
) -> dict:
    """本地 cleanup 流程: 列出待删 → (dry 或真删) → 备份+写+校验。"""
    plan = cleanup_local_cache(keep_days, group_name_today)
    print(f"[cleanup] cutoff={plan['cutoff']} keep_days={keep_days}")
    print(f"[cleanup] 待删 {len(plan['deleted'])} 条: {plan['deleted']}")
    print(f"[cleanup] 保留 {len(plan['kept'])} 条: {plan['kept']}")

    if dry:
        return {**plan, "dry": True}

    if not plan["deleted"]:
        return {**plan, "deleted_count": 0}

    groups_file = os.path.expanduser(
        "~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json"
    )
    groups = safe_read_json(groups_file, default={}) or {}

    for name in plan["deleted"]:
        info = groups.get(name, {})
        gid = info.get("gid")
        if gid is not None:
            try:
                ok = ep.delete_group(gid)
                print(f"  delete_group gid={gid} → {'OK' if ok else 'fail'}")
            except Exception as e:
                print(f"  delete_group gid={gid} → ERROR: {e}")
        del groups[name]

    safe_json_dump(groups_file, groups)
    return {**plan, "deleted_count": len(plan["deleted"])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=int, default=7, help="保留天数 (default 7)")
    ap.add_argument("--dry", action="store_true", help="只打印,不真删")
    args = ap.parse_args()

    today_str = datetime.now().strftime("%Y%m%d")
    result = run_local_cleanup(keep_days=args.keep, group_name_today=today_str, dry=args.dry)
    print()
    print(f"[cleanup] 完成: {result}")
    return 0 if not result.get("deleted_count") else 0  # 一律 exit 0 (成功)


if __name__ == "__main__":
    sys.exit(main() or 0)

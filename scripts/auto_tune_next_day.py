#!/usr/bin/env python3
"""
scripts/auto_tune_next_day.py — AAna 次日自动调参 (Phase 12)

读取 scripts/daily_root_cause.py 输出的 data/daily_root_cause.json,
合并 rec_tuning.json 的基础配置, 生成 data/next_day_strategy.json,
让 aana_afternoon_screen 在生成次日推荐时读取并应用。

合并策略 (优先级 从低到高):
  1. rec_tuning.json (rec_optimizer 的基础建议)
  2. daily_root_cause.json (昨日根因触发的额外调参)
  3. 硬编码安全边界 (阈值 [55,80] / 仓位 [10,90])

输出:
  - data/next_day_strategy.json
    {
      "score_threshold": 73,
      "hold_days": 1,
      "weak_sectors": [...],
      "position_final": 45,
      "tuning_log": [
        {"source": "rec_tuning", "action": "baseline", "threshold": 70},
        {"source": "daily_root_cause", "action": "+threshold", "delta": 3, "reason": "..."}
      ]
    }

用法:
  python3 scripts/auto_tune_next_day.py
  python3 scripts/auto_tune_next_day.py --dry-run   # 只打印不写文件

cron 推荐: 16:05 (daily_root_cause.py 之后, run_afterhours.py 之前)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "scripts"))

DATA_DIR = PROJECT / "data"
REC_TUNING = DATA_DIR / "rec_tuning.json"
DAILY_RC = DATA_DIR / "daily_root_cause.json"
OUT_JSON = DATA_DIR / "next_day_strategy.json"

# 硬编码安全边界 (防止 daily_root_cause 给出极端值)
SAFE_THRESHOLD_MIN = 55
SAFE_THRESHOLD_MAX = 80
SAFE_POSITION_MIN = 10
SAFE_POSITION_MAX = 90
SAFE_WEAK_SECTOR_MIN_SAMPLES = 3  # 冷启动盲区里的板块样本 < 3 暂不进 weak_sectors

# v2.5 默认 base (strategy_policy.DEFAULT_SCORE_THRESHOLD = 65, 但 rec_tuning 已加严到 70)
BASE_THRESHOLD = 70
BASE_POSITION = 50


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="只打印不写文件")
    args = p.parse_args()

    tuning = load_json(REC_TUNING, {})
    rc = load_json(DAILY_RC, {})

    log = []

    # ── 1. baseline from rec_tuning ──
    base_threshold = tuning.get('recommended_score_threshold') or BASE_THRESHOLD
    base_hold_days = tuning.get('recommended_hold_days') or 1
    base_weak = list(tuning.get('weak_sectors') or [])

    log.append({"source": "rec_tuning", "action": "baseline",
                "threshold": base_threshold, "hold_days": base_hold_days,
                "weak_sectors": base_weak})

    # ── 2. daily_root_cause 加成 ──
    suggestion = rc.get('tuning_suggestion', {})
    if suggestion:
        threshold_delta = suggestion.get('score_threshold_delta', 0)
        position_delta = suggestion.get('position_delta', 0)
        weak_add = suggestion.get('weak_sectors_add', [])
        watchlist = suggestion.get('watchlist', [])
        cold_sectors = suggestion.get('cold_sectors', [])
        reasons = suggestion.get('reasons', [])

        # 阈值: base + delta, 钳制 [55,80]
        new_threshold = clamp(base_threshold + threshold_delta,
                              SAFE_THRESHOLD_MIN, SAFE_THRESHOLD_MAX)
        # 仓位: 50 + delta, 钳制 [10,90]
        new_position = clamp(BASE_POSITION + position_delta,
                             SAFE_POSITION_MIN, SAFE_POSITION_MAX)

        # weak_sectors: 不要从 daily_root_cause 的 watchlist/cold_sectors 直接加进 weak_sectors
        # (冷启动样本不足, 加进 weak_sectors 反而误杀)
        # 只加 rec_tuning 已有 n>=3 但 win_rate<35 的板块
        sec_stats = tuning.get('sector_stats', {})
        new_weak = list(set(base_weak) | set(weak_add))

        # 加严: 至少 n>=3 才进 (防误杀冷启动板块)
        final_weak = []
        for s in new_weak:
            stat = sec_stats.get(s, {})
            n = stat.get('count', 0)
            wr = stat.get('win_rate', 100)
            if n >= SAFE_WEAK_SECTOR_MIN_SAMPLES and wr < 40:
                final_weak.append(s)
        final_weak = sorted(final_weak)

        log.append({
            "source": "daily_root_cause",
            "action": "applied" if suggestion else "skipped",
            "threshold_delta": threshold_delta,
            "position_delta": position_delta,
            "weak_sectors_added": weak_add,
            "watchlist": watchlist,
            "cold_sectors": cold_sectors,
            "reasons": reasons,
        })

        threshold_final = new_threshold
        position_final = new_position
    else:
        threshold_final = base_threshold
        position_final = BASE_POSITION
        final_weak = base_weak

    # ── 3. 安全最终检查 ──
    if not isinstance(final_weak, list):
        final_weak = []

    strategy = {
        "date_for": datetime.now().strftime("%Y-%m-%d"),
        "score_threshold": threshold_final,
        "hold_days": base_hold_days,
        "weak_sectors": final_weak,
        "position_final": position_final,
        "position_base": BASE_POSITION,
        "watchlist": suggestion.get('watchlist', []),
        "cold_sectors": suggestion.get('cold_sectors', []),
        "tuning_log": log,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_files": {
            "rec_tuning": str(REC_TUNING.name),
            "daily_root_cause": str(DAILY_RC.name),
        },
    }

    # 打印
    print("=" * 60)
    print(f"🎯 AAna 次日自动调参 — {strategy['date_for']}")
    print("=" * 60)
    print(f"  score_threshold: {strategy['score_threshold']} (base={base_threshold})")
    print(f"  hold_days:       {strategy['hold_days']}")
    print(f"  position_final:  {strategy['position_final']}% (base={BASE_POSITION}%)")
    print(f"  weak_sectors ({len(strategy['weak_sectors'])}): {strategy['weak_sectors']}")
    if strategy['watchlist']:
        print(f"  watchlist ({len(strategy['watchlist'])}): {strategy['watchlist']}")
    if strategy['cold_sectors']:
        print(f"  cold_sectors ({len(strategy['cold_sectors'])}): {strategy['cold_sectors']}")
    print(f"\n  决策依据:")
    for entry in log:
        if entry.get('source') == 'daily_root_cause':
            for r in entry.get('reasons', []):
                print(f"    - {r}")
    print("=" * 60)

    if args.dry_run:
        print("\n[dry-run] 未写入文件")
        return 0

    OUT_JSON.write_text(json.dumps(strategy, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ next_day_strategy.json 写入: {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

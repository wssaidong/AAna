"""
scripts/strategy_policy.py — 策略参数执行层 (数据驱动推荐的最后一环)

v2026-08-23:

闭环链路 (全自动化):
    feedback_loop.py (每日补 ret_1d)
      → rec_optimizer.py (Phase 5B 后置 hook, 复盘胜率)
      → data/rec_tuning.json (调参建议)
      → **strategy_policy.py (本文件, 建议→当日策略参数)**
      → aana_afternoon_screen.py (动态阈值 + weak_sectors 过滤)

设计原则:
  1. 安全默认: rec_tuning.json 缺失/损坏/字段异常 → 一律回落 v2.4 硬编码默认值
  2. 边界钳制: 阈值只允许 [55, 80] — 数据再差也不把阈值调到离谱区间
  3. 冷启动保护: 调参数据 < MIN_TOTAL_RECORDS (100) 时用默认值,并在 source 里标明
  4. 幂等只读: 本模块只读 rec_tuning.json,绝不写

用法 (推荐链路内):
    from strategy_policy import get_today_policy
    policy = get_today_policy()
    if stock_score >= policy.score_threshold and sector not in policy.sector_blacklist:
        recommend(...)
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).parent.parent.resolve()
TUNING_PATH = PROJECT / "data" / "rec_tuning.json"

# v2.4 硬编码默认 (与 aana_afternoon_screen 原始行为一致)
DEFAULT_SCORE_THRESHOLD = 65
DEFAULT_TOP_N = 10
DEFAULT_HOLD_DAYS = 1

# 钳制边界 — 超出视为数据异常,回落默认
MIN_SCORE_THRESHOLD = 55
MAX_SCORE_THRESHOLD = 80
# 冷启动最小样本 — total_records 少于这个数不动策略
MIN_TOTAL_RECORDS = 100
# 板块黑名单最短板块样本 — 该板块样本 < 此数不拉黑 (防小样本)
MIN_SECTOR_SAMPLES = 10
# 板块胜率拉黑线
SECTOR_WEAK_WINRATE = 35.0


@dataclass
class StrategyPolicy:
    """当日推荐策略参数 — 由 rec_tuning.json + 安全规则推导"""
    score_threshold: int = DEFAULT_SCORE_THRESHOLD
    top_n: int = DEFAULT_TOP_N
    hold_days: int = DEFAULT_HOLD_DAYS
    sector_blacklist: list[str] = field(default_factory=list)
    # 决策溯源 — 为什么是这些参数 (写进日报, 用户可审计)
    source: str = "default"
    tuning_age_days: float | None = None
    data_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score_threshold": self.score_threshold,
            "top_n": self.top_n,
            "hold_days": self.hold_days,
            "sector_blacklist": self.sector_blacklist,
            "source": self.source,
            "tuning_age_days": self.tuning_age_days,
            "data_notes": self.data_notes,
        }


def _load_tuning() -> dict[str, Any] | None:
    if not TUNING_PATH.exists():
        return None
    try:
        d = json.loads(TUNING_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def get_today_policy() -> StrategyPolicy:
    """读取 rec_tuning.json → 产出当日策略。任何异常都回落默认值。"""
    policy = StrategyPolicy()
    tuning = _load_tuning()
    if tuning is None:
        policy.data_notes.append("rec_tuning.json 缺失/损坏 → v2.4 默认参数")
        return policy

    # 调参文件新鲜度
    gen_at = str(tuning.get("generated_at", ""))
    if gen_at:
        try:
            age = (datetime.now() - datetime.fromisoformat(gen_at)).total_seconds() / 86400
            policy.tuning_age_days = round(age, 1)
            if age > 14:
                policy.data_notes.append(
                    f"调参数据已 {age:.0f} 天未更新 (feedback_loop Phase 5B 是否在跑?)")
        except ValueError:
            pass

    # ── 冷启动保护 ────────────────────────────────────────────────
    total = int(tuning.get("total_records", 0) or 0)
    if total < MIN_TOTAL_RECORDS:
        policy.data_notes.append(
            f"样本 {total} < {MIN_TOTAL_RECORDS} (冷启动) → 默认参数")
        return policy

    # ── score 阈值 (钳制边界内才采纳) ─────────────────────────────
    try:
        raw_th = int(tuning.get("recommended_score_threshold", DEFAULT_SCORE_THRESHOLD))
    except (TypeError, ValueError):
        raw_th = DEFAULT_SCORE_THRESHOLD
    if MIN_SCORE_THRESHOLD <= raw_th <= MAX_SCORE_THRESHOLD:
        if raw_th != DEFAULT_SCORE_THRESHOLD:
            policy.data_notes.append(f"阈值 {DEFAULT_SCORE_THRESHOLD}→{raw_th} (rec_tuning)")
        policy.score_threshold = raw_th
    else:
        policy.data_notes.append(
            f"阈值 {raw_th} 越界 [{MIN_SCORE_THRESHOLD},{MAX_SCORE_THRESHOLD}] → 保持默认")

    # ── 持有天数 ──────────────────────────────────────────────────
    try:
        raw_hold = int(tuning.get("recommended_hold_days", DEFAULT_HOLD_DAYS))
        if raw_hold in (1, 3, 5):
            policy.hold_days = raw_hold
    except (TypeError, ValueError):
        pass

    # ── 板块黑名单 (样本 >= MIN_SECTOR_SAMPLES 且胜率 < SECTOR_WEAK_WINRATE) ──
    # v1 逻辑直接信任 rec_tuning.weak_sectors;v2 加样本门槛复核 —
    # rec_optimizer 的 weak_sectors 可能基于 < 10 条的小样本板块。
    sector_stats = tuning.get("sector_stats", {}) or {}
    weak_from_tuning = set(str(s) for s in tuning.get("weak_sectors", []) or [])
    blacklist: list[str] = []
    for sec, st in sector_stats.items():
        if not isinstance(st, dict):
            continue
        n = int(st.get("count", 0) or 0)
        wr = float(st.get("win_rate", 100.0) or 0.0)
        if n >= MIN_SECTOR_SAMPLES and wr < SECTOR_WEAK_WINRATE:
            blacklist.append(sec)
    # tuning 明示的 weak_sectors 但 sector_stats 缺它 → 也纳入 (保守)
    for sec in weak_from_tuning:
        if sec not in blacklist and sec not in sector_stats:
            blacklist.append(sec)
    policy.sector_blacklist = sorted(blacklist)
    if blacklist:
        policy.data_notes.append(
            f"板块黑名单 {len(blacklist)} 个: {','.join(blacklist)} "
            f"(样本≥{MIN_SECTOR_SAMPLES} 且胜率<{SECTOR_WEAK_WINRATE:.0f}%)")

    policy.source = "rec_tuning"
    return policy


def policy_banner(policy: StrategyPolicy) -> str:
    """一行策略摘要 — 打进推荐日志/日报头部,用户可审计当天策略从哪来"""
    bl = ",".join(policy.sector_blacklist) if policy.sector_blacklist else "无"
    return (f"[strategy_policy] source={policy.source} "
            f"threshold={policy.score_threshold} top_n={policy.top_n} "
            f"hold={policy.hold_days}d blacklist=[{bl}]"
            + (f" tuning_age={policy.tuning_age_days}d" if policy.tuning_age_days is not None else ""))


# ── CLI 自测 ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    p = get_today_policy()
    print(policy_banner(p))
    for note in p.data_notes:
        print(f"  · {note}")
    print(json.dumps(p.to_dict(), ensure_ascii=False, indent=2))
    sys.exit(0)

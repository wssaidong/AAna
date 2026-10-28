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
# v2026-10-02: 暴露全局 _nd_path, 让测试能 monkeypatch 屏蔽真实 next_day_strategy.json
ND_PATH = PROJECT / "data" / "next_day_strategy.json"

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
    cold_start = int(tuning.get("total_records", 0) or 0) < MIN_TOTAL_RECORDS
    if cold_start:
        policy.data_notes.append(
            f"样本 {tuning.get('total_records', 0)} < {MIN_TOTAL_RECORDS} (冷启动) → weak_sectors 不加载, 但 next_day_strategy 阈值仍生效"
        )

    # ── score 阈值 (优先级: next_day_strategy > rec_tuning > DEFAULT) ──
    # v2026-09-09 (Phase 12): 优先读 next_day_strategy.json (含昨日根因调参)
    raw_th = DEFAULT_SCORE_THRESHOLD
    nd_score_threshold = None
    try:
        import json as _json
        # v2026-10-02: 用全局 ND_PATH 替换局部 path, 让测试能 monkeypatch
        if ND_PATH.exists():
            _nd = _json.loads(ND_PATH.read_text(encoding="utf-8"))
            nd_score_threshold = _nd.get("score_threshold")
            if isinstance(nd_score_threshold, (int, float)):
                raw_th = int(nd_score_threshold)
                policy.data_notes.append(
                    f"阈值 {DEFAULT_SCORE_THRESHOLD}→{raw_th} (next_day_strategy, 含昨日根因调参)"
                )
    except Exception as _nd_err:
        policy.data_notes.append(f"next_day_strategy 加载失败: {_nd_err}")

    # 如果 next_day_strategy 没有, 回退到 rec_tuning
    if nd_score_threshold is None:
        try:
            tuning_th = int(tuning.get("recommended_score_threshold", DEFAULT_SCORE_THRESHOLD))
            if MIN_SCORE_THRESHOLD <= tuning_th <= MAX_SCORE_THRESHOLD:
                raw_th = tuning_th
                if raw_th != DEFAULT_SCORE_THRESHOLD:
                    policy.data_notes.append(f"阈值 {DEFAULT_SCORE_THRESHOLD}→{raw_th} (rec_tuning)")
            else:
                # v2026-10-02 B6 修复: rec_tuning 越界也加警示 (之前静默钳制)
                policy.data_notes.append(
                    f"rec_tuning 阈值 {tuning_th} 越界 [{MIN_SCORE_THRESHOLD},{MAX_SCORE_THRESHOLD}] → 保持默认 {DEFAULT_SCORE_THRESHOLD}"
                )
        except (TypeError, ValueError):
            pass
    if MIN_SCORE_THRESHOLD <= raw_th <= MAX_SCORE_THRESHOLD:
        policy.score_threshold = raw_th
    else:
        policy.data_notes.append(
            f"阈值 {raw_th} 越界 [{MIN_SCORE_THRESHOLD},{MAX_SCORE_THRESHOLD}] → 保持默认"
        )
        policy.score_threshold = DEFAULT_SCORE_THRESHOLD

    # ── 持有天数 ──────────────────────────────────────────────────
    try:
        raw_hold = int(tuning.get("recommended_hold_days", DEFAULT_HOLD_DAYS))
        if raw_hold in (1, 3, 5):
            policy.hold_days = raw_hold
    except (TypeError, ValueError):
        pass

    # ── 板块黑名单 ──────────────────────────────────────────────────
    # v2026-10-28 P0-2 修复 (P0-1 只修了"匹配层", 生产层仍关着):
    #
    #   症状: 10-13 至今所有运行日志都是 `blacklist=[无]` → 弱势板块 100% 未生效。
    #   根因: **两个权威的门槛互相打架**, 消费者把生产者的结论全否掉:
    #     生产者 rec_optimizer.find_weak_sectors()  门槛 n>=3 且 (wr<40% 或 avg_change<-1%)
    #     消费者 strategy_policy (本段)             门槛 n>=10 且 wr<35%
    #     实测 6 个弱势板块样本全是 n=3 → 消费者门槛把 6 个全否 → blacklist=[]。
    #   更隐蔽的一层: 下面原 L180 fallback 条件写反了 ——
    #     原条件 `sec not in sector_stats` 只在"板块完全不在 stats 里"时才纳入,
    #     而这 6 个板块**都在** sector_stats 里(只是 n 不够门槛) → fallback 永不触发。
    #     于是"生产者明说弱 + 消费者门槛否掉" = 双重保险把结论彻底埋掉。
    #
    #   修法 (单一权威 + 两条独立路径):
    #     路径A 生产者显式判定 → 直接采信 rec_tuning.weak_sectors。
    #           rec_optimizer 自己已按 n>=3 & (wr<40% 或 avg_change<-1%) 过滤过,
    #           它就是"哪些板块弱势"的唯一权威, 消费者不该用另一套门槛二次否决。
    #     路径B 消费者自动发现 → 只覆盖**生产者没列入**的板块, 保留 n>=10 严门槛
    #           (防小样本误杀, 保住 v2 的设计意图)。
    #   实测 (2026-10-28, 354 笔已结算去重样本):
    #     路径A+B 合并 → 6 个板块进黑名单; 反事实回测把这 6 个板块剔除后
    #     胜率 48.9% → 49.7% (+0.8pp), 被剔除子集胜率仅 31.2% (整体 48.9%)。
    sector_stats = tuning.get("sector_stats", {}) or {}
    weak_from_tuning = set(str(s) for s in tuning.get("weak_sectors", []) or [])
    blacklist: list[str] = []

    # 路径B: 严门槛自动发现 (仅限生产者未列入的板块)
    auto_derived: list[str] = []
    for sec, st in sector_stats.items():
        if not isinstance(st, dict):
            continue
        n = int(st.get("count", 0) or 0)
        wr = float(st.get("win_rate", 100.0) or 0.0)
        if n >= MIN_SECTOR_SAMPLES and wr < SECTOR_WEAK_WINRATE:
            auto_derived.append(sec)
    for sec in auto_derived:
        if sec not in weak_from_tuning:
            blacklist.append(sec)
    # 路径A: 生产者显式判定 → 无条件纳入 (它已自带 n>=3 & wr<40% 过滤)
    for sec in sorted(weak_from_tuning):
        if sec not in blacklist:
            blacklist.append(sec)

    policy.sector_blacklist = sorted(blacklist)
    if blacklist:
        _n_a = len(weak_from_tuning & set(blacklist))
        _n_b = len(blacklist) - _n_a
        policy.data_notes.append(
            f"板块黑名单 {len(blacklist)} 个: {','.join(blacklist)} "
            f"(生产者判定 {_n_a} 个 + 自动发现 {_n_b} 个, 自动发现门槛 n≥{MIN_SECTOR_SAMPLES} 且胜率<{SECTOR_WEAK_WINRATE:.0f}%)"
        )

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

#!/usr/bin/env python3
"""scripts/verify_sector_filter_chain.py — 弱板块过滤链路端到端防错脚本

v2026-10-28 新增。背景见 references/sector-blacklist-authority-conflict-2026-10-28.md:
弱板块过滤从 10-13 起 100% 失效, 而**所有单元测试都是绿的** —— 因为
「生产层」「匹配层」「消费层」三处各自都对, 只有**串起来**才暴露。

所以这个脚本的验收标准不是「函数返回对不对」, 而是**链路最终产出物**:
  1. rec_tuning.weak_sectors 非空 (生产者有结论)
  2. strategy_policy.sector_blacklist 非空 (消费者没把结论否掉)  ← 10-13~10-28 恒空
  3. 过滤真的能命中 (中文名 OR enum 双路)
  4. 健康板块不被误伤 (冷启动 veto 不能拦掉高胜率板块)
  5. 关键 key 口径一致 (sector_stats 用中文名, 查的时候也要用中文名)

用法:
  python3 scripts/verify_sector_filter_chain.py            # 报告 + 非零退出码(失败)
  python3 scripts/verify_sector_filter_chain.py --quiet    # 只输出失败项
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "scripts"))

FAILURES: list[str] = []
WARNINGS: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> bool:
    if cond:
        print(f"  ✅ {label}" + (f" — {detail}" if detail else ""))
    else:
        FAILURES.append(label + (f" — {detail}" if detail else ""))
        print(f"  ❌ {label}" + (f" — {detail}" if detail else ""))
    return cond


def main() -> int:
    quiet = "--quiet" in sys.argv

    print("=" * 78)
    print("🔍 弱板块过滤链路端到端验证")
    print("=" * 78)

    # ── 1. 生产者有结论吗? ───────────────────────────────────────
    print("\n[1/5] 生产者 (rec_tuning.weak_sectors)")
    tuning_path = PROJECT / "data" / "rec_tuning.json"
    if not tuning_path.exists():
        FAILURES.append("data/rec_tuning.json 不存在")
        print("  ❌ data/rec_tuning.json 不存在 — 先跑 rec_optimizer.py")
        return 1
    tuning = json.loads(tuning_path.read_text(encoding="utf-8"))
    weak = tuning.get("weak_sectors") or []
    check(bool(weak), "生产者产出了弱势板块", f"{len(weak)} 个: {', '.join(weak)}")

    # ── 2. 消费者把结论保住了吗? (历史失效点) ───────────────────
    print("\n[2/5] 消费者 (strategy_policy.sector_blacklist)")
    from strategy_policy import get_today_policy

    policy = get_today_policy()
    bl = policy.sector_blacklist
    check(bool(bl), "黑名单非空 (10-13~10-28 恒空 = 失效)", f"{len(bl)} 个: {', '.join(bl)}")
    missing = [s for s in weak if s not in bl]
    check(not missing, "生产者判定的板块全部进了黑名单",
          "" if not missing else f"被消费层否决: {missing}")

    # ── 3. 过滤真的能命中? ───────────────────────────────────────
    print("\n[3/5] 匹配层 (中文名 OR enum 双路)")
    try:
        from aana_afternoon_screen import _cn_sector_to_enum, _sector_blacklisted
    except Exception as exc:
        WARNINGS.append(f"无法导入 aana_afternoon_screen: {exc}")
        _sector_blacklisted = None
        _cn_sector_to_enum = lambda s: ""  # noqa: E731
    if _sector_blacklisted:
        bl_set = set(bl)
        for sec in weak:
            enum = _cn_sector_to_enum(sec)
            hit = _sector_blacklisted(sec, enum, bl_set)
            check(hit, f"弱板块 {sec} (enum={enum or 'unknown'}) 能被拦截")

        # ── 4. 健康板块不被误伤 ─────────────────────────────────
        print("\n[4/5] 冷启动 veto 不误伤高胜率板块")
        sec_stats = tuning.get("sector_stats", {}) or {}
        healthy = [
            (name, st.get("count", 0), st.get("win_rate", 0))
            for name, st in sec_stats.items()
            if isinstance(st, dict)
            and st.get("count", 0) >= 5
            and st.get("win_rate", 0) >= 60
            and name not in bl
        ]
        healthy.sort(key=lambda x: -x[2])
        nd_path = PROJECT / "data" / "next_day_strategy.json"
        cold = []
        if nd_path.exists():
            cold = json.loads(nd_path.read_text(encoding="utf-8")).get("cold_sectors") or []
        false_pos = [
            (name, n, wr) for name, n, wr in healthy
            if name in cold
        ]
        check(not false_pos, "高胜率板块未被 cold_sectors 一票否决",
              "" if not false_pos
              else f"误伤: {[(n, f'n={c}', f'wr={w:.1f}%') for n, c, w in false_pos]}")
        if healthy:
            print(f"     (健康板块样本: {[(n, f'n={c}', f'wr={w:.0f}%') for n, c, w in healthy[:5]]})")

    # ── 5. key 口径一致 ───────────────────────────────────────────
    print("\n[5/5] key 口径一致性 (sector_stats = 中文行业名)")
    sec_stats = tuning.get("sector_stats", {}) or {}
    if _sector_blacklisted:
        cn_keyed = [k for k in sec_stats if any('一' <= c <= '鿿' for c in k)]
        enum_keyed = [k for k in sec_stats if k and not any('一' <= c <= '鿿' for c in k)]
        check(
            len(cn_keyed) >= len(enum_keyed),
            "sector_stats 以中文名为主要 key",
            f"中文名 {len(cn_keyed)} 个 / enum {len(enum_keyed)} 个",
        )
        # enum 桶若存在, 提醒它与中文桶可能是同一板块的两个分桶
        if enum_keyed:
            WARNINGS.append(
                f"sector_stats 里存在 enum 桶 {enum_keyed} — 可能是同一板块的第二分桶, "
                f"黑名单会连带命中中文桶 (分桶口径问题, 需专项回测)"
            )

    # ── 汇总 ──────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    if WARNINGS:
        for w in WARNINGS:
            print(f"⚠️  {w}")
    if FAILURES:
        print(f"❌ 失败 {len(FAILURES)} 项:")
        for f in FAILURES:
            print(f"   - {f}")
        print("=" * 78)
        return 1
    print("✅ 弱板块过滤链路全部贯通")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())

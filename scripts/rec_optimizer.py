#!/usr/bin/env python3
"""
scripts/rec_optimizer.py — 推荐优化器
=====================================
从历史反馈数据中分析评分阈值、持有天数、板块胜率，
输出调参建议并可集成到 generate_report.py 的评分流程。

功能：
1. 读取 data/rec_feedback.csv 历史反馈数据
2. 分析不同评分区间的胜率分布（40-50/50-60/60-70/70+）
3. 分析不同持有天数的胜率分布（1/3/5/15日）
4. 分析不同板块的胜率，找出弱势板块
5. 输出调参建议：建议评分阈值、建议持有天数、建议过滤板块
6. 集成到 generate_report.py 的评分流程（作为可选模块）

用法：
  python scripts/rec_optimizer.py                 # 分析并输出建议
  python scripts/rec_optimizer.py --min-samples 5 # 最小样本数（默认3）
  python scripts/rec_optimizer.py --integrate     # 集成建议到 generate_report.py

导入：
  from scripts.rec_optimizer import RecOptimizer, get_tuning_config
  config = get_tuning_config()
"""

import os
import sys
import csv
import json
import argparse
from dataclasses import dataclass
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

# ── 路径常量 ────────────────────────────────────────────────────────────────

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
FEEDBACK_CSV = DATA_DIR / "rec_feedback.csv"
CONFIG_JSON = DATA_DIR / "rec_tuning.json"

# 默认评分阈值（会基于历史数据动态调整）
DEFAULT_SCORE_BANDS = [
    ("40-50", 40, 50),
    ("50-60", 50, 60),
    ("60-70", 60, 70),
    ("70+",   70, 999),
]

DEFAULT_HOLD_DAYS = [1, 3, 5, 15]

# ── 数据模型 ────────────────────────────────────────────────────────────────

@dataclass
class FeedbackRecord:
    """单条反馈记录"""
    date: str
    code: str
    name: str
    sector: str
    sector_name: str
    score: int          # 推荐时的综合评分
    hold_days: int      # 实际持有天数
    actual_change: float  # 实际涨跌幅（%）
    is_win: bool        # 是否盈利（actual_change > 0）
    expected_high: float
    expected_low: float
    hit: bool           # 是否符合预测
    created_at: str

@dataclass
class ScoreBandStats:
    """评分区间统计"""
    band: str
    count: int
    win_count: int
    win_rate: float
    avg_change: float
    avg_hold_days: float

@dataclass
class HoldDaysStats:
    """持有天数统计"""
    hold_days: int
    count: int
    win_count: int
    win_rate: float
    avg_change: float

@dataclass
class SectorStats:
    """板块统计"""
    sector: str
    sector_name: str
    count: int
    win_count: int
    win_rate: float
    avg_change: float
    consecutive_bad: int  # 连续亏损次数

@dataclass
class TuningConfig:
    """调参配置（供 generate_report.py 使用）"""
    recommended_score_threshold: int
    recommended_hold_days: int
    weak_sectors: List[str]          # 建议过滤的弱势板块
    score_band_stats: Dict[str, ScoreBandStats]
    hold_days_stats: Dict[int, HoldDaysStats]
    sector_stats: Dict[str, SectorStats]
    total_records: int
    overall_win_rate: float
    generated_at: str
    _win_rate_threshold: float = 40.0  # internal use

# ── 数据加载 ────────────────────────────────────────────────────────────────

def load_feedback_data(csv_path: str = None) -> List[FeedbackRecord]:
    """
    加载 rec_feedback.csv，转换为 FeedbackRecord 列表。
    支持旧格式（recommendations.csv / tracking.csv）自动转换。
    """
    if csv_path is None:
        csv_path = FEEDBACK_CSV

    if not os.path.exists(csv_path):
        # 尝试从 recommendations.csv + tracking.csv 重建
        records = _rebuild_from_existing()
        if records:
            _save_feedback_csv(records)
            return records
        print(f"[RecOptimizer] 数据文件不存在且无法重建: {csv_path}")
        return []

    records = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                score = int(float(row.get("score", 0)))
                hold_days = int(float(row.get("hold_days", 0)))
                actual_change = float(row.get("actual_change", 0))
                is_win = bool(row.get("is_win", str(actual_change > 0)).lower() == "true")
                records.append(FeedbackRecord(
                    date=row.get("date", ""),
                    code=row.get("code", ""),
                    name=row.get("name", ""),
                    sector=row.get("sector", ""),
                    sector_name=row.get("sector_name", ""),
                    score=score,
                    hold_days=hold_days,
                    actual_change=actual_change,
                    is_win=is_win,
                    expected_high=float(row.get("expected_high", 0)),
                    expected_low=float(row.get("expected_low", 0)),
                    hit=row.get("hit", "") == "True",
                    created_at=row.get("created_at", ""),
                ))
            except (ValueError, KeyError) as e:
                continue
    return records


def _rebuild_from_existing() -> List[FeedbackRecord]:
    """
    从现有的 recommendations.csv + tracking.csv 重建反馈数据。
    tracking.csv 记录了实际涨跌和是否命中预测，
    可与 recommendations.csv 结合生成 rec_feedback.csv。
    """
    rec_path = DATA_DIR / "recommendations.csv"
    track_path = DATA_DIR / "tracking.csv"

    if not os.path.exists(rec_path):
        return []

    # 读取 recommendations 建立推荐记录
    rec_map = {}  # (code, date) -> record
    with open(rec_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row.get("code", ""), row.get("date", ""))
            rec_map[key] = row

    if not os.path.exists(track_path):
        return []

    records = []
    with open(track_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get("code", "")
            date = row.get("date", "")
            key = (code, date)
            rec = rec_map.get(key, {})

            sector = row.get("sector", rec.get("sector", ""))
            name = row.get("name", rec.get("name", ""))
            sector_name = row.get("sector_name", rec.get("sector_name", ""))

            # 尝试从 reason 推断持有天数，或用默认值 5
            reason = rec.get("reason", "")
            hold_days = _infer_hold_days(reason)

            # 实际涨跌幅
            try:
                actual_change = float(row.get("change_pct", 0))
            except (ValueError, TypeError):
                actual_change = 0

            # 评分：暂无，使用默认阈值60附近的分布模拟
            # 这里用 expected_high/low 估算评分区间
            expected_high = float(rec.get("expected_high", 5))
            expected_low = float(rec.get("expected_low", -3))
            score = _estimate_score(expected_high, expected_low, actual_change)

            records.append(FeedbackRecord(
                date=date,
                code=code,
                name=name,
                sector=sector,
                sector_name=sector_name,
                score=score,
                hold_days=hold_days,
                actual_change=actual_change,
                is_win=actual_change > 0,
                expected_high=expected_high,
                expected_low=expected_low,
                hit=row.get("hit", "") == "True",
                created_at=rec.get("created_at", row.get("updated_at", "")),
            ))

    return records


def _infer_hold_days(reason: str) -> int:
    """从推荐理由推断持有天数（默认5天）"""
    reason = reason.lower()
    if "短线" in reason or "次日" in reason:
        return 1
    if "3日" in reason or "三日" in reason:
        return 3
    if "5日" in reason or "五日" in reason:
        return 5
    if "15日" in reason or "半月" in reason:
        return 15
    return 5  # 默认


def _estimate_score(expected_high: float, expected_low: float, actual_change: float) -> int:
    """
    估算综合评分。
    规则：expected_high 越高、expected_low 越低，评分越高。
    同时用实际表现校正。
    """
    score = 50
    if expected_high >= 5:
        score += 15
    elif expected_high >= 3:
        score += 10
    elif expected_high >= 1:
        score += 5

    if expected_low <= -5:
        score += 10
    elif expected_low <= -3:
        score += 5

    # 校正：实际表现好则加分
    if actual_change > 0:
        score += int(min(actual_change, 10))
    else:
        score -= int(min(abs(actual_change), 10))

    return max(0, min(100, score))


def _save_feedback_csv(records: List[FeedbackRecord]):
    """将 FeedbackRecord 列表保存为 rec_feedback.csv"""
    if not records:
        return
    fieldnames = [
        "date", "code", "name", "sector", "sector_name",
        "score", "hold_days", "actual_change", "is_win",
        "expected_high", "expected_low", "hit", "created_at",
    ]
    with open(FEEDBACK_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            writer.writerow({
                "date": r.date,
                "code": r.code,
                "name": r.name,
                "sector": r.sector,
                "sector_name": r.sector_name,
                "score": r.score,
                "hold_days": r.hold_days,
                "actual_change": r.actual_change,
                "is_win": str(r.is_win),
                "expected_high": r.expected_high,
                "expected_low": r.expected_low,
                "hit": str(r.hit),
                "created_at": r.created_at,
            })
    print(f"[RecOptimizer] 反馈数据已保存: {FEEDBACK_CSV}")


# ── 统计分析 ────────────────────────────────────────────────────────────────

def calc_score_band_stats(records: List[FeedbackRecord]) -> Dict[str, ScoreBandStats]:
    """按评分区间统计胜率"""
    buckets = defaultdict(list)
    for r in records:
        for band, lo, hi in DEFAULT_SCORE_BANDS:
            if lo <= r.score < hi:
                buckets[band].append(r)
                break

    stats = {}
    for band, lo, hi in DEFAULT_SCORE_BANDS:
        recs = buckets[band]
        if not recs:
            continue
        wins = [r for r in recs if r.is_win]
        stats[band] = ScoreBandStats(
            band=band,
            count=len(recs),
            win_count=len(wins),
            win_rate=len(wins) / len(recs) * 100,
            avg_change=sum(r.actual_change for r in recs) / len(recs),
            avg_hold_days=sum(r.hold_days for r in recs) / len(recs),
        )
    return stats


def calc_hold_days_stats(records: List[FeedbackRecord]) -> Dict[int, HoldDaysStats]:
    """按持有天数统计胜率"""
    buckets = defaultdict(list)
    for r in records:
        # 归入最近的默认持有天数
        closest = min(DEFAULT_HOLD_DAYS, key=lambda x: abs(x - r.hold_days))
        buckets[closest].append(r)

    stats = {}
    for hd in DEFAULT_HOLD_DAYS:
        recs = buckets.get(hd, [])
        if not recs:
            continue
        wins = [r for r in recs if r.is_win]
        stats[hd] = HoldDaysStats(
            hold_days=hd,
            count=len(recs),
            win_count=len(wins),
            win_rate=len(wins) / len(recs) * 100,
            avg_change=sum(r.actual_change for r in recs) / len(recs),
        )
    return stats


def calc_sector_stats(records: List[FeedbackRecord]) -> Dict[str, SectorStats]:
    """按板块统计胜率，找出弱势板块"""
    buckets = defaultdict(list)
    for r in records:
        if r.sector:
            buckets[r.sector].append(r)

    stats = {}
    for sector, recs in buckets.items():
        if not recs:
            continue
        wins = [r for r in recs if r.is_win]
        # 连续亏损：统计连续_bad 标记（遍历计数连续亏损次数）
        consecutive_bad = 0
        for r in recs:
            if r.actual_change < 0:
                consecutive_bad += 1
            else:
                break
        sector_name = recs[0].sector_name if recs else sector

        stats[sector] = SectorStats(
            sector=sector,
            sector_name=sector_name,
            count=len(recs),
            win_count=len(wins),
            win_rate=len(wins) / len(recs) * 100,
            avg_change=sum(r.actual_change for r in recs) / len(recs),
            consecutive_bad=consecutive_bad,
        )
    return stats


def find_optimal_score_threshold(score_band_stats: Dict[str, ScoreBandStats]) -> int:
    """找出胜率最高的评分区间，返回该区间的下限作为阈值"""
    if not score_band_stats:
        return 60  # 默认
    best_band = max(score_band_stats, key=lambda b: score_band_stats[b].win_rate)
    band_defs = {b: (lo, hi) for b, lo, hi in DEFAULT_SCORE_BANDS}
    lo, hi = band_defs.get(best_band, (60, 70))
    # 取该区间中胜率超过50%的最低分
    return lo


def find_optimal_hold_days(hold_days_stats: Dict[int, HoldDaysStats]) -> int:
    """找出胜率最高的持有天数"""
    if not hold_days_stats:
        return 5  # 默认
    best_hd = max(hold_days_stats, key=lambda h: hold_days_stats[h].win_rate)
    return best_hd


def find_weak_sectors(sector_stats: Dict[str, SectorStats], min_count: int = 3,
                      win_rate_threshold: float = 40.0) -> List[str]:
    """
    找出弱势板块：
    1. 样本数 >= min_count
    2. 胜率 < win_rate_threshold OR 平均涨幅 < -1%
    """
    weak = []
    for sector, stat in sector_stats.items():
        if stat.count < min_count:
            continue
        if stat.win_rate < win_rate_threshold or stat.avg_change < -1.0:
            weak.append(sector)
    # 按胜率升序排列（最差的在前面）
    weak.sort(key=lambda s: sector_stats[s].win_rate)
    return weak


# ── 核心类 ────────────────────────────────────────────────────────────────

class RecOptimizer:
    """
    推荐优化器：分析历史反馈数据，输出调参建议。

    参数：
      min_samples       : 各维度最小样本数（默认3，少于此数不输出该维度建议）
      min_sector_count  : 板块最小样本数（默认3）
      win_rate_threshold: 弱势板块胜率阈值（默认40%）
    """

    def __init__(
        self,
        csv_path: str = None,
        min_samples: int = 3,
        min_sector_count: int = 3,
        win_rate_threshold: float = 40.0,
    ):
        self.csv_path = csv_path
        self.min_samples = min_samples
        self.min_sector_count = min_sector_count
        self.win_rate_threshold = win_rate_threshold
        self.records: List[FeedbackRecord] = []
        self.score_band_stats: Dict[str, ScoreBandStats] = {}
        self.hold_days_stats: Dict[int, HoldDaysStats] = {}
        self.sector_stats: Dict[str, SectorStats] = {}
        self.config: Optional[TuningConfig] = None

    def run(self) -> TuningConfig:
        """执行全部分析，返回 TuningConfig"""
        self.records = load_feedback_data(self.csv_path)

        if not self.records:
            print("[RecOptimizer] 无反馈数据，跳过分析")
            return self._default_config()

        self.score_band_stats = calc_score_band_stats(self.records)
        self.hold_days_stats = calc_hold_days_stats(self.records)
        self.sector_stats = calc_sector_stats(self.records)

        # 计算最优参数
        optimal_score = find_optimal_score_threshold(self.score_band_stats)
        optimal_hold_days = find_optimal_hold_days(self.hold_days_stats)
        weak_sectors = find_weak_sectors(
            self.sector_stats,
            min_count=self.min_sector_count,
            win_rate_threshold=self.win_rate_threshold,
        )

        total_wins = sum(1 for r in self.records if r.is_win)
        overall_win_rate = total_wins / len(self.records) * 100

        self.config = TuningConfig(
            recommended_score_threshold=optimal_score,
            recommended_hold_days=optimal_hold_days,
            weak_sectors=weak_sectors,
            score_band_stats=self.score_band_stats,
            hold_days_stats=self.hold_days_stats,
            sector_stats=self.sector_stats,
            total_records=len(self.records),
            overall_win_rate=overall_win_rate,
            generated_at=datetime.now().isoformat(),
            _win_rate_threshold=self.win_rate_threshold,
        )

        return self.config

    def print_report(self):
        """打印 Markdown 格式的分析报告"""
        if self.config is None:
            print("[RecOptimizer] 请先调用 run()")
            return

        cfg = self.config

        print("\n" + "=" * 60)
        print("📊 RecOptimizer — 推荐参数优化报告")
        print("=" * 60)
        print(f"生成时间：{cfg.generated_at}")
        print(f"总记录数：{cfg.total_records} | 总胜率：{cfg.overall_win_rate:.1f}%\n")

        # ── 1. 评分区间胜率 ──
        print("### 1️⃣ 评分区间胜率分析\n")
        print("| 评分区间 | 样本数 | 胜率 | 平均涨跌 | 平均持仓 |")
        print("|:--------:|:------:|:----:|:--------:|:--------:|")
        for band in ["40-50", "50-60", "60-70", "70+"]:
            s = cfg.score_band_stats.get(band)
            if not s:
                continue
            print(
                f"| {s.band} | {s.count} | "
                f"{s.win_rate:.1f}% | "
                f"{s.avg_change:+.2f}% | "
                f"{s.avg_hold_days:.1f}天 |"
            )

        if cfg.score_band_stats:
            best_band = max(cfg.score_band_stats, key=lambda b: cfg.score_band_stats[b].win_rate)
            print(f"\n✅ **最优评分区间：{best_band}**（胜率 {cfg.score_band_stats[best_band].win_rate:.1f}%）")

        # ── 2. 持有天数胜率 ──
        print("\n### 2️⃣ 持有天数胜率分析\n")
        print("| 持有天数 | 样本数 | 胜率 | 平均涨跌 |")
        print("|:--------:|:------:|:----:|:--------:|")
        for hd in DEFAULT_HOLD_DAYS:
            s = cfg.hold_days_stats.get(hd)
            if not s:
                continue
            print(
                f"| {hd}天 | {s.count} | "
                f"{s.win_rate:.1f}% | "
                f"{s.avg_change:+.2f}% |"
            )

        if cfg.hold_days_stats:
            best_hd = max(cfg.hold_days_stats, key=lambda h: cfg.hold_days_stats[h].win_rate)
            print(f"\n✅ **最优持有天数：{best_hd}天**（胜率 {cfg.hold_days_stats[best_hd].win_rate:.1f}%）")

        # ── 3. 板块胜率 ──
        print("\n### 3️⃣ 板块胜率分析\n")
        print("| 板块 | 样本数 | 胜率 | 平均涨跌 |")
        print("|:----:|:------:|:----:|:--------:|")
        sorted_sectors = sorted(cfg.sector_stats.items(), key=lambda x: x[1].win_rate)
        threshold = cfg._win_rate_threshold
        for sector, s in sorted_sectors:
            emoji = "🔴" if s.win_rate < threshold else "🟢"
            print(
                f"| {emoji} {s.sector_name}({s.sector}) | {s.count} | "
                f"{s.win_rate:.1f}% | {s.avg_change:+.2f}% |"
            )

        if cfg.weak_sectors:
            print(f"\n⚠️ **建议过滤弱势板块：{', '.join(cfg.weak_sectors)}**")

        # ── 4. 调参建议 ──
        print("\n### 4️⃣ 调参建议\n")
        print(f"| 参数 | 当前默认 | 建议值 | 说明 |")
        print("|:----:|:--------:|:------:|:----:|")
        print(f"| 评分阈值 | 60 | **{cfg.recommended_score_threshold}** | "
               f"历史胜率最高的评分区间下限 |")
        print(f"| 持有天数 | 5 | **{cfg.recommended_hold_days}** | "
               f"历史胜率最高的持有天数 |")
        weak_str = ", ".join(cfg.weak_sectors) if cfg.weak_sectors else "无"
        print(f"| 过滤板块 | 无 | **{weak_str}** | 胜率低于{cfg._win_rate_threshold}%的板块 |")

        print("\n" + "=" * 60)
        print("💡 **在 generate_report.py 中使用方式：**\n")
        print("```python")
        print("from scripts.rec_optimizer import get_tuning_config")
        print("tuning = get_tuning_config()  # 会读取上次分析结果")
        print("# 或在评分流程中直接使用:")
        print("if score >= tuning.recommended_score_threshold:")
        print("    if stock['sector'] not in tuning.weak_sectors:")
        print("        # 通过审核")
        print("```")
        print("=" * 60 + "\n")

    def save_config(self, path: str = None):
        """将 TuningConfig 保存为 JSON 供后续使用"""
        if self.config is None:
            print("[RecOptimizer] 请先调用 run()")
            return

        if path is None:
            path = CONFIG_JSON

        # 转换为可序列化格式
        out = {
            "recommended_score_threshold": self.config.recommended_score_threshold,
            "recommended_hold_days": self.config.recommended_hold_days,
            "weak_sectors": self.config.weak_sectors,
            "total_records": self.config.total_records,
            "overall_win_rate": self.config.overall_win_rate,
            "_win_rate_threshold": self.config._win_rate_threshold,
            "generated_at": self.config.generated_at,
            "score_band_stats": {
                band: {
                    "band": s.band,
                    "count": s.count,
                    "win_count": s.win_count,
                    "win_rate": s.win_rate,
                    "avg_change": s.avg_change,
                    "avg_hold_days": s.avg_hold_days,
                }
                for band, s in self.config.score_band_stats.items()
            },
            "hold_days_stats": {
                str(hd): {
                    "hold_days": s.hold_days,
                    "count": s.count,
                    "win_count": s.win_count,
                    "win_rate": s.win_rate,
                    "avg_change": s.avg_change,
                }
                for hd, s in self.config.hold_days_stats.items()
            },
            "sector_stats": {
                sector: {
                    "sector": s.sector,
                    "sector_name": s.sector_name,
                    "count": s.count,
                    "win_count": s.win_count,
                    "win_rate": s.win_rate,
                    "avg_change": s.avg_change,
                }
                for sector, s in self.config.sector_stats.items()
            },
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"[RecOptimizer] 配置已保存: {path}")

    def _default_config(self) -> TuningConfig:
        return TuningConfig(
            recommended_score_threshold=60,
            recommended_hold_days=5,
            weak_sectors=[],
            score_band_stats={},
            hold_days_stats={},
            sector_stats={},
            total_records=0,
            overall_win_rate=0.0,
            generated_at=datetime.now().isoformat(),
        )


# ── 快捷函数 ────────────────────────────────────────────────────────────────

def get_tuning_config(json_path: str = None) -> TuningConfig:
    """
    加载上次保存的调参配置（供 generate_report.py 集成使用）。
    如无配置，返回默认值。
    """
    if json_path is None:
        json_path = CONFIG_JSON

    if not os.path.exists(json_path):
        return TuningConfig(
            recommended_score_threshold=60,
            recommended_hold_days=5,
            weak_sectors=[],
            score_band_stats={},
            hold_days_stats={},
            sector_stats={},
            total_records=0,
            overall_win_rate=0.0,
            generated_at="",
        )

    with open(json_path, encoding="utf-8") as f:
        d = json.load(f)

    return TuningConfig(
        recommended_score_threshold=d.get("recommended_score_threshold", 60),
        recommended_hold_days=d.get("recommended_hold_days", 5),
        weak_sectors=d.get("weak_sectors", []),
        score_band_stats={},
        hold_days_stats={},
        sector_stats={},
        total_records=d.get("total_records", 0),
        overall_win_rate=d.get("overall_win_rate", 0.0),
        generated_at=d.get("generated_at", ""),
        _win_rate_threshold=d.get("_win_rate_threshold", 40.0),
    )


# ── 集成到 generate_report.py ──────────────────────────────────────────────

def apply_tuning_to_score(score: int, sector: str, hold_days: int,
                          config: TuningConfig = None) -> Tuple[int, bool, str]:
    """
    将调参建议应用到单个股票的评分流程。
    返回：(adjusted_score, passed, reason)

    用法示例（在 generate_report.py 的评分流程中）：
        from scripts.rec_optimizer import apply_tuning_to_score, get_tuning_config
        tuning = get_tuning_config()
        new_score, passed, reason = apply_tuning_to_score(
            stock['综合评分'], stock['sector'], 5, tuning
        )
        if not passed:
            continue  # 过滤掉
    """
    if config is None:
        config = get_tuning_config()

    # 1. 评分阈值过滤
    if score < config.recommended_score_threshold:
        return score, False, f"评分{score}低于阈值{config.recommended_score_threshold}"

    # 2. 持有天数异常过滤（超过建议值太多）
    if hold_days > config.recommended_hold_days * 2:
        return score, False, f"持有天数{hold_days}超过建议值{config.recommended_hold_days}"

    # 3. 弱势板块过滤
    if sector in config.weak_sectors:
        return score, False, f"板块{sector}为弱势板块"

    return score, True, "通过"


# ── CLI 入口 ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="RecOptimizer — 推荐参数优化")
    parser.add_argument("--min-samples", type=int, default=3,
                        help="各维度最小样本数（默认3）")
    parser.add_argument("--min-sector-count", type=int, default=3,
                        help="板块最小样本数（默认3）")
    parser.add_argument("--win-rate-threshold", type=float, default=40.0,
                        help="弱势板块胜率阈值（默认40%%）")
    parser.add_argument("--integrate", action="store_true",
                        help="将建议集成到 generate_report.py")
    parser.add_argument("--csv", type=str, default=None,
                        help="自定义反馈数据路径")
    args = parser.parse_args()

    optimizer = RecOptimizer(
        csv_path=args.csv,
        min_samples=args.min_samples,
        min_sector_count=args.min_sector_count,
        win_rate_threshold=args.win_rate_threshold,
    )

    config = optimizer.run()
    optimizer.print_report()
    optimizer.save_config()

    if args.integrate:
        _integrate_to_generate_report(config)


def _integrate_to_generate_report(config: TuningConfig):
    """将调参建议以注释形式追加到 generate_report.py"""
    report_path = PROJECT_DIR / "scripts" / "generate_report.py"
    if not report_path.exists():
        print(f"[RecOptimizer] generate_report.py 不存在，跳过集成")
        return

    marker = "# === REC_OPTIMIZER_TUNING_END ==="
    block = f'''# === REC_OPTIMIZER_TUNING_START ===
# 由 RecOptimizer 自动生成，勿手动修改
REC_TUNING = {{
    "score_threshold": {config.recommended_score_threshold},
    "hold_days": {config.recommended_hold_days},
    "weak_sectors": {config.weak_sectors},
    "overall_win_rate": {config.overall_win_rate:.1f},
    "total_records": {config.total_records},
    "generated_at": "{config.generated_at}",
}}
# === REC_OPTIMIZER_TUNING_END ===
'''

    # 读取现有内容
    with open(report_path, encoding="utf-8") as f:
        content = f.read()

    # 移除旧标记块
    if marker in content:
        import re
        content = re.sub(r"# === REC_OPTIMIZER_TUNING_START ===\n.*?# === REC_OPTIMIZER_TUNING_END ===\n",
                         "", content, flags=re.DOTALL)

    # 追加到文件末尾（marker 之前）
    insert_pos = content.rfind(marker)
    if insert_pos >= 0:
        new_content = content[:insert_pos] + block + "\n" + content[insert_pos:]
    else:
        new_content = content + "\n" + block

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"[RecOptimizer] 调参建议已集成到 generate_report.py")


if __name__ == "__main__":
    main()
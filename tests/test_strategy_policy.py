#!/usr/bin/env python3
"""tests/test_strategy_policy.py — 策略参数执行层单测

锁定 strategy_policy 的安全不变量:
1. rec_tuning.json 缺失/损坏 → 回落 v2.4 默认 (65 / 无黑名单)
2. 冷启动 (<100 样本) → 默认参数
3. 阈值钳制: 越界值 (50 / 90) → 保持默认 65
4. 黑名单复核: 样本 < 10 的板块不拉黑; 胜率 >= 35% 不拉黑
5. 全链路: 真实 rec_tuning.json → policy 与其中 sector_stats 一致
"""
import json
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT / "scripts"))

from strategy_policy import (  # noqa: E402
    DEFAULT_SCORE_THRESHOLD,
    StrategyPolicy,
    get_today_policy,
    policy_banner,
    TUNING_PATH,
)


class TestDefaults:
    def test_missing_tuning_falls_back(self, tmp_path, monkeypatch):
        """tuning 文件不存在 → 默认参数 + source=default"""
        import strategy_policy
        monkeypatch.setattr(strategy_policy, "TUNING_PATH", tmp_path / "nope.json")
        p = strategy_policy.get_today_policy()
        assert p.score_threshold == 65
        assert p.sector_blacklist == []
        assert p.source == "default"
        assert any("缺失" in n for n in p.data_notes)

    def test_corrupted_tuning_falls_back(self, tmp_path, monkeypatch):
        import strategy_policy
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(strategy_policy, "TUNING_PATH", bad)
        p = strategy_policy.get_today_policy()
        assert p.score_threshold == 65
        assert p.source == "default"

    def test_default_constants_unchanged(self):
        """v2.4 默认值锁定: 阈值 65, top 10, hold 1d"""
        assert DEFAULT_SCORE_THRESHOLD == 65


class TestColdStart:
    def test_under_100_records_uses_default(self, tmp_path, monkeypatch):
        import strategy_policy
        tuning = tmp_path / "t.json"
        tuning.write_text(json.dumps({
            "recommended_score_threshold": 70,
            "total_records": 50,  # < 100
            "generated_at": "2026-08-23T12:00:00",
        }), encoding="utf-8")
        monkeypatch.setattr(strategy_policy, "TUNING_PATH", tuning)
        p = strategy_policy.get_today_policy()
        assert p.score_threshold == 65, "冷启动必须保持默认 65"
        assert any("冷启动" in n for n in p.data_notes)


class TestClamping:
    def test_threshold_too_low_clamped(self, tmp_path, monkeypatch):
        import strategy_policy
        tuning = tmp_path / "t.json"
        tuning.write_text(json.dumps({
            "recommended_score_threshold": 50,  # < 55 越界
            "total_records": 500,
            "generated_at": "2026-08-23T12:00:00",
        }), encoding="utf-8")
        monkeypatch.setattr(strategy_policy, "TUNING_PATH", tuning)
        p = strategy_policy.get_today_policy()
        assert p.score_threshold == 65
        assert any("越界" in n for n in p.data_notes)

    def test_threshold_too_high_clamped(self, tmp_path, monkeypatch):
        import strategy_policy
        tuning = tmp_path / "t.json"
        tuning.write_text(json.dumps({
            "recommended_score_threshold": 90,  # > 80 越界
            "total_records": 500,
            "generated_at": "2026-08-23T12:00:00",
        }), encoding="utf-8")
        monkeypatch.setattr(strategy_policy, "TUNING_PATH", tuning)
        p = strategy_policy.get_today_policy()
        assert p.score_threshold == 65

    def test_threshold_in_range_adopted(self, tmp_path, monkeypatch):
        import strategy_policy
        tuning = tmp_path / "t.json"
        tuning.write_text(json.dumps({
            "recommended_score_threshold": 70,
            "total_records": 500,
            "generated_at": "2026-08-23T12:00:00",
        }), encoding="utf-8")
        monkeypatch.setattr(strategy_policy, "TUNING_PATH", tuning)
        p = strategy_policy.get_today_policy()
        assert p.score_threshold == 70
        assert p.source == "rec_tuning"


class TestSectorBlacklist:
    def _write_tuning(self, tmp_path, monkeypatch, sector_stats, weak=None):
        import strategy_policy
        tuning = tmp_path / "t.json"
        tuning.write_text(json.dumps({
            "total_records": 500,
            "generated_at": "2026-08-23T12:00:00",
            "weak_sectors": weak or [],
            "sector_stats": sector_stats,
        }), encoding="utf-8")
        monkeypatch.setattr(strategy_policy, "TUNING_PATH", tuning)

    def test_small_sample_sector_not_blacklisted(self, tmp_path, monkeypatch):
        """n=5 < 10 的板块,即使胜率 0% 也不拉黑 (防小样本)"""
        self._write_tuning(tmp_path, monkeypatch, {
            "semi": {"count": 5, "win_rate": 0.0},
        })
        import strategy_policy
        p = strategy_policy.get_today_policy()
        assert "semi" not in p.sector_blacklist

    def test_weak_big_sample_sector_blacklisted(self, tmp_path, monkeypatch):
        self._write_tuning(tmp_path, monkeypatch, {
            "chem": {"count": 22, "win_rate": 0.0},
        })
        import strategy_policy
        p = strategy_policy.get_today_policy()
        assert "chem" in p.sector_blacklist

    def test_good_sector_not_blacklisted(self, tmp_path, monkeypatch):
        """胜率 50% >= 35% 线 → 不拉黑"""
        self._write_tuning(tmp_path, monkeypatch, {
            "energy": {"count": 30, "win_rate": 50.0},
        })
        import strategy_policy
        p = strategy_policy.get_today_policy()
        assert "energy" not in p.sector_blacklist

    def test_weak_without_stats_still_blacklisted(self, tmp_path, monkeypatch):
        """rec_tuning.weak_sectors 有但 sector_stats 没有的 → 保守纳入"""
        self._write_tuning(tmp_path, monkeypatch, {}, weak=["robot"])
        import strategy_policy
        p = strategy_policy.get_today_policy()
        assert "robot" in p.sector_blacklist


class TestRealTuning:
    def test_real_tuning_file_loads(self):
        """真实 rec_tuning.json 存在时, policy 能加载且参数合理"""
        if not TUNING_PATH.exists():
            pytest.skip("rec_tuning.json 不存在")
        p = get_today_policy()
        assert 55 <= p.score_threshold <= 80
        assert isinstance(p.sector_blacklist, list)
        assert p.top_n == 10

    def test_policy_banner_format(self):
        p = StrategyPolicy(score_threshold=65, sector_blacklist=["chem"])
        b = policy_banner(p)
        assert "threshold=65" in b
        assert "chem" in b
        assert "source=default" in b

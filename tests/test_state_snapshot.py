#!/usr/bin/env python3
"""
tests/test_state_snapshot.py — data/state/latest.json 快照层单测

v2026-11-16: 锁定三件事
  ① 快照结构完整 (各段独立, 失败段写 error 不拖垮整份)
  ② 写入是**原子**的 (tmp + os.replace), 写后校验, 失败能从 .bak 还原
  ③ 数值字段显式判空 (0 / 0.0 是合法值, 不能被 falsy 吞成缺失) → 教训 (ae)
"""
import json
import os
import sys

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))

import write_state_snapshot as wss


class TestSnapshotStructure:
    """① 结构: 任一段失败都不影响其余段"""

    def test_all_sections_present(self, monkeypatch):
        """五段都要在 (即使内容是 error)"""
        monkeypatch.setattr(wss, "collect_market", lambda *a, **k: {"score": 55, "label": "分歧"})
        monkeypatch.setattr(wss, "collect_pool", lambda *a, **k: {"codes": ["600519"], "count": 1})
        monkeypatch.setattr(wss, "collect_strategy", lambda *a, **k: {"score_threshold": 60})
        monkeypatch.setattr(wss, "collect_feedback", lambda *a, **k: {"total": 10, "win_rate": 70.0})
        monkeypatch.setattr(wss, "collect_eastmoney", lambda *a, **k: {"groups": {}})
        snap = wss.build_snapshot()
        for key in ("market", "pool", "strategy", "feedback", "eastmoney"):
            assert key in snap, f"缺段落 {key}"
        assert snap["sections_ok"] is True
        assert snap["errors"] == {}
        assert snap["schema_version"] == 1
        assert snap["generated_at"]

    def test_one_section_failure_is_isolated(self, monkeypatch):
        """一段抛异常 → 只有该段带 error, 其余照常产出"""
        def boom():
            raise RuntimeError("市场情绪接口挂了")

        monkeypatch.setattr(wss, "collect_market", boom)
        monkeypatch.setattr(wss, "collect_pool", lambda *a, **k: {"codes": [], "count": 0})
        monkeypatch.setattr(wss, "collect_strategy", lambda *a, **k: {"score_threshold": 60})
        monkeypatch.setattr(wss, "collect_feedback", lambda *a, **k: {"total": 1})
        monkeypatch.setattr(wss, "collect_eastmoney", lambda *a, **k: {"groups": {}})
        snap = wss.build_snapshot()
        assert snap["sections_ok"] is False
        assert "market" in snap["errors"]
        assert "RuntimeError" in snap["errors"]["market"]
        assert snap["market"]["error"]
        # 其余段不受影响
        assert snap["pool"]["count"] == 0
        assert snap["strategy"]["score_threshold"] == 60


class TestFalsyZero:
    """③ 数值显式判空: 0 是合法值"""

    def test_zero_preserved(self):
        assert wss._num(0) == 0
        assert wss._num(0.0) == 0.0
        assert wss._num(None) is None
        # 关键: 不能变成 "" 或 None
        assert wss._num(0) != ""
        assert wss._num(0) is not None

    def test_zero_threshold_survives_snapshot(self, monkeypatch):
        """阈值为 0 时必须原样保留 (旧代码 `x or ""` 会吞掉)"""
        monkeypatch.setattr(wss, "collect_strategy", lambda *a, **k: {"score_threshold": 0})
        monkeypatch.setattr(wss, "collect_market", lambda *a, **k: {})
        monkeypatch.setattr(wss, "collect_pool", lambda *a, **k: {})
        monkeypatch.setattr(wss, "collect_feedback", lambda *a, **k: {})
        monkeypatch.setattr(wss, "collect_eastmoney", lambda *a, **k: {})
        snap = wss.build_snapshot()
        assert snap["strategy"]["score_threshold"] == 0


class TestAtomicWrite:
    """② 原子写 + 写后校验"""

    def test_write_is_atomic_and_valid(self, tmp_path, monkeypatch):
        target = tmp_path / "latest.json"
        monkeypatch.setattr(wss, "collect_market", lambda: {"score": 1})
        monkeypatch.setattr(wss, "collect_pool", lambda: {})
        monkeypatch.setattr(wss, "collect_strategy", lambda: {})
        monkeypatch.setattr(wss, "collect_feedback", lambda: {})
        monkeypatch.setattr(wss, "collect_eastmoney", lambda: {})
        path, snap = wss.write_snapshot(path=target)
        assert path == target
        assert target.exists()
        # 落盘内容必须是合法 JSON
        with open(target, encoding="utf-8") as f:
            reloaded = json.load(f)
        assert reloaded["generated_at"] == snap["generated_at"]
        # 原子写: 不留 tmp 文件
        assert not (tmp_path / "latest.json.tmp").exists()

    def test_backup_created_on_second_write(self, tmp_path, monkeypatch):
        target = tmp_path / "latest.json"
        for getter in ("collect_market", "collect_pool", "collect_strategy",
                       "collect_feedback", "collect_eastmoney"):
            monkeypatch.setattr(wss, getter, lambda *a, **k: {})
        wss.write_snapshot(path=target)
        assert not (tmp_path / "latest.json.bak").exists()
        wss.write_snapshot(path=target)
        assert (tmp_path / "latest.json.bak").exists()

    def test_existing_file_survives_failed_write(self, tmp_path, monkeypatch):
        """写失败不能毁掉上一份好文件 (8/7 JSON dump fp= 陷阱的根治)"""
        target = tmp_path / "latest.json"
        for getter in ("collect_market", "collect_pool", "collect_strategy",
                       "collect_feedback", "collect_eastmoney"):
            monkeypatch.setattr(wss, getter, lambda *a, **k: {})
        wss.write_snapshot(path=target)
        with open(target, encoding="utf-8") as f:
            good = json.load(f)

        # 让写入失败: data 里放不可序列化的对象
        monkeypatch.setattr(wss, "build_snapshot", lambda days=30: {"bad": object()})
        with pytest.raises(Exception):
            wss.write_snapshot(path=target)

        # 原文件必须完好
        with open(target, encoding="utf-8") as f:
            after = json.load(f)
        assert after == good


class TestReadJson:
    """_read_json 失败返回 error 而不是空 dict (教训 u)"""

    def test_missing_file(self, tmp_path):
        r = wss._read_json(tmp_path / "nope.json")
        assert "error" in r

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.json"
        p.write_text("")
        r = wss._read_json(p)
        assert "error" in r

    def test_valid(self, tmp_path):
        p = tmp_path / "ok.json"
        p.write_text(json.dumps({"a": 1}), encoding="utf-8")
        assert wss._read_json(p) == {"a": 1}

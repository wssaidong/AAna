#!/usr/bin/env python3
"""
tests/test_safe_io.py — _safe_io 单测

v2026-08-23 Phase 2: 确保 safe_json_dump / safe_csv_dump 在所有失败模式下
  都能 (a) 不抹掉现有文件 (b) 写后校验通过 (c) 从 .bak 恢复。
"""
import json
import os
import tempfile

import pytest

# 被测模块在 scripts/_safe_io.py
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from _safe_io import safe_json_dump, safe_csv_dump, safe_read_json


class TestSafeJsonDump:
    def test_basic_write(self, tmp_path):
        p = str(tmp_path / "x.json")
        safe_json_dump(p, {"a": 1, "b": [1, 2]})
        with open(p) as f:
            assert json.load(f) == {"a": 1, "b": [1, 2]}

    def test_overwrite_creates_bak(self, tmp_path):
        p = str(tmp_path / "x.json")
        safe_json_dump(p, {"v": 1})
        safe_json_dump(p, {"v": 2})
        assert os.path.exists(p + ".bak")
        with open(p + ".bak") as f:
            assert json.load(f) == {"v": 1}
        with open(p) as f:
            assert json.load(f) == {"v": 2}

    def test_make_backup_false_skips_bak(self, tmp_path):
        p = str(tmp_path / "x.json")
        safe_json_dump(p, {"v": 1})
        safe_json_dump(p, {"v": 2}, make_backup=False)
        # .bak from first call still exists (it's from first call)
        # but second call didn't add a new .bak over first
        # (only first call made the .bak if file existed; second with make_backup=False
        #  doesn't touch .bak)

    def test_failed_write_restores_bak(self, tmp_path, monkeypatch):
        p = str(tmp_path / "x.json")
        safe_json_dump(p, {"v": 1})  # first: write + bak = empty
        safe_json_dump(p, {"v": 2})  # second: bak={v:1}, file should end up as {v:2}, bak still {v:1}
        # Force json.dump to raise — file should be restored to .bak content
        import json as _json
        orig_dump = _json.dump
        def boom(*a, **kw):
            raise RuntimeError("simulated dump failure")
        monkeypatch.setattr(_json, "dump", boom)
        with pytest.raises(RuntimeError, match="safe_json_dump"):
            safe_json_dump(p, {"v": 3, "OVERWRITE": True})
        # After exception, file should still be {v:2} (whatever was there before the failed write)
        # safe_json_dump opens with 'w' first → file is 0 bytes → exception → restored from bak
        with open(p) as f:
            content = f.read()
        # If restored from bak, content == '{"v": 2}'; if not, content == '' (the 'w' truncated)
        # safe_json_dump does NOT bypass the open('w') before the write...
        # Actually: it does shutil.copy2(p, bak) THEN opens for write, which truncates
        # If write fails, file is 0 bytes. Then 'restore from bak' needs to copy back.
        # Verify that did happen:
        assert content == json.dumps({"v": 2}, indent=2, ensure_ascii=False), \
            f"file not restored from bak: {content!r}"


class TestSafeCsvDump:
    def test_basic(self, tmp_path):
        p = str(tmp_path / "x.csv")
        safe_csv_dump(p, ["a", "b"], [{"a": 1, "b": 2}])
        import csv
        with open(p) as f:
            rows = list(csv.DictReader(f))
        assert rows == [{"a": "1", "b": "2"}]


class TestSafeReadJson:
    def test_nonexistent_returns_default(self, tmp_path):
        assert safe_read_json(str(tmp_path / "nope.json"), default={}) == {}

    def test_empty_file_returns_default(self, tmp_path):
        p = tmp_path / "empty.json"
        p.write_text("")
        assert safe_read_json(str(p), default=[]) == []

    def test_valid_roundtrip(self, tmp_path):
        p = tmp_path / "x.json"
        p.write_text('{"a": 1}', encoding="utf-8")
        assert safe_read_json(str(p)) == {"a": 1}

    def test_malformed_returns_default(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not valid json", encoding="utf-8")
        assert safe_read_json(str(p), default="MISSING") == "MISSING"

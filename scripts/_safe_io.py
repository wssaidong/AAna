#!/usr/bin/env python3
"""
scripts/_safe_io.py — 防丢失式 JSON / CSV 写入 helper

v2026-08-23 Phase 2: 防 8/7 JSON dump `fp=` 双重参数陷阱(导致 groups.json 被 truncate 为 0 字节)。

核心模式: 写前 `.bak` 备份 + try/except 失败恢复 + 写后 load 校验。
任何"groups.json / state.json / rec_feedback.csv" 这类**真理之源**的写操作都必须走这里，
不允许手工 `open(path, 'w').write(...)`。

用法:
    from _safe_io import safe_json_dump, safe_csv_dump

    safe_json_dump('/path/to/groups.json', data)         # 备份+写+校验
    safe_json_dump('/path/to/x.json', data, make_backup=False)  # 不备份(快路径)

设计目标:
1. **绝不**让一次失败的写抹掉现有文件
2. `.bak` 永远从上一次成功状态恢复
3. 写后 load 校验: file 不是合法 JSON 立即 raise,从 .bak 还原
4. 零依赖 (std lib only)
"""
import csv
import json
import os
import shutil
from typing import Any, Iterable, Mapping


def safe_json_dump(path: str, data: Any, make_backup: bool = True, indent: int = 2) -> None:
    """
    Write data to JSON file safely:
    1. 如果 make_backup 且 path 存在 → .bak 备份 (shutil.copy2 保留 mtime)
    2. 打开 path 'w' 写新内容
    3. 写完后用 json.load() 校验文件 roundtrip 合法
    4. 任一步骤 raise → 从 .bak 还原 + 再次 raise

    ⚠️ 只用位置参数传 fp，禁止 fp= 关键字（双重参数陷阱导致 file truncate to 0 bytes）。
    """
    path = os.path.abspath(path)
    bak = path + ".bak"
    has_bak = False

    if make_backup and os.path.exists(path):
        shutil.copy2(path, bak)
        has_bak = True

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)  # ⚠️ 位置参数 only
        # 写后校验
        with open(path, encoding="utf-8") as f:
            json.load(f)
    except Exception as e:
        if has_bak and os.path.exists(bak):
            shutil.copy2(bak, path)
        raise RuntimeError(
            f"safe_json_dump({path}) failed: {type(e).__name__}: {e}"
            + (" — restored from .bak" if has_bak else "")
        ) from e


def safe_csv_dump(
    path: str,
    fields: Iterable[str],
    rows: Iterable[Mapping[str, Any]],
    make_backup: bool = True,
) -> None:
    """
    Write rows to CSV safely (与 safe_json_dump 同样模式):
    1. 备份 → 写 → 校验 → 失败恢复。
    2. 用 csv.DictWriter,extrasaction='ignore' 多余字段不写。
    """
    import tempfile

    path = os.path.abspath(path)
    bak = path + ".bak"
    has_bak = False
    tmp = path + ".tmp"

    if make_backup and os.path.exists(path):
        shutil.copy2(path, bak)
        has_bak = True

    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(fields), extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        # 校验 (文件存在 + 非 0 字节)
        if os.path.getsize(tmp) == 0:
            raise RuntimeError(f"safe_csv_dump wrote 0 bytes to {tmp}")
        # 原子替换
        os.replace(tmp, path)
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        if has_bak and os.path.exists(bak):
            shutil.copy2(bak, path)
        raise RuntimeError(
            f"safe_csv_dump({path}) failed: {type(e).__name__}: {e}"
            + (" — restored from .bak" if has_bak else "")
        ) from e


def safe_read_json(path: str, default: Any = None) -> Any:
    """
    读 JSON 失败（file not found / 0 bytes / malformed）→ 返回 default，不抛。
    与 safe_json_dump 配合 = "open → mutate → write" 模式的安全版。
    """
    try:
        if not os.path.exists(path):
            return default
        if os.path.getsize(path) == 0:
            return default
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


# ─────────────────────────────────────────────────────
# Self-test (可以在脚本里 `python3 _safe_io.py` 直接跑)
# ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    import tempfile

    print("🧪 _safe_io self-test...")
    with tempfile.TemporaryDirectory() as td:
        # Test 1: 普通写
        p = os.path.join(td, "x.json")
        safe_json_dump(p, {"a": 1, "b": [2, 3]})
        with open(p) as f:
            assert json.load(f) == {"a": 1, "b": [2, 3]}, "Test 1 FAIL"
        print("  ✅ safe_json_dump 正常写")

        # Test 2: 二次写 (有 .bak)
        safe_json_dump(p, {"a": 99})
        with open(p) as f:
            assert json.load(f) == {"a": 99}, "Test 2 FAIL"
        assert os.path.exists(p + ".bak"), "Test 2 FAIL: no .bak"
        with open(p + ".bak") as f:
            assert json.load(f) == {"a": 1, "b": [2, 3]}, "Test 2 FAIL: bak wrong"
        print("  ✅ safe_json_dump 二次写 + .bak 保留旧")

        # Test 3: safe_csv_dump
        cp = os.path.join(td, "x.csv")
        safe_csv_dump(cp, ["a", "b"], [{"a": 1, "b": 2}, {"a": 3, "b": 4}])
        with open(cp) as f:
            rows = list(csv.DictReader(f))
        assert rows == [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}], f"Test 3 FAIL: {rows}"
        print("  ✅ safe_csv_dump 正常写")

        # Test 4: safe_read_json fallback
        empty = os.path.join(td, "empty.json")
        open(empty, "w").close()
        assert safe_read_json(empty, default={}) == {}, "Test 4 FAIL"
        assert safe_read_json("/tmp/nonexistent.json", default="MISSING") == "MISSING", "Test 4 FAIL"
        print("  ✅ safe_read_json 0 bytes / 不存在 走 default")

    print()
    print("=" * 50)
    print("✅ _safe_io self-test 4/4 PASS")
    print("=" * 50)

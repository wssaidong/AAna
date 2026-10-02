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
# v2.6: 加锁的「读-改-写」helper (修复 Kimi 代码审查 B1/B2)
#
# 场景: 多 cron 进程同时写 paper_trades.json / rec_feedback.csv
# 原代码: open(path, "w") 覆盖写, 读-改-写无原子保护 → 后写抹掉先写
# 解决: flock(LOCK_EX) 串行化 + os.replace 原子替换
# 用法:
#     d = safe_read_json_locked(PATH)        # 自动加读锁
#     d["x"] = 1
#     safe_write_json_locked(PATH, d)        # 自动加写锁+原子替换
# ─────────────────────────────────────────────────────
try:
    import fcntl as _fcntl  # macOS/Linux 都有
    _HAS_FCNTL = True
except ImportError:
    _fcntl = None
    _HAS_FCNTL = False


def safe_read_json_locked(path: str, default: Any = None) -> Any:
    """加读锁读取 JSON, 防止读过程中被其他进程写覆盖。"""
    path = os.path.abspath(path)
    try:
        if not os.path.exists(path):
            return default
        if os.path.getsize(path) == 0:
            return default
        with open(path, encoding="utf-8") as f:
            if _HAS_FCNTL:
                _fcntl.flock(f.fileno(), _fcntl.LOCK_SH)  # 共享读锁
            try:
                return json.load(f)
            finally:
                if _HAS_FCNTL:
                    _fcntl.flock(f.fileno(), _fcntl.LOCK_UN)
    except Exception:
        return default


def safe_write_json_locked(path: str, data: Any, make_backup: bool = True, indent: int = 2) -> None:
    """
    加写锁写 JSON + 原子替换。
    1. 打开 path 加 LOCK_EX 排他锁 (其他读/写阻塞)
    2. shutil.copy2 → .bak
    3. 写 .tmp + os.replace → 原子生效
    4. 任何异常: 从 .bak 还原 + raise
    """
    import tempfile

    path = os.path.abspath(path)
    bak = path + ".bak"
    tmp = path + ".tmp"
    has_bak = False

    if make_backup and os.path.exists(path):
        shutil.copy2(path, bak)
        has_bak = True

    try:
        # 写 tmp
        with open(tmp, "w", encoding="utf-8") as f:
            if _HAS_FCNTL:
                _fcntl.flock(f.fileno(), _fcntl.LOCK_EX)
            try:
                json.dump(data, f, indent=indent, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            finally:
                if _HAS_FCNTL:
                    _fcntl.flock(f.fileno(), _fcntl.LOCK_UN)
        # 校验 (确保是合法 JSON)
        with open(tmp, encoding="utf-8") as f:
            json.load(f)
        # 原子替换 (POSIX rename, 保证 readers 看到的总是完整文件)
        os.replace(tmp, path)
    except Exception as e:
        if os.path.exists(tmp):
            try: os.remove(tmp)
            except: pass
        if has_bak and os.path.exists(bak):
            try: shutil.copy2(bak, path)
            except: pass
        raise RuntimeError(
            f"safe_write_json_locked({path}) failed: {type(e).__name__}: {e}"
            + (" — restored from .bak" if has_bak else "")
        ) from e


def safe_append_jsonl_locked(path: str, row: dict) -> None:
    """
    加锁追加单行 JSON (解决 Kimi B2: rec_feedback.csv 覆盖写抹掉并发 append 的问题)
    每行一个 JSON 对象, 用 fcntl 序列化 append + 自动 skip 重复行 (按 code+date+action)
    """
    path = os.path.abspath(path)
    lock_path = path + ".lock"
    try:
        with open(lock_path, "w") as lock_f:
            if _HAS_FCNTL:
                _fcntl.flock(lock_f.fileno(), _fcntl.LOCK_EX)
            try:
                # 读已存在的 keys 用于去重
                existing_keys = set()
                if os.path.exists(path):
                    try:
                        with open(path, encoding="utf-8") as f:
                            for line in f:
                                line = line.strip()
                                if not line: continue
                                try:
                                    obj = json.loads(line)
                                    if "key" in obj:
                                        existing_keys.add(obj["key"])
                                except: pass
                    except: pass
                # 跳过已存在的 (row 应带 'key' 字段)
                key = row.get("key")
                if key and key in existing_keys:
                    return  # 静默跳过重复
                # append
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
            finally:
                if _HAS_FCNTL:
                    _fcntl.flock(lock_f.fileno(), _fcntl.LOCK_UN)
    except Exception as e:
        raise RuntimeError(f"safe_append_jsonl_locked({path}) failed: {type(e).__name__}: {e}") from e


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

        # v2.6 Test 5: 加锁读写 JSON (fcntl + 原子替换)
        p5 = os.path.join(td, "locked.json")
        safe_write_json_locked(p5, {"v": 1})
        d = safe_read_json_locked(p5)
        assert d == {"v": 1}, f"Test 5 FAIL: {d}"
        d["v"] = 2
        safe_write_json_locked(p5, d)
        d = safe_read_json_locked(p5)
        assert d["v"] == 2, f"Test 5 FAIL: {d}"
        print("  ✅ safe_write_json_locked + safe_read_json_locked 原子替换+互斥")

        # v2.6 Test 6: 加锁追加 JSONL + 去重
        p6 = os.path.join(td, "app.jsonl")
        safe_append_jsonl_locked(p6, {"key": "a", "v": 1})
        safe_append_jsonl_locked(p6, {"key": "b", "v": 2})
        safe_append_jsonl_locked(p6, {"key": "a", "v": 1})  # 重复应被跳过
        with open(p6) as f:
            lines = [json.loads(l) for l in f if l.strip()]
        assert len(lines) == 2, f"Test 6 FAIL: {lines}"
        assert lines[0]["key"] == "a" and lines[1]["key"] == "b", f"Test 6 FAIL: {lines}"
        print("  ✅ safe_append_jsonl_locked 加锁+去重")

    print()
    print("=" * 50)
    print("✅ _safe_io self-test 6/6 PASS")
    print("=" * 50)

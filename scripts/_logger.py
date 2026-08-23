#!/usr/bin/env python3
"""
scripts/_logger.py — 集中式异常日志 helper

v2026-08-23 Phase 3-2: 解决 history 多处 `except Exception: pass` (silent swallow)
散落在 scripts/ + analysis_tools/ 的问题。

设计目标:
1. 不改变现有 except Exception: pass 的"不抛"语义（保住脏数据下的可恢复性）
2. 加 stderr 日志 + 可选写 file → 提供事后追溯
3. 零侵入: 一行 `from _logger import silenced` 替代原 except 块

用法:
    from _logger import silenced

    # 旧:
    try:
        risky()
    except Exception:
        pass

    # 新:
    try:
        risky()
    except Exception as e:
        silenced("daily_screen.py:L75 risky()", e)
"""
import json
import os
import sys
import traceback
from datetime import datetime

LOG_FILE = os.path.expanduser("~/.hermes/state/aana/runtime_errors.log")
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)


def silenced(label: str, exc: BaseException, *, level: str = "WARN",
             log_file: str = LOG_FILE) -> None:
    """
    静默吞错但写 stderr + log_file。

    Args:
        label:  简短描述 (e.g. "daily_screen.py:75 get_kline")
        exc:    catch 到的异常
        level:  WARN / ERROR / INFO
        log_file: 默认写到 ~/.hermes/state/aana/runtime_errors.log
    """
    ts = datetime.now().isoformat(timespec="seconds")
    msg = f"[{ts}] {level} {label}: {type(exc).__name__}: {exc}"
    print(msg, file=sys.stderr)
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        # 日志写失败也吞,但不要递归
        pass


def log_event(label: str, data: dict | None = None, *,
              level: str = "INFO", log_file: str = LOG_FILE) -> None:
    """普通事件日志（不抛错，用来 trace 数据流）"""
    ts = datetime.now().isoformat(timespec="seconds")
    payload = {"ts": ts, "level": level, "label": label}
    if data:
        payload["data"] = data
    msg = json.dumps(payload, ensure_ascii=False)
    print(msg, file=sys.stderr)
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    # Self-test
    silenced("self_test", ValueError("hello"))
    log_event("self_test_event", {"foo": "bar"})
    print(f"✅ log written to {LOG_FILE}")
    print("Last 5 lines:")
    with open(LOG_FILE) as f:
        lines = f.readlines()
    for line in lines[-5:]:
        print(f"  {line.rstrip()}")

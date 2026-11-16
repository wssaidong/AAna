#!/usr/bin/env python3
"""
scripts/sync_afternoon_pp.py — 尾盘 PP 组「只放 1 只」的同步器

v2026-11-16 新增:
  背景: 尾盘 cron prompt (job 49bbdf3c555a) 步骤 6 在 **prompt 里手写**了
        create_group / add_stocks / gstkinfos / groups.json 写回, 而且写着
        「删除 gid 内所有现有股票」—— **东财没有单股删除 API**
        (delstock/delstk 均返非 JSON, 10-26 / 10-28 实测), 只能整组退役重建。
        prompt 层手写副作用 = 9/1 铁律说的「配置即代码盲区」, 也是 10-28
        「尾盘把缓存写进裸日期 key → 覆盖早盘组条目」的温床。
  本脚本把这套逻辑收到脚本层, prompt 只负责「选出哪只股票」。

零推荐短路 (9/1 铁律):
  没有 --code → **不碰任何东财 API**, 直接退出 (exit 1)。

退出码:
  0 = 同步成功且服务端复核通过
  1 = 0 推荐短路 (未调用任何东财 API)
  2 = 异常 / 复核失败

用法:
  python3 scripts/sync_afternoon_pp.py --code 600519
  python3 scripts/sync_afternoon_pp.py --code 600519 --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
GROUPS_JSON = Path.home() / ".hermes/skills/a-stock/eastmoney-portfolio-api/groups.json"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

EXIT_OK = 0
EXIT_ZERO = 1
EXIT_ERROR = 2


def _group_codes(ep: Any, gid: Any) -> list[str]:
    """取组内真实股票代码 (东财 stkinfolist 只有 security 字段)。"""
    stocks = ep.get_group_stocks(gid)
    return [s["security"].split("$")[1] for s in stocks if "$" in s.get("security", "")]


def _load_groups() -> dict:
    """读 groups.json 缓存 (损坏时返回空 dict, 不抛)。"""
    try:
        if not GROUPS_JSON.exists() or GROUPS_JSON.stat().st_size == 0:
            return {}
        with open(GROUPS_JSON, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _write_groups(groups: dict) -> None:
    """写回 groups.json: 原子替换 + 写后校验 (8/24 双 SOP 的写侧)。"""
    from _safe_io import safe_write_json_locked

    GROUPS_JSON.parent.mkdir(parents=True, exist_ok=True)
    safe_write_json_locked(str(GROUPS_JSON), groups)


def sync_single_stock(code: str, name: str, ep: Any = None, log=print) -> dict:
    """
    把 PP 组合同步成**恰好 1 只** = code。

    返回 payload: {status, code, name, gid, verified, action, existing, error}
    status ∈ synced / idempotent / error
    """
    payload: dict = {"status": "error", "code": code, "name": name}
    if ep is None:
        import eastmoney_portfolio as ep  # noqa: N813

    groups = _load_groups()
    entry = groups.get(name) if isinstance(groups.get(name), dict) else None
    existing_gid = entry.get("gid") if entry else None

    try:
        existing_codes = _group_codes(ep, existing_gid) if existing_gid else []
    except Exception as exc:  # noqa: BLE001
        payload["error"] = f"读取组内股票失败: {type(exc).__name__}: {exc}"
        return payload

    # ── 幂等: 组内已经是这唯一 1 只 → 不做任何写操作 ──
    if existing_gid and existing_codes == [code]:
        payload.update(status="idempotent", gid=existing_gid, verified=True,
                       action="复用", existing=existing_codes)
        return payload

    # ── 内容不一致 → 整组退役重建 (东财无单股删除 API) ──
    if existing_gid and existing_codes != [code]:
        log(f"  [组内容不一致] 组内 {len(existing_codes)} 只 != 目标 1 只 → 整组退役重建")
        log(f"    组内原: {existing_codes}")
        try:
            if not ep.delete_group(existing_gid):
                payload["error"] = f"退役组合 gid={existing_gid} 失败"
                return payload
        except Exception as exc:  # noqa: BLE001
            payload["error"] = f"退役异常: {type(exc).__name__}: {exc}"
            return payload
        time.sleep(3)
        groups.pop(name, None)

    # ── 建组 + 写入 ──
    try:
        gid = ep.get_or_create_group(name)
    except Exception as exc:  # noqa: BLE001
        payload["error"] = f"建组异常: {type(exc).__name__}: {exc}"
        return payload
    if gid is None:
        payload["error"] = "get_or_create_group 返回 None"
        return payload

    try:
        added = ep.add_stocks(gid, [code])
    except Exception as exc:  # noqa: BLE001
        payload["error"] = f"add_stocks 异常: {type(exc).__name__}: {exc}"
        return payload

    # add_stocks 返回 int (不是 dict) —— 见教训 (8/14 add_stocks 返回 int / api_call tuple)
    if isinstance(added, int):
        added_n = added
    else:
        try:
            added_n = int(added.get("added", 0))
        except Exception:  # noqa: BLE001
            added_n = 0
    time.sleep(1)

    # ── 服务端复核: 组内必须恰好 1 只且等于目标 ──
    try:
        final = _group_codes(ep, gid)
    except Exception as exc:  # noqa: BLE001
        payload.update(gid=gid, added=added_n, error=f"复核读取失败: {type(exc).__name__}: {exc}")
        return payload
    if final != [code]:
        payload.update(gid=gid, added=added_n, existing=final, verified=False,
                       error=f"复核失败: 组内 {final} != 目标 [{code}]")
        return payload

    # ── 写回缓存: 用服务端真实 codes + 精确匹配断言 (SOP-B) ──
    try:
        groups[name] = {"gid": gid, "date": name.rstrip("PP"), "stocks": list(final)}
        _write_groups(groups)
    except Exception as exc:  # noqa: BLE001
        payload.update(gid=gid, added=added_n, existing=final,
                       error=f"缓存写回失败 (服务端已正确): {type(exc).__name__}: {exc}")
        return payload

    payload.update(status="synced", gid=gid, verified=True, added=added_n,
                   action="退役重建" if existing_gid else "新建", existing=final)
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="尾盘 PP 组单只同步")
    ap.add_argument("--code", default="", help="要同步的唯一股票代码 (6 位数字)")
    ap.add_argument("--date", default="", help="日期 YYYYMMDD, 默认今天")
    ap.add_argument("--name", default="", help="组合名, 默认 {date}PP")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = ap.parse_args(argv)

    from datetime import datetime

    date_str = args.date or datetime.now().strftime("%Y%m%d")
    name = args.name or f"{date_str}PP"
    code = (args.code or "").strip()

    # ── 0 推荐短路: 没有代码 → 不碰东财 ──
    if not code:
        msg = "0 推荐短路: 未提供 --code, 不调用任何东财 API"
        if args.json:
            print(json.dumps({"status": "zero_recommend", "message": msg}, ensure_ascii=False))
        else:
            print(f"⚠️ {msg}")
        return EXIT_ZERO

    if not re.fullmatch(r"\d{6}", code):
        msg = f"代码格式非法: {code!r} (应为 6 位数字)"
        if args.json:
            print(json.dumps({"status": "error", "error": msg}, ensure_ascii=False))
        else:
            print(f"❌ {msg}")
        return EXIT_ERROR

    payload = sync_single_stock(code, name)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"同步结果: {payload.get('status')}  gid={payload.get('gid')}  "
              f"verified={payload.get('verified')}  {payload.get('error') or ''}")
    return EXIT_OK if payload.get("status") in ("synced", "idempotent") else EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())

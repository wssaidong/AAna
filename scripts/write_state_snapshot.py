#!/usr/bin/env python3
"""
scripts/write_state_snapshot.py — 生成 data/state/latest.json「当日全景快照」

v2026-11-16 新增:
  目的: 让外部消费者 (Hermes / 人工) 读**一个文件**就能拿到 AAna 当日全景,
        彻底摆脱「解析 markdown 报告」这条脆弱链路。
        背景教训: 2026-11-03「深度分析池表二级标题按日改名 → 盘前池回捞恒 0 行」
                (上游文案改版 → 解析器静默失效 → 下游真实池整段丢失)。
                快照走结构化字段, 不依赖任何报告文案。

设计约束 (逐条对标 AAna 既有教训):
  - 每一段独立 try/except: 某段失败只在该段写 {"error": ...}, 不让整份快照失败
    → 教训 (u): 「静默空 ≠ 正常空」, 失败必须显式可见
  - 写入走 _safe_io.safe_write_json_locked
    (flock + .bak 备份 + tmp 写后校验 + os.replace 原子替换)
  - 只读数据源, 本脚本**不产生任何东财/飞书/组合同副作用**
  - 数值字段显式判空, 不用 `x or ""` 这种 falsy-zero 温床 → 教训 (ae)

用法:
    python3 scripts/write_state_snapshot.py            # 写 data/state/latest.json
    python3 scripts/write_state_snapshot.py --print    # 只打印不落盘
"""
from __future__ import annotations

import json
import os
import re
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
DATA_DIR = PROJECT_ROOT / "data"
STATE_DIR = DATA_DIR / "state"
REPORTS_DIR = PROJECT_ROOT / "reports"
SNAPSHOT_PATH = STATE_DIR / "latest.json"
GROUPS_JSON = Path.home() / ".hermes/skills/a-stock/eastmoney-portfolio-api/groups.json"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _read_json(path: Path) -> dict:
    """读 JSON; 失败返回 {"error": ...} 而不是抛异常或返回空 dict (教训 u)。"""
    try:
        if not path.exists() or path.stat().st_size == 0:
            return {"error": f"文件不存在或为空: {path}"}
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"error": f"顶层不是 dict: {type(data).__name__}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _num(value: Any) -> Any:
    """数值字段显式判空: 只有 None 算缺失, 0 / 0.0 是合法值必须保留 (教训 ae)。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    return value


class _SectionTimeout(Exception):
    """某一段采集超时。"""


def _with_timeout(seconds: int, fn, *args, **kwargs):
    """
    给单个采集函数加硬超时 (SIGALRM)。

    为什么需要: AAna 的数据源会「卡 30-60s 不返回」(datacenter 已挂 76 天),
    cron 步骤被拖住就会整体超时失败 → 必须给每段独立的时间上限。
    """
    if not hasattr(signal, "SIGALRM"):
        return fn(*args, **kwargs)

    def _handler(signum, frame):
        raise _SectionTimeout(f"采集超时 (>{seconds}s)")

    old_handler = signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return fn(*args, **kwargs)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)


def collect_market() -> dict:
    """市场情绪 + 指数概览。取不到时返回带 error 的 dict。"""
    try:
        from market_sentiment import get_market_sentiment

        s = get_market_sentiment()
        if not isinstance(s, dict):
            return {"error": f"get_market_sentiment 返回 {type(s).__name__}"}
        keys = ("score", "label", "zt_count", "dt_count", "avg_change", "index", "date")
        out = {}
        for k in keys:
            if k in s:
                out[k] = _num(s[k]) if not isinstance(s[k], (str, dict, list)) else s[k]
        if not out:
            return {"error": "情绪字典里没有已知字段"}
        return out
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _latest_report() -> Path | None:
    if not REPORTS_DIR.exists():
        return None
    files = sorted(p for p in REPORTS_DIR.glob("*-选股报告.md"))
    return files[-1] if files else None


def collect_pool() -> dict:
    """当日推荐池: 代码来自**权威解析器** parse_top10_from_report, 不自己写正则。"""
    out: dict = {}
    try:
        report = _latest_report()
        if report is None:
            return {"error": "reports/ 下没有 *-选股报告.md"}
        out["report"] = report.name
        from eastmoney_portfolio import parse_top10_from_report

        content = report.read_text(encoding="utf-8")
        codes = parse_top10_from_report(content)
        out["codes"] = list(codes)
        out["count"] = len(codes)
        if not codes:
            out["note"] = "当日 0 推荐 (正常状态, 非解析失败)"
    except Exception as exc:  # noqa: BLE001
        out.setdefault("error", f"{type(exc).__name__}: {exc}")

    # 深度分析分数 (只读, 失败不影响 codes)
    try:
        da_files = sorted(DATA_DIR.glob("deep_analysis_*.json"))
        if da_files:
            da = json.loads(da_files[-1].read_text(encoding="utf-8"))
            scores = {}
            for row in (da.get("results") or []):
                code = str(row.get("code") or row.get("symbol") or "")[-6:]
                score = row.get("v24_score", row.get("score"))
                if re.fullmatch(r"\d{6}", code) and score is not None:
                    scores[code] = _num(score)
            if scores:
                out["deep_analysis_file"] = da_files[-1].name
                out["scores"] = scores
    except Exception as exc:  # noqa: BLE001
        out.setdefault("deep_analysis_error", f"{type(exc).__name__}: {exc}")

    return out


def collect_strategy() -> dict:
    """策略参数: next_day_strategy (生效值) + rec_tuning (回溯统计)。"""
    out: dict = {}
    nds = _read_json(DATA_DIR / "next_day_strategy.json")
    if "error" in nds:
        out["next_day_strategy_error"] = nds["error"]
    else:
        out["date_for"] = nds.get("date_for")
        out["score_threshold"] = _num(nds.get("score_threshold"))
        out["hold_days"] = _num(nds.get("hold_days"))
        out["position_final"] = _num(nds.get("position_final"))
        out["position_base"] = _num(nds.get("position_base"))
        out["weak_sectors"] = list(nds.get("weak_sectors") or [])
        out["cold_sectors"] = list(nds.get("cold_sectors") or [])
        out["generated_at"] = nds.get("generated_at")
    rt = _read_json(DATA_DIR / "rec_tuning.json")
    if "error" in rt:
        out["rec_tuning_error"] = rt["error"]
    else:
        out["tuning_recommended_threshold"] = _num(rt.get("recommended_score_threshold"))
        out["tuning_total_records"] = _num(rt.get("total_records"))
        out["tuning_win_rate"] = _num(rt.get("overall_win_rate"))
    return out


def collect_feedback(days: int = 30) -> dict:
    """反馈闭环统计 (最近 N 条推荐)。"""
    try:
        from feedback_loop import compute_stats, load_recent_recommendations

        rows = load_recent_recommendations(days)
        if not rows:
            return {"error": f"最近 {days} 天没有推荐记录 (可能是真没有, 也可能是源停了)"}
        wins, total, winrate, avg_win, avg_loss, profit_ratio, flat_count = compute_stats(rows)
        out = {
            "days": days,
            "wins": _num(wins),
            "total": _num(total),
            "win_rate": _num(winrate),
            "avg_win": _num(avg_win),
            "avg_loss": _num(avg_loss),
            "profit_ratio": _num(profit_ratio),
            "flat_count": _num(flat_count),
        }
        if not total:
            # 教训 (u): 「静默空 ≠ 正常空」—— 0 有效样本时 win_rate=0.0 会被误读成「胜率 0%」
            out["note"] = (f"最近 {days} 天没有已回填的有效样本 (T+1 未发生 / 回填链未跑)。"
                           "win_rate=0.0 表示无样本, 不是胜率为零。")
        return out
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def collect_eastmoney() -> dict:
    """东财组合缓存 (只读 groups.json)。服务端才是真理源, 这里只是缓存快照。"""
    data = _read_json(GROUPS_JSON)
    if "error" in data:
        return {"error": data["error"], "path": str(GROUPS_JSON)}
    groups = {}
    for name, entry in data.items():
        if not isinstance(entry, dict):
            continue
        groups[name] = {
            "gid": entry.get("gid"),
            "date": entry.get("date"),
            "stocks": list(entry.get("stocks") or []),
            "count": len(entry.get("stocks") or []),
        }
    return {"path": str(GROUPS_JSON), "groups": groups, "group_count": len(groups)}


def build_snapshot(days: int = 30, section_timeout: int = 20) -> dict:
    """组装完整快照。任何一段失败都只影响那一段, 其余照常产出。"""
    collectors = {
        "market": collect_market,
        "pool": collect_pool,
        "strategy": collect_strategy,
        "feedback": lambda: collect_feedback(days),
        "eastmoney": collect_eastmoney,
    }
    sections: dict = {}
    errors: dict = {}
    for name, fn in collectors.items():
        try:
            section = _with_timeout(section_timeout, fn)
        except _SectionTimeout as exc:
            section = {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            section = {"error": f"{type(exc).__name__}: {exc}"}
        sections[name] = section
        if isinstance(section, dict) and section.get("error"):
            errors[name] = section["error"]
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "date": datetime.now().strftime("%Y%m%d"),
        "schema_version": 1,
        "sections_ok": not errors,
        "errors": errors,
        **sections,
    }


def write_snapshot(path: Path | None = None, days: int = 30) -> tuple[Path, dict]:
    """写快照 (原子 + 写后校验)。返回 (路径, 快照内容)。"""
    from _safe_io import safe_write_json_locked

    target = Path(path) if path else SNAPSHOT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    snap = build_snapshot(days=days)
    safe_write_json_locked(str(target), snap)
    # 写后校验: 落盘内容必须能读回来且是合法 JSON
    with open(target, encoding="utf-8") as f:
        reloaded = json.load(f)
    if not isinstance(reloaded, dict) or "generated_at" not in reloaded:
        raise RuntimeError(f"快照写后校验失败: {target}")
    return target, reloaded


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--print" in argv:
        snap = build_snapshot()
        print(json.dumps(snap, ensure_ascii=False, indent=2))
        return 0
    path, snap = write_snapshot()
    print(f"✅ 快照已写入: {path}")
    print(f"   生成时间: {snap['generated_at']}")
    print(f"   各段状态: {'全部正常' if snap['sections_ok'] else '有失败段 (见 errors)'}")
    if snap["errors"]:
        for k, v in snap["errors"].items():
            print(f"     ⚠️ {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

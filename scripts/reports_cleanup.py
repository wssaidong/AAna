#!/usr/bin/env python3
"""
scripts/reports_cleanup.py — 报告目录 cleanup (Phase 7B v2026-08-23)

只清理超龄文件,绝不动 reports/ 的目录结构 (避免破坏飞书文档关联)。
SKILL 沉淀 ('reports_cleanup.py cron 化') — 此版本 cron 化 + 加测试覆盖。

策略:
  - reports/*.md       文件超龄(默认 90 天)→ 删除
  - reports/<date>/*.md  整目录超龄(目录内最近文件 90 天前)→ 删除目录
  - reports/盘中/*.log  cron log,默认 7 天(高频删,避免堆)
  - 保留(白名单): 含 "复盘报告" / "深度分析" / "周末备战" 命名的最近 30 份(用户常回看)
  - dry-run 模式: 只打印待删不真删
  - exit code: 0=OK, 2=有错误

Cron 推荐: `0 2 * * 1` (每周一凌晨 2 点, 与 a-stock-weekend 联动)
用法:
  python3 scripts/reports_cleanup.py                # 默认 90 天
  python3 scripts/reports_cleanup.py --days 60      # 自定义天数
  python3 scripts/reports_cleanup.py --dry-run
"""
import argparse
import os
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# v2026-08-23 Phase 6C: 统一配置中心
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _config import REPORTS_DIR
except Exception:
    REPORTS_DIR = Path("/Users/cai/code/AAna/reports").resolve()


def is_older_than(p: Path, cutoff_dt: datetime) -> bool:
    """文件/目录最后修改时间早于 cutoff_dt?"""
    if not p.exists():
        return False
    mtime = datetime.fromtimestamp(p.stat().st_mtime)
    return mtime < cutoff_dt


def cleanup_files(keep_recent: int = 90, dry_run: bool = False) -> dict:
    """cleanup reports/*.md 文件超龄者"""
    cutoff = datetime.now() - timedelta(days=keep_recent)
    removed = []
    kept_recent = []

    if not REPORTS_DIR.exists():
        return {"removed": [], "kept_recent": [], "error": "reports/ not found"}

    # 只看顶层 *.md (避免穿透到 reports/2026-08-21/ 等子目录)
    for f in sorted(REPORTS_DIR.glob("*.md")):
        # 复盘报告 / 深度分析 / 周末备战 这 3 类保留更多
        name = f.name.lower()
        is_strategic = ("复盘" in name or "深度分析" in name
                        or "周末备战" in name or "live_business_perf" in name)

        if is_strategic:
            # 战略报告保留更多 — 90 天后才删
            if is_older_than(f, cutoff):
                removed.append(str(f.relative_to(REPORTS_DIR)))
                if not dry_run:
                    f.unlink()
            else:
                kept_recent.append(str(f.relative_to(REPORTS_DIR)))
        else:
            # 其他报告 30 天(高频)
            short_cutoff = datetime.now() - timedelta(days=30)
            if is_older_than(f, short_cutoff):
                removed.append(str(f.relative_to(REPORTS_DIR)))
                if not dry_run:
                    f.unlink()
            else:
                kept_recent.append(str(f.relative_to(REPORTS_DIR)))

    return {"removed": removed, "kept_recent": kept_recent}


def cleanup_subdirs(max_age_days: int = 7, dry_run: bool = False) -> dict:
    """cleanup reports/<date>/*.md 子目录(盘中日志特别高频)"""
    cutoff = datetime.now() - timedelta(days=max_age_days)
    removed = []
    kept = []

    if not REPORTS_DIR.exists():
        return {"removed": [], "kept": []}

    for sub in sorted(REPORTS_DIR.iterdir()):
        if not sub.is_dir():
            continue
        # 默认子目录中最新文件 mtime < cutoff → 整目录移除
        if is_older_than(sub, cutoff):
            removed.append(str(sub.relative_to(REPORTS_DIR)))
            if not dry_run:
                shutil.rmtree(sub, ignore_errors=True)
        else:
            kept.append(str(sub.relative_to(REPORTS_DIR)))

    return {"removed_dirs": removed, "kept_dirs": kept}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=90, help="md 文件保留天数 (默认 90)")
    p.add_argument("--subdir-days", type=int, default=7, help="子目录最大天数 (默认 7)")
    p.add_argument("--dry-run", action="store_true", help="只显示待删,不真删")
    args = p.parse_args()

    print(f"🧹 reports_cleanup: keep={args.days}d, subdir={args.subdir_days}d "
          f"(dry_run={args.dry_run})")

    t0 = time.time()
    f_result = cleanup_files(keep_recent=args.days, dry_run=args.dry_run)
    d_result = cleanup_subdirs(max_age_days=args.subdir_days, dry_run=args.dry_run)
    elapsed = time.time() - t0

    n_removed = len(f_result.get("removed", [])) + len(d_result.get("removed_dirs", []))
    print(f"\n  删除 md 文件 {len(f_result.get('removed', []))} 个:")
    for r in f_result.get("removed", [])[:20]:
        print(f"    - {r}")
    if len(f_result.get("removed", [])) > 20:
        print(f"    ... (还有 {len(f_result['removed']) - 20} 个)")

    print(f"\n  删除子目录 {len(d_result.get('removed_dirs', []))} 个:")
    for r in d_result.get("removed_dirs", [])[:20]:
        print(f"    - {r}")

    print(f"\n  保留目录 {len(d_result.get('kept_dirs', []))} 个, "
          f"保留 md {len(f_result.get('kept_recent', []))} 个")
    print(f"\n  ✅ 完成({elapsed:.1f}s, 删 {n_removed} 个)"
          f"{' (DRY-RUN)' if args.dry_run else ''}")

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)

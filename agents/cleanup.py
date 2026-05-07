#!/usr/bin/env python3
"""
AAna 滚动清理 - 只保留最近7天数据
清理范围：
  - state/                 → 只保留最近7天状态文件
  - reports/               → 各子目录下只保留7天内报告
  - *.md (根目录)          → 保留根目录的选股/复盘报告
"""
import os
import sys
import glob
import logging
from datetime import datetime, timedelta

sys.path.insert(0, os.path.expanduser('~/code/AAna'))

from agents.config import PROJECT_DIR, STATE_DIR, REPORTS_DIR

logging.basicConfig(level=logging.INFO, format='[cleanup] %(message)s')
log = logging.getLogger('cleanup')

KEEP_DAYS = 7


def get_cutoff_date():
    return datetime.now() - timedelta(days=KEEP_DAYS)


def parse_date_from_filename(filename, patterns):
    """从文件名中提取日期，返回 datetime 或 None"""
    basename = os.path.basename(filename)
    for pattern in patterns:
        try:
            dt = datetime.strptime(basename, pattern)
            return dt
        except ValueError:
            continue
    return None


def cleanup_state():
    """清理 state/ 目录，只保留最近7天"""
    cutoff = get_cutoff_date()
    removed = []

    if not os.path.exists(STATE_DIR):
        return removed

    for fname in os.listdir(STATE_DIR):
        fpath = os.path.join(STATE_DIR, fname)
        if os.path.isdir(fpath):
            continue

        dt = parse_date_from_filename(fname, [
            'postmarket_summary_%Y-%m-%d.json',
            'premarket_briefing_%Y-%m-%d.json',
            'premarket_selfcheck_%Y-%m-%d.json',
            'close_snapshot_%Y-%m-%d.json',
            'intraday_monitor_%Y-%m-%d.json',
            'competitive_quote_%Y-%m-%d.json',
        ])

        if dt is None:
            log.debug(f"跳过未知格式: {fname}")
            continue

        if dt < cutoff:
            os.remove(fpath)
            removed.append(f"state/{fname}")

    return removed


def cleanup_reports():
    """清理 reports/ 各子目录，只保留7天内报告"""
    cutoff = get_cutoff_date()
    removed = []

    if not os.path.exists(REPORTS_DIR):
        return removed

    # 日期模式：YYYY-MM-DD 或 YYYY-MM
    date_patterns = [
        '%Y-%m-%d_%H%M_%s.md',   # 2026-05-06_2145_复盘评分.md
        '%Y-%m-%d_%s.md',         # 2026-04-30_风险评估.md
        '%Y-%m-%d_%s.md',         # 2026-05-05_周度总结.md
    ]

    # 遍历 reports 下所有子目录
    for subdir, _, files in os.walk(REPORTS_DIR):
        for fname in files:
            if not fname.endswith('.md'):
                continue
            fpath = os.path.join(subdir, fname)

            dt = parse_date_from_filename(fname, [
                '%Y-%m-%d_%H%M_%s.md',   # 2026-05-06_2145_复盘评分.md
                '%Y-%m-%d_%s.md',         # 2026-04-30_风险评估.md
                '%Y-%m-%d_%s.md',         # 2026-05-05_周度总结.md
            ])

            if dt is None:
                # 尝试更宽松的解析：从文件名中提取 YYYY-MM-DD
                import re
                m = re.search(r'(\d{4}-\d{2}-\d{2})', fname)
                if m:
                    try:
                        dt = datetime.strptime(m.group(1), '%Y-%m-%d')
                    except ValueError:
                        log.debug(f"跳过未知格式: {fname}")
                        continue
                else:
                    log.debug(f"跳过无日期文件: {fname}")
                    continue

            if dt < cutoff:
                os.remove(fpath)
                rel = fpath.replace(PROJECT_DIR + '/', '')
                removed.append(rel)

    return removed


def cleanup_root_reports():
    """清理根目录的选股报告/复盘评分，只保留7天内"""
    cutoff = get_cutoff_date()
    removed = []

    for fname in os.listdir(PROJECT_DIR):
        if not fname.endswith('.md'):
            continue
        fpath = os.path.join(PROJECT_DIR, fname)

        # 只处理明显的日期报告文件
        import re
        m = re.search(r'(\d{4}-\d{2}-\d{2})-(选股报告|复盘评分)\.md', fname)
        if not m:
            continue

        try:
            dt = datetime.strptime(m.group(1), '%Y-%m-%d')
        except ValueError:
            continue

        if dt < cutoff:
            os.remove(fpath)
            removed.append(fname)

    return removed


def run():
    """执行全量清理"""
    log.info(f"🧹 AAna 滚动清理开始，保留最近 {KEEP_DAYS} 天数据")
    cutoff = get_cutoff_date()
    log.info(f"截止日期: {cutoff.strftime('%Y-%m-%d')}")

    all_removed = []

    state_removed = cleanup_state()
    all_removed.extend(state_removed)

    reports_removed = cleanup_reports()
    all_removed.extend(reports_removed)

    root_removed = cleanup_root_reports()
    all_removed.extend(root_removed)

    if all_removed:
        log.info(f"✅ 已删除 {len(all_removed)} 个过期文件:")
        for r in sorted(all_removed):
            log.info(f"   - {r}")
    else:
        log.info("✅ 无过期文件需要清理")

    return all_removed


if __name__ == '__main__':
    run()

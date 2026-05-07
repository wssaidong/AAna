#!/usr/bin/env python3
"""
AAna 滚动清理 - 只保留最近7天数据
清理范围：
  - state/                         → 只保留最近7天状态文件
  - reports/YYYY-MM-DD/{phase}/    → 按新目录规则，删除整个过期日期目录
  - *.md (根目录)                  → 选股报告、复盘评分等旧格式
新目录规则（save_report）：
  reports/YYYY-MM-DD/{phase}/{time}_{type}.md
  - 盘前/竞价/盘中/复盘
"""
import os
import sys
import re
import logging
from datetime import datetime, timedelta

sys.path.insert(0, os.path.expanduser('~/code/AAna'))

from agents.config import PROJECT_DIR, STATE_DIR, REPORTS_DIR

logging.basicConfig(level=logging.INFO, format='[cleanup] %(message)s')
log = logging.getLogger('cleanup')

KEEP_DAYS = 7


def get_cutoff_date():
    return datetime.now() - timedelta(days=KEEP_DAYS)


def parse_date_from_dirname(dirname):
    """从目录名提取 YYYY-MM-DD 日期"""
    try:
        return datetime.strptime(dirname, '%Y-%m-%d')
    except ValueError:
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

        dt = _parse_date_from_state_filename(fname)
        if dt is None:
            log.debug(f"跳过未知格式: {fname}")
            continue

        if dt < cutoff:
            os.remove(fpath)
            removed.append(f"state/{fname}")

    return removed


def _parse_date_from_state_filename(fname):
    """从 state 文件名中解析日期"""
    patterns = [
        ('postmarket_summary_', '%Y-%m-%d'),
        ('premarket_briefing_', '%Y-%m-%d'),
        ('premarket_selfcheck_', '%Y-%m-%d'),
        ('close_snapshot_', '%Y-%m-%d'),
        ('intraday_monitor_', '%Y-%m-%d'),
        ('competitive_quote_', '%Y-%m-%d'),
    ]
    for prefix, fmt in patterns:
        if fname.startswith(prefix):
            date_str = fname[len(prefix):].replace('.json', '')
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                return None
    return None


def cleanup_reports():
    """按新目录规则清理 reports/：
    - reports/YYYY-MM-DD/    → 整个过期日期目录删除
    - reports/YYYY-MM-DD/*   → 不再逐文件清理
    旧格式（reports/复盘/, reports/盘中/ 等扁平结构）也一并清理
    """
    cutoff = get_cutoff_date()
    removed = []

    if not os.path.exists(REPORTS_DIR):
        return removed

    # 1. 新格式：reports/YYYY-MM-DD/ 子目录
    for dirname in os.listdir(REPORTS_DIR):
        day_dir = os.path.join(REPORTS_DIR, dirname)
        if not os.path.isdir(day_dir):
            # 扁平目录（旧格式）或文件，跳过，由下面 2 处理
            continue

        dt = parse_date_from_dirname(dirname)
        if dt is None:
            # 非日期目录（如 复盘、盘中、盘前、竞价），跳过
            log.debug(f"跳过非日期目录: {dirname}")
            continue

        if dt < cutoff:
            # 删除整个日期目录
            import shutil
            shutil.rmtree(day_dir)
            removed.append(f"reports/{dirname}/")
            log.debug(f"已删除日期目录: {dirname}/")

    # 2. 旧格式扁平目录清理（复盘、盘中、盘前、竞价）
    old_flat_dirs = ['复盘', '盘中', '盘前', '竞价', '尾盘']
    for flat_name in old_flat_dirs:
        flat_dir = os.path.join(REPORTS_DIR, flat_name)
        if not os.path.isdir(flat_dir):
            continue

        for fname in os.listdir(flat_dir):
            fpath = os.path.join(flat_dir, fname)
            if os.path.isdir(fpath):
                continue
            if not fname.endswith('.md'):
                continue

            m = re.search(r'(\d{4}-\d{2}-\d{2})', fname)
            if not m:
                log.debug(f"跳过无日期文件: {fname}")
                continue
            try:
                dt = datetime.strptime(m.group(1), '%Y-%m-%d')
            except ValueError:
                log.debug(f"日期解析失败: {fname}")
                continue

            if dt < cutoff:
                os.remove(fpath)
                removed.append(f"reports/{flat_name}/{fname}")

    # 3. 旧格式扁平 .md 文件（直接在 reports/ 下的 策略分析/风险评估/周度总结）
    for fname in os.listdir(REPORTS_DIR):
        fpath = os.path.join(REPORTS_DIR, fname)
        if os.path.isdir(fpath):
            continue
        if not fname.endswith('.md'):
            continue

        m = re.search(r'(\d{4}-\d{2}-\d{2})', fname)
        if not m:
            continue
        try:
            dt = datetime.strptime(m.group(1), '%Y-%m-%d')
        except ValueError:
            continue

        if dt < cutoff:
            os.remove(fpath)
            removed.append(f"reports/{fname}")

    return removed


def cleanup_root_reports():
    """清理根目录的旧格式选股报告/复盘评分，只保留7天内"""
    cutoff = get_cutoff_date()
    removed = []

    for fname in os.listdir(PROJECT_DIR):
        if not fname.endswith('.md'):
            continue
        fpath = os.path.join(PROJECT_DIR, fname)

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
        log.info(f"✅ 已删除 {len(all_removed)} 个过期文件/目录:")
        for r in sorted(all_removed):
            log.info(f"   - {r}")
    else:
        log.info("✅ 无过期文件需要清理")

    return all_removed


if __name__ == '__main__':
    run()

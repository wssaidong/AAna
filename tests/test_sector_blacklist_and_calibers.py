#!/usr/bin/env python3
"""
tests/test_sector_blacklist_and_calibers.py — v2026-10-28 反馈闭环 P0 回归测试

锁定 3 个修复 (否则会静默复发):

1. **板块黑名单 100% 失效** (P0)
   rec_tuning.sector_stats 的 key 是 rec_feedback.csv `sector` 列的中文原值
   (如 '房地产开发'), 而旧代码只拿英文 enum 去比 → 永不匹配。
   实测 10-13 至今日志全是 `blacklist=[无]`。

2. **generate_report.py 拿 category 比对** (P0)
   category 是选股池分组 id (high_rise/active/potential), 不是板块名 →
   弱势板块过滤恒不生效。

3. **报告口径不可比** (P1)
   标题只给「最近 20 只」胜率 (95.0%), 全历史去重只有 48.9% → 必须三口径并列。
"""
import os
import sys
from datetime import datetime, timedelta

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))
sys.path.insert(0, PROJECT)

from feedback_loop import compute_calibers  # noqa: E402
from aana_afternoon_screen import _sector_blacklisted, _cn_sector_to_enum  # noqa: E402


# ───────────────────────── 修复 1: 板块黑名单双路匹配 ─────────────────────────

class TestSectorBlacklist:
    """黑名单匹配必须同时认中文原名和英文 enum。"""

    def test_chinese_name_matches(self):
        """中文原名在黑名单里 → 必须拦截 (旧代码漏掉这条)"""
        bl = ['房地产开发', '印制电路板', '其他家用轻工', '影视动漫', '造纸']
        assert _sector_blacklisted('房地产开发', 'realestate', bl) is True
        assert _sector_blacklisted('印制电路板', 'unknown', bl) is True
        assert _sector_blacklisted('造纸', 'unknown', bl) is True

    def test_legacy_enum_still_matches(self):
        """历史英文 enum key 仍要能命中 (兼容 2026-05 老数据)"""
        bl = ['semi', 'chem', 'ai_app']
        assert _sector_blacklisted('半导体设备', 'semi', bl) is True
        assert _sector_blacklisted('化工', 'chem', bl) is True

    def test_non_blacklisted_passes(self):
        """不在黑名单的板块必须放过 (不能误杀)"""
        bl = ['房地产开发', 'semi']
        assert _sector_blacklisted('汽车零部件', 'unknown', bl) is False
        assert _sector_blacklisted('', '', bl) is False
        assert _sector_blacklisted('unknown', 'unknown', bl) is False

    def test_empty_blacklist_never_blocks(self):
        """黑名单为空 → 恒不过滤 (当前生产状态)"""
        assert _sector_blacklisted('房地产开发', 'realestate', []) is False
        assert _sector_blacklisted('房地产开发', 'realestate', set()) is False

    def test_real_data_blacklist_is_matched(self):
        """真实 rec_tuning weak_sectors 必须能被真实黑名单匹配上。

        锁定 2026-10-28 实测: 这 6 个板块在旧代码下全部漏网。
        """
        import json
        tuning_path = os.path.join(PROJECT, "data", "rec_tuning.json")
        if not os.path.exists(tuning_path):
            pytest.skip("rec_tuning.json 不存在")
        with open(tuning_path, encoding="utf-8") as f:
            weak = json.load(f).get("weak_sectors", [])
        if not weak:
            pytest.skip("当前 weak_sectors 为空")
        # 每个中文名板块都必须能被自己的 raw 名命中
        for name in weak:
            if name.isascii():  # 历史英文 enum key 由 enum 路径命中
                continue
            assert _sector_blacklisted(name, _cn_sector_to_enum(name), set(weak)) is True, \
                f"板块 {name!r} 在黑名单中但匹配不上 (P0 复发)"


# ───────────────────────── 修复 3: 三口径胜率对照 ─────────────────────────

class TestCalibers:
    """报告必须并列三个口径, 不能只给最近 20 只。"""

    def _row(self, code, rec_date, ret):
        return {
            "date": rec_date, "code": code, "name": f"股{code}",
            "rec_date": rec_date, "trend": "震荡",
            "ret_1d": ret, "ret_3d": "", "ret_5d": "", "ret_15d": "",
            "score": "70", "sentiment_score": "50",
            "macd_gold": "False", "macd_confirmed": "False", "sector": "测试",
        }

    def test_three_calibers_returned(self):
        rows = [self._row(f"{i:06d}", "2026-10-28", "5.0") for i in range(5)]
        rows += [self._row(f"9{i:05d}", "2026-01-01", "-5.0") for i in range(5)]
        cals = compute_calibers(rows)
        assert len(cals) == 3, f"应返回 3 个口径, 实际 {len(cals)}"

    def test_small_window_vs_full_history_diverge(self):
        """最近 20 只全涨 + 全历史大半跌 → 两口径必须不同 (旧代码只报前者)"""
        today = datetime.now().strftime("%Y-%m-%d")
        old = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d")
        rows = [self._row(f"{i:06d}", today, "5.0") for i in range(20)]
        rows += [self._row(f"8{i:05d}", old, "-5.0") for i in range(20)]
        cals = compute_calibers(rows)
        head_n, head_wr = cals[0][1], cals[0][2]
        full_n, full_wr = cals[-1][1], cals[-1][2]
        assert head_wr == 100.0, f"最近 20 只应全涨, 实际 {head_wr}"
        assert full_wr == 50.0, f"全历史应 50%, 实际 {full_wr}"
        assert head_wr != full_wr, "两口径必须能区分"

    def test_caliber_sample_sizes_consistent(self):
        """口径 (c) 的样本数 = 去重后有效样本数, 必须 <= 原始行数"""
        today = datetime.now().strftime("%Y-%m-%d")
        rows = [self._row(f"{i:06d}", today, "5.0") for i in range(10)]
        cals = compute_calibers(rows)
        assert cals[-1][1] == 10, f"全历史样本应为 10, 实际 {cals[-1][1]}"
        assert cals[-1][1] <= len(rows)


# ───────────────────────── 修复 2: generate_report 板块口径 ─────────────────────────

class TestGenerateReportSectorField:
    """generate_report.py 的 sector 必须是真实行业名, 不能是 category 分组 id。"""

    def test_category_is_not_a_sector_name(self):
        """category 是选股池分组 id — 与板块黑名单不同命名空间"""
        import generate_report as gr
        src = open(os.path.join(PROJECT, "scripts", "generate_report.py"),
                   encoding="utf-8").read()
        # 修复后必须用 industry_for_code 反查真实行业名
        assert "industry_for_code" in src, \
            "generate_report.py 必须用 industry_for_code 反查板块 (否则 category 比对恒失效)"
        # 旧的错误写法已移除
        assert "sector = info.get('category', '') or info.get('sector', '')" not in src, \
            "旧的 category 比对写法仍在 (板块过滤恒失效)"

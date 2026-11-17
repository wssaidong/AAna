#!/usr/bin/env python3
"""
tests/test_feedback_loop_20261110_regressions.py — 2026-11-10 早盘实战沉淀的 2 个缺陷回归

🔴 缺陷 1: `_ensure_store_current()` 把「缺失集合里恰好只有 1 只 raw 股」误判为
   「qfq 通道被 WAF 拦」 → 跳过**整池** sync → 其它正常股永远补不上当日 bar
   → ret_1d 静默留空 (教训 z 同款症状)。
   实证: 603407 长裕集团上游无 qfqday 键 (无除权事件) → 探针报 raw;
   同日 69/70 只 qfq 正常入库 → 通道明明是通的, 但探针只看了缺失集合 → 判死。
   修法 (教训 ab: 阴性结论必须多样本交叉): 缺失候选全 raw 时, 再用
   **池内非缺失股**做对照探针; 对照股 qfq + 当日 bar → 通道正常 → 照常 sync。

🔴 缺陷 2: 「最新推荐详情」表用 _valid_rows 渲染 → ret_1d 为空的行 (T+1 未到)
   整池被丢弃 → 标题写「最新推荐详情」实际展示更早的池 → 用户看不到今日选股。
   修法: 展示口径用 _latest_rows (保留 ret_* 为空的行), 统计口径仍用 _valid_rows。

不变量:
  A. 缺失集合只有 1 只 raw 股 + 池内对照股 qfq+当日 bar → 必须照常 sync (不判 WAF)
  B. 缺失候选全 raw **且** 对照股也全 raw → 仍判 WAF 并跳过 (保护原意)
  C. 详情表必须包含 ret_1d 为空的今日池行, 且明示待回填行数
  D. 统计口径不受影响: 无 ret_1d 的行进不了胜率分母
"""
import os
import sys
from datetime import datetime
from unittest.mock import patch

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))
sys.path.insert(0, PROJECT)

import feedback_loop as fl


def _fake_store(have_symbols=None, enabled=True):
    from unittest.mock import MagicMock
    st = MagicMock()
    st.enabled = enabled
    st.symbols_with_bar.return_value = set(have_symbols or set())
    r = MagicMock()
    r.fetched = 10
    r.inserted_rows = 10
    r.missing = 0
    r.failed = 0
    r.elapsed_s = 0.5
    st.sync_day.return_value = r
    return st


class TestProbeControlCrossCheck:
    """缺陷 1 回归 — 探针阴性结论必须多样本交叉 (教训 ab)"""

    def test_single_raw_missing_does_not_kill_channel(self):
        """A. 缺失集合只含 1 只 raw 股 → 不得判「WAF 拦截」→ 必须照常 sync

        2026-11-10 实测故障态: missing = {603407} (上游无 qfqday 键),
        池内其余 69 只当日 qfq bar 正常。旧逻辑误判 WAF → 整池跳过 →
        其它股永远补不上当日 bar → ret_1d 静默留空。
        """
        st = _fake_store(have_symbols={"600699", "002354"})   # 只缺 603407

        def fake_probe(code, count=90):
            if code == "603407":        # 无除权事件 → 上游无 qfqday 键 → raw
                return ([{"date": "2026-11-10", "close": 42.58}], "raw")
            return ([{"date": "2026-11-10", "close": 25.0}], "qfq")  # 对照股正常

        with patch.object(fl, "datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 11, 10, 16, 0)
            with patch("generate_report.is_trading_day", return_value=(True, "")), \
                 patch("data.market_store.MarketStore", return_value=st), \
                 patch("data.market_store.default_symbols",
                       return_value=["600699", "002354", "603407"]), \
                 patch.object(fl, "_probe_qfq_endpoint", side_effect=fake_probe):
                synced, detail = fl._ensure_store_current(verbose=False)

        assert synced is True, f"不应判通道死: {detail}"
        assert "WAF" not in detail
        st.sync_day.assert_called_once()

    def test_all_raw_including_control_still_blocks(self):
        """B. 缺失候选 + 对照股**全部** raw → 仍判 WAF 并跳过 (保护原意)"""
        st = _fake_store(have_symbols=set())

        def fake_probe(code, count=90):
            return ([{"date": "2026-11-10", "close": 25.0}], "raw")

        with patch.object(fl, "datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 11, 10, 16, 0)
            with patch("generate_report.is_trading_day", return_value=(True, "")), \
                 patch("data.market_store.MarketStore", return_value=st), \
                 patch("data.market_store.default_symbols",
                       return_value=["600501", "600502", "600503"]), \
                 patch.object(fl, "_probe_qfq_endpoint", side_effect=fake_probe):
                synced, detail = fl._ensure_store_current(verbose=False)

        assert synced is False
        assert "WAF" in detail and "raw" in detail
        st.sync_day.assert_not_called()

    def test_control_qfq_without_today_bar_is_data_delay(self):
        """对照股 qfq 但无当日 bar → 判「数据延迟」而非 WAF"""
        st = _fake_store(have_symbols={"600699"})

        def fake_probe(code, count=90):
            if code == "603407":
                return ([{"date": "2026-11-09", "close": 42.57}], "raw")
            return ([{"date": "2026-11-09", "close": 25.0}], "qfq")  # 无当日 bar

        with patch.object(fl, "datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 11, 10, 16, 0)
            with patch("generate_report.is_trading_day", return_value=(True, "")), \
                 patch("data.market_store.MarketStore", return_value=st), \
                 patch("data.market_store.default_symbols",
                       return_value=["600699", "603407"]), \
                 patch.object(fl, "_probe_qfq_endpoint", side_effect=fake_probe):
                synced, detail = fl._ensure_store_current(verbose=False)

        assert synced is False
        assert "均无当日 bar" in detail
        st.sync_day.assert_not_called()


class TestDetailTableKeepsPendingRows:
    """缺陷 2 回归 — 详情表必须展示今日池 (ret_1d 待 T+1)"""

    def _rows(self):
        # 今日池 10 只 (ret_1d 空), 昨日池 13 只 (有 ret_1d)
        rows = []
        for i in range(10):
            rows.append({
                "date": "2026-11-10 14:46:33", "code": f"60000{i}", "name": f"今日{i}",
                "rec_date": "2026-11-10", "trend": "上升", "ret_1d": "",
                "ret_3d": "", "ret_5d": "", "ret_15d": "",
            })
        for i in range(13):
            rows.append({
                "date": "2026-11-09 14:46:53", "code": f"60001{i}", "name": f"昨日{i}",
                "rec_date": "2026-11-09", "trend": "上升", "ret_1d": "1.23",
                "ret_3d": "", "ret_5d": "", "ret_15d": "",
            })
        return rows

    def test_latest_rows_keeps_pending(self):
        """_latest_rows 保留 ret_1d 为空的行"""
        out = fl._latest_rows(self._rows(), 20)
        assert len(out) == 20
        # 23 行按 (rec_date, code) 升序取末 20 → 昨日池剩 10 + 今日池 10
        assert sum(1 for r in out if not r["ret_1d"]) == 10
        assert out[-1]["rec_date"] == "2026-11-10"
        assert out[-1]["name"].startswith("今日")

    def test_report_detail_table_shows_today_pool(self):
        """C. 报告详情表必须含今日池行 + 明示待回填行数"""
        rows = self._rows()
        stats = fl.compute_stats(rows, top_n=20)
        trend = fl.compute_trend_stats(rows, top_n=60)
        md = fl.build_markdown_report([], rows, stats, trend)

        assert "今日0" in md, "今日池必须出现在详情表"
        assert "2026-11-10" in md
        assert "待 T+1" in md or "尚未回填" in md, "必须明示待回填行数"

    def test_stats_caliber_excludes_pending(self):
        """D. 统计口径不受影响: 无 ret_1d 的行进不了胜率分母"""
        rows = self._rows()
        stats = fl.compute_stats(rows, top_n=20)
        assert stats[1] == 13, "胜率分母只能是有收益率的行"

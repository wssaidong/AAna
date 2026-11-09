#!/usr/bin/env python3
"""tests/test_feedback_loop_store_sync.py — 2026-11-09 根因回归测试

🔴 背景 (根因第 2 次复现, 首次 2026-11-06):
  `save_kline_cached()` 故意**不写当日 bar** (盘中快照未定格, 教训 z) →
  但全系统**没有任何调度在收盘后跑 `market_store --sync`** → 库里永远缺当日 bar。
  而 `kline()` 是 store 优先 (库存根数够就零网络返回) → 拿到**截至 T-1 的陈旧 K 线**,
  线上已有的正确值被永久压制 → ret_3d / ret_5d **静默留空** (不报错, 闭环"看起来正常")。

  11-09 实测: 11-04 池 14 只只有 603407 一只算出 ret_3d (库存 <260 根走了网络),
  其余 13 只因库存 523 根命中 store → 全部留空。

修法: `feedback_loop._ensure_store_current()` — 收盘后自动补齐 store。

本测试锁定 5 个不变量:
  1. 非交易日 → no-op (零网络, 绝不写 bar)
  2. 未到收盘 (盘中) → no-op (绝不写当日未定格快照, 沿用教训 z 的 REFUSE 保护)
  3. 库已含当日 bar → no-op (零网络, 幂等)
  4. qfq 通道探针不通 (WAF 降级成 raw 口径) → 跳过整池 sync (避免 74 只 × 3 重试 ≈22s 空跑)
  5. sync 抛异常 → 不阻断主流程 (返回 (False, 原因)), 反馈闭环照常跑

⚠️ 断言不硬编码历史快照数字 — 全部 mock, 只断言行为分支。
"""
import os
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))
sys.path.insert(0, PROJECT)

import feedback_loop as fl


def _fake_store(have_symbols=None, enabled=True, sync_result=None):
    """构造一个 mock 的 market_store.MarketStore"""
    st = MagicMock()
    st.enabled = enabled
    st.symbols_with_bar.return_value = set(have_symbols or [])
    if sync_result is None:
        sync_result = MagicMock(fetched=72, inserted_rows=72, missing=0,
                                 failed=0, elapsed_s=12.3)
    st.sync_day.return_value = sync_result
    return st


class TestEnsureStoreCurrentNoOpPaths:
    """no-op 分支 — 全部必须零网络"""

    def test_non_trading_day_is_noop(self):
        """非交易日 → no-op, 绝不碰 store"""
        with patch.object(fl, "datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 11, 7, 16, 0)  # 周六
            with patch("generate_report.is_trading_day", return_value=(False, "周末")), \
                 patch("data.market_store.MarketStore") as mock_store_cls:
                synced, detail = fl._ensure_store_current(verbose=False)

        assert synced is False
        assert "非交易日" in detail
        mock_store_cls.assert_not_called()   # 零网络

    def test_intraday_is_noop(self):
        """盘中 (<15:05) → no-op, 绝不写当日未定格 bar (教训 z)"""
        with patch.object(fl, "datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 11, 9, 10, 30)  # 盘中
            with patch("generate_report.is_trading_day", return_value=(True, "")), \
                 patch("data.market_store.MarketStore") as mock_store_cls:
                synced, detail = fl._ensure_store_current(verbose=False)

        assert synced is False
        assert "未到收盘" in detail
        mock_store_cls.assert_not_called()   # 零网络

    def test_store_already_current_is_noop(self):
        """同步池全量就绪 → no-op (幂等, 零网络)"""
        pool = ["600501", "603375"]
        with patch.object(fl, "datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 11, 9, 16, 0)
            with patch("generate_report.is_trading_day", return_value=(True, "")), \
                 patch("data.market_store.MarketStore",
                       return_value=_fake_store(have_symbols=set(pool))), \
                 patch("data.market_store.default_symbols", return_value=pool):
                synced, detail = fl._ensure_store_current(verbose=False)

        assert synced is False
        assert "全部就绪" in detail

    def test_partial_missing_triggers_sync(self):
        """🔴 2026-11-09 16:00 E2E 实证缺陷回归: 部分缺失 (59/72) 也必须补齐

        旧判据「库里有没有当日 bar」把部分缺失当"已最新" → 缺的 13 只永远不补,
        正是要修的故障态换个马甲复现。新判据: 同步池内缺任意一只 → 增量 sync。
        """
        st = _fake_store(have_symbols={"600501"})   # 只缺 603375
        probe_bars = [{"date": "2026-11-09", "close": 25.0}]
        with patch.object(fl, "datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 11, 9, 16, 0)
            with patch("generate_report.is_trading_day", return_value=(True, "")), \
                 patch("data.market_store.MarketStore", return_value=st), \
                 patch("data.market_store.default_symbols",
                       return_value=["600501", "603375"]), \
                 patch.object(fl, "_probe_qfq_endpoint",
                              return_value=(probe_bars, "qfq")):
                synced, detail = fl._ensure_store_current(verbose=False)

        assert synced is True
        assert "缺1" in detail
        st.sync_day.assert_called_once()

    def test_probe_uses_missing_symbols_not_first_symbol(self):
        """探针候选必须从缺失集合挑 — 缺的那几只才是要拉的"""
        st = _fake_store(have_symbols={"600501"})   # 缺 603375
        probed = []

        def fake_probe(code, count=90):
            probed.append(code)
            return ([{"date": "2026-11-09", "close": 25.0}], "qfq")

        with patch.object(fl, "datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 11, 9, 16, 0)
            with patch("generate_report.is_trading_day", return_value=(True, "")), \
                 patch("data.market_store.MarketStore", return_value=st), \
                 patch("data.market_store.default_symbols",
                       return_value=["600501", "603375"]), \
                 patch.object(fl, "_probe_qfq_endpoint", side_effect=fake_probe):
                synced, _ = fl._ensure_store_current(verbose=False)

        assert synced is True
        assert probed == ["603375"]   # 探针用的是缺失股, 不是 symbols[0]

    def test_store_disabled_is_noop(self):
        """market_store 未启用 → no-op, 不报错"""
        with patch.object(fl, "datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 11, 9, 16, 0)
            with patch("generate_report.is_trading_day", return_value=(True, "")), \
                 patch("data.market_store.MarketStore",
                       return_value=_fake_store(enabled=False)):
                synced, detail = fl._ensure_store_current(verbose=False)

        assert synced is False
        assert "未启用" in detail


class TestEnsureStoreCurrentSyncPath:
    """真实 sync 分支"""

    def test_syncs_when_store_missing_today(self):
        """库缺当日 bar + qfq 通道通 → 调 sync_day 补齐"""
        st = _fake_store(have_symbols=set())
        probe_bars = [{"date": "2026-11-09", "close": 25.0}]
        with patch.object(fl, "datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 11, 9, 16, 0)
            with patch("generate_report.is_trading_day", return_value=(True, "")), \
                 patch("data.market_store.MarketStore", return_value=st), \
                 patch("data.market_store.default_symbols", return_value=["600501", "603375"]), \
                 patch.object(fl, "_probe_qfq_endpoint",
                              return_value=(probe_bars, "qfq")):
                synced, detail = fl._ensure_store_current(verbose=False)

        assert synced is True
        st.sync_day.assert_called_once()
        assert st.sync_day.call_args.kwargs["adjust"] == "qfq"
        assert "inserted" in detail

    def test_probe_raw_adjust_skips_whole_pool_sync(self):
        """🔴 关键: 探针发现通道被 WAF 降级成 raw 口径 → 整池 sync 跳过

        整池跑 = 74 只 × 3 次重试 ≈ 22s 纯浪费, 且拉高 WAF 触发率。
        口径 raw ≠ qfq → sync_day 会把整池判 missing (宁缺毋滥) → 白跑。
        """
        st = _fake_store(have_symbols=set())
        with patch.object(fl, "datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 11, 9, 16, 0)
            with patch("generate_report.is_trading_day", return_value=(True, "")), \
                 patch("data.market_store.MarketStore", return_value=st), \
                 patch("data.market_store.default_symbols", return_value=["600501"]), \
                 patch.object(fl, "_probe_qfq_endpoint",
                              return_value=([{"date": "2026-11-09", "close": 25.0}], "raw")):
                synced, detail = fl._ensure_store_current(verbose=False)

        assert synced is False
        assert "WAF" in detail and "raw" in detail
        st.sync_day.assert_not_called()   # 不做整池空跑

    def test_single_stock_raw_does_not_kill_channel(self):
        """🔴 2026-11-09 16:00 二次实证回归: 单只 raw ≠ 通道挂

        无除权事件的股票 (001239) qfqday 键缺失 → 解析器降级 day → 报 raw。
        旧逻辑在第一只 raw 就中止 → 通道明明正常也被判死。
        正确: 继续探下一只, 任一 qfq+今日 bar 即放行; 全部 raw 才判 WAF。
        """
        st = _fake_store(have_symbols=set())

        def fake_probe(code, count=90):
            if code == "001239":      # 缺失集合首只: 无除权 → raw
                return ([{"date": "2026-11-09", "close": 9.9}], "raw")
            return ([{"date": "2026-11-09", "close": 25.0}], "qfq")   # 第二只: 正常

        with patch.object(fl, "datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 11, 9, 16, 0)
            with patch("generate_report.is_trading_day", return_value=(True, "")), \
                 patch("data.market_store.MarketStore", return_value=st), \
                 patch("data.market_store.default_symbols",
                       return_value=["001239", "002354"]), \
                 patch.object(fl, "_probe_qfq_endpoint", side_effect=fake_probe):
                synced, detail = fl._ensure_store_current(verbose=False)

        assert synced is True            # 通道被第二只证明正常 → 照常 sync
        st.sync_day.assert_called_once()

    def test_probe_ok_but_no_today_bar_skips(self):
        """探针通但今日 bar 未发布 (数据延迟/非交易日) → 跳过 sync"""
        st = _fake_store(have_symbols=set())
        with patch.object(fl, "datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 11, 9, 16, 0)
            with patch("generate_report.is_trading_day", return_value=(True, "")), \
                 patch("data.market_store.MarketStore", return_value=st), \
                 patch("data.market_store.default_symbols", return_value=["600501"]), \
                 patch.object(fl, "_probe_qfq_endpoint",
                              return_value=([{"date": "2026-11-06", "close": 25.0}], "qfq")):
                synced, detail = fl._ensure_store_current(verbose=False)

        assert synced is False
        assert "均无当日 bar" in detail
        st.sync_day.assert_not_called()

    def test_sync_exception_does_not_block(self):
        """🔴 关键: sync 抛异常 → 不阻断主流程 (闭环照常跑)"""
        st = _fake_store(have_symbols=set())
        st.sync_day.side_effect = RuntimeError("network down")
        with patch.object(fl, "datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 11, 9, 16, 0)
            with patch("generate_report.is_trading_day", return_value=(True, "")), \
                 patch("data.market_store.MarketStore", return_value=st), \
                 patch("data.market_store.default_symbols", return_value=["600501"]), \
                 patch.object(fl, "_probe_qfq_endpoint",
                              return_value=([{"date": "2026-11-09", "close": 25.0}], "qfq")):
                synced, detail = fl._ensure_store_current(verbose=False)

        assert synced is False
        assert "sync 跳过" in detail and "RuntimeError" in detail


class TestProbeQfqEndpoint:
    """探针本身 — 网络异常必须吞掉, 返回 ([], None) 而非抛"""

    def test_probe_swallows_exception(self):
        with patch("data.quotes.QuoteService._tencent_kline",
                   side_effect=RuntimeError("boom")):
            bars, adjust = fl._probe_qfq_endpoint("600501")
        assert bars == []
        assert adjust is None

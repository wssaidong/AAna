#!/usr/bin/env python3
"""
tests/test_kline_caliber_label.py — XWI-83 QA 回归：腾讯 K 线口径标签跟数据走

**背景 (XWI-83 S4 QA 发现的 P0 级口径漏洞)**:
腾讯 fqkline 端点**间歇性**返回 HTTP 200 但 payload 里没有 qfqday 键、
只有裸 day 键（不复权数据）。原 `_parse_tencent_bars` 会静默回退取用裸
day 数据，而 `_tencent_kline` 对 fqkline 端点的结果**推定**标注为请求
口径（qfq）——于是不复权数据戴着 qfq 标签穿透了下游全部口径防线
（market_store.sync_day / rps.backfill 的口径校验、kline() 回写）。

**实战后果（2026-11-04 11:17 S3 backfill 实际发生）**:
002178 的整段历史以 raw 值冒充 qfq 入库，10-21→10-22 收益 = -3.73%
（新浪 raw 口径的分红除权假跌幅），而真 qfq 应为 ≈0.00% —— 正是
XWI-80 P0-1 立项要消灭的 002178 事故，经由缓存复现。

**本测试锁定**:
- 裸 day payload → 必须标 'raw'（不得推定 qfq）；
- qfqday payload → 标 'qfq'；
- NOAJ 降级端点 → 恒 'raw'；
- 端到端：state-2 payload 经 kline()/sync_day 不得写入任何 qfq 行。
"""
import json
import os
import sys

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

import data.quotes as q  # noqa: E402
from data.quotes import QuoteService  # noqa: E402

BAR = ['2026-11-03', '10.00', '12.00', '13.00', '9.00', '123456.0']
# state-2：fqkline HTTP 200 但只有裸 day 键（不复权）
PAYLOAD_BARE_DAY = {'code': 0, 'msg': '', 'data': {'sh600000': {'day': [BAR]}}}
# 正常：qfqday 键（真前复权）
PAYLOAD_QFQ = {'code': 0, 'msg': '', 'data': {'sh600000': {'qfqday': [BAR]}}}


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self.text = 'kline_dayqfq=' + json.dumps(payload)


def _patch(monkeypatch, responder):
    """responder(url) -> _Resp | None；按端点区分响应。"""
    monkeypatch.setattr(q, '_retry_req',
                        lambda url, params=None, **k: responder(url))


class TestCaliberLabelFollowsPayload:
    def test_bare_day_payload_labeled_raw(self, monkeypatch):
        """state-2 回归核心：裸 day(不复权) 不得被标成 qfq"""
        _patch(monkeypatch, lambda url: _Resp(PAYLOAD_BARE_DAY))
        bars, actual = QuoteService()._tencent_kline(
            '600000', 'daily', 10, 'qfq', return_adjust=True)
        assert bars and actual == 'raw', \
            f"裸 day payload 必须标 raw, 实际标了 {actual!r} (raw 冒充 qfq 入库的根因)"

    def test_qfqday_payload_labeled_qfq(self, monkeypatch):
        _patch(monkeypatch, lambda url: _Resp(PAYLOAD_QFQ))
        bars, actual = QuoteService()._tencent_kline(
            '600000', 'daily', 10, 'qfq', return_adjust=True)
        assert bars and actual == 'qfq'

    def test_noaj_degrade_labeled_raw(self, monkeypatch):
        """fqkline 被拦(无响应) → NOAJ 降级端点 → 恒 raw"""
        def by_url(url):
            if url == q.TENCENT_KL:
                return None
            return _Resp(PAYLOAD_BARE_DAY)
        _patch(monkeypatch, by_url)
        bars, actual = QuoteService()._tencent_kline(
            '600000', 'daily', 10, 'qfq', return_adjust=True)
        assert bars and actual == 'raw'

    def test_default_return_keeps_list_shape(self, monkeypatch):
        """return_adjust=False 向后兼容：只返回 bars 列表"""
        _patch(monkeypatch, lambda url: _Resp(PAYLOAD_QFQ))
        out = QuoteService()._tencent_kline('600000', 'daily', 10, 'qfq')
        assert isinstance(out, list) and out[0]['close'] == pytest.approx(12.0)


class TestState2NeverPoisonsStore:
    def test_kline_state2_writes_raw_not_qfq(self, monkeypatch, tmp_path):
        """端到端：state-2 数据经 kline() 回写只能落 raw 行, qfq 查询不得命中"""
        import data.market_store as ms
        _patch(monkeypatch, lambda url: _Resp(PAYLOAD_BARE_DAY))
        monkeypatch.setenv("AANA_MARKET_STORE_DB", str(tmp_path / "s.db"))
        kl = QuoteService().kline('600000', count=1, adjust='qfq',
                                  allow_sina_fallback=False)
        assert kl and kl[0]['close'] == pytest.approx(12.0)
        assert ms.load_kline_cached('600000', count=1, adjust='qfq') == [], \
            "qfq 查询不得命中 raw 数据 (002178 事故防线)"
        st = ms.MarketStore()
        assert st.has_bar('600000', '2026-11-03', 'raw'), "应如实落 raw 行"

    def test_sync_refuses_state2(self, monkeypatch, tmp_path):
        """sync_day 遇 state-2 → 计 missing, 零 qfq 入库"""
        import data.market_store as ms
        _patch(monkeypatch, lambda url: _Resp(PAYLOAD_BARE_DAY))
        monkeypatch.setenv("AANA_MARKET_STORE_DB", str(tmp_path / "s.db"))
        st = ms.MarketStore()
        r = st.sync_day('2026-11-03', symbols=['600000'], adjust='qfq',
                        qs=QuoteService(), sleeper=lambda s: None)
        assert r.missing == 1 and r.inserted_rows == 0
        assert not st.has_bar('600000', '2026-11-03', 'qfq')

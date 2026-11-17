#!/usr/bin/env python3
"""
tests/test_kline_field_mapping.py — v2026-10-29 腾讯 K 线字段错位 P0 回归测试

**背景 (P0)**:
腾讯 fqkline 每根 bar 的真实字段顺序是::

    [date, open, close, high, low, volume]

AAna 原实现 (data/quotes.py + aana_afternoon_screen.py + daily_v24_sell.py
+ fund_comparison.py + 5 个 backtest 脚本) 写成了::

    [date, open, high, low, close, volume]      # ← 三重错位

后果:
- "close" 实际取到 **最低价** → 所有收益率 = (最低价 - 最低价)/最低价,
  系统性偏低 (当天跌幅越大偏得越多) → 实测 14 只样本胜率 93% (错位) vs
  50% (正确), **虚构了近乎翻倍的胜率**;
- "high"/"low" 互换 → low > high (物理不可能) → 止盈止损判定全错;
- MA / MACD / RSI / 20 日区间位置全部基于错的收盘价 → 选股评分失真。

**三重独立证据** (2026-10-29):
1. 新浪实时 hq.sinajs.cn 逐项比对: 正确映射 14/14 匹配, 错位映射 0/14;
2. 内部不变量 low <= open <= high: 正确映射 0% 违例, 错位映射 99.4% 违例;
3. 本仓库 scripts/deep_analysis_2026*.py 一直用 k[2]=close / k[3]=high /
   k[4]=low (正确), 与被测模块相互矛盾 —— 仓库内部自证。

**本测试锁定**:
- 解析器把 bar[2] 当 close, bar[3] 当 high, bar[4] 当 low (用假数据, 不依赖网络);
- 解析出来的 bar 满足 low <= open <= high 且 close ∈ [low, high];
- 被测模块之间字段语义一致 (防止再次各写各的)。
"""
import os
import sys

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))
sys.path.insert(0, PROJECT)

from data.quotes import QuoteService  # noqa: E402


# ── 构造一条「形状正确」的腾讯 bar ──────────────────────────────────────────
# 真实腾讯 bar: [date, open, close, high, low, vol]
# 这里刻意让 4 个价格互不相同, 且 high 明显 > close > open > low,
# 这样任何一种错位映射都立刻暴露 (而不是碰巧相等而测不出来)。
FAKE_BAR = ['2026-10-29', '10.00', '12.00', '13.00', '9.00', '123456.0']
# 腾讯 fqkline 响应结构: data → <mkt><code> → qfqday / day
FAKE_RAW = {'code': 0, 'msg': '', 'data': {'sh600000': {'qfqday': [FAKE_BAR]}}}


@pytest.fixture
def patched_tencent(monkeypatch):
    """把 _tencent_kline 依赖的 HTTP 返回替换成 FAKE_RAW。"""
    import json

    import data.quotes as q

    class _Resp:
        status_code = 200
        text = 'kline_dayqfq=' + json.dumps(FAKE_RAW)

    monkeypatch.setattr(q, '_retry_req', lambda *a, **k: _Resp())
    return q


class TestTencentKlineFieldMapping:
    """腾讯 bar 字段顺序: [date, open, close, high, low, vol]"""

    def test_close_is_bar_index_2(self, patched_tencent):
        """close 必须取 bar[2] (原实现取 bar[4] = 最低价)"""
        kl = patched_tencent.QuoteService()._tencent_kline('600000', 'daily', 10, 'qfq')
        assert len(kl) == 1, "应解析出 1 根 bar"
        bar = kl[0]
        assert bar['close'] == pytest.approx(12.00), \
            f"close 应为 bar[2]=12.00, 实际 {bar['close']} (错位映射会取到 9.00 最低价)"
        assert bar['high'] == pytest.approx(13.00), \
            f"high 应为 bar[3]=13.00, 实际 {bar['high']}"
        assert bar['low'] == pytest.approx(9.00), \
            f"low 应为 bar[4]=9.00, 实际 {bar['low']}"
        assert bar['open'] == pytest.approx(10.00), \
            f"open 应为 bar[1]=10.00, 实际 {bar['open']}"

    def test_no_physically_impossible_bar(self, patched_tencent):
        """真实 bar 必满足 low <= open <= high —— 错位映射会产出 low > high"""
        kl = patched_tencent.QuoteService()._tencent_kline('600000', 'daily', 10, 'qfq')
        for bar in kl:
            assert bar['low'] <= bar['open'] <= bar['high'], \
                f"违反 low<=open<=high: {bar} (字段错位)"
            assert bar['low'] <= bar['close'] <= bar['high'], \
                f"close 不在 [low, high] 区间: {bar} (字段错位)"

    def test_kline_public_api_uses_same_mapping(self, patched_tencent):
        """kline() 公开 API 与 _tencent_kline 必须同语义 (不能一个修一个没修)"""
        qs = patched_tencent.QuoteService()
        kl = qs.kline('600000', count=10, adjust='qfq', allow_sina_fallback=False)
        assert len(kl) == 1
        assert kl[0]['close'] == pytest.approx(12.00)


class TestFieldSemanticsConsistentAcrossModules:
    """防复发: 各模块对腾讯 bar 的字段理解必须一致 (历史上各写各的)"""

    def test_other_modules_use_same_index(self):
        """daily_v24_sell / aana_afternoon_screen / fund_comparison 源码级校验"""
        import re

        checks = [
            (os.path.join(PROJECT, 'scripts', 'daily_v24_sell.py'),
             "'close': float(last[2])"),
            (os.path.join(PROJECT, 'scripts', 'aana_afternoon_screen.py'),
             "'close': float(item[2])"),
            (os.path.join(PROJECT, 'data', 'fund_comparison.py'),
             "'close': float(x[2])"),
        ]
        for path, needle in checks:
            assert os.path.exists(path), f"文件缺失: {path}"
            with open(path, encoding='utf-8') as f:
                src = f.read()
            assert needle in src, (
                f"{os.path.basename(path)} 必须用 {needle} "
                f"(腾讯 bar[2]=close) —— 若退回到 bar[4] 即为字段错位复发"
            )
            # 旧错位写法不应再出现
            assert not re.search(r"'close':\s*(float|_sf)\(\w+\[4\]\)", src), (
                f"{os.path.basename(path)} 仍存在 'close' 取 bar[4] 的错位写法"
            )


class TestReturnCalculationUsesClose:
    """收益率必须基于真实收盘价 —— 这是本 P0 的实际受害面"""

    def test_future_close_uses_close_field(self, patched_tencent):
        """feedback_loop._future_close 应基于 close 而非最低价"""
        from feedback_loop import _future_close, _get_kline_close

        patched_tencent.QuoteService()
        bars = [{'date': '2026-10-29', 'open': 10.0, 'close': 12.0,
                 'high': 13.0, 'low': 9.0, 'vol': 100.0}]
        import feedback_loop as fl
        fl._KLINE_CACHE['600000'] = bars
        price, _ = _get_kline_close('600000', '2026-10-29')
        assert price == pytest.approx(12.0), \
            f"基准价应取 close=12.0, 实际 {price} (取到最低价会系统性压低收益率)"


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))

#!/usr/bin/env python3
"""
tests/test_market_store.py — XWI-80 P0-1 本地日线库 market_store 测试

锁定三件事：
1. 幂等：同批数据重复写入行数不变（借鉴 Sequoia-X 按 date 先 DELETE 再
   append 的设计，AAna 按 (symbol, adjust, date) 精细删除）；
2. 零网络：已入库自动 skip（断点续传），缓存命中路径不触发任何网络函数
   —— monkeypatch 掉网络层，断言 0 次调用；
3. 复权口径显式化：qfq/hfq/raw 分行存储分行查询，绝不互串 —— 新浪
   fallback（raw）与腾讯 NOAJ 降级（raw）拿到的数据绝不伪装成 qfq 入库
   （002178 3.73pp 假跌幅事故的根因，见 data/quotes.py kline docstring）。

全部用临时库（conftest 的 AANA_MARKET_STORE_DB 环境变量 + 显式 db_path），
不依赖网络、不碰 ~/.aana/ 生产库。
"""
import sqlite3
import sys

import pytest

from data import market_store as ms
from data.quotes import QuoteService


def mk_bar(date, close=10.0, vol=100.0):
    return {'date': date, 'open': close - 0.5, 'high': close + 1.0,
            'low': close - 1.0, 'close': close, 'vol': vol}


def make_store(tmp_path):
    return ms.MarketStore(db_path=str(tmp_path / "t.db"))


# ── 存储 / 查询 API ─────────────────────────────────────────────────────────

class TestStoreApi:
    def test_save_and_load_roundtrip(self, tmp_path):
        """存 3 根 qfq bar，load 出同数据（升序、字段 shape 同 kline）"""
        st = make_store(tmp_path)
        bars = [mk_bar('2026-01-05', 10.0), mk_bar('2026-01-06', 10.5),
                mk_bar('2026-01-07', 11.0)]
        assert st.save_bars('600000', bars, adjust='qfq') == 3
        out = st.load_kline('600000', count=3, adjust='qfq')
        assert [b['date'] for b in out] == ['2026-01-05', '2026-01-06', '2026-01-07']
        assert out[0]['close'] == 10.0 and out[2]['close'] == 11.0
        for b in out:
            assert {'date', 'open', 'high', 'low', 'close', 'vol'} <= set(b)

    def test_load_desc_limit(self, tmp_path):
        """load_kline(count=N) 返回最新的 N 根（不是最老的）"""
        st = make_store(tmp_path)
        bars = [mk_bar(f'2026-01-{d:02d}', float(d)) for d in range(1, 11)]
        st.save_bars('600000', bars, adjust='qfq')
        out = st.load_kline('600000', count=3, adjust='qfq')
        assert [b['date'] for b in out] == ['2026-01-08', '2026-01-09', '2026-01-10']

    def test_load_insufficient_rows_returns_empty(self, tmp_path):
        """库里不足 count 根 → 返回 []（宁缺毋滥，让 kline() 回网络补全量）"""
        st = make_store(tmp_path)
        st.save_bars('600000', [mk_bar('2026-01-05')], adjust='qfq')
        assert st.load_kline('600000', count=30, adjust='qfq') == []

    def test_idempotent_rewrite(self, tmp_path):
        """同批数据写两次 → 行数不变（先 DELETE 再 INSERT，幂等重跑安全）"""
        st = make_store(tmp_path)
        bars = [mk_bar('2026-01-05', 10.0), mk_bar('2026-01-06', 10.5)]
        st.save_bars('600000', bars, adjust='qfq')
        st.save_bars('600000', bars, adjust='qfq')  # 原样重跑
        assert st.stats()['rows'] == 2
        # 覆盖更新（价格修正场景）：重写同一日期不同价，行数仍不变
        fixed = [mk_bar('2026-01-05', 10.2), mk_bar('2026-01-06', 10.7)]
        st.save_bars('600000', fixed, adjust='qfq')
        assert st.stats()['rows'] == 2
        assert st.load_kline('600000', count=2, adjust='qfq')[0]['close'] == 10.2

    def test_invalid_bars_not_written(self, tmp_path):
        """缺 date/close 的脏 bar 不入库"""
        st = make_store(tmp_path)
        dirty = [{'open': 1, 'close': 2}, {'date': '2026-01-05'},
                 mk_bar('2026-01-06')]
        assert st.save_bars('600000', dirty, adjust='qfq') == 1


# ── 复权口径显式化 ──────────────────────────────────────────────────────────

class TestAdjustCaliber:
    def test_adjust_isolation(self, tmp_path):
        """同 (symbol,date) 的 qfq 与 raw 分行存储，查询互不串（qfq/hfq 不混）"""
        st = make_store(tmp_path)
        st.save_bars('600000', [mk_bar('2026-01-05', close=10.0)], adjust='qfq')
        st.save_bars('600000', [mk_bar('2026-01-05', close=9.0)], adjust='raw')
        st.save_bars('600000', [mk_bar('2026-01-05', close=8.0)], adjust='hfq')
        assert st.stats()['rows'] == 3  # 三口径各一行，互不覆盖
        assert st.load_kline('600000', count=1, adjust='qfq')[0]['close'] == 10.0
        assert st.load_kline('600000', count=1, adjust='raw')[0]['close'] == 9.0
        assert st.load_kline('600000', count=1, adjust='hfq')[0]['close'] == 8.0

    def test_has_bar_is_adjust_aware(self, tmp_path):
        """has_bar 口径敏感：qfq 入库 ≠ raw 已入库"""
        st = make_store(tmp_path)
        assert st.has_bar('600000', '2026-01-05', adjust='qfq') is False
        st.save_bars('600000', [mk_bar('2026-01-05')], adjust='qfq')
        assert st.has_bar('600000', '2026-01-05', adjust='qfq') is True
        assert st.has_bar('600000', '2026-01-05', adjust='raw') is False

    def test_normalize_adjust(self):
        assert ms.normalize_adjust('qfq') == 'qfq'
        assert ms.normalize_adjust('QFQ') == 'qfq'
        assert ms.normalize_adjust('hfq') == 'hfq'
        assert ms.normalize_adjust('') == 'raw'
        assert ms.normalize_adjust(None) == 'raw'
        assert ms.normalize_adjust('raw') == 'raw'

    def test_stats_by_adjust(self, tmp_path):
        st = make_store(tmp_path)
        st.save_bars('600000', [mk_bar('2026-01-05')], adjust='qfq')
        st.save_bars('000001', [mk_bar('2026-01-05'), mk_bar('2026-01-06')],
                     adjust='raw')
        s = st.stats()
        assert s['rows'] == 3 and s['symbols'] == 2
        assert s['by_adjust'] == {'qfq': 1, 'raw': 2}
        assert s['min_date'] == '2026-01-05' and s['max_date'] == '2026-01-06'


# ── sync_day：skip 断点续传 / 重试 / 幂等 ──────────────────────────────────

class FakeQS:
    """替身 QuoteService：_tencent_kline 调用可数，返回预置数据
    （sync_day 走 _tencent_kline(return_adjust=True) 精确拿口径，不走 kline()）"""

    def __init__(self, plan=None):
        self.plan = plan or {}   # {code: bars 或 Exception}
        self.calls = []

    def _tencent_kline(self, code, period='daily', count=30, adjust='qfq',
                       return_adjust=False):
        self.calls.append(code)
        v = self.plan.get(code)
        if isinstance(v, Exception):
            raise v
        bars = v or []
        return (bars, ms.normalize_adjust(adjust)) if return_adjust else bars


class TestSyncDay:
    def test_sync_skip_existing_zero_network(self, tmp_path):
        """已入库自动 skip：网络函数 0 次调用（断点续传 + 二次零网络）"""
        st = make_store(tmp_path)
        st.save_bars('600000', [mk_bar('2026-01-05')], adjust='qfq')
        st.save_bars('000001', [mk_bar('2026-01-05')], adjust='qfq')
        fake = FakeQS()
        r = st.sync_day('2026-01-05', symbols=['600000', '000001'],
                        adjust='qfq', qs=fake)
        assert fake.calls == [], "已入库股票不应触发任何网络请求"
        assert r.skipped == 2 and r.inserted_rows == 0
        assert st.stats()['rows'] == 2

    def test_sync_fetches_missing_then_zero_network(self, tmp_path):
        """缺的拉网络入库；再 sync 同一天 → 0 网络 0 新增，行数一致"""
        st = make_store(tmp_path)
        fake = FakeQS(plan={'600000': [mk_bar('2026-01-05', 10.0)]})
        r1 = st.sync_day('2026-01-05', symbols=['600000', '000001'],
                         adjust='qfq', qs=fake)
        assert fake.calls.count('600000') == 1 and '000001' in fake.calls
        assert r1.inserted_rows == 1 and r1.missing == 1  # 000001 无该日数据
        rows_after_first = st.stats()['rows']
        n_calls_after_first = len(fake.calls)

        r2 = st.sync_day('2026-01-05', symbols=['600000'], adjust='qfq', qs=fake)
        assert len(fake.calls) == n_calls_after_first, "第二次 sync 不应再触网"
        assert r2.skipped == 1 and r2.inserted_rows == 0
        assert st.stats()['rows'] == rows_after_first, "第二次 stats 行数与第一次一致"

    def test_sync_retry_exponential_backoff(self, tmp_path):
        """单只失败指数退避重试（2**attempt），最终成功"""
        st = make_store(tmp_path)
        sleeps = []

        class FlakyQS(FakeQS):
            def _tencent_kline(self, code, period='daily', count=30,
                               adjust='qfq', return_adjust=False):
                self.calls.append(code)
                if len(self.calls) < 3:  # 前 2 次抛异常，第 3 次成功
                    raise ConnectionError('WAF')
                bars = [mk_bar('2026-01-05')]
                return (bars, 'qfq') if return_adjust else bars

        r = st.sync_day('2026-01-05', symbols=['600000'], adjust='qfq',
                        qs=FlakyQS(), sleeper=sleeps.append)
        assert r.inserted_rows == 1 and r.failed == 0
        assert sleeps == [1.0, 2.0], "退避应为 base * 2**attempt"

    def test_sync_failure_does_not_block_others(self, tmp_path):
        """单只彻底失败只计 failed，不影响其它股票入库"""
        st = make_store(tmp_path)
        fake = FakeQS(plan={'600000': RuntimeError('down'),
                            '000001': [mk_bar('2026-01-05')]})
        sleeps = []
        r = st.sync_day('2026-01-05', symbols=['600000', '000001'],
                        adjust='qfq', qs=fake, sleeper=sleeps.append)
        assert r.failed == 1 and r.inserted_rows == 1
        assert st.has_bar('000001', '2026-01-05', adjust='qfq')

    def test_sync_only_writes_target_date(self, tmp_path):
        """sync_day 只落目标日期的 bar（网络拉回的是多日窗口）"""
        st = make_store(tmp_path)
        window = [mk_bar('2026-01-02'), mk_bar('2026-01-05'),
                  mk_bar('2026-01-06')]
        st.sync_day('2026-01-05', symbols=['600000'], adjust='qfq',
                    qs=FakeQS(plan={'600000': window}))
        out = st.load_kline('600000', count=1, adjust='qfq')
        assert [b['date'] for b in out] == ['2026-01-05']

    def test_sync_rejects_caliber_mismatch(self, tmp_path):
        """请求 qfq 实得 raw（NOAJ 降级）→ 不入库计 missing，绝不拿 raw 凑数"""
        st = make_store(tmp_path)

        class DegradedQS(FakeQS):
            def _tencent_kline(self, code, period='daily', count=30,
                               adjust='qfq', return_adjust=False):
                self.calls.append(code)
                bars = [mk_bar('2026-01-05', close=8.8)]
                return (bars, 'raw') if return_adjust else bars

        r = st.sync_day('2026-01-05', symbols=['600000'], adjust='qfq',
                        qs=DegradedQS())
        assert r.inserted_rows == 0 and r.missing == 1
        assert not st.has_bar('600000', '2026-01-05', adjust='qfq')


# ── quotes.kline() store 优先 / 网络兜底 / 口径如实回写 ────────────────────

class TestKlineStoreIntegration:
    def test_store_hit_zero_network(self, tmp_path, monkeypatch):
        """缓存命中：monkeypatch 网络层为必炸桩，断言不触发且返回缓存"""
        db = str(tmp_path / "k.db")
        monkeypatch.setenv("AANA_MARKET_STORE_DB", db)
        bars = [mk_bar(f'2026-01-{d:02d}', close=float(d)) for d in range(1, 6)]
        ms.MarketStore(db_path=db).save_bars('600000', bars, adjust='qfq')

        def bomb(*a, **k):
            raise AssertionError("缓存命中路径不应触发网络")

        monkeypatch.setattr(QuoteService, '_tencent_kline', bomb)
        monkeypatch.setattr(QuoteService, '_sina_kline_fallback', bomb)
        out = QuoteService().kline('600000', count=5, adjust='qfq')
        assert len(out) == 5 and out[-1]['close'] == 5.0

    def test_network_miss_writes_store_then_second_call_cached(self, tmp_path,
                                                               monkeypatch):
        """库空 → 网络兜底 → 回写；第二次调用零网络（桩不再被调）"""
        db = str(tmp_path / "k.db")
        monkeypatch.setenv("AANA_MARKET_STORE_DB", db)
        calls = []

        def fake_tk(self, code, period, count, adjust, return_adjust=False):
            calls.append(code)
            bars = [mk_bar(f'2026-01-{d:02d}') for d in range(1, 6)]
            return (bars, ms.normalize_adjust(adjust)) if return_adjust else bars

        monkeypatch.setattr(QuoteService, '_tencent_kline', fake_tk)
        out1 = QuoteService().kline('600000', count=5, adjust='qfq')
        assert len(out1) == 5
        assert ms.MarketStore(db_path=db).stats()['by_adjust'] == {'qfq': 5}
        n = len(calls)
        out2 = QuoteService().kline('600000', count=5, adjust='qfq')
        assert len(calls) == n, "回写后第二次 kline() 应走 store，不再触网"
        assert out2 == out1

    def test_sina_fallback_stored_as_raw_never_qfq(self, tmp_path, monkeypatch):
        """新浪 fallback = 不复权：只能以 raw 入库，qfq 查询绝不命中它"""
        db = str(tmp_path / "k.db")
        monkeypatch.setenv("AANA_MARKET_STORE_DB", db)

        def no_tencent(self, code, period, count, adjust, return_adjust=False):
            return ([], None) if return_adjust else []

        def sina(self, code, count):
            return [mk_bar('2026-01-05', close=9.9)]

        monkeypatch.setattr(QuoteService, '_tencent_kline', no_tencent)
        monkeypatch.setattr(QuoteService, '_sina_kline_fallback', sina)
        out = QuoteService().kline('600000', count=1, adjust='qfq',
                                   allow_sina_fallback=True)
        assert len(out) == 1 and out[0]['close'] == 9.9  # 兼容：数据照返回
        st = ms.MarketStore(db_path=db)
        assert st.load_kline('600000', count=1, adjust='raw')[0]['close'] == 9.9
        assert st.load_kline('600000', count=1, adjust='qfq') == [], \
            "raw 数据绝不能伪装成 qfq 被命中（002178 事故根因）"

    def test_noaj_degrade_stored_as_raw(self, tmp_path, monkeypatch):
        """腾讯 NOAJ 降级端点 = 不复权：请求 qfq 实得 raw，入库必须标 raw"""
        db = str(tmp_path / "k.db")
        monkeypatch.setenv("AANA_MARKET_STORE_DB", db)

        def degraded(self, code, period, count, adjust, return_adjust=False):
            bars = [mk_bar('2026-01-05', close=8.8)]
            return (bars, 'raw') if return_adjust else bars

        monkeypatch.setattr(QuoteService, '_tencent_kline', degraded)
        out = QuoteService().kline('600000', count=1, adjust='qfq')
        assert out[0]['close'] == 8.8  # 向后兼容：行为不变
        st = ms.MarketStore(db_path=db)
        assert st.has_bar('600000', '2026-01-05', adjust='raw')
        assert not st.has_bar('600000', '2026-01-05', adjust='qfq')

    def test_today_bar_not_cached(self, tmp_path, monkeypatch):
        """当日未收盘 bar 不回写（盘中快照不入库，收盘后由 --sync 落最终值）"""
        db = str(tmp_path / "k.db")
        monkeypatch.setenv("AANA_MARKET_STORE_DB", db)
        monkeypatch.setattr(ms, '_today', lambda: '2026-01-06')

        def fake_tk(self, code, period, count, adjust, return_adjust=False):
            bars = [mk_bar('2026-01-05'), mk_bar('2026-01-06', 99.0)]
            return (bars, 'qfq') if return_adjust else bars

        monkeypatch.setattr(QuoteService, '_tencent_kline', fake_tk)
        QuoteService().kline('600000', count=2, adjust='qfq')
        st = ms.MarketStore(db_path=db)
        assert st.has_bar('600000', '2026-01-05', adjust='qfq')
        assert not st.has_bar('600000', '2026-01-06', adjust='qfq')

    def test_store_off_env_disables(self, tmp_path, monkeypatch):
        """AANA_MARKET_STORE_DB=off → store 关闭，kline() 纯网络（逃生门）"""
        monkeypatch.setenv("AANA_MARKET_STORE_DB", "off")

        def fake_tk(self, code, period, count, adjust, return_adjust=False):
            bars = [mk_bar('2026-01-05')]
            return (bars, 'qfq') if return_adjust else bars

        monkeypatch.setattr(QuoteService, '_tencent_kline', fake_tk)
        out = QuoteService().kline('600000', count=1, adjust='qfq')
        assert len(out) == 1
        assert ms.load_kline_cached('600000', count=1, adjust='qfq') == []

    def test_store_failure_never_breaks_kline(self, tmp_path, monkeypatch):
        """store 抛异常不影响 kline() 主链路（行情可用性 > 缓存）"""
        def bomb(*a, **k):
            raise sqlite3.DatabaseError("corrupt")

        monkeypatch.setattr(ms, 'load_kline_cached', bomb)
        monkeypatch.setattr(ms, 'save_kline_cached', bomb)

        def fake_tk(self, code, period, count, adjust, return_adjust=False):
            bars = [mk_bar('2026-01-05')]
            return (bars, 'qfq') if return_adjust else bars

        monkeypatch.setattr(QuoteService, '_tencent_kline', fake_tk)
        out = QuoteService().kline('600000', count=1, adjust='qfq')
        assert len(out) == 1


# ── CLI 入口 ────────────────────────────────────────────────────────────────

class TestCli:
    def test_sync_and_stats_output(self, tmp_path, monkeypatch, capsys):
        db = str(tmp_path / "cli.db")
        monkeypatch.setenv("AANA_MARKET_STORE_DB", db)
        monkeypatch.setattr(ms, 'default_symbols', lambda **kw: ['600000', '000001'])
        fake = FakeQS(plan={'600000': [mk_bar('2026-01-05')],
                            '000001': [mk_bar('2026-01-05')]})

        class _QS:
            def _tencent_kline(self, *a, **k):
                return fake._tencent_kline(*a, **k)

        monkeypatch.setattr('data.market_store._new_quote_service', lambda: _QS())
        code = ms.main(['--sync', '--date', '2026-01-05', '--stats'])
        out = capsys.readouterr().out
        assert code == 0
        assert 'inserted=2' in out and '[stats]' in out and 'rows=2' in out


# ── 默认股票池 ─────────────────────────────────────────────────────────────

class TestDefaultSymbols:
    def test_reads_groups_and_csv(self, tmp_path, monkeypatch):
        """默认池 = groups.json 最新组 ∪ rec_feedback/recommendations 近期 code"""
        import csv
        data_dir = tmp_path / "d"
        data_dir.mkdir()
        (data_dir / "groups.json").write_text(
            '{"20260101": {"stocks": ["600001"]}, "20260105": {"stocks": ["600002"]}}',
            encoding='utf-8')
        with open(data_dir / "rec_feedback.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(['date', 'code'])
            w.writerow(['2026-01-04', '300001'])
            w.writerow(['2025-01-01', '300999'])   # 太老，应被过滤
        with open(data_dir / "recommendations.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(['date', 'code'])
            w.writerow(['2026-01-05', '600003'])

        syms = ms.default_symbols(data_dir=str(data_dir), today='2026-01-06')
        assert syms == ['600002', '300001', '600003']


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))

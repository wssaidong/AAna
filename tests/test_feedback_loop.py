"""
tests/test_feedback_loop.py — 反馈闭环回归测试

锁定 2026-08-13 修复的 6 个 bug（详见
~/.hermes/skills/a-stock/a-stock-system/references/feedback-loop-silent-empty-2026-08-13.md）。
全部为纯静态/纯内存测试，不联网、不碰真实 data/ 文件。
"""
import os, sys, csv, json, tempfile, warnings
warnings.filterwarnings('ignore')

PROJECT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, PROJECT)
sys.path.insert(0, os.path.join(PROJECT, 'scripts'))

import feedback_loop as fb


# ── 测试夹具 ────────────────────────────────────────────────────────────────

BARS = [  # 升序（旧 → 新），与 QuoteService 真实顺序一致
    {"date": "2026-06-01", "close": 10.0},
    {"date": "2026-06-02", "close": 11.0},
    {"date": "2026-06-03", "close": 12.0},
    {"date": "2026-06-04", "close": 13.0},
    {"date": "2026-06-05", "close": 14.0},  # 周五
    # 周末缺口：6/6、6/7 无 K 线
    {"date": "2026-06-08", "close": 15.0},
]


def _stub_kline(monkeypatch, bars=BARS, code="TEST01"):
    """把 K 线缓存直接灌好，绕过网络。"""
    fb._KLINE_CACHE.clear()
    fb._KLINE_CACHE[code] = bars
    return code


# ── bug#2: 找不到目标日回退 klines[0]（升序=最老一根）────────────────────────

def test_missing_date_returns_none_not_oldest_bar(monkeypatch):
    """
    回归 bug#2：旧实现找不到目标日就回退 klines[0]。
    K 线是升序 → [0] 是**最老**一根，可能是几个月前的价格，
    会静默算出 -58% 这类天文数字。现在必须返回 None。
    """
    code = _stub_kline(monkeypatch)
    price, _ = fb._get_kline_close(code, "2020-01-01")  # 远早于所有 K 线
    assert price is None, "早于全部K线时必须返回 None，绝不能回退到最老一根"


def test_lookup_falls_back_to_prior_trading_day():
    """非交易日（周末）应取之前最近一个交易日，而不是 None、更不是最老一根。"""
    code = _stub_kline(None)
    price, date = fb._get_kline_close(code, "2026-06-07")  # 周日
    assert (price, date) == (14.0, "2026-06-05"), "周末应回落到上一个交易日"


def test_exact_date_hit():
    code = _stub_kline(None)
    assert fb._get_kline_close(code, "2026-06-03") == (12.0, "2026-06-03")


# ── bug#3: 用日历日 +N 天取收益，遇周末必落空 ──────────────────────────────

def test_future_close_walks_trading_days_not_calendar_days():
    """
    回归 bug#3：6/5(周五) 的「+1 日」应是 6/8(周一)，
    旧实现按日历日会落在 6/6(周六) → 查不到 → 触发 bug#2 的错误回退。
    """
    code = _stub_kline(None)
    assert fb._future_close(code, "2026-06-05", 1) == (15.0, "2026-06-08")


def test_future_close_returns_none_when_not_enough_bars():
    """未来 bar 不够时留空，而不是拿最后一根充数（否则 ret_15d 会假装已实现）。"""
    code = _stub_kline(None)
    assert fb._future_close(code, "2026-06-05", 15) == (None, None)


# ── bug#4/#5: 写 CSV 抹列 + 去重导致永不回填 ────────────────────────────────

def _write_csv(path, fields, rows):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def test_append_feedback_preserves_extra_columns_and_backfills(monkeypatch):
    """
    回归 bug#4（抹列）+ bug#5（永不回填）：
    - score 等非标准列必须保留（rec_optimizer.py 依赖）
    - 已存在但 ret_* 为空的行必须被补上，而不是被去重丢弃
    """
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, 'rec_feedback.csv')
    fields = fb.FEEDBACK_FIELDS + ['score', 'macd_gold']
    _write_csv(path, fields, [{
        'date': '2026-06-01', 'code': 'TEST01', 'name': '测试', 'rec_date': '2026-06-01',
        'trend': '', 'ret_1d': '', 'ret_3d': '', 'ret_5d': '', 'ret_15d': '',
        'score': '100', 'macd_gold': 'True',
    }])

    monkeypatch.setattr(fb, 'FEEDBACK_CSV', __import__('pathlib').Path(path))
    added, backfilled = fb.append_feedback([{
        'date': '2026-06-08', 'code': 'TEST01', 'name': '测试', 'rec_date': '2026-06-01',
        'trend': '上升', 'ret_1d': '1.5', 'ret_3d': '', 'ret_5d': '', 'ret_15d': '',
    }])

    rows = list(csv.DictReader(open(path, encoding='utf-8')))
    assert (added, backfilled) == (0, 1), "同 (code,rec_date) 应回填而非新增"
    assert len(rows) == 1, "不应产生重复行"
    assert rows[0]['score'] == '100', "score 列被抹掉了（rec_optimizer 依赖它）"
    assert rows[0]['macd_gold'] == 'True', "macd_gold 列被抹掉了"
    assert rows[0]['ret_1d'] == '1.5', "空的 ret_1d 应被回填"


def test_append_feedback_never_overwrites_existing_values(monkeypatch):
    """回填只补空字段，绝不覆盖已算好的值。"""
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, 'rec_feedback.csv')
    _write_csv(path, fb.FEEDBACK_FIELDS, [{
        'date': '2026-06-01', 'code': 'TEST01', 'name': '测试', 'rec_date': '2026-06-01',
        'trend': '震荡', 'ret_1d': '2.22', 'ret_3d': '', 'ret_5d': '', 'ret_15d': '',
    }])
    monkeypatch.setattr(fb, 'FEEDBACK_CSV', __import__('pathlib').Path(path))
    fb.append_feedback([{
        'date': '2026-06-08', 'code': 'TEST01', 'name': '测试', 'rec_date': '2026-06-01',
        'trend': '上升', 'ret_1d': '9.99', 'ret_3d': '3.3', 'ret_5d': '', 'ret_15d': '',
    }])
    row = list(csv.DictReader(open(path, encoding='utf-8')))[0]
    assert row['ret_1d'] == '2.22', "已有值不得被覆盖"
    assert row['ret_3d'] == '3.3', "空值应被补上"


# ── 统计层 sanity check：物理不可能的收益率必须被剔除 ────────────────────────

def test_stats_drops_physically_impossible_returns():
    """A股单日涨跌上限 ±20%，|ret_1d|>22% 一律视为脏数据（对齐 SKILL.md 阈值表）。"""
    rows = [
        {'code': 'A', 'rec_date': '2026-06-01', 'trend': '震荡', 'ret_1d': '-58.18'},  # 脏
        {'code': 'B', 'rec_date': '2026-06-01', 'trend': '震荡', 'ret_1d': '2.0'},
        {'code': 'C', 'rec_date': '2026-06-01', 'trend': '震荡', 'ret_1d': '-1.0'},
    ]
    _, total, winrate, _, _, _ = fb.compute_stats(rows, top_n=20)
    assert total == 2, "-58.18% 属物理不可能，必须被剔除"
    assert winrate == 0.5


def test_stats_dedupes_repeated_recommendations():
    """
    同一条推荐被 record_recommendation 多次追加时，
    「最近20只」不应被少数几只重复票占满，否则胜率严重失真。
    """
    rows = [{'code': 'A', 'rec_date': '2026-06-01', 'trend': '震荡', 'ret_1d': '-5.0'}] * 8
    rows.append({'code': 'B', 'rec_date': '2026-06-01', 'trend': '震荡', 'ret_1d': '3.0'})
    _, total, winrate, _, _, _ = fb.compute_stats(rows, top_n=20)
    assert total == 2, f"(code,rec_date) 应去重，实得 {total}"
    assert winrate == 0.5


# ── bug#1: 写入/读取源分裂 —— 必须同时读两个源 ──────────────────────────────

def test_loader_merges_both_sources(monkeypatch, tmp_path):
    """
    回归 bug#1：尾盘主链路只写 rec_feedback.csv，
    只读 recommendations.csv 会导致连续 15 天「0 条推荐」静默空跑。
    """
    from datetime import datetime, timedelta
    today = datetime.now().strftime('%Y-%m-%d')
    recent = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')

    rec = tmp_path / 'recommendations.csv'
    _write_csv(str(rec), ['date', 'code', 'name'],
               [{'date': recent, 'code': 'OLD001', 'name': '旧源股'}])

    fbk = tmp_path / 'rec_feedback.csv'
    _write_csv(str(fbk), fb.FEEDBACK_FIELDS,
               [{'date': today, 'code': 'NEW001', 'name': '新源股', 'rec_date': today}])

    monkeypatch.setattr(fb, 'REC_CSV', rec)
    monkeypatch.setattr(fb, 'FEEDBACK_CSV', fbk)

    codes = {r['code'] for r in fb.load_recent_recommendations(days=7)}
    assert codes == {'OLD001', 'NEW001'}, f"两个源都要读到，实得 {codes}"


def test_loader_respects_cutoff(monkeypatch, tmp_path):
    """超出回看窗口的记录不应被捞进来。"""
    fbk = tmp_path / 'rec_feedback.csv'
    _write_csv(str(fbk), fb.FEEDBACK_FIELDS,
               [{'date': '2020-01-01', 'code': 'ANCIENT', 'name': '远古股',
                 'rec_date': '2020-01-01'}])
    monkeypatch.setattr(fb, 'REC_CSV', tmp_path / 'nonexistent.csv')
    monkeypatch.setattr(fb, 'FEEDBACK_CSV', fbk)
    assert fb.load_recent_recommendations(days=7) == []


# ── bug#6: 复权基准混用 ─────────────────────────────────────────────────────

def test_returns_use_single_adjusted_series_not_raw_trade_price():
    """
    回归 bug#6：paper_trades.json 存的是**未复权**成交价，K 线是 **qfq 前复权**。
    两者相除会算出假暴跌（603269 实际 +2.9% 被算成 -34.61%）。
    收益率两端必须来自同一条 qfq 序列。
    """
    code = _stub_kline(None)
    recs = [{'code': code, 'name': '测试', 'date': '2026-06-01'}]
    trades = [{'code': code, 'action': 'buy', 'date': '2026-06-01',
               'price': 99.0, 'shares': 100}]  # 未复权价，与 K 线 10.0 差 10 倍

    row = fb.calculate_returns(recs, trades)[0]
    # 基准应是 qfq 的 10.0 而非 99.0 → 1日收益 = (11-10)/10 = +10%
    assert row['ret_1d'] == 10.0, f"复权基准混用未修复，实得 {row['ret_1d']}"

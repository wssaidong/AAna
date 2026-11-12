"""(ad) D_大盘错配基线修复回归 — 2026-11-12

背景: get_day_baseline 旧实现硬编码 `{date}-复盘报告.md` + `4 大核心平均`,
上游 11-04 起只产 `复盘评分.md` 且字段改版 → D 检测器连续 ~21 天静默禁用。
本文件锁定新契约: 指数日线主源 / 报告备源 (含盘中快照守卫) / 三源皆败显式告警。
"""
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT / "scripts"))

import daily_root_cause as drc  # noqa: E402


# ---------- 指数日线主源 ----------

def _fake_series(dates_closes):
    return [(d, c) for d, c in dates_closes]


def test_kline_baseline_avg_math(monkeypatch):
    """4 指数 close-to-close 均值的算术必须精确"""
    prev = {"sh000001": 100.0, "sz399001": 200.0, "sz399006": 50.0, "sh000688": 1000.0}
    cur = {"sh000001": 99.0, "sz399001": 196.0, "sz399006": 50.5, "sh000688": 1010.0}
    series_map = {
        code: _fake_series([("2026-11-11", prev[code]), ("2026-11-12", cur[code])])
        for code in prev
    }
    monkeypatch.setattr(drc, "_fetch_index_closes", lambda count=30: series_map)
    val, src = drc._core_index_baseline_from_kline("2026-11-12")
    assert val is not None
    expect = sum((cur[c] / prev[c] - 1) * 100 for c in prev) / 4
    assert abs(val - expect) < 1e-9
    assert "2026-11-12" in src


def test_kline_baseline_falls_back_to_latest_common_date(monkeypatch):
    """目标日无 bar (节假日) → 自动落到 4 指数共有的最近交易日"""
    series_map = {}
    for code in ("sh000001", "sz399001", "sz399006", "sh000688"):
        series_map[code] = _fake_series([
            ("2026-11-10", 100.0), ("2026-11-11", 101.0),
        ])
    monkeypatch.setattr(drc, "_fetch_index_closes", lambda count=30: series_map)
    val, src = drc._core_index_baseline_from_kline("2026-11-12")
    assert val == pytest.approx(1.0)  # 100 → 101 = +1% 全部 → 均值 +1%
    assert "2026-11-11" in src


def test_kline_baseline_rejects_when_one_index_missing_date(monkeypatch):
    """任一指数缺当日 bar → 该日不可用 (宁缺毋滥, 不用 3/4 拼均值)"""
    series_map = {}
    for i, code in enumerate(("sh000001", "sz399001", "sz399006", "sh000688")):
        rows = [("2026-11-10", 100.0), ("2026-11-11", 101.0)]
        if code == "sh000688":
            rows = [("2026-11-10", 100.0)]  # 缺 11-11
        series_map[code] = _fake_series(rows)
    monkeypatch.setattr(drc, "_fetch_index_closes", lambda count=30: series_map)
    val, _src = drc._core_index_baseline_from_kline("2026-11-11")
    assert val is None


# ---------- 报告备源 ----------

def test_report_source_reads_new_field_name(tmp_path, monkeypatch):
    """上游文案改版后的「四大核心指数均值」必须能解析 (教训 (s))"""
    monkeypatch.setattr(drc, "REPORTS_DIR", tmp_path)
    content = ("# 复盘\n> 生成时间：2026-11-11 17:05\n"
               "四大核心指数均值 **+1.92%**\n")
    (tmp_path / "2026-11-11-复盘评分.md").write_text(content, encoding="utf-8")
    val, src = drc._baseline_from_report("2026-11-11")
    assert val == pytest.approx(1.92)
    assert "复盘评分" in src


def test_report_source_reads_legacy_field_name(tmp_path, monkeypatch):
    """旧文案「4 大核心平均」兼容不丢"""
    monkeypatch.setattr(drc, "REPORTS_DIR", tmp_path)
    (tmp_path / "2026-11-09-复盘报告.md").write_text(
        "# 复盘\n4 大核心平均 +0.02%\n", encoding="utf-8")
    val, src = drc._baseline_from_report("2026-11-09")
    assert val == pytest.approx(0.02)
    assert "复盘报告" in src


def test_report_source_rejects_intraday_snapshot(tmp_path, monkeypatch):
    """🔴 盘中快照守卫: 09:39 生成的复盘评分含未定格数据, 不得当收盘基线
    (11-12 实测: 表内 +0.10% vs 真实收盘 -0.67%)"""
    monkeypatch.setattr(drc, "REPORTS_DIR", tmp_path)
    (tmp_path / "2026-11-12-复盘评分.md").write_text(
        "# 复盘\n> 生成时间：2026-11-12 09:39\n四大核心指数均值 **+0.10%**\n",
        encoding="utf-8")
    val, _src = drc._baseline_from_report("2026-11-12")
    assert val is None


# ---------- D 检测器 ----------

def test_detector_disabled_when_baseline_none():
    r = drc.detect_大盘错配([{"ret_1d": "-3"}], None)
    assert not r["hit"]
    assert "无大盘数据" in r["summary"]


def test_detector_fires_on_losing_pool_with_real_baseline():
    """基线 -1.02% (11-12 实测值) + 池均值 -2.75% → 必须命中 (修复前: None → 静默禁用)"""
    recs = [{"ret_1d": "-3.0"}, {"ret_1d": "-2.5"}]
    r = drc.detect_大盘错配(recs, -1.016)
    assert r["hit"]


def test_detector_not_fire_when_pool_beats_market():
    r = drc.detect_大盘错配([{"ret_1d": "+1.0"}], -1.016)
    assert not r["hit"]
    assert "跑赢" in r["summary"]


# ---------- 三源皆败 → None (显式告警在 stderr, 由 get_day_baseline_detail 打印) ----------

def test_detail_returns_none_when_all_sources_fail(monkeypatch, capsys):
    monkeypatch.setattr(drc, "_core_index_baseline_from_kline",
                        lambda date: (None, "指数日线缺失"))
    monkeypatch.setattr(drc, "_realtime_core_baseline",
                        lambda: (None, "实时快照拉取失败"))
    monkeypatch.setattr(drc, "_baseline_from_report",
                        lambda date: (None, "无报告产物"))
    val, src = drc.get_day_baseline_detail("2026-01-01", [])
    assert val is None
    assert "三源" in src
    captured = capsys.readouterr()
    assert "⚠️" in captured.err  # 显式告警必须存在 (教训 (u): 静默空 ≠ 正常空)

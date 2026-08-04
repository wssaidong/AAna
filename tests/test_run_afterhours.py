"""Regression tests for A-stock afterhours report correctness."""
from pathlib import Path
import importlib.util


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_afterhours.py"
spec = importlib.util.spec_from_file_location("run_afterhours", SCRIPT)
assert spec is not None and spec.loader is not None
run_afterhours = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_afterhours)


def test_parse_top10_stops_at_next_h3_and_deduplicates(tmp_path, monkeypatch):
    report = tmp_path / "2026-08-04-选股报告.md"
    report.write_text(
        """### 🏆 重点关注 Top 10
| 排名 | 股票 | 代码 | 涨跌幅 |
| 1 | 📊甲 | 600001 | +4.00% |
| 2 | 📊乙 | 600002 | +3.00% |
| 3 | 📊甲重复 | 600001 | +4.00% |
### 🚀 强势股
| 股票 | 代码 | 涨跌幅 |
| 📊丙 | 600003 | +9.99% |
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(run_afterhours, "REPORT_DIR", str(tmp_path))

    assert run_afterhours.parse_top10_with_baseline("2026-08-04") == [
        ("600001", "甲", 4.0),
        ("600002", "乙", 3.0),
    ]


def test_market_feature_distinguishes_tail_surge_from_tail_drop():
    surge = [("创业板指", -1.52, 5.64, 7.16)]
    drop = [("创业板指", 1.12, -3.23, -4.35)]

    assert "假平稳真急涨" in run_afterhours.classify_market_feature(
        3.33, 0.33, 5.64, 4.09, surge
    )
    assert "假突破后尾盘跳水" in run_afterhours.classify_market_feature(
        -1.71, 0.07, -3.23, -2.26, drop
    )


def test_previous_nonempty_hot_day_skips_empty_natural_yesterday(monkeypatch):
    calls = []

    def fake_hot(day):
        calls.append(day)
        if day == "2026-08-03":
            return []
        if day == "2026-08-02":
            return [{"code": "600001"}]
        return []

    monkeypatch.setattr(run_afterhours, "ths_hot", fake_hot)

    day, rows = run_afterhours.previous_nonempty_hot_day("2026-08-04")
    assert day == "2026-08-02"
    assert rows == [{"code": "600001"}]
    assert calls == ["2026-08-03", "2026-08-02"]


def test_dry_run_does_not_overwrite_report(tmp_path, monkeypatch):
    existing = tmp_path / "2026-08-04-盘后战报.md"
    existing.write_text("keep-me", encoding="utf-8")
    monkeypatch.setattr(run_afterhours, "REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(run_afterhours, "generate_full_report", lambda _: ("preview", "new"))
    monkeypatch.setattr(
        run_afterhours.sys,
        "argv",
        ["run_afterhours.py", "2026-08-04", "--dry"],
    )

    run_afterhours.main()

    assert existing.read_text(encoding="utf-8") == "keep-me"


def _minimal_indices():
    return {
        "sh000001": {"current": 3822.28, "change_pct": 0.33},
        "sz399001": {"current": 13885.71, "change_pct": 3.25},
        "sz399006": {"current": 3488.97, "change_pct": 5.64},
        "sz399005": {"current": 8510.13, "change_pct": 2.68},
        "sz399300": {"current": 4600.93, "change_pct": 1.27},
        "sh000688": {"current": 1616.36, "change_pct": 4.09},
    }


def test_feishu_first_line_exposes_generation_and_target_close_time():
    md = run_afterhours.format_feishu(
        "2026-08-04", _minimal_indices(), [], {}, {}, [], [], [],
        0, 0, 0, 0.33, 5.64, 4.09, [], 0,
    )

    first_line = md.splitlines()[0]
    assert "生成时间" in first_line
    assert "目标交易日 2026-08-04 15:00 收盘" in first_line


def test_candidate_stats_include_baseline_continuation_and_core_alpha():
    hit_rows = [
        ("600001", "甲", 4.0, 1.0, -3.0),
        ("600002", "乙", 5.0, -1.0, -6.0),
    ]
    md = run_afterhours.format_feishu(
        "2026-08-04", _minimal_indices(), ["AI应用"], {"AI应用": 2}, {},
        hit_rows, [hit_rows[0]], [hit_rows[1]], 0.0, 1.0, -1.0,
        0.33, 5.64, 4.09, [], 10,
    )

    assert "baseline均值：+4.50%" in md
    assert "2/2 负延续" in md
    assert "vs 四大核心指数均值 +3.33% 超额：**-3.33pp**" in md


def test_final_report_has_no_internal_filesystem_path():
    gap_md = (
        "\n⚠️ **数据口径警示**\n"
        "> 数据源：/Users/cai/code/AAna/reports/2026-08-04/盘中/"
        "2026-08-04_1445_尾盘分析.md（共 4/6 指数）\n"
    )
    md = run_afterhours.format_feishu(
        "2026-08-04", _minimal_indices(), [], {}, {}, [], [], [],
        0, 0, 0, 0.33, 5.64, 4.09, [], 0, gap_md,
    )

    assert "/Users/cai/" not in md
    assert "2026-08-04_1445_尾盘分析.md" in md

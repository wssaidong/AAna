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


# ── 2026-10-21 v1.28 回归测试（三个生产 bug 修复）────────────────────────

def test_industry_bottom_is_worst_first_not_best_first(monkeypatch):
    """东财行业榜：涨幅榜降序、跌幅榜升序（最差在前）。

    2026-10-21 生产 bug：push2 不带 fid=f3 时按板块代码序返回，
    战报"涨幅 Top5"显示的全是负数、"跌幅 Bottom5"全是正数 —— 标签与内容相反。
    """
    from scripts import data_sources as ds
    import requests as _rq

    order = [
        {"f3": -3.0, "f14": "甲", "f12": "BK1", "f104": 1, "f105": 9,
         "f136": 1.0, "f140": "x"},
        {"f3": 5.0, "f14": "乙", "f12": "BK2", "f104": 9, "f105": 1,
         "f136": 5.0, "f140": "y"},
        {"f3": -1.0, "f14": "丙", "f12": "BK3", "f104": 4, "f105": 6,
         "f136": 2.0, "f140": "z"},
    ]

    def fake_get(url, params=None, headers=None, timeout=None):
        return type("R", (), {"json": lambda self: {"data": {"total": 3, "diff": order}}})()

    monkeypatch.setattr(_rq, "get", fake_get)
    res = ds.industry_comparison(top_n=10)

    top_pcts = [r["change_pct"] for r in res["top"]]
    bottom_pcts = [r["change_pct"] for r in res["bottom"]]
    assert top_pcts == sorted(top_pcts, reverse=True), f"涨幅榜未降序: {top_pcts}"
    assert bottom_pcts == sorted(bottom_pcts), f"跌幅榜未升序: {bottom_pcts}"
    assert res["top"][0]["name"] == "乙"
    assert res["bottom"][0]["name"] == "甲"


def test_industry_comparison_requests_fid_f3_and_paginates(monkeypatch):
    """必须带 fid=f3（按涨跌幅排序）且按 total 分页拉全 496 个板块。"""
    from scripts import data_sources as ds
    import requests as _rq

    seen_params = []

    def fake_get(url, params=None, headers=None, timeout=None):
        seen_params.append(params)
        pn = int(params["pn"])
        # 第 1 页 100 条，第 2 页 50 条，total=150
        n = 100 if pn == 1 else 50
        diff = [{"f3": float(i), "f14": f"P{pn}_{i}", "f12": f"BK{pn}{i}",
                 "f104": 1, "f105": 1, "f136": 0.0, "f140": "L"} for i in range(n)]
        return type("R", (), {"json": lambda self: {"data": {"total": 150, "diff": diff}}})()

    monkeypatch.setattr(_rq, "get", fake_get)
    res = ds.industry_comparison(top_n=5)

    assert all(p.get("fid") == "f3" for p in seen_params), "缺 fid=f3 会导致榜单顺序错位"
    assert len({p["pn"] for p in seen_params}) == 2, "未按 total 分页拉全"
    assert res["total"] == 150
    assert res["fetched"] == 150
    assert res["universe"] == 150
    # top 是涨幅榜前 5，bottom 是跌幅榜前 5（最差在前）
    assert res["top"][0]["change_pct"] == 99.0
    assert res["bottom"][0]["change_pct"] == 0.0


def test_gap_alert_matches_short_index_label():
    """盘中报告写 "| 创业板 |" 时也要能解析（旧代码只认 "创业板指"）。"""
    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "盘中.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write(
                "| 指数 | 涨跌 |\n|---|---|\n"
                "| 上证指数 | 🟢 -0.26% |\n"
                "| 深证成指 | 🟢 -0.96% |\n"
                "| 创业板 | 🟢 -1.81% |\n"
                "| 科创50 | 🟢 -2.58% |\n"
            )
        indices = {
            "sh000001": {"change_pct": -0.60}, "sz399001": {"change_pct": -0.82},
            "sz399006": {"change_pct": -1.62}, "sz399005": {"change_pct": -0.50},
            "sz399300": {"change_pct": -0.97}, "sh000688": {"change_pct": 0.06},
        }
        md, has_alert, rows, used = run_afterhours.realtime_gap_alert(indices, [p])

    assert rows, "未抓到任何指数"
    names = [r[0] for r in rows]
    assert "创业板指" in names, f"创业板被静默跳过: {names}"
    assert len(rows) == 4, f"应抓到 4 个指数: {names}"
    assert has_alert is True
    # 科创50 -2.58% → +0.06% = +2.64pp，跨越零点
    kc = next(r for r in rows if r[0] == "科创50")
    assert abs(kc[3] - 2.64) < 0.01


def test_single_point_v_reversal_market_feature():
    """科创50 盘中 -2.58% → 收盘 +0.06%（跨越零点）应判为单点V型反转，而非"震荡"。"""
    gap_rows = [("上证指数", -0.26, -0.60, -0.34), ("深证成指", -0.96, -0.82, 0.14),
                ("创业板指", -1.81, -1.62, 0.19), ("科创50", -2.58, 0.06, 2.64)]
    feature = run_afterhours.classify_market_feature(
        -0.74, -0.60, -1.62, 0.06, gap_rows
    )
    assert "V型反转" in feature, feature
    assert "震荡" not in feature, feature


def test_small_candidate_pool_hit_rate_is_flagged():
    """上游只有 1 只时，命中率必须带 ⚠️ 前缀（v1.19/v1.24 降级评估）。"""
    hit_rows = [("600732", "爱旭股份", 1.89, 1.46, -0.43)]
    md = run_afterhours.format_feishu(
        "2026-10-21", _minimal_indices(), ["AI应用"], {"AI应用": 2}, {},
        hit_rows, hit_rows, [], 1.46, 1.46, 0.0, -0.60, -1.62, 0.06, [], 50,
    )
    assert "⚠️ 📊 **命中率：** 1/1" in md
    assert "上游 Top10 严重不完整" in md


def test_new_mover_theme_label_uses_specific_stock_tag():
    """priority 命中子串时，新晋异动标签应显示标的自身的更具体标签。

    2026-10-21 实战：利亚德 reason 含"人形机器人"，但硬编码 priority 里只有
    "机器人"（子串），旧代码输出"机器人"，丢掉了"人形机器人当日 ↓5"这一信息。
    """
    priority = ["AI应用", "算力", "半导体设备", "固态电池", "稀土永磁", "低空经济",
                "液冷服务器", "PCB概念", "先进封装", "MLCC", "存储芯片", "机器人",
                "商业航天", "数字科技", "央企", "一季报增长", "创新药", "可控核聚变",
                "分红", "黄金"]

    # 利亚德: reason 含"人形机器人"，priority 只命中子串"机器人" → 应显示"人形机器人"
    assert run_afterhours.resolve_theme_label(
        "物理AI+数据+人形机器人+Micro LED", priority) == "人形机器人"
    # 慧辰股份: priority 命中"AI应用"，自身标签也是"AI应用"
    assert run_afterhours.resolve_theme_label(
        "数据要素+数据分析+具身智能+AI应用", priority) == "AI应用"
    # 新题材未命中 priority → 取首个非 ST 标签
    assert run_afterhours.resolve_theme_label(
        "AI智能体+DeepSeek投资", priority) == "AI智能体"
    # ST板块 标签要被跳过
    assert run_afterhours.resolve_theme_label(
        "ST板块+重组", priority) == "重组"
    # 无标签 → None
    assert run_afterhours.resolve_theme_label("", priority) is None

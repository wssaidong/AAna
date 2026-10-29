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


# ── 2026-10-28 v1.31 回归测试（冰点守卫空池 + 成长领涨型）────────────────

def test_empty_premarket_pool_is_not_replaced_by_intraday_rerun(monkeypatch, tmp_path):
    """盘前版存在但 Top10 为空（冰点守卫 0 推荐）时，**必须返回空池**。

    2026-10-28 生产 bug：git 历史里 08:02 盘前版存在但 Top10 为空
    （冰点守卫短路，属设计行为）。旧实现 `if rows:` 把空表版本静默跳过，
    最终回落到 09:37 开盘后重跑版的 7 只池并标注"盘前口径"，
    战报输出虚假的"命中率 7/7 = 100.0% / vs 上证超额 +4.29pp"。
    """
    monkeypatch.setattr(run_afterhours, "REPORT_DIR", str(tmp_path))
    # 工作区 = 开盘后重跑版（有 7 行，intraday 口径）
    (tmp_path / "2026-10-28-选股报告.md").write_text(
        "### 🏆 重点关注 Top 10\n"
        "| 排名 | 股票 | 代码 | 涨跌幅 |\n"
        "| 1 | 📊甲 | 600001 | +2.79% |\n"
        "| 2 | 📊乙 | 000002 | +1.92% |\n",
        encoding="utf-8",
    )
    # git 历史：盘前版存在但 Top10 为空 → found_prev_close=True, rows=[]
    monkeypatch.setattr(
        run_afterhours, "_git_history_premarket_top10",
        lambda d: ([], "abc1234", True),
    )
    monkeypatch.setattr(
        run_afterhours, "_git_head_top10_with_semantics", lambda d: ([], "unknown")
    )
    monkeypatch.setattr(
        run_afterhours, "_parse_top10_from_deep_analysis", lambda d: []
    )

    rows, source, note, sem = run_afterhours.resolve_candidate_pool("2026-10-28")

    assert rows == [], f"空盘前池不应回落到开盘后重跑版: {rows}"
    assert "空表" in source, source
    assert "Top10 为空" in note, note
    assert sem == "prev_close"


def test_empty_premarket_pool_reports_design_not_fault():
    """空池（冰点守卫）应标注"设计行为"，不能写成"上游报告缺失"。"""
    note = ("⚠️ 上游盘前版选股报告（git commit abc1234）**Top10 为空** —— "
            "冰点守卫短路（情绪冰点/仓位 10%/停止交易）时**有意**输出 0 推荐，"
            "属**设计行为**而非数据故障。")
    md = run_afterhours.format_feishu(
        "2026-10-28", _minimal_indices(), [], {}, {}, [], [], [],
        0, 0, 0, 0.91, 3.40, 2.45, [], 73,
        pool_note=note,
    )
    assert "上游冰点守卫短路（0 推荐·设计行为）" in md
    assert "上游报告缺失" not in md
    assert "无候选池命中率评估" in md


def test_growth_leading_market_feature_detected():
    """主板滞涨 + 成长集体走强，应判"成长领涨型"而非"震荡"。

    2026-10-28 实战：上证 +0.91% / 创业板 +3.40% / 科创50 +2.45%。
    旧代码只在 sh_pct > 1.5 时给"强势行情"，主板滞涨日一律回落成"震荡"，
    并给出方向完全相反的"央企/红利对冲"建议。
    """
    feature = run_afterhours.classify_market_feature(
        2.20, 0.91, 3.40, 2.45, [], other_5_avg=1.77
    )
    assert "成长领涨" in feature, feature
    assert "震荡" not in feature, feature

    # 普涨日（上证也 > 1.5%）仍走"强势行情"，不能被成长领涨层抢走
    broad = run_afterhours.classify_market_feature(
        2.50, 2.20, 3.40, 2.45, [], other_5_avg=2.50
    )
    assert broad == "📈 强势行情", broad


def test_growth_leading_day_defense_advice_not_red_hedge():
    """成长领涨日的防御建议不能是"央企/红利对冲"（当日红利全线下跌）。"""
    md = run_afterhours.format_feishu(
        "2026-10-28", _minimal_indices(), ["半导体"], {"半导体": 3}, {},
        [], [], [], 0, 0, 0, 0.91, 3.40, 2.45, [], 73,
    )
    assert "成长领涨型" in md
    assert "红利仅作低位观察而非对冲盘" in md
    assert "央企/红利股作为底仓对冲" not in md


def test_t1_closed_loop_section_rendered_when_pool_empty():
    """当日池为空时必须补 T+1 闭环段（否则战报失去与盘前情报的闭环）。"""
    t1 = {
        "rows": [("600085", "同仁堂", 1.95, 2.10, 0.15),
                 ("603883", "老百姓", 1.89, -0.50, -2.39)],
        "hits": 1, "n": 2, "hit_rate": 50.0, "avg": 0.80, "alpha_sh": -0.11,
        "avg_baseline": 1.92, "neg_continuation": 1,
        "best": ("600085", "同仁堂", 1.95, 2.10, 0.15),
        "worst": ("603883", "老百姓", 1.89, -0.50, -2.39),
        "prev_date": "2026-10-27",
    }
    md = run_afterhours.format_feishu(
        "2026-10-28", _minimal_indices(), [], {}, {}, [], [], [],
        0, 0, 0, 0.91, 3.40, 2.45, [], 73, t1=t1,
    )
    assert "T+1 闭环复核（2026-10-27 盘前池 → 2026-10-28 收盘）" in md
    assert "📊 **T+1 命中率：** 1/2 = 50.0%" in md
    assert "不代表今日新推荐" in md
    # 当日池为空时不应出现虚假的当日命中率
    assert "📊 **命中率：**" not in md


def test_t1_pool_evaluation_uses_today_close(monkeypatch):
    """T+1 评估必须用今日收盘涨跌与 baseline 做差（真实 T+1，不是自指）。"""
    monkeypatch.setattr(
        run_afterhours, "tencent_quote",
        lambda codes: {"sh600085": {"change_pct": 2.10},
                       "sh603883": {"change_pct": -0.50}},
    )
    rows = [("600085", "同仁堂", 1.95), ("603883", "老百姓", 1.89)]
    res = run_afterhours.evaluate_t1_pool(rows, "2026-10-27", _minimal_indices())

    assert res["n"] == 2
    assert res["hits"] == 1
    assert abs(res["avg"] - 0.80) < 0.01
    # baseline 与今日收盘比较 → delta 分别为 +0.15 / -2.39
    deltas = sorted(r[4] for r in res["rows"])
    assert abs(deltas[0] - (-2.39)) < 0.01
    assert abs(deltas[1] - 0.15) < 0.01
    assert res["prev_date"] == "2026-10-27"


def test_send_feishu_skipped_in_cron_auto_delivery(monkeypatch, capsys):
    """cron 自动投递环境下必须跳过手动 lark-cli 推送（避免重复消息）。

    2026-10-26 实战：本 cron 的回复由 Hermes 自动投递到 origin chat，
    脚本再手动推一遍 → 两条内容相同的战报。
    """
    import sys as _sys
    sent = []
    fake_lark = type("M", (), {
        "push_markdown": staticmethod(lambda md, user_id=None, **kw:
                                       sent.append(md) or (True, "ok")),
    })()
    monkeypatch.setitem(_sys.modules, "lark_push", fake_lark)
    monkeypatch.setenv("HERMES_CRON_AUTO_DELIVERY", "1")

    run_afterhours.send_feishu("body")

    assert sent == [], "cron 自动投递环境不应手动推送"
    assert "跳过飞书手动推送" in capsys.readouterr().out

    # AANA_FORCE_FEISHU=1 时强制推送
    monkeypatch.setenv("AANA_FORCE_FEISHU", "1")
    run_afterhours.send_feishu("body")
    assert sent == ["body"], "强制推送未生效"


def test_growth_collective_dump_layer7_detected():
    """v1.27 第七层「主板稳态 + 成长方向集体杀跌」必须有检测层。

    changelog v1.27 只写了检测条件（kc50/cyb 双破 -3%，主板未破），
    代码此前从未实现。2026-10-29 实战（创业板 -4.45% / 科创50 -4.27%、
    其余 4 指数未破 -3%）落在这个盲区。
    """
    # 成长双破 -3%，主板 4 指数全部 > -3% → 第七层
    feature = run_afterhours.classify_market_feature(
        -1.85, -0.85, -4.45, -4.27, [],
        other_idx_pcts=[-0.85, -1.10, -0.60, -0.90],
    )
    assert "成长方向集体杀跌" in feature, feature

    # 主板也破 -3%（普跌）→ 不能叫"主板稳态"
    broad = run_afterhours.classify_market_feature(
        -3.20, -3.10, -4.45, -4.27, [],
        other_idx_pcts=[-3.10, -3.50, -2.80, -3.00],
    )
    assert "主板稳态" not in broad, broad

    # 与模式⑤双层嵌套：4 核心均值破 -3% 由成长拖累造成（主板 4 指数未破 -3%）
    # → 模式⑤（外层）+ 第七层（内层结构）两个标签都要有
    nested = run_afterhours.classify_market_feature(
        -3.68, -1.00, -6.50, -6.00, [],
        other_idx_pcts=[-1.00, -1.20, -1.00, -1.10],
    )
    assert "模式⑤" in nested and "成长方向集体杀跌" in nested, nested


def test_pool_attribution_rendered_in_feishu():
    """候选池偏差归因必须出现在战报里（skill 交付物 #2）。"""
    hit_rows = [("603683", "海兴电力", 4.99, -6.20, -11.19),
                ("002242", "九阳股份", 4.62, -1.20, -5.82),
                ("000810", "创新维", 4.88, -7.30, -12.18),
                ("001233", "华兰生物", 4.74, 9.95, 5.21)]
    positives = [r for r in hit_rows if r[3] > 0]
    negatives = [r for r in hit_rows if r[3] <= 0]
    avg = sum(r[3] for r in hit_rows) / len(hit_rows)
    md = run_afterhours.format_feishu(
        "2026-10-29", _minimal_indices(), ["医药"], {"医药": 3}, {},
        hit_rows, positives, negatives,
        avg, 9.95, -4.90, -0.85, -4.45, -4.27, [], 73,
        pool_mode="⑩-h", pool_label="模式⑩-h 极端情绪日 + 昨日+5%追高 + 全天单边杀跌",
        pool_attr="候选池 1/4 命中、整体均值 -4.04%（破 -3%）",
        pool_industries={"603683": "电网设备", "002242": "家电行业"},
    )
    assert "偏差归因" in md
    assert "⑩-h" in md
    assert "电网设备" in md  # 行业暴露行


def test_pool_failure_mode_10h_classified():
    """2026-10-29 实战形态: 25%命中 + 均值破 -3% + baseline +5% → 必须判 ⑩-h。"""
    hit_rows = [("603683", "海兴电力", 4.99, -9.90, -14.89),
                ("002242", "九阳股份", 4.62, -6.20, -10.82),
                ("000810", "创新维", 4.88, -8.30, -13.18),
                ("001233", "华兰生物", 4.74, 9.95, 5.21)]
    positives = [r for r in hit_rows if r[3] > 0]
    negatives = [r for r in hit_rows if r[3] <= 0]
    avg = sum(r[3] for r in hit_rows) / len(hit_rows)
    # 注意 gap = |avg_pos| + |avg_neg| —— ⑧ 分支要求 gap < 10（高Beta特征），
    # ⑩-h 是"破 -3% + 追高"，要避免正负差距大到落进 ⑧。
    mode, label, attr = run_afterhours.classify_pool_failure_mode(
        hit_rows, avg, positives, negatives, 9.95, -8.13,
        sh_pct=-0.85, market_avg=-3.20,
        tail_dive=False, in_hot_count=1, hot_count=73,
    )
    assert mode == "⑩-h", (mode, label)
    assert "全天单边杀跌" in label or "追高" in label, label
    assert "无 ≥3.5pp 尾盘跳水" in attr, attr
    # 极端情绪日 → 归因必须带大盘层
    assert "模式⑤" in attr, attr
    # 样本 N=4 < 5 → 必须降级标注
    assert "置信度低" in attr, attr

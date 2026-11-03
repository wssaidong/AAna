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


# ── v1.33（2026-11-02 实战）: 盘前池空表未被 git 提交 → 虚假 100% 命中率 ──────

_EMPTY_DEEP_ANALYSIS = """# 深度分析 — 2026-11-02 (周一交易日盘前 · 冰点快照延续 · 0 推荐 · 空仓观望)

## 一、报告确认

| 项 | 值 |
|---|---|
| 采用报告 | **reports/2026-11-02-选股报告.md** (5464 字节, 2026-11-02T08:03:31 盘前版) |
| 采用报告 Top10 表 | ⛔ **0 只 (空表)** — 解析器正确排除 |
| 候选池 | **空 (0 只)** — 无标的可评分 |
| 链路状态 | is_ice_point=True 短路, 情绪 20 冰点 / 仓位 10% / 停止交易 |

## 二、候选池: 0 只 — 盘前报告空表 + 冰点守卫延续 (单一真源判定)

- P0 冰点守卫 (`check_ice_point_guard`): 情绪 20(冰点) · 仓位 10% · **is_ice_point=True**,
  短路原因 "情绪=冰点/仓位=10%"。
- 11-02 盘前报告 Top10 空表 = 冰点守卫短路设计行为。

## 三、逐股基本面

N/A — 候选池 0 只。
"""

_POPULATED_DEEP_ANALYSIS = """# 深度分析 — 2026-10-29 (周四交易日盘前 · 候选池 4 只)

## 一、报告确认

| 项 | 值 |
|---|---|
| 候选池 | **4 只** — 晶华新材 603683 / 九阳股份 002242 / 创维数字 000810 / 海安集团 001233 |

## 二、市场环境与守卫

盘前情绪偏暖, 冰点守卫未触发。
"""

# ⚠️ 2026-11-03 实战: 池表所在二级标题按日改名, 且**前一节还有一张同含"代码"
# 列的"昨日复核"表**(列名是"收盘/实收"而非基准日"涨跌")。旧实现只认"候选池"
# 标题 → 整张池表漏解析; 若只改成"任意含代码的表" → 会误取昨日复核表。
# 这里同时锁两条: (1) 新标题"逐股深度评分"必须能回捞; (2) 昨日复核表不得混入。
_RENAMED_SECTION_DEEP_ANALYSIS = """# 深度分析 — 2026-11-03 (周二交易日盘前 · 候选池 5 只)

## 一、报告确认

| 项 | 值 |
|---|---|
| 采用报告 Top10 表 | **5 只** (原始数据行 5 行) |

## 二、昨日 (11-02) 尾盘深度 Top5 当日实现复核 (11-02 收盘, 腾讯快照)

| 深度分 | 股票 | 代码 | 11-02 实收 | vs 大盘均 +1.34% | 快照日 |
|---|---|---|---|---|---|
| 60.0 中性 | 妙可蓝多 | 600882 | **+6.04%** | ✅ 胜 +4.70pp | 20261102 |

## 三、逐股深度评分 (技术50% + 基本面30% + 估值20%, 含失真修正 v1)

| 深度分 | 股票 | 代码 | 现价 | 11-02 涨跌 | 技术/55 | 基本面/30 | 估值/15 | 状态 |
|---|---|---|---|---|---|---|---|---|
| **85.6 买入** | **西麦食品** | **002956** | ¥20.25 | **+6.69%** (#2) | 48 | **26** | 12 | 未破 |
| 62.7 中性 | 力鼎光电 | 605118 | ¥37.20 | +6.99% (#1) | 36 | 26 | 3 | 未破 |
| 51.6 中性 | 汇顶科技 | 603160 | ¥59.96 | +5.69% (#3) | 48 | 0 | 6 | 未破 |
"""


def test_pool_table_parsed_when_section_renamed_from_candidate_pool(
    monkeypatch, tmp_path
):
    """池表二级标题改名后仍须回捞 (11-03 实战: "候选池" → "逐股深度评分")。

    2026-11-03 生产 bug: 08:03 盘前版选股报告从未入库 git, 而 09:37 开盘后
    重跑又覆盖了工作区那份 → 盘前池四源(工作区/HEAD/git 历史/深度分析表)
    全落空, 盘后战报输出"三源均无候选池", 真实 5 只盘前池被整个丢弃。
    根因: _parse_top10_from_deep_analysis 只认"候选池"标题, 漏掉新标题。
    """
    monkeypatch.setattr(run_afterhours, "REPORT_DIR", str(tmp_path))
    (tmp_path / "2026-11-03-深度分析.md").write_text(
        _RENAMED_SECTION_DEEP_ANALYSIS, encoding="utf-8"
    )
    rows = run_afterhours._parse_top10_from_deep_analysis("2026-11-03")
    codes = [r[0] for r in rows]
    assert codes == ["002956", "605118", "603160"], rows
    # 基准日涨跌幅 (prev_close 口径), 不是现价也不是昨日复核表的实收
    assert rows[0][2] == 6.69, rows


def test_pool_table_excludes_yesterday_review_table(monkeypatch, tmp_path):
    """池表回捞不得混入"昨日复核"表 (列名是收盘/实收, 非基准日涨跌)。"""
    monkeypatch.setattr(run_afterhours, "REPORT_DIR", str(tmp_path))
    (tmp_path / "2026-11-03-深度分析.md").write_text(
        _RENAMED_SECTION_DEEP_ANALYSIS, encoding="utf-8"
    )
    rows = run_afterhours._parse_top10_from_deep_analysis("2026-11-03")
    assert "600882" not in [r[0] for r in rows], rows


def test_resolve_candidate_pool_recovers_pool_via_renamed_deep_analysis_section(
    monkeypatch, tmp_path
):
    """端到端: 盘前池四源全落空时, 深度分析(改名章节)仍能救回 prev_close 池。"""
    monkeypatch.setattr(run_afterhours, "REPORT_DIR", str(tmp_path))
    (tmp_path / "2026-11-03-深度分析.md").write_text(
        _RENAMED_SECTION_DEEP_ANALYSIS, encoding="utf-8"
    )
    # 工作区 = 开盘后重跑版 (intraday 口径, 空表) → 口径不符必须拒绝
    (tmp_path / "2026-11-03-选股报告.md").write_text(
        "# A股选股报告 — 2026-11-03 v2.5\n\n"
        "> **生成时间：** 2026-11-03 09:37:55\n\n"
        "### 🏆 重点关注 Top 10\n\n"
        "| 排名 | 股票 | 代码 | 价格 | 涨跌幅 | 技术分 | 综合评分 |\n"
        "|:----:|:----:|:----:|:----:|:------:|:------:|:--------:|\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        run_afterhours, "_git_head_top10_with_semantics", lambda d: ([], "unknown")
    )
    monkeypatch.setattr(
        run_afterhours, "_git_history_premarket_top10", lambda d: ([], None, False)
    )

    rows, source, note, sem = run_afterhours.resolve_candidate_pool("2026-11-03")

    assert sem == "prev_close", sem
    assert len(rows) == 3, rows
    assert "深度分析" in source, source
    assert rows[0][0] == "002956", rows


def test_empty_pool_detected_from_deep_analysis_when_premarket_never_committed(
    monkeypatch, tmp_path
):
    """盘前版**从未入库 git**时，深度分析的空池声明是真源。

    2026-11-02 生产 bug：08:03 盘前版选股报告从未被 git 提交（git log 只有
    09:38 开盘后重跑版那条），于是 v1.31 的三源回捞全部落空：
      工作区=intraday 口径拒绝 / git HEAD=intraday 口径拒绝 /
      git 历史无 prev_close 版本 / 深度分析候选池**表**是空表解析 0 行
    结果回落到兜底分支，把 09:38 的 6 只当"盘前池"评估，战报输出虚假的
    「命中率 6/6 = 100.0% / vs 上证超额 +4.08pp」。
    """
    monkeypatch.setattr(run_afterhours, "REPORT_DIR", str(tmp_path))
    # 工作区 = 09:38 开盘后重跑版（intraday 口径，6 只）
    (tmp_path / "2026-11-02-选股报告.md").write_text(
        "# A股选股报告 — 2026-11-02 v2.5\n\n"
        "> **生成时间：** 2026-11-02 09:38:23\n\n"
        "### 🏆 重点关注 Top 10\n\n"
        "| 排名 | 股票 | 代码 | 价格 | 涨跌幅 | 技术分 | 综合评分 |\n"
        "|:----:|:----:|:----:|:----:|:------:|:------:|:--------:|\n"
        "| 1 | 📊襄阳轴承 | 000678 | ¥18.48 | 🔴 +2.21% | 78 | **64** |\n"
        "| 2 | 📊润建股份 | 002929 | ¥50.77 | 🔴 +2.40% | 78 | **64** |\n"
        "| 3 | 📊云南白药 | 000538 | ¥54.44 | 🔴 +1.36% | 78 | **64** |\n"
        "| 4 | 📊完美世界 | 002624 | ¥10.04 | 🔴 +1.31% | 78 | **64** |\n"
        "| 5 | 📊三一重工 | 600031 | ¥17.95 | 🔴 +1.07% | 68 | **60** |\n"
        "| 6 | 📊中创智领 | 601717 | ¥14.77 | 🔴 +1.86% | 68 | **60** |\n",
        encoding="utf-8",
    )
    # 深度分析（盘前时段生成）声明空池
    (tmp_path / "2026-11-02-深度分析.md").write_text(
        _EMPTY_DEEP_ANALYSIS, encoding="utf-8"
    )
    # git 历史无盘前版本（盘前版从未入库）
    monkeypatch.setattr(
        run_afterhours, "_git_history_premarket_top10", lambda d: ([], None, False)
    )
    monkeypatch.setattr(
        run_afterhours, "_git_head_top10_with_semantics",
        lambda d: ([("000678", "襄阳轴承", 2.21)], "intraday"),
    )
    monkeypatch.setattr(
        run_afterhours, "_parse_top10_from_deep_analysis", lambda d: []
    )

    rows, source, note, sem = run_afterhours.resolve_candidate_pool("2026-11-02")

    assert rows == [], f"空盘前池不应回落到开盘后重跑版: {rows}"
    assert "空池" in source, source
    assert "设计行为" in note, note
    assert "冰点守卫" in note, note
    assert sem == "prev_close"


def test_populated_deep_analysis_is_not_mistaken_for_empty_pool(monkeypatch, tmp_path):
    """有池的日子（10-29，4 只）不能被误判为空池。"""
    monkeypatch.setattr(run_afterhours, "REPORT_DIR", str(tmp_path))
    (tmp_path / "2026-10-29-深度分析.md").write_text(
        _POPULATED_DEEP_ANALYSIS, encoding="utf-8"
    )
    is_empty, evidence = run_afterhours.detect_empty_premarket_pool_from_deep_analysis(
        "2026-10-29"
    )
    assert is_empty is False, evidence


def test_empty_pool_renders_design_behavior_not_fault():
    """空池标注必须是"冰点守卫·设计行为"，不能写成"上游报告缺失"。"""
    md = run_afterhours.format_feishu(
        "2026-11-02", _minimal_indices(), [], {}, {}, [], [], [],
        0, 0, 0, 1.08, 1.87, 3.11, [], 131,
        pool_note=(
            "⚠️ 深度分析报告（盘前时段生成）确认 2026-11-02 盘前候选池为空"
            "（冰点守卫短路，**设计行为而非数据故障**）"
        ),
    )
    assert "上游冰点守卫短路（0 推荐·设计行为）" in md
    assert "上游报告缺失" not in md
    assert "无候选池命中率评估" in md
    # 关键: 不得出现虚假的高命中率
    assert "100.0%" not in md


# ── v1.33: 成长领涨价差口径（v1.31 窄口径漏判） ──────────────────────────

def test_growth_lead_detected_by_spread_not_only_absolute_thresholds():
    """2026-11-02 实战: 科创50 +3.11% 领先上证 +1.08% 达 2.03pp。

    v1.31 窄口径 (cyb>=2.0 and kc50>=1.5 and sh<1.0) 不命中
    （创业板 +1.87% < 2.0，上证 +1.08% ≥ 1.0），战报误标"震荡"并给出
    "央企/红利股对冲"建议，而当日红利防御全线下跌 —— 方向完全相反。
    """
    feature = run_afterhours.classify_market_feature(
        1.92, 1.08, 1.87, 3.11, [], other_5_avg=1.33
    )
    assert "成长领涨型" in feature, feature


def test_growth_lead_spread_does_not_fire_on_broad_rally():
    """普涨日（科创50 与上证同步涨）不应被误判为成长领涨。"""
    feature = run_afterhours.classify_market_feature(
        2.00, 2.10, 2.30, 2.00, [], other_5_avg=2.00
    )
    assert "成长领涨型" not in feature, feature


def test_growth_lead_spread_does_not_fire_on_weak_market():
    """全市场下跌中的科创50相对抗跌，不是"结构性走强"。"""
    feature = run_afterhours.classify_market_feature(
        -1.50, -0.20, -1.00, 0.30, [], other_5_avg=-0.80
    )
    assert "成长领涨型" not in feature, feature


def test_growth_lead_advice_uses_real_industry_data_not_hardcoded_sectors():
    """成长领涨日的建议必须引用**当日真实**板块，不得写死其他日期的板块名。"""
    industry = {
        "top": [
            {"name": "影视院线", "change_pct": 9.36},
            {"name": "游戏", "change_pct": 8.91},
            {"name": "文化传媒", "change_pct": 8.31},
        ],
        "bottom": [
            {"name": "贵金属", "change_pct": -1.45},
            {"name": "银行", "change_pct": -0.83},
            {"name": "煤炭开采加工", "change_pct": -0.35},
        ],
    }
    md = run_afterhours.format_feishu(
        "2026-11-02", _minimal_indices(), ["三季报增长"], {"三季报增长": 22}, {},
        [], [], [], 0, 0, 0, 1.08, 1.87, 3.11, [], 131,
        industry=industry,
    )
    assert "影视院线" in md, md
    assert "贵金属" in md, md
    # 旧代码写死的 10-28 板块名不应出现在 11-02 的战报里
    assert "电子化学品" not in md, md


def test_gap_source_warning_trusts_same_day_intraday_snapshot(tmp_path):
    """同日 14:4x 生成的尾盘报告是可信盘中快照，不该挂"历史失真"警示。

    2026-11-02 实战: 旧代码按**文件名**一刀切警告"该源历史已连续确认失真"，
    但当日文件生成于 14:46:55（真实盘中快照，Δ 仅 0.19pp），误伤可信数据源。
    """
    src = tmp_path / "2026-11-02-尾盘选股.md"
    src.write_text(
        "# A股尾盘选股建议 — 2026-11-02 14:46\n\n"
        "> **生成时间：** 2026-11-02 14:46:55\n\n"
        "| 上证指数 | 🔴 +0.89% | 上涨 |\n",
        encoding="utf-8",
    )
    warn = run_afterhours._gap_source_warning(str(src), "2026-11-02")
    assert "历史已连续确认失真" not in warn, warn
    assert "真实盘中快照" in warn, warn


def test_gap_source_warning_flags_stale_or_undated_source(tmp_path):
    """非目标交易日 / 无生成时间字段的源必须保留失真警示。"""
    stale = tmp_path / "stale-尾盘选股.md"
    stale.write_text(
        "> **生成时间：** 2026-07-02 08:03:10\n\n| 上证指数 | 🔴 +1.18% | 上涨 |\n",
        encoding="utf-8",
    )
    warn = run_afterhours._gap_source_warning(str(stale), "2026-11-02")
    assert "疑为陈旧快照" in warn, warn

    undated = tmp_path / "undated-尾盘选股.md"
    undated.write_text("| 上证指数 | 🔴 +1.18% | 上涨 |\n", encoding="utf-8")
    warn2 = run_afterhours._gap_source_warning(str(undated), "2026-11-02")
    assert "历史已连续确认失真" in warn2, warn2


def test_dragon_tiger_note_distinguishes_trading_day_from_non_trading(monkeypatch):
    """交易日但龙虎榜未发布，不能写成"非交易日"（事实性错误）。"""
    monkeypatch.setattr(run_afterhours, "ths_hot", lambda d: [{"code": "000001"}])

    def _fake_ds(trade_date=None, **kw):
        return {"date": trade_date, "total_records": 0, "stocks": [],
                "note": "无数据（非交易日或盘后未更新）"}

    monkeypatch.setattr(run_afterhours.ds, "daily_dragon_tiger", _fake_ds)
    res = run_afterhours.get_daily_dragon_tiger("2026-11-02")
    assert "非交易日" not in res["note"], res["note"]
    assert "尚未发布" in res["note"], res["note"]

    monkeypatch.setattr(run_afterhours, "ths_hot", lambda d: [])
    res2 = run_afterhours.get_daily_dragon_tiger("2026-11-02")
    assert "非交易日" in res2["note"], res2["note"]


# ── v1.34（2026-11-03 实战）: 成长方向单边杀跌被判成"震荡" + 建议写死旧数据 ────

def test_growth_dump_detected_by_spread_not_only_absolute_thresholds():
    """2026-11-03 实战: 上证 -0.82% / 创业板 -2.73% / 科创50 -3.81%。

    v1.29 窄口径 (kc50<-2.0 and cyb<-1.5 and sh>-0.5) 不命中
    （上证 -0.82% 不 > -0.5%），v1.27 第七层也不命中
    （创业板 -2.73% 未破 -3.0%），战报误标"震荡"并丢掉
    "成长方向被单边绞杀"这一当天最重要的结构信息。
    """
    feature = run_afterhours.classify_market_feature(
        -2.143, -0.82, -2.73, -3.81, [], other_5_avg=-1.158,
        other_idx_pcts=[-0.82, -1.21, -0.83, -0.20],
    )
    assert "成长方向杀跌" in feature, feature
    assert "震荡" not in feature.replace("主板稳态", ""), feature


def test_growth_dump_spread_does_not_fire_on_broad_market_selloff():
    """全市场普跌（上证也重挫）不是"主板稳态+成长杀跌"，应走极端情绪/模式⑦。"""
    feature = run_afterhours.classify_market_feature(
        -3.40, -2.60, -4.00, -4.30, [], other_5_avg=-3.00,
        other_idx_pcts=[-2.60, -3.00, -2.80, -3.20],
    )
    assert "成长方向杀跌" not in feature, feature
    assert "极端情绪日" in feature, feature


def test_growth_dump_spread_does_not_fire_when_growth_leads():
    """成长领涨日不应被"成长杀跌"价差口径误伤。"""
    assert not run_afterhours._growth_dump_spread(1.87, 3.11, 1.08)


def test_growth_dump_advice_uses_real_pool_and_industry_data():
    """v1.29 建议分支写死了 2026-10-26 当天的"+1.01pp 超额 / 9/10 负延续"
    和"半导体/元件"板块名 —— 必须改为当日实测数据。"""
    industry = {
        "top": [
            {"name": "保险", "change_pct": 2.67},
            {"name": "机场航运", "change_pct": 2.01},
            {"name": "养殖业", "change_pct": 1.89},
        ],
        "bottom": [
            {"name": "元件", "change_pct": -5.13},
            {"name": "半导体", "change_pct": -5.09},
            {"name": "电子化学品", "change_pct": -5.05},
        ],
    }
    hit_rows = [
        ("002956", "西麦食品", 6.69, 2.22, -4.47),
        ("605118", "力鼎光电", 6.99, -10.00, -16.99),
        ("603160", "汇顶科技", 5.69, -1.92, -7.61),
        ("000860", "顺鑫农业", 5.59, -1.14, -6.73),
        ("002242", "九阳股份", 5.37, -1.93, -7.30),
    ]
    positives = [r for r in hit_rows if r[3] > 0]
    negatives = [r for r in hit_rows if r[3] <= 0]
    avg = sum(r[3] for r in hit_rows) / len(hit_rows)
    md = run_afterhours.format_feishu(
        "2026-11-03", _minimal_indices(), ["固态电池"], {"固态电池": 4}, {},
        hit_rows, positives, negatives, avg, 2.22, -4.40,
        -0.82, -2.73, -3.81, [], 52,
        industry=industry,
    )
    # 写死的旧快照数字必须消失
    assert "+1.01pp" not in md, md
    assert "9/10 负延续" not in md, md
    # 当日实测候选池数据必须出现
    assert "1/5 命中" in md, md
    assert "5/5 负延续" in md, md
    # 板块名必须来自当日数据
    assert "保险 +2.67%" in md, md
    assert "元件 -5.13%" in md, md
    # 防御建议按当日红利防御真实涨跌给出
    assert "红利防御今日领涨" in md, md


def test_pool_attribution_alpha_zone_is_data_driven():
    """v1.34: "模式①"分支硬编码"（中性区间）"，与实测 Alpha -1.73pp 自相矛盾。

    2026-11-03 实测: 1/5 命中、均值 -2.55%、Alpha -1.73pp、baseline 全部
    +5.37%~+6.99%（昨日强势股）→ 应判 ⑩-i（追高 + 全天单边杀跌），
    而不是"模式① 风格切换 + 中性区间"。
    """
    hit_rows = [
        ("002956", "西麦食品", 6.69, 2.22, -4.47),
        ("605118", "力鼎光电", 6.99, -10.00, -16.99),
        ("603160", "汇顶科技", 5.69, -1.92, -7.61),
        ("000860", "顺鑫农业", 5.59, -1.14, -6.73),
        ("002242", "九阳股份", 5.37, -1.93, -7.30),
    ]
    positives = [r for r in hit_rows if r[3] > 0]
    negatives = [r for r in hit_rows if r[3] <= 0]
    avg = sum(r[3] for r in hit_rows) / len(hit_rows)
    mode, label, attr = run_afterhours.classify_pool_failure_mode(
        hit_rows, avg, positives, negatives, 2.22, -4.40,
        sh_pct=-0.82, market_avg=-2.143,
        tail_dive=False, in_hot_count=0, hot_count=52,
    )
    assert mode == "⑩-i", (mode, label)
    assert "追高" in label, label
    assert "5/5 负延续" in attr, attr
    # 极端情绪日标签不能误加（大盘均值 -2.14% 未破 -3%）
    assert "模式⑤" not in attr, attr
    # "中性区间" 措辞不得出现在显著负 Alpha 上
    assert "中性区间" not in attr, attr


def test_alpha_zone_describes_sign_magnitude():
    """Alpha 措辞必须由数值决定，不得硬编码。"""
    assert run_afterhours._alpha_zone(1.2) == "正 Alpha"
    assert run_afterhours._alpha_zone(0.2) == "中性区间"
    assert run_afterhours._alpha_zone(-0.7) == "小幅负 Alpha"
    assert run_afterhours._alpha_zone(-1.73) == "显著负 Alpha"

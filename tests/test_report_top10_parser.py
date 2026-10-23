#!/usr/bin/env python3
"""tests/test_report_top10_parser.py — Top10 报告解析回归测试

v2026-10-21: 锁定 P0「内部同步静默空跑」修复。
  背景: 2026-08-07 commit fd7b691 在 "## 三、精选个股" 标题后插入了
        "### ⏱ 持仓策略" 块 + 一条 `---` 分隔线, 导致
        `## 三、精选个股.*?(?=^---)` 非贪婪匹配在 Top10 表格 **之前** 就被截断,
        sync_top10_v9.extract_top10() 与 eastmoney_portfolio.get_snapshot_top10()
        自 8/7 起对所有真实报告返回 [] —— 东财自动同步静默失效 ~33 个交易日, 且无报错。

  锁定三件事:
    1. 解析器能处理带 "### ⏱ 持仓策略" + `---` 的新模板 (不再返回 [])
    2. 解析结果去重 (同一只股票在 Top10 / 强势股 / 活跃股 等小节重复出现只算一次)
    3. 报告不足 10 只时返回实际数量 (不凑数), 0 只时返回 []
"""
import os
import sys

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))

import eastmoney_portfolio as ep
from sync_top10_v9 import extract_top10

# 2026-08-07 之后的真实报告模板 (含 持仓策略 块 + `---` 分隔线 —— 就是打断旧正则的那一行)
NEW_TEMPLATE = """# A股选股报告 — 2026-10-21 v2.5

## 三、精选个股（按综合评分排序）

### ⏱ 持仓策略

**持仓周期：14 个交易日（中线 2 周）**

---

### 🏆 重点关注 Top 10

| 排名 | 股票 | 代码 | 价格 | 涨跌幅 | 技术分 | 资金流 | 综合评分 | 信号 | 风险 | 软止损 | 趋势 |
|:----:|:----:|:----:|:----:|:------:|:------:|:------:|:--------:|:----:|:----:|:------:|:----:|
| 1 | 📊金奥博 | 002917 | ¥12.47 | 🔴 +4.09% | 78 | ~ | **64** | MA多头MACD金叉 | 🟡 中风险 | 12.1 | 📈上升 |
| 2 | 📊西麦食品 | 002956 | ¥19.15 | 🔴 +4.53% | 78 | ~ | **64** | MA多头MACD金叉 | 🟡 中风险 | 18.58 | 📈上升 |

### 🚀 强势股

| 股票 | 代码 | 最新价 | 涨跌幅 | 技术分 | 综合分 | 评级 | 推荐理由 | 趋势 |
|:----:|:----:|:------:|:------:|:------:|:------:|:----:|:--------:|:----:|
| 📊金奥博 | 002917 | ¥12.47 | 🔴 +4.09% | 78 | **64** | ⭐⭐ 观察 | 今日强势上涨+放量 | 📈上升 |

---

## 四、🎯 最佳买点
"""


class TestParseTop10FromReport:
    """共享解析器 parse_top10_from_report"""

    def test_new_template_with_hold_strategy_block(self):
        """新模板 (持仓策略 + ---) 必须能解析出代码, 不能返回 []"""
        codes = ep.parse_top10_from_report(NEW_TEMPLATE)
        assert codes == ["002917", "002956"], f"新模板解析失败: {codes}"

    def test_dedup_across_sections(self):
        """同一只股票出现在 Top10 + 强势股 等多小节 → 只算一次"""
        codes = ep.parse_top10_from_report(NEW_TEMPLATE)
        assert len(codes) == len(set(codes)), f"重复代码未去重: {codes}"
        assert codes.count("002917") == 1

    def test_skips_header_row(self):
        """表头行 (含 '代码'/'排名') 不能被当成数据行"""
        codes = ep.parse_top10_from_report(NEW_TEMPLATE)
        assert "代码" not in codes
        assert all(len(c) == 6 and c.isdigit() for c in codes)

    def test_empty_content_returns_empty(self):
        assert ep.parse_top10_from_report("") == []

    def test_no_top10_table_returns_empty(self):
        """没有 Top10 表格 → 返回 [] (调用方据此走 0 推荐铁律)"""
        assert ep.parse_top10_from_report("## 一、市场情绪\n\n| 指标 | 数值 |\n|:--|:--|\n| 情绪 | 55 |\n") == []

    def test_fewer_than_10_returns_actual_count(self):
        """候选不足 10 只 → 返回实际数量, 不补足 (不凑数铁律)"""
        codes = ep.parse_top10_from_report(NEW_TEMPLATE)
        assert len(codes) == 2
        assert len(codes) < 10


class TestExtractTop10File:
    """sync_top10_v9.extract_top10 (文件入口)"""

    def test_reads_new_template_from_file(self, tmp_path):
        p = tmp_path / "2026-10-21-选股报告.md"
        p.write_text(NEW_TEMPLATE, encoding="utf-8")
        assert extract_top10(str(p)) == ["002917", "002956"]

    def test_missing_file_returns_empty(self, tmp_path):
        assert extract_top10(str(tmp_path / "nope.md")) == []

    def test_real_reports_not_empty(self):
        """
        回归: 真实历史报告必须与报告里 Top10 表格的实际行数一致。

        注意: 有的历史报告当天真的 0 候选 (表格只有表头, 如 2026-10-14),
        解析结果应当是 [] —— 这是 0 推荐铁律的正确行为, 不是 bug。
        """
        import re as _re
        reports_dir = os.path.join(PROJECT, "reports")
        if not os.path.isdir(reports_dir):
            pytest.skip("reports dir 不存在")
        files = sorted(f for f in os.listdir(reports_dir) if f.endswith("-选股报告.md"))
        if not files:
            pytest.skip("无历史报告")

        checked = 0
        for f in files:
            path = os.path.join(reports_dir, f)
            codes = extract_top10(path)
            assert len(codes) == len(set(codes)), f"真实报告有重复: {f} -> {codes}"
            assert len(codes) <= 10, f"超过 10 只: {f} -> {codes}"

            # 与报告里的 Top10 表格实际行数交叉校验
            content = open(path, encoding="utf-8").read()
            m = _re.search(r'###\s*[^\n]*重点关注\s*Top\s*10(.*?)(?=\n###|\n##\s|\Z)',
                           content, _re.DOTALL)
            if m:
                table_rows = [ln for ln in m.group(1).split('\n')
                              if ln.strip().startswith('|')
                              and not ln.strip().startswith('|:')
                              and '代码' not in ln
                              and _re.match(r'^\s*\|\s*\d+\s*\|', ln)]
                assert len(codes) == len(table_rows), \
                    f"解析数与表格行数不符: {f} -> parsed={len(codes)} table={len(table_rows)}"
            checked += 1
        assert checked > 0

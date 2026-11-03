#!/usr/bin/env python3
"""
tests/test_generate_report_snapshot.py — 早盘快照链路 + git 白名单回归锁定

🔴 2026-11-03 修复背景 (两个耦合缺陷, 必须一起修):

缺陷 A (P1 断链): `save_morning_snapshot()` 的调用点在 2026-05-23 的 v2.5 重构
(93f7ad8) 中被删掉 → 快照永不生成 → `generate_review_report()` 每次都在
"快照不存在"处 return → **复盘评分报告连续 127 次 cron 跳过**,
2026-05-25 之后彻底停更 (reports/ 里只剩 5/21~5/25 共 17 份, 且 0 份被 git 跟踪)。

缺陷 B (P0 连带): 修好 A 之后, `generate_review_report()` 末尾的
`git add '.'` 会被**首次真正执行** → 把工作区所有改动一起 stage,
包括 cleanup 脚本删掉的 20 份旧报告 (8/23 事故同款:
git add -A 删 1174 文件致 x-compass 全线 404)。⇒ 必须同时改成白名单 stage。

不变量:
A. save_morning_snapshot 在【开盘后~收盘前】才写盘 (9 ≤ hour < 15)
   - 08:00 那趟未开盘 → 写进去会毒化基准 (sina 返回昨收, change_pct≈0)
   - 17:00 那趟用收盘价 → 会覆盖真实早盘快照
B. 文件已存在时不覆盖 (17:00 不许污染 09:35 写的快照)
C. generate_report() 里必须真的调用了 save_morning_snapshot (调用点存在性)
D. generate_review_report() 里不得出现 `git add '.'` (必须是白名单 stage)
E. 白名单 stage 后必须做 reports/ 跟踪文件数量守卫 (减少则中止 push)
"""
import ast
import inspect
import os
import sys
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))

import generate_report as gr


class _FakeDT:
    """可控时钟 — 用于验证保存窗口"""
    _now = None

    def __init__(self, y, m, d, hh):
        type(self)._now = datetime(y, m, d, hh)

    @classmethod
    def now(cls):
        return cls._now


def _patch_clock(monkeypatch, y, m, d, hh):
    fake = type("FakeDT", (), {
        "now": staticmethod(lambda: datetime(y, m, d, hh)),
    })
    monkeypatch.setattr(gr, "datetime", fake)


class TestSnapshotSaveWindow:
    """不变量 A: 只在开盘后~收盘前写"""

    def test_skips_before_open(self, monkeypatch, tmp_path):
        """08:00 那趟 (未开盘) → 不写快照"""
        monkeypatch.setattr(gr, "get_morning_snapshot_filename",
                            lambda: str(tmp_path / ".snap.json"))
        _patch_clock(monkeypatch, 2026, 11, 3, 8)

        assert gr.save_morning_snapshot({"600000": {"price": 10}}) is False
        assert not (tmp_path / ".snap.json").exists()

    def test_writes_after_open(self, monkeypatch, tmp_path):
        """09:35 那趟 (开盘后) → 真正落盘"""
        snap = tmp_path / ".snap.json"
        monkeypatch.setattr(gr, "get_morning_snapshot_filename", lambda: str(snap))
        _patch_clock(monkeypatch, 2026, 11, 3, 9)

        assert gr.save_morning_snapshot({"600000": {"price": 10}}) is True
        assert snap.exists()

    def test_skips_after_close(self, monkeypatch, tmp_path):
        """17:00 那趟 (收盘后) → 不写快照 (否则覆盖真实早盘快照)"""
        monkeypatch.setattr(gr, "get_morning_snapshot_filename",
                            lambda: str(tmp_path / ".snap.json"))
        _patch_clock(monkeypatch, 2026, 11, 3, 17)

        assert gr.save_morning_snapshot({"600000": {"price": 10}}) is False
        assert not (tmp_path / ".snap.json").exists()

    def test_does_not_overwrite_existing(self, monkeypatch, tmp_path):
        """不变量 B: 文件已存在 → 不覆盖"""
        snap = tmp_path / ".snap.json"
        snap.write_text('{"prices": {"ORIGINAL": 1}}', encoding="utf-8")
        monkeypatch.setattr(gr, "get_morning_snapshot_filename", lambda: str(snap))
        _patch_clock(monkeypatch, 2026, 11, 3, 10)

        assert gr.save_morning_snapshot({"600000": {"price": 10}}) is False
        assert "ORIGINAL" in snap.read_text(encoding="utf-8")


class TestCallSiteExists:
    """不变量 C: generate_report() 里必须真的调用 save_morning_snapshot"""

    def test_generate_report_calls_save_morning_snapshot(self):
        src = inspect.getsource(gr.generate_report)
        assert "save_morning_snapshot(prices)" in src, \
            "generate_report() 未调用 save_morning_snapshot → 快照链路仍是断的"

    def test_call_site_is_after_price_enrichment(self):
        """调用点必须在 enrich 之后 (复盘要读 综合评分/评级/stop_soft)"""
        src = inspect.getsource(gr.generate_report)
        assert src.index("save_morning_snapshot(prices)") > src.index("info['综合评分']")


class TestReviewGitWhitelist:
    """不变量 D/E: 复盘报告的 git 操作必须是白名单 + 数量守卫"""

    def _review_src(self):
        return inspect.getsource(gr.generate_review_report)

    def test_no_bare_git_add_dot(self):
        """❌ 不得出现 `git add '.'` (8/23 事故同款)"""
        assert "['git', 'add', '.']" not in self._review_src()
        assert '"git", "add", "."' not in self._review_src()

    def test_uses_path_scoped_git_add(self):
        """✅ 必须用 `git add -- <path>` 白名单逐路径 stage"""
        assert "'--'" in self._review_src()
        assert "whitelist" in self._review_src()

    def test_has_reports_count_guard(self):
        """✅ 必须有 reports/ 跟踪文件数量守卫"""
        src = self._review_src()
        assert "ls-files" in src
        assert "before_count" in src and "after_count" in src

    def test_push_aborts_when_reports_count_drops(self):
        """守卫逻辑: after < before → 中止 push"""
        src = self._review_src()
        assert "after_count < before_count" in src

    def test_module_has_no_other_bare_git_add_dot(self):
        """模块级扫描: generate_report.py 里不得再有裸 `git add '.'`"""
        path = os.path.join(PROJECT, "scripts", "generate_report.py")
        tree = ast.parse(open(path, encoding="utf-8").read())
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                args = node.args
                if len(args) == 3 and all(isinstance(a, ast.Constant) for a in args):
                    if [a.value for a in args] == ["git", "add", "."]:
                        offenders.append(node.lineno)
        assert not offenders, f"generate_report.py 仍有裸 `git add '.'` @ 行 {offenders}"

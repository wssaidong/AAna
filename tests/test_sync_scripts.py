#!/usr/bin/env python3
"""
tests/test_sync_scripts.py — 早盘/尾盘同步脚本的机器可读输出层单测

v2026-11-16: 锁定三件事
  ① 早盘 `sync_top10_v9.py --json` 的 stdout 只有 JSON + 退出码语义
     (0=已同步 / 1=0 推荐短路 / 2=异常或复核失败)
  ② 0 推荐短路时**一次东财 API 都不许调**
  ③ 尾盘 `sync_afternoon_pp.py` 同步后服务端必须恰好 1 只, 且幂等时不重复写
"""
import json
import os
import sys
from unittest.mock import patch

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))

import sync_afternoon_pp as sapp
import sync_top10_v9 as s9


class FakeEP:
    """假的东财客户端 (记录所有调用, 用来断言「有没有碰东财」)。"""

    def __init__(self):
        self.stocks = {}      # gid -> [codes]
        self.created = []     # 建组调用
        self.added = []       # add_stocks 调用
        self.deleted = []     # delete_group 调用
        self._next = 9000

    def get_group_stocks(self, gid):
        return [{"security": f"0${c}$0"} for c in self.stocks.get(gid, [])]

    def get_or_create_group(self, name):
        self.created.append(name)
        self._next += 1
        self.stocks.setdefault(self._next, [])
        return self._next

    def add_stocks(self, gid, codes):
        self.added.append((gid, list(codes)))
        cur = self.stocks.setdefault(gid, [])
        for c in codes:
            if c not in cur:
                cur.append(c)
        return len(codes)   # 真实实现返回 int (不是 dict)

    def delete_group(self, gid):
        self.deleted.append(gid)
        self.stocks.pop(gid, None)
        return True


@pytest.fixture
def fake_ep():
    return FakeEP()


@pytest.fixture
def no_sleep(monkeypatch):
    """去掉退役重建里的 3 秒等待。"""
    monkeypatch.setattr(sapp.time, "sleep", lambda s: None)


@pytest.fixture
def tmp_groups(tmp_path, monkeypatch):
    """把 groups.json 指到临时文件。"""
    p = tmp_path / "groups.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sapp, "GROUPS_JSON", p)
    return p


# ─────────────────────────────────────────────────────────
# ① 早盘 sync_top10_v9 --json
# ─────────────────────────────────────────────────────────

@pytest.fixture
def reports_dir(tmp_path, monkeypatch):
    """一个真实的报告目录 (空目录 = 没有报告 → 0 推荐短路)。"""
    d = tmp_path / "reports"
    d.mkdir()
    monkeypatch.setattr(s9, "REPORT_DIR", str(d))
    return d


def _run_json(argv):
    """跑 --json 模式, 返回 (exit_code, payload)。"""
    import io as _io
    from contextlib import redirect_stdout
    buf = _io.StringIO()
    with redirect_stdout(buf):
        code = s9.main(argv)
    payload = json.loads(buf.getvalue().strip().splitlines()[-1])
    return code, payload


class TestMorningJsonMode:
    def test_zero_recommend_short_circuit(self, reports_dir, monkeypatch):
        """0 推荐 → status=zero_recommend, exit 1, 且一次东财调用都没有"""
        (reports_dir / "2026-11-16-选股报告.md").write_text("# 报告\n", encoding="utf-8")
        monkeypatch.setattr(s9, "extract_top10", lambda p: [])
        with patch("eastmoney_portfolio.get_or_create_group") as goc:
            code, payload = _run_json(["--json"])
        assert code == 1
        assert payload["status"] == "zero_recommend"
        assert payload["codes"] == []
        assert goc.call_count == 0

    def test_no_report_file_is_error(self, reports_dir):
        """报告目录里一个报告都没有 = 报告没生成 → exit 2 (不是 0 推荐)"""
        code, payload = _run_json(["--json"])
        assert code == 2
        assert payload["status"] == "error"

    def test_missing_report_dir_is_error(self, tmp_path, monkeypatch):
        """报告目录不存在 = 异常 (不是 0 推荐) → exit 2"""
        monkeypatch.setattr(s9, "REPORT_DIR", str(tmp_path / "does_not_exist"))
        code, payload = _run_json(["--json"])
        assert code == 2
        assert payload["status"] == "error"

    def test_success_payload(self, reports_dir, monkeypatch):
        """正常同步 → status=synced + verified=True + codes"""
        (reports_dir / "2026-11-16-选股报告.md").write_text("# 报告\n", encoding="utf-8")
        monkeypatch.setattr(s9, "extract_top10", lambda p: ["600519", "000001"])
        final_codes = [{"security": "0$600519$0"}, {"security": "0$000001$0"}]
        with patch("eastmoney_portfolio.get_or_create_group", return_value=777):
            with patch("eastmoney_portfolio.add_stocks", return_value=2):
                # 第一次读 existing (空) → 新建; 第二次读 final (2 只) → 复核通过
                with patch("eastmoney_portfolio.get_group_stocks", side_effect=[[], final_codes]):
                    code, payload = _run_json(["--json"])
        assert code == 0
        assert payload["status"] == "synced"
        assert payload["verified"] is True
        assert payload["codes"] == ["600519", "000001"]
        assert payload["count"] == 2
        assert payload["gid"] == 777
        assert isinstance(payload["logs"], list)

    def test_verification_failure_is_error(self, reports_dir, monkeypatch):
        """复核不一致 → status=error, exit 2 (不能谎报成功)"""
        (reports_dir / "2026-11-16-选股报告.md").write_text("# 报告\n", encoding="utf-8")
        monkeypatch.setattr(s9, "extract_top10", lambda p: ["600519"])
        with patch("eastmoney_portfolio.get_or_create_group", return_value=778):
            with patch("eastmoney_portfolio.add_stocks", return_value=1):
                # existing 空 → 新建; final 读回 0 只 → 复核失败
                with patch("eastmoney_portfolio.get_group_stocks", side_effect=[[], []]):
                    code, payload = _run_json(["--json"])
        assert code == 2
        assert payload["status"] == "error"
        assert payload["verified"] is False
        assert "error" in payload

    def test_default_mode_exit_code_unchanged(self, reports_dir):
        """默认模式必须永远 exit 0 —— generate_report.py 内部靠它 (历史上多次 wrapper failed 内部成功)"""
        with patch.object(s9, "extract_top10", return_value=[]):
            code = s9.main([])
        assert code == 0


# ─────────────────────────────────────────────────────────
# ② 尾盘 sync_afternoon_pp
# ─────────────────────────────────────────────────────────

class TestAfternoonPP:
    def test_no_code_short_circuit(self, tmp_groups, no_sleep):
        """没有 --code → exit 1, 一次东财调用都没有 (9/1 0 推荐铁律)"""
        code = sapp.main([])
        assert code == 1

    def test_invalid_code(self, tmp_groups, no_sleep):
        code = sapp.main(["--code", "60x519"])
        assert code == 2

    def test_sync_single_stock(self, tmp_groups, no_sleep, fake_ep):
        """同步 1 只 → 服务端恰好 1 只, 缓存写回"""
        payload = sapp.sync_single_stock("600519", "20261116PP", ep=fake_ep)
        assert payload["status"] == "synced"
        assert payload["verified"] is True
        assert payload["existing"] == ["600519"]
        assert len(fake_ep.added) == 1
        # 缓存写回
        data = json.loads(tmp_groups.read_text(encoding="utf-8"))
        assert "20261116PP" in data
        assert data["20261116PP"]["stocks"] == ["600519"]

    def test_idempotent_no_rewrite(self, tmp_groups, no_sleep, fake_ep):
        """组内已经是这 1 只 → 幂等, 不做任何写操作"""
        gid = 9001
        fake_ep.stocks[gid] = ["600519"]
        tmp_groups.write_text(json.dumps({"20261116PP": {"gid": gid, "stocks": ["600519"]}}),
                              encoding="utf-8")
        payload = sapp.sync_single_stock("600519", "20261116PP", ep=fake_ep)
        assert payload["status"] == "idempotent"
        assert payload["action"] == "复用"
        assert fake_ep.added == []
        assert fake_ep.deleted == []

    def test_content_mismatch_triggers_rebuild(self, tmp_groups, no_sleep, fake_ep):
        """组内是别的股票 → 整组退役重建 (东财无单股删除 API)"""
        gid = 9002
        fake_ep.stocks[gid] = ["000001"]
        tmp_groups.write_text(json.dumps({"20261116PP": {"gid": gid, "stocks": ["000001"]}}),
                              encoding="utf-8")
        payload = sapp.sync_single_stock("600519", "20261116PP", ep=fake_ep)
        assert payload["status"] == "synced"
        assert payload["action"] == "退役重建"
        assert fake_ep.deleted == [gid]
        assert len(fake_ep.added) == 1

    def test_verification_failure_reports_error(self, tmp_groups, no_sleep):
        """写入后服务端读回不是目标 → status=error (不能谎报成功)"""

        class BrokenEP(FakeEP):
            def add_stocks(self, gid, codes):
                self.added.append((gid, list(codes)))
                return len(codes)   # 假装成功, 但服务端实际没写进去

        ep = BrokenEP()
        payload = sapp.sync_single_stock("600519", "20261116PP", ep=ep)
        assert payload["status"] == "error"
        assert payload.get("error")
        assert payload["verified"] is not True

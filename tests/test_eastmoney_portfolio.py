#!/usr/bin/env python3
"""tests/test_eastmoney_portfolio.py — Phase 1B eastmoney_portfolio 单测

v2026-08-23: 锁定 L410 fix 单测 (cleanup([]) 不清空已有 stocks)
              锁定 api_call_dict helper 工作
              第一天新建 → 真实 stocks 写入
              cleanup 保留 stocks across multiple sync calls
"""
import json
import os
import sys
from datetime import datetime
from unittest.mock import patch

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))

import eastmoney_portfolio as ep


class TestApiCallDict:
    """Phase 1B-2: api_call_dict helper"""

    def test_returns_dict_part(self):
        """不传 max_retries: 调用方拿到的就是 dict 部分"""
        with patch.object(ep, "api_call", return_value=({"state": 0, "data": {}}, 1)):
            r = ep.api_call_dict("fake://url")
        assert isinstance(r, dict)
        assert r["state"] == 0

    def test_passes_max_retries(self):
        with patch.object(ep, "api_call", return_value=({"state": 0}, 1)) as mock_call:
            ep.api_call_dict("fake://url", max_retries=5)
        args, _ = mock_call.call_args
        assert args[0] == "fake://url"
        assert mock_call.call_args.kwargs.get("max_retries") == 5


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """把 ~/.hermes/ 整个映射到 tmp_path/fake_home."""
    fake_home_dir = tmp_path / "fake_home"
    fake_home_dir.mkdir()
    target_dir = fake_home_dir / ".hermes" / "skills" / "a-stock" / "eastmoney-portfolio-api"
    target_dir.mkdir(parents=True)
    target_groups = target_dir / "groups.json"
    with open(target_groups, "w") as f:
        json.dump({}, f)

    real_expanduser = os.path.expanduser

    def fake_expanduser(p):
        if isinstance(p, str) and p.startswith("~"):
            return str(fake_home_dir) + p[1:]
        return real_expanduser(p)

    monkeypatch.setattr(os.path, "expanduser", fake_expanduser)
    return target_groups


def _run_sync(monkeypatch, target_groups, today_str, stock_codes, gid):
    """Helper: 同步一次，given mock setup. Returns the written groups_file."""
    with patch.object(ep, "get_or_create_group", return_value=gid), \
         patch.object(ep, "add_stocks", return_value=len(stock_codes)), \
         patch.object(ep, "delete_group", return_value=True), \
         patch.object(ep, "load_cookie", return_value=("", {})), \
         patch.object(ep, "save_cookie"):
        ok = ep.sync_portfolio_to_eastmoney(
            stock_codes=stock_codes,
            group_name=today_str,
        )
    assert ok
    with open(target_groups) as f:
        return json.load(f)


class TestSyncPortfolioL410Fix:
    """Phase 1B-1: cleanup([]) 不清空已有 stocks"""

    def test_cleanup_preserves_existing_stocks(self, fake_home, monkeypatch):
        """核心场景: 今日条目已有 stocks → cleanup([]) 不清空它们。"""
        target_groups = fake_home
        today_str = datetime.now().strftime("%Y%m%d")
        seed = {
            today_str: {
                "gid": 9999,
                "date": today_str,
                "stocks": ["600000", "601318", "002594"],
            }
        }
        with open(target_groups, "w") as f:
            json.dump(seed, f, ensure_ascii=False, indent=2)

        after = _run_sync(monkeypatch, target_groups, today_str, [], 9999)
        assert after[today_str]["stocks"] == ["600000", "601318", "002594"], \
            f"stocks got wiped: {after}"

    def test_first_time_creates_with_real_stocks(self, fake_home, monkeypatch):
        """Phase 1B-1 (L410 fix): 第一天新建 → 真实 stocks 写入"""
        target_groups = fake_home
        today_str = datetime.now().strftime("%Y%m%d")
        new_codes = ["601398", "600519", "601318"]

        after = _run_sync(monkeypatch, target_groups, today_str, new_codes, 7777)
        assert after[today_str]["stocks"] == new_codes, \
            f"first-time create wrote wrong stocks: {after}"

    def test_second_cleanup_still_preserves(self, fake_home, monkeypatch):
        """二次 cleanup 也不应当把已有的 4 只 stocks 删掉"""
        target_groups = fake_home
        today_str = datetime.now().strftime("%Y%m%d")
        seed = {
            today_str: {
                "gid": 9999,
                "date": today_str,
                "stocks": ["600000", "601318"],
            }
        }
        with open(target_groups, "w") as f:
            json.dump(seed, f, ensure_ascii=False, indent=2)

        # First cleanup
        _run_sync(monkeypatch, target_groups, today_str, [], 9999)
        # Second cleanup
        after = _run_sync(monkeypatch, target_groups, today_str, [], 9999)
        assert after[today_str]["stocks"] == ["600000", "601318"]


class TestGetOrCreateGroupSmoke:
    """Smoke test: mkurl 参数正确"""

    def test_mkurl_basic(self):
        url = ep.mkurl("ag", gn="20260101")
        assert "appkey=" in url
        assert "gn=20260101" in url
        assert url.startswith(ep.BASE_URL)

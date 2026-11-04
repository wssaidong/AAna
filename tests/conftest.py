"""tests/conftest.py — 全局测试隔离

XWI-80 P0-1 起 data/quotes.py 的 kline() 会「store 优先 + 网络回写」，
测试中任何 fake K 线（如 test_kline_field_mapping 的 FAKE_BAR）都可能经
回写路径污染 ~/.aana/market_store.db 生产库。本 fixture 把所有测试的
market_store 指向每个测试独立的临时 SQLite，杜绝污染。
"""
import os
import sys

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)


@pytest.fixture(autouse=True)
def isolate_market_store(tmp_path, monkeypatch):
    monkeypatch.setenv("AANA_MARKET_STORE_DB", str(tmp_path / "market_store_test.db"))
    yield

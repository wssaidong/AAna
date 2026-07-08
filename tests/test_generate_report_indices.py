"""
tests/test_generate_report_indices.py — generate_report 指数 fallback 回归测试

覆盖 2026-07-03/07-08 P0：报告显示“上证指数 数据待获取 +0.00%”，
但 market_sentiment.get_index_data() 实际可以拉到指数。
"""
import os
import sys
import warnings

warnings.filterwarnings("ignore")

PROJECT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))

import generate_report as gr


def test_refresh_index_prices_uses_market_sentiment_names():
    """指数代码不在股票池时，应按 market_sentiment 返回的 name 补进 prices。"""
    prices = {}

    def fake_get_index_data():
        return [
            {"name": "上证指数", "price": 3970.88, "change": -0.49},
            {"name": "深证成指", "price": 14939.73, "change": -1.87},
            {"name": "创业板指", "price": 3845.35, "change": -1.70},
            {"name": "沪深300", "price": 4755.53, "change": -0.77},
        ]

    count = gr.refresh_index_prices_from_market_sentiment(prices, fake_get_index_data)

    assert count == 4
    assert prices["000001"]["name"] == "上证指数"
    assert prices["000001"]["price"] == 3970.88
    assert prices["000001"]["change_pct"] == -0.49
    assert prices["399001"]["name"] == "深证成指"
    assert prices["399006"]["name"] == "创业板指"
    assert prices["000300"]["name"] == "沪深300"


def test_refresh_index_prices_skips_invalid_or_unknown_indices():
    """未知名称/无效价格不应污染 prices，也不应抛异常。"""
    prices = {"000001": {"name": "上证指数", "price": 1, "change_pct": 0}}

    def fake_get_index_data():
        return [
            {"name": "未知指数", "price": 1234.56, "change": 1.23},
            {"name": "深证成指", "price": 0, "change": 0.12},
            {"name": "创业板指", "price": "not-a-number", "change": 0.12},
        ]

    count = gr.refresh_index_prices_from_market_sentiment(prices, fake_get_index_data)

    assert count == 0
    assert list(prices.keys()) == ["000001"]
    assert prices["000001"]["price"] == 1


def test_market_overview_renders_all_available_indices():
    """大盘概览不应再把深证/创业板/沪深300硬编码成 '-'。"""
    prices = {
        "000001": {"name": "上证指数", "price": 3970.88, "change_pct": -0.49},
        "399001": {"name": "深证成指", "price": 14939.73, "change_pct": -1.87},
        "399006": {"name": "创业板指", "price": 3845.35, "change_pct": -1.70},
        "000300": {"name": "沪深300", "price": 4755.53, "change_pct": -0.77},
    }

    rows = gr.format_market_overview_rows(prices)

    assert "| 上证指数 | 3970.88 | 🟢 下跌 |" in rows
    assert "| 深证成指 | 14939.73 | 🟢 下跌 |" in rows
    assert "| 创业板指 | 3845.35 | 🟢 下跌 |" in rows
    assert "| 沪深300 | 4755.53 | 🟢 下跌 |" in rows
    assert "数据待获取" not in rows
    assert "| 深证成指 | - | - |" not in rows
    assert "| 创业板 | - | - |" not in rows

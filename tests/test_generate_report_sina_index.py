"""
tests/test_generate_report_sina_index.py — sina 指数代码交易所前缀回归测试

覆盖 2026-11-05 P1: 复盘评分报告"大盘环境对比"表把**平安银行**当成上证指数显示。
根因: generate_report.get_stock_data_sina() 的 get_market_sina() 按个股规则加前缀,
      '000001' → 'sz000001' = 平安银行 (个股), 而不是 'sh000001' = 上证指数。
      同理 '000688' → 'sz000688' = 国城矿业, 而不是 'sh000688' = 科创50。

实测症状 (11-05): 复盘报告写「上证指数 | - | 11.73 | -0.09%」, 真实上证 3665.70 / -0.34%。

修法: 拆出独立的 get_index_data_sina() (专属前缀表), 与个股取数分离
      —— 因为个股池里 '000001' 可能真的是平安银行, 不能改个股的前缀规则。

断言方式: 全 mock requests.get, 不打真实网络 (遵守"测试断言避免硬编码历史快照数字"的反面:
          这里断言的是**前缀映射逻辑**本身, 属于结构性不变量, 不是历史数值快照)。
"""
import os
import sys
import warnings

warnings.filterwarnings("ignore")

PROJECT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))

import generate_report as gr


class _FakeResp:
    def __init__(self, text):
        self.text = text
        self.encoding = None


def _sina_line(symbol, name, prev_close, price):
    """构造一行 sina hq 返回: name,open,prev_close,price,high,low,...,volume,amount"""
    fields = [name, "0", str(prev_close), str(price), "0", "0", "0", "0", "0", "1000"]
    return f'var hq_str_{symbol}="{",".join(fields)}";'


def test_index_prefix_map_uses_sh_for_shanghai_indices():
    """000001/000300/000688 必须映射到 sh (上证/沪深300/科创50), 不能是 sz。"""
    assert gr._INDEX_SINA_PREFIX["000001"] == "sh"
    assert gr._INDEX_SINA_PREFIX["000300"] == "sh"
    assert gr._INDEX_SINA_PREFIX["000688"] == "sh"
    assert gr._INDEX_SINA_PREFIX["399001"] == "sz"
    assert gr._INDEX_SINA_PREFIX["399006"] == "sz"


def test_get_index_data_sina_requests_sh_prefix_for_000001(monkeypatch):
    """核心回归: 拉上证指数时请求的必须是 sh000001, 而不是 sz000001。"""
    requested = {}

    def fake_get(url, headers=None, timeout=None):
        requested["url"] = url
        return _FakeResp("\n".join([
            _sina_line("sh000001", "上证指数", 3665.0, 3680.0),
            _sina_line("sz399001", "深证成指", 11300.0, 11400.0),
        ]))

    monkeypatch.setattr(gr.requests if hasattr(gr, "requests") else __import__("requests"),
                        "get", fake_get)
    import requests
    monkeypatch.setattr(requests, "get", fake_get)

    result = gr.get_index_data_sina(["000001", "399001"])

    assert "sh000001" in requested["url"], f"必须请求 sh000001, 实际: {requested['url']}"
    assert "sz000001" not in requested["url"], f"不能请求 sz000001 (那是平安银行): {requested['url']}"
    assert result["000001"]["name"] == "上证指数"
    assert result["000001"]["price"] == 3680.0
    assert result["399001"]["name"] == "深证成指"


def test_get_index_data_sina_does_not_use_stock_prefix_rule(monkeypatch):
    """指数取数与个股取数是两条路径 —— 指数函数不得走 get_market_sina 的个股规则。"""
    requested = {}

    def fake_get(url, headers=None, timeout=None):
        requested["url"] = url
        return _FakeResp(_sina_line("sh000688", "科创50", 1200.0, 1287.0))

    import requests
    monkeypatch.setattr(requests, "get", fake_get)

    result = gr.get_index_data_sina(["000688"])

    assert "sh000688" in requested["url"]
    assert "sz000688" not in requested["url"], f"不能请求 sz000688 (那是国城矿业): {requested['url']}"
    assert result["000688"]["name"] == "科创50"


def test_get_stock_data_sina_still_resolves_000001_as_stock(monkeypatch):
    """个股取数**不能**被改成 sh 前缀 —— 个股池里 000001 可能真的是平安银行。"""
    requested = {}

    def fake_get(url, headers=None, timeout=None):
        requested["url"] = url
        return _FakeResp(_sina_line("sz000001", "平安银行", 11.70, 11.64))

    import requests
    monkeypatch.setattr(requests, "get", fake_get)

    result = gr.get_stock_data_sina(["000001"])

    assert "sz000001" in requested["url"], f"个股 000001 必须走 sz (平安银行): {requested['url']}"
    assert result["000001"]["name"] == "平安银行"


def test_get_index_data_sina_fills_missing_codes(monkeypatch):
    """接口没返回的指数要补零值占位, 不能 KeyError。"""
    import requests
    monkeypatch.setattr(requests, "get", lambda url, headers=None, timeout=None: _FakeResp(""))

    result = gr.get_index_data_sina(["000001", "399001"])

    assert set(result.keys()) == {"000001", "399001"}
    assert result["000001"]["price"] == 0
    assert result["000001"]["change_pct"] == 0


def test_review_report_uses_index_fetcher_not_stock_fetcher():
    """调用点回归: 复盘报告的指数取数必须走 get_index_data_sina。

    只测函数存在不够 —— 11-05 首次修复时新函数建好了但调用点还指向旧的
    get_stock_data_sina, 测试全绿而线上仍显示平安银行。这里直接断言源码调用点。
    """
    import inspect

    src = inspect.getsource(gr.generate_review_report)
    assert "get_index_data_sina(index_codes)" in src, \
        "复盘报告的指数取数必须调用 get_index_data_sina(index_codes)"
    assert "get_stock_data_sina(index_codes)" not in src, \
        "复盘报告不能复用个股取数拉指数 (000001 → 平安银行)"


def test_review_report_has_index_sanity_guard():
    """调用点必须有 sanity guard: 指数点位 <1000 说明又取到个股 → 丢弃。"""
    import inspect

    src = inspect.getsource(gr.generate_review_report)
    assert "_BAD_INDEX" in src and "点位异常" in src, \
        "复盘报告的指数取数必须带点位量级 sanity check (fail-closed)"


def test_review_report_index_rows_use_index_data_not_stock_prices():
    """核心调用点回归: 指数行必须读 index_data, 不能读 current_prices。

    11-05 真实根因: index_data 虽然用对了取数函数, 但渲染 index_rows 时读的是
    current_prices (来自 get_stock_data_sina(all_codes), all_codes 含指数代码
    000001 → sz000001 = 平安银行) → 报告写"上证指数 11.62"。
    只测"取数函数对"不够, 必须测"渲染用哪个 dict"。
    """
    import inspect

    src = inspect.getsource(gr.generate_review_report)
    idx_block = src.split("index_rows = []", 1)[1].split("模拟交易", 1)[0]
    assert "index_data.get(code" in idx_block, \
        "指数行必须从 index_data 取 (get_index_data_sina 的结果)"
    assert "current_prices.get(code" not in idx_block, \
        "指数行不能从 current_prices 取 (那是个股口径, 000001=平安银行)"

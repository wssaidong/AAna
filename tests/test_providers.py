"""
tests/test_providers.py — 数据源 Provider 契约层单测

版本: v1.0 (2026-11-16)

覆盖:
  ① ProviderRequestError 在三个适配器里被 raise (模拟底层抛异常 / 空数据冒充成功)
  ② 注册 / 查询 / 列举
  ③ build_capability_matrix 结构正确
  ④ capability_gate 在能力缺失时返回 False
  ⑤ 探测失败不抛异常, 且对应能力位 usable=False + 错误可归因
  ⑥ 适配器成功路径返回规范化字段 (至少含 code / name / price)

⚠️ 硬约束: 本文件 **禁止访问外网**。
   - autouse fixture 直接封死 socket.connect, 任何漏网的真实网络调用会立刻失败
   - 所有 data_sources 函数 / requests.get 都被 monkeypatch 成内存桩
"""

import os
import socket
import sys

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(PROJECT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from providers import base as pbase                      # noqa: E402
from providers import capabilities as pcap                # noqa: E402
from providers import eastmoney as p_em                   # noqa: E402
from providers import registry as preg                    # noqa: E402
from providers import sina as p_sina                      # noqa: E402
from providers import tencent as p_tx                     # noqa: E402
from providers.base import (                              # noqa: E402
    CAPABILITY_IDS,
    ProviderCapabilities,
    ProviderRequestError,
)


# ======================================================================
# 全局隔离: 禁止任何真实网络
# ======================================================================

@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    """封死所有 socket 连接 — 任何真实网络访问都会让测试直接失败。"""
    def _blocked(*args, **kwargs):
        raise AssertionError("测试禁止访问外网: 检测到真实 socket 连接")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield


@pytest.fixture
def clean_registry():
    """保存在场 provider, 清空注册表给用例独占, 结束后还原。"""
    saved = dict(preg._REGISTRY)
    saved_errors = {k: dict(v) for k, v in preg._PROBE_ERRORS.items()}
    preg.clear_registry()
    try:
        yield preg
    finally:
        preg.clear_registry()
        preg._REGISTRY.update(saved)
        preg._PROBE_ERRORS.update(saved_errors)


class FakeProvider:
    """测试用最小 provider — 可单独指定每个方法的返回 / 抛错行为。"""

    name = "fake"

    def __init__(self, caps=None, daily=None, realtime=None, instruments=None):
        self.capabilities = caps or ProviderCapabilities(daily=True, realtime=True)
        self._daily = daily
        self._realtime = realtime
        self._instruments = instruments

    def get_instruments(self, asset_type="stock"):
        if isinstance(self._instruments, Exception):
            raise self._instruments
        return self._instruments if self._instruments is not None else []

    def get_daily(self, symbols, start_time, end_time, asset_type="stock"):
        if isinstance(self._daily, Exception):
            raise self._daily
        return self._daily if self._daily is not None else []

    def get_realtime(self, universes=None, symbols=None):
        if isinstance(self._realtime, Exception):
            raise self._realtime
        return self._realtime if self._realtime is not None else []


class FakeResponse:
    """requests.Response 的最小桩 — 只实现适配器用到的 .json()。"""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


# ======================================================================
# ① ProviderRequestError 契约本身
# ======================================================================

def test_provider_request_error_is_runtime_error_with_required_docstring():
    """ProviderRequestError 必须是 RuntimeError 子类, docstring 含中文硬要求。"""
    assert issubclass(ProviderRequestError, RuntimeError)
    doc = ProviderRequestError.__doc__ or ""
    assert "数据源明确请求失败" in doc
    assert "调用方须标记失败" in doc
    assert "不得转换成成功的空数据" in doc


def test_tencent_raises_when_underlying_throws(monkeypatch):
    """① 腾讯: 底层 tencent_quote 抛异常 → 适配器抛 ProviderRequestError。"""
    monkeypatch.setattr(p_tx._ds, "tencent_quote",
                        lambda codes: (_ for _ in ()).throw(ValueError("boom")))
    with pytest.raises(ProviderRequestError) as ei:
        p_tx.TencentProvider().get_realtime(symbols=["600519"])
    assert "腾讯行情请求失败" in str(ei.value)


def test_tencent_raises_when_result_empty(monkeypatch):
    """① 腾讯: 底层吞异常返回空 dict (冒充成功) → 适配器仍须抛错。"""
    monkeypatch.setattr(p_tx._ds, "tencent_quote", lambda codes: {})
    # 兜底原始请求也失败 (模拟网络全断)
    monkeypatch.setattr(p_tx.requests, "get",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("net down")))
    with pytest.raises(ProviderRequestError) as ei:
        p_tx.TencentProvider().get_realtime(symbols=["600519"])
    assert "原始请求失败" in str(ei.value) or "空结果" in str(ei.value)


def test_sina_raises_when_underlying_throws(monkeypatch):
    """① 新浪: 底层 sina_quote 抛异常 → ProviderRequestError。"""
    monkeypatch.setattr(p_sina._ds, "sina_quote",
                        lambda codes: (_ for _ in ()).throw(RuntimeError("kaboom")))
    with pytest.raises(ProviderRequestError) as ei:
        p_sina.SinaProvider().get_realtime(symbols=["600519"])
    assert "新浪行情请求失败" in str(ei.value)


def test_sina_raises_on_placeholder_rows(monkeypatch):
    """① 新浪: 底层返回全占位行 (name=''/price=0) → 判失败而非"成功的空数据"。"""
    monkeypatch.setattr(p_sina._ds, "sina_quote",
                        lambda codes: {"600519": {"code": "600519", "name": "",
                                                  "price": 0, "change_pct": 0, "amount": 0}})
    with pytest.raises(ProviderRequestError) as ei:
        p_sina.SinaProvider().get_realtime(symbols=["600519"])
    assert "占位行" in str(ei.value)


def test_eastmoney_raises_when_underlying_throws(monkeypatch):
    """① 东财: 底层 eastmoney_datacenter 抛异常 → ProviderRequestError。"""
    monkeypatch.setattr(p_em._ds, "eastmoney_datacenter",
                        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("reset")))
    with pytest.raises(ProviderRequestError) as ei:
        p_em.EastmoneyProvider().get_instruments("stock")
    assert "东财 datacenter 请求失败" in str(ei.value)


def test_eastmoney_raises_when_datacenter_returns_empty(monkeypatch):
    """① 东财: datacenter 返回 [] (内部吞异常) → 仍须抛错并带上 report 名。"""
    monkeypatch.setattr(p_em._ds, "eastmoney_datacenter", lambda *a, **k: [])
    with pytest.raises(ProviderRequestError) as ei:
        p_em.EastmoneyProvider().get_financial("600519")
    assert "返回空结果" in str(ei.value)
    assert "RPT_LICO_FN_CPD" in str(ei.value)


def test_eastmoney_raises_on_kline_failure(monkeypatch):
    """① 东财: push2his K 线请求异常 → ProviderRequestError (不返回空 K 线)。"""
    monkeypatch.setattr(p_em.requests, "get",
                        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("disconnected")))
    with pytest.raises(ProviderRequestError) as ei:
        p_em.EastmoneyProvider().get_daily(["600519"], "", "", "stock")
    assert "东财K线请求失败" in str(ei.value)


# ======================================================================
# ② 注册 / 查询 / 列举
# ======================================================================

def test_register_get_list_provider(clean_registry):
    """② 注册后能按名查询、能列举, 且顺序即注册顺序。"""
    p1 = FakeProvider()
    p1.name = "alpha"
    p2 = FakeProvider()
    p2.name = "beta"

    clean_registry.register_provider(p1)
    clean_registry.register_provider(p2)

    assert clean_registry.list_providers() == ["alpha", "beta"]
    assert clean_registry.get_provider("alpha") is p1
    assert clean_registry.get_provider("beta") is p2


def test_get_unknown_provider_raises_keyerror(clean_registry):
    """② 查不存在的 provider → KeyError (不返回 None 让调用方踩空指针)。"""
    with pytest.raises(KeyError):
        clean_registry.get_provider("nope")


def test_register_rejects_invalid_provider(clean_registry):
    """② 非法对象注册 → TypeError。"""
    class NoName:
        capabilities = ProviderCapabilities(daily=True)

        def get_instruments(self, asset_type="stock"):
            return []

        def get_daily(self, *a, **k):
            return []

        def get_realtime(self, *a, **k):
            return []

    with pytest.raises(TypeError):
        clean_registry.register_provider(NoName())


def test_register_dedup_without_overwrite(clean_registry):
    """② overwrite=False 时重复注册不同实例 → ValueError。"""
    a1 = FakeProvider()
    a1.name = "dup"
    a2 = FakeProvider()
    a2.name = "dup"
    clean_registry.register_provider(a1, overwrite=False)
    with pytest.raises(ValueError):
        clean_registry.register_provider(a2, overwrite=False)


def test_builtin_providers_registered_at_import():
    """② 内置三源在 import 时自动注册 (能力矩阵开箱可用)。"""
    names = preg.list_providers()
    for expected in ("tencent", "sina", "eastmoney"):
        assert expected in names


# ======================================================================
# ③ 能力矩阵
# ======================================================================

def test_capability_matrix_structure(clean_registry):
    """③ 矩阵覆盖全部能力位, 每项含 provider/usable 且类型正确。"""
    p = FakeProvider(caps=ProviderCapabilities(daily=True, realtime=True, financial=True))
    p.name = "matrix_src"
    clean_registry.register_provider(p)

    matrix = clean_registry.build_capability_matrix()
    assert set(matrix.keys()) == set(CAPABILITY_IDS)

    for cap_id, info in matrix.items():
        assert set(info.keys()) == {"provider", "usable"}
        assert isinstance(info["usable"], bool)
        assert info["provider"] is None or isinstance(info["provider"], str)

    assert matrix["daily"] == {"provider": "matrix_src", "usable": True}
    assert matrix["realtime"] == {"provider": "matrix_src", "usable": True}
    assert matrix["financial"] == {"provider": "matrix_src", "usable": True}
    # 未声明的能力位 → provider=None, usable=False
    assert matrix["depth5"] == {"provider": None, "usable": False}
    assert matrix["instruments"] == {"provider": None, "usable": False}


def test_capability_matrix_prefers_first_registered(clean_registry):
    """③ 同一能力被多个 provider 声明时, 取注册顺序第一个。"""
    first = FakeProvider(caps=ProviderCapabilities(daily=True))
    first.name = "first"
    second = FakeProvider(caps=ProviderCapabilities(daily=True))
    second.name = "second"
    clean_registry.register_provider(first)
    clean_registry.register_provider(second)

    assert clean_registry.build_capability_matrix()["daily"]["provider"] == "first"


def test_capability_matrix_after_probe_downgrade(clean_registry, monkeypatch):
    """③ 探测失败后能力位被置 False, 矩阵生效源让位给其它源。"""
    broken = FakeProvider(caps=ProviderCapabilities(daily=True),
                          daily=ProviderRequestError("日线挂了"))
    broken.name = "broken"
    backup = FakeProvider(caps=ProviderCapabilities(daily=True),
                          daily=[{"code": "600519", "date": "2026-11-14"}])
    backup.name = "backup"
    clean_registry.register_provider(broken)
    clean_registry.register_provider(backup)

    assert clean_registry.build_capability_matrix()["daily"]["provider"] == "broken"

    clean_registry.probe_capabilities("broken")
    assert clean_registry.build_capability_matrix()["daily"]["provider"] == "backup"


# ======================================================================
# ④ capability_gate
# ======================================================================

def test_capability_gate_true_for_declared(clean_registry):
    """④ 声明的能力 → (True, 标签含 provider 名)。"""
    p = FakeProvider(caps=ProviderCapabilities(daily=True))
    p.name = "gated"
    clean_registry.register_provider(p)

    ok, label = clean_registry.capability_gate("daily")
    assert ok is True
    assert "gated" in label


def test_capability_gate_false_when_missing(clean_registry):
    """④ 无人提供的能力 → (False, 说明标签), 不抛异常。"""
    p = FakeProvider(caps=ProviderCapabilities(daily=True))
    p.name = "only_daily"
    clean_registry.register_provider(p)

    ok, label = clean_registry.capability_gate("depth5")
    assert ok is False
    assert "depth5" in label
    assert "不可用" in label


def test_capability_gate_false_on_unknown_capability(clean_registry):
    """④ 未知能力名 → (False, 提示合法取值)。"""
    ok, label = clean_registry.capability_gate("no_such_cap")
    assert ok is False
    assert "未知能力" in label


# ======================================================================
# ⑤ 探测失败不抛异常 + usable=False
# ======================================================================

def test_probe_failure_does_not_raise_and_marks_unusable(clean_registry):
    """⑤ provider 方法全抛错 → probe 不抛异常, 能力位全 False, 错误可归因。"""
    p = FakeProvider(
        caps=ProviderCapabilities(daily=True, realtime=True, instruments=True),
        daily=ProviderRequestError("日线 500"),
        realtime=TimeoutError("实时超时"),
        instruments=ConnectionError("清单断连"),
    )
    p.name = "all_broken"
    clean_registry.register_provider(p)

    caps = clean_registry.probe_capabilities("all_broken")  # 不得抛异常

    assert caps.daily is False
    assert caps.realtime is False
    assert caps.instruments is False
    assert clean_registry.build_capability_matrix()["daily"]["usable"] is False

    errs = clean_registry.get_probe_errors()["all_broken"]
    assert "日线 500" in errs["daily"]
    assert "实时超时" in errs["realtime"]


def test_probe_success_keeps_capability_usable(clean_registry):
    """⑤ 探测成功 → 能力位保持 True。"""
    p = FakeProvider(
        caps=ProviderCapabilities(daily=True, realtime=True),
        daily=[{"code": "600519", "date": "2026-11-14"}],
        realtime=[{"code": "600519", "name": "贵州茅台", "price": 1435.2}],
    )
    p.name = "healthy"
    clean_registry.register_provider(p)

    caps = clean_registry.probe_capabilities("healthy")
    assert caps.daily is True
    assert caps.realtime is True
    assert clean_registry.get_probe_errors()["healthy"] == {}


def test_probe_of_unknown_provider_does_not_raise(clean_registry):
    """⑤ 探测不存在的 provider → 返回全 False 能力位, 不抛异常。"""
    caps = clean_registry.probe_capabilities("not_registered")
    assert caps == ProviderCapabilities()


def test_probe_skips_undeclared_capabilities(clean_registry):
    """⑤ 未声明的能力不探测 (不打无意义的网络请求)。"""
    calls = {"n": 0}

    class Spy:
        name = "spy"
        capabilities = ProviderCapabilities(daily=True)

        def get_instruments(self, asset_type="stock"):
            calls["n"] += 1
            return [{"code": "600519"}]

        def get_daily(self, symbols, start_time, end_time, asset_type="stock"):
            return [{"code": "600519", "date": "2026-11-14"}]

        def get_realtime(self, universes=None, symbols=None):
            calls["n"] += 1
            return [{"code": "600519", "name": "x", "price": 1.0}]

    clean_registry.register_provider(Spy())
    caps = clean_registry.probe_capabilities("spy")

    assert caps.daily is True
    assert caps.instruments is False
    assert caps.realtime is False
    assert calls["n"] == 0, "未声明的能力不应触发真实请求"


def test_capability_report_renders_error_reason(clean_registry):
    """⑤ capability_report 在能力不可用时展示探测错误原文。"""
    p = FakeProvider(caps=ProviderCapabilities(daily=True),
                     daily=ProviderRequestError("K线接口 502"))
    p.name = "report_src"
    clean_registry.register_provider(p)
    clean_registry.probe_capabilities("report_src")

    text = pcap.capability_report()
    assert "能力" in text and "生效源" in text and "是否可用" in text and "错误原因" in text
    assert "K线接口 502" in text
    for cap_id in CAPABILITY_IDS:
        assert cap_id in text


def test_probe_recovers_after_transient_failure(clean_registry):
    """⑤ 回归: 一次探测失败不能把能力位永久锁死 —— 接口恢复后须能重新置 True。

    旧实现的坑: 探测只探测"当前已声明为 True"的位, 失败后该位变 False,
    下次探测就跳过它 → 一次瞬时断连 = 永久降级。
    """
    class Flaky:
        name = "flaky"
        capabilities = ProviderCapabilities(daily=True)

        def __init__(self):
            self.healthy = False

        def get_instruments(self, asset_type="stock"):
            return []

        def get_daily(self, symbols, start_time, end_time, asset_type="stock"):
            if not self.healthy:
                raise ProviderRequestError("暂时断连")
            return [{"code": "600519", "date": "2026-11-14"}]

        def get_realtime(self, universes=None, symbols=None):
            return []

    prov = Flaky()
    clean_registry.register_provider(prov)

    assert clean_registry.probe_capabilities("flaky").daily is False
    assert clean_registry.build_capability_matrix()["daily"]["usable"] is False

    prov.healthy = True  # 接口恢复
    assert clean_registry.probe_capabilities("flaky").daily is True
    assert clean_registry.build_capability_matrix()["daily"]["usable"] is True


# ======================================================================
# ⑥ 适配器成功路径 → 规范化字段 (code / name / price)
# ======================================================================

def test_tencent_realtime_normalizes_fields(monkeypatch):
    """⑥ 腾讯成功路径: 返回含 code/name/price 的普通 list[dict]。"""
    monkeypatch.setattr(p_tx._ds, "tencent_quote", lambda codes: {
        "600519": {"name": "贵州茅台", "price": 1435.26, "last_close": 1410.27,
                   "change_pct": 1.77, "open": 1404.0, "high": 1437.69, "low": 1394.0,
                   "amount_wan": 595483.0, "turnover_pct": 0.33, "pe_ttm": 21.84,
                   "pb": 8.0, "mcap_yi": 18000.0, "limit_up": 1551.3, "limit_down": 1269.2},
        # data_sources 会同时塞入带前缀的镜像 key, 适配器必须去重
        "sh600519": {"name": "贵州茅台", "price": 1435.26, "last_close": 1410.27,
                     "change_pct": 1.77},
    })

    rows = p_tx.TencentProvider().get_realtime(symbols=["600519"])

    assert isinstance(rows, list)
    assert len(rows) == 1, "带前缀的镜像 key 不应产生重复行"
    row = rows[0]
    assert row["code"] == "600519"
    assert row["name"] == "贵州茅台"
    assert row["price"] == 1435.26
    assert row["source"] == "tencent"


def test_sina_realtime_normalizes_fields(monkeypatch):
    """⑥ 新浪成功路径: 返回含 code/name/price 的普通 list[dict]。"""
    monkeypatch.setattr(p_sina._ds, "sina_quote", lambda codes: {
        "600519": {"code": "600519", "name": "贵州茅台", "price": 1435.26,
                   "yesterday_close": 1410.27, "open": 1404.0, "high": 1437.69,
                   "low": 1394.0, "change_pct": 1.77, "change_amt": 24.99,
                   "amount": 5954834070.0},
    })

    rows = p_sina.SinaProvider().get_realtime(symbols=["600519"])
    row = rows[0]
    assert row["code"] == "600519"
    assert row["name"] == "贵州茅台"
    assert row["price"] == 1435.26
    assert row["source"] == "sina"


def test_tencent_daily_normalizes_fields(monkeypatch):
    """⑥ 腾讯日线成功路径: [date, open, close, high, low, volume] 顺序不能错位。"""
    monkeypatch.setattr(p_tx.requests, "get", lambda *a, **k: FakeResponse({
        "code": 0,
        "data": {"sh600519": {"qfqday": [
            ["2026-11-13", "1410.00", "1439.10", "1447.00", "1395.02", "82691.00"],
        ]}},
    }))

    rows = p_tx.TencentProvider().get_daily(["600519"], "2026-11-01", "2026-11-30", "stock")

    assert rows and rows[0]["code"] == "600519"
    bar = rows[0]
    assert bar["date"] == "2026-11-13"
    assert bar["open"] == 1410.0
    assert bar["close"] == 1439.1   # bar[2] 是收盘, 不是最高
    assert bar["high"] == 1447.0
    assert bar["low"] == 1395.02


def test_eastmoney_instruments_normalizes_fields(monkeypatch):
    """⑥ 东财标的清单成功路径: code/name 规范化, 并透传数据源标记。"""
    monkeypatch.setattr(p_em._ds, "eastmoney_datacenter", lambda *a, **k: [
        {"SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "贵州茅台",
         "SECUCODE": "600519.SH", "LISTING_STATE": "0"},
    ])

    rows = p_em.EastmoneyProvider().get_instruments("stock")
    assert rows[0]["code"] == "600519"
    assert rows[0]["name"] == "贵州茅台"
    assert rows[0]["market"] == "SH"
    assert rows[0]["source"] == "eastmoney"


def test_eastmoney_financial_normalizes_fields(monkeypatch):
    """⑥ 东财财务成功路径: 字段名从东财大写列名映射到规范化小写。"""
    monkeypatch.setattr(p_em._ds, "eastmoney_datacenter", lambda *a, **k: [
        {"SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "贵州茅台",
         "REPORTDATE": "2026-09-30 00:00:00", "REPORT_TYPE": "三季报",
         "BASIC_EPS": 50.1, "TOTAL_OPERATE_INCOME": 1.2e11,
         "PARENT_NETPROFIT": 6.0e10, "WEIGHTAVG_ROE": 30.5},
    ])

    rows = p_em.EastmoneyProvider().get_financial("600519")
    row = rows[0]
    assert row["code"] == "600519"
    assert row["report_date"] == "2026-09-30"
    assert row["eps"] == 50.1
    assert row["source"] == "eastmoney"


def test_eastmoney_realtime_normalizes_fields(monkeypatch):
    """⑥ 东财实时快照成功路径: f12/f14/f2/f3 → code/name/price/change_pct。"""
    monkeypatch.setattr(p_em.requests, "get", lambda *a, **k: FakeResponse({
        "data": {"total": 1, "diff": [
            {"f12": "600519", "f14": "贵州茅台", "f2": 1435.26, "f3": 1.77},
        ]},
    }))

    rows = p_em.EastmoneyProvider().get_realtime(symbols=["600519"])
    row = rows[0]
    assert row["code"] == "600519"
    assert row["name"] == "贵州茅台"
    assert row["price"] == 1435.26
    assert row["change_pct"] == 1.77


def test_eastmoney_adj_factor_computed_from_two_kline_modes(monkeypatch):
    """⑥ 东财复权因子: fqt=0 与 fqt=1 收盘价比值 = 因子。"""
    def fake_get(url, params=None, headers=None, timeout=None):
        fqt = (params or {}).get("fqt")
        close = "100.00" if fqt == "0" else "150.00"
        return FakeResponse({"data": {"klines": [f"2026-11-13,90,{close},160,80,1000"]}})

    monkeypatch.setattr(p_em.requests, "get", fake_get)

    rows = p_em.EastmoneyProvider().get_adj_factor(["600519"])
    assert rows[0]["code"] == "600519"
    assert rows[0]["adj_factor"] == pytest.approx(1.5)


# ======================================================================
# 契约一致性: 三个适配器都满足 MarketDataProvider 协议
# ======================================================================

@pytest.mark.parametrize("cls,name", [
    (p_tx.TencentProvider, "tencent"),
    (p_sina.SinaProvider, "sina"),
    (p_em.EastmoneyProvider, "eastmoney"),
])
def test_adapters_satisfy_protocol(cls, name):
    """三个内置适配器均满足 MarketDataProvider 结构协议。"""
    inst = cls()
    assert isinstance(inst, pbase.MarketDataProvider)
    assert inst.name == name
    assert isinstance(inst.capabilities, ProviderCapabilities)
    for method in ("get_instruments", "get_daily", "get_realtime"):
        assert callable(getattr(inst, method))


def test_capabilities_dataclass_is_frozen():
    """能力位不可变 (frozen), 防止下游随手改坏契约。"""
    caps = ProviderCapabilities(daily=True)
    with pytest.raises(Exception):
        caps.daily = False  # type: ignore[misc]

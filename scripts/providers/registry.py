"""
AAna 数据源 Provider 契约层 — 注册表与能力门禁

版本: v1.0 (2026-11-16)

职责:
  1. 注册 / 查询 / 列举 provider
  2. build_capability_matrix() — {capability: {"provider": 名称或 None, "usable": bool}}
  3. capability_gate(cap_id)   — (bool, 说明标签), 供调用方在写数据前先判能力
  4. probe_capabilities(name)  — 真实探测, 用探测结果更新能力位 + 记错误
  5. 内置三源自动注册 (tencent / sina / eastmoney)

关键语义:
  - 能力矩阵里的 usable **依据 provider.capabilities 的对应位**, 不靠 provider 自夸:
    探测失败会把对应能力位置 False（这是本层存在的意义）。
  - probe_capabilities 绝不向上抛异常: 探测失败只记错误, 不打断调用方。
  - 一个能力位有多个 provider 声明时, 按注册顺序取第一个 **usable** 的作为生效源;
    全都不行则 provider=None, usable=False。
"""

from __future__ import annotations

import dataclasses
from typing import Optional

from .base import (
    CAPABILITY_IDS,
    AssetType,
    MarketDataProvider,
    ProviderCapabilities,
    ProviderRequestError,
)
from .capabilities import PROBES

__all__ = [
    "register_provider",
    "get_provider",
    "list_providers",
    "unregister_provider",
    "clear_registry",
    "build_capability_matrix",
    "capability_gate",
    "probe_capabilities",
    "probe_all",
    "get_probe_errors",
]

# 注册表: name → provider (按注册顺序, 即优先级顺序)
_REGISTRY: dict[str, MarketDataProvider] = {}

# 探测错误表: name → {capability: 错误消息}
_PROBE_ERRORS: dict[str, dict[str, str]] = {}


# ----------------------------------------------------------------------
# 注册 / 查询
# ----------------------------------------------------------------------

def register_provider(provider: MarketDataProvider, overwrite: bool = True) -> MarketDataProvider:
    """注册一个 provider。

    Args:
        provider: 满足 MarketDataProvider 协议的对象
        overwrite: 同名时是否覆盖 (默认 True; 重复注册同一实例不报错)

    Returns:
        传入的 provider 本身 (便于链式调用)

    Raises:
        TypeError: 对象缺少 name / capabilities / 必需方法
    """
    name = getattr(provider, "name", None)
    if not isinstance(name, str) or not name:
        raise TypeError("provider 必须有非空的 str 类型 name 属性")

    caps = getattr(provider, "capabilities", None)
    if not isinstance(caps, ProviderCapabilities):
        raise TypeError(f"provider {name!r} 的 capabilities 必须是 ProviderCapabilities 实例")

    for method in ("get_instruments", "get_daily", "get_realtime"):
        if not callable(getattr(provider, method, None)):
            raise TypeError(f"provider {name!r} 缺少必需方法 {method}()")

    if name in _REGISTRY and not overwrite and _REGISTRY[name] is not provider:
        raise ValueError(f"provider {name!r} 已注册, overwrite=False 时不可重复注册")

    # 记录"声明基线": 探测会把 capabilities 改成实测值 (失败→False),
    # 若不保留基线, 一次瞬时断连就会把能力位永久锁死为 False, 之后再探测
    # 也不会重试该能力 (因为探测只探测已声明的位)。基线让能力位可恢复。
    if not hasattr(provider, "_declared_capabilities"):
        provider._declared_capabilities = caps  # type: ignore[attr-defined]

    _REGISTRY[name] = provider
    _PROBE_ERRORS.setdefault(name, {})
    return provider


def get_provider(name: str) -> MarketDataProvider:
    """按名称取 provider。

    Raises:
        KeyError: 该名称未注册
    """
    if name not in _REGISTRY:
        raise KeyError(f"provider {name!r} 未注册; 已注册: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def list_providers() -> list[str]:
    """返回所有已注册 provider 名称 (按注册顺序 = 优先级顺序)。"""
    return list(_REGISTRY.keys())


def unregister_provider(name: str) -> None:
    """注销 provider (不存在时静默跳过, 便于测试清理)。"""
    _REGISTRY.pop(name, None)
    _PROBE_ERRORS.pop(name, None)


def clear_registry() -> None:
    """清空注册表 (测试用)。"""
    _REGISTRY.clear()
    _PROBE_ERRORS.clear()


# ----------------------------------------------------------------------
# 能力矩阵 / 能力门禁
# ----------------------------------------------------------------------

def build_capability_matrix() -> dict[str, dict]:
    """构建能力矩阵。

    Returns:
        {capability: {"provider": 名称 或 None, "usable": bool}}
        usable 依据该能力对应 provider 的 capabilities 位; 没有 provider 声明
        该能力时 provider=None, usable=False。
    """
    matrix: dict[str, dict] = {}
    for cap_id in CAPABILITY_IDS:
        chosen: Optional[str] = None
        for name, provider in _REGISTRY.items():
            if provider.capabilities.get(cap_id):
                chosen = name
                break
        matrix[cap_id] = {"provider": chosen, "usable": chosen is not None}
    return matrix


def capability_gate(cap_id: str) -> tuple[bool, str]:
    """能力门禁: 判断某能力当前是否可用。

    Args:
        cap_id: 能力名 (instruments/daily/adj_factor/minute/realtime/depth5/financial)

    Returns:
        (bool, 说明标签)
          - 可用: (True,  "daily:可用(tencent)")
          - 不可用: (False, "daily:不可用(无数据源提供)") 或带探测错误
          - 未知能力: (False, "xxx:未知能力")
    """
    if cap_id not in CAPABILITY_IDS:
        return False, f"{cap_id}:未知能力(合法: {'/'.join(CAPABILITY_IDS)})"

    info = build_capability_matrix()[cap_id]
    if info["usable"]:
        return True, f"{cap_id}:可用({info['provider']})"

    # 不可用时附上探测错误原因, 便于日志定位
    for prov_name, cap_errors in _PROBE_ERRORS.items():
        if cap_id in cap_errors:
            return False, f"{cap_id}:不可用({prov_name}探测失败: {cap_errors[cap_id]})"
    return False, f"{cap_id}:不可用(无数据源提供)"


# ----------------------------------------------------------------------
# 真实探测
# ----------------------------------------------------------------------

def probe_capabilities(name: str) -> ProviderCapabilities:
    """对单个 provider 做真实探测, 并用结果更新其能力位。

    Args:
        name: provider 名称

    Returns:
        探测后的 ProviderCapabilities (同时写回 provider.capabilities)

    行为:
      - 只探测该 provider **声明的能力位** 对应的探测函数 (没声明的不探测,
        避免为一个不支持的能力白打网络请求)。
      - 探测成功: 该位保持/置 True
      - 探测失败: 该位置 False + 把错误写进 _PROBE_ERRORS[name][cap]
      - **绝不抛异常** —— 探测只是"测健康度", 不能打断调用方主流程
    """
    try:
        provider = get_provider(name)
    except KeyError:
        return ProviderCapabilities()  # 未注册: 全 False, 不抛异常

    # 用"声明基线"而不是当前值决定探测哪些位 —— 上次探测失败把某位置 False 后,
    # 若拿当前值判断, 该能力会永远不再重试 (一次瞬时断连 = 永久降级)。
    declared: ProviderCapabilities = getattr(
        provider, "_declared_capabilities", provider.capabilities
    )
    updates: dict[str, bool] = {}
    errors: dict[str, str] = {}

    for cap_id, probe_fn in PROBES.items():
        if not declared.get(cap_id):
            updates[cap_id] = False  # 未声明的能力位探测后仍为 False
            continue
        try:
            ok = bool(probe_fn(provider))
            updates[cap_id] = ok
            if not ok:
                errors[cap_id] = "探测返回非 True"
        except ProviderRequestError as e:
            updates[cap_id] = False
            errors[cap_id] = str(e) or e.__class__.__name__
        except Exception as e:  # 探测函数任何异常都不许冒泡
            updates[cap_id] = False
            errors[cap_id] = f"{e.__class__.__name__}: {e}"

    _PROBE_ERRORS[name] = errors

    # 未探测的能力位 (depth5/financial) 保留原声明
    new_caps = dataclasses.replace(provider.capabilities, **updates)
    provider.capabilities = new_caps
    return new_caps


def probe_all() -> dict[str, ProviderCapabilities]:
    """对所有已注册 provider 做真实探测。

    Returns:
        {provider名: 探测后的能力位}
    """
    return {name: probe_capabilities(name) for name in list_providers()}


def get_probe_errors() -> dict[str, dict[str, str]]:
    """返回探测错误表副本 {provider名: {capability: 错误消息}}。"""
    return {k: dict(v) for k, v in _PROBE_ERRORS.items()}


# ----------------------------------------------------------------------
# 内置三源自动注册
# ----------------------------------------------------------------------

def _register_builtins() -> None:
    """注册内置三源 (tencent / sina / eastmoney)。

    导入失败不致命: 某个适配器的依赖缺失时, 其余数据源照常可用,
    只是能力矩阵里该源缺席 (而不是整个包 import 失败)。
    """
    for module_name, class_name in (
        ("tencent", "TencentProvider"),
        ("sina", "SinaProvider"),
        ("eastmoney", "EastmoneyProvider"),
    ):
        try:
            module = __import__(f"{__package__}.{module_name}", fromlist=[class_name])
            provider = getattr(module, class_name)()
            register_provider(provider)
        except Exception as e:  # pragma: no cover - 仅在依赖缺失时触发
            print(f"[providers.registry] 内置数据源 {module_name} 注册失败: {e}")


_register_builtins()

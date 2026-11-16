"""
AAna 数据源 Provider 契约层 — 能力探测与能力报告

版本: v1.0 (2026-11-16)

职责:
  1. PROBES      — 每个 capability 对应的真实探测函数 (发一次最小请求, 1 个标的)
  2. capability_report() — 人类可读的能力表格 (能力 | 生效源 | 是否可用 | 错误原因)

设计原则:
  - 探测必须 **打真网络**: 能力位不能只靠"适配器自己声明支持",
    否则接口悄悄改版后能力位会永久骗人。
  - 探测失败必须 **可归因**: 把异常原文写进错误表, capability_report 会展示出来。
  - 探测函数本身不吞异常: 失败就 raise ProviderRequestError,
    由 registry.probe_capabilities 统一捕获并写状态 (调用方不会被抛出打断)。

⚠️ 循环导入说明:
  registry 需要 PROBES (模块级 import), 而 capability_report 需要 registry 的
  注册表与探测错误表。因此 capabilities 不在模块级 import registry,
  而是在 capability_report() 内部做局部 import。
"""

from __future__ import annotations

import unicodedata
from typing import Callable, cast

from .base import CAPABILITY_IDS, MarketDataProvider, ProviderRequestError

__all__ = ["PROBES", "PROBE_SYMBOL", "probe_daily", "probe_realtime",
           "probe_minute", "probe_adj_factor", "probe_instruments",
           "capability_report"]

# 探测统一用贵州茅台: 流动性最好, 不会停牌, 各数据源都覆盖
PROBE_SYMBOL = "600519"


# ----------------------------------------------------------------------
# 探测函数: 成功返回 True, 失败 raise ProviderRequestError
# ----------------------------------------------------------------------

def probe_daily(provider: MarketDataProvider) -> bool:
    """探测日线能力: 取 1 个标的近端日线, 空结果视为失败。"""
    rows = provider.get_daily([PROBE_SYMBOL], "", "", "stock")
    if not rows:
        raise ProviderRequestError("日线探测: 返回空列表")
    first = rows[0]
    if not first.get("code") or not first.get("date"):
        raise ProviderRequestError(f"日线探测: 字段缺失 {sorted(first)}")
    return True


def probe_realtime(provider: MarketDataProvider) -> bool:
    """探测实时快照能力: 取 1 个标的, 缺 code/name/price 视为失败。"""
    rows = provider.get_realtime(symbols=[PROBE_SYMBOL])
    if not rows:
        raise ProviderRequestError("实时探测: 返回空列表")
    first = rows[0]
    for key in ("code", "name", "price"):
        if key not in first:
            raise ProviderRequestError(f"实时探测: 缺字段 {key}")
    return True


def probe_minute(provider: MarketDataProvider) -> bool:
    """探测分钟线能力: 适配器没实现 get_minute 直接判不可用。"""
    fn = getattr(provider, "get_minute", None)
    if not callable(fn):
        raise ProviderRequestError("分钟线探测: 适配器未实现 get_minute")
    rows: list[dict] = cast(list, fn([PROBE_SYMBOL], count=5) or [])
    if not rows:
        raise ProviderRequestError("分钟线探测: 返回空列表")
    return True


def probe_adj_factor(provider: MarketDataProvider) -> bool:
    """探测复权因子能力: 适配器没实现 get_adj_factor 直接判不可用。"""
    fn = getattr(provider, "get_adj_factor", None)
    if not callable(fn):
        raise ProviderRequestError("复权因子探测: 适配器未实现 get_adj_factor")
    rows: list[dict] = cast(list, fn([PROBE_SYMBOL]) or [])
    if not rows:
        raise ProviderRequestError("复权因子探测: 返回空列表")
    if "adj_factor" not in rows[0]:
        raise ProviderRequestError("复权因子探测: 缺字段 adj_factor")
    return True


def probe_instruments(provider: MarketDataProvider) -> bool:
    """探测标的清单能力: 取极小一页, 空结果视为失败。"""
    rows = provider.get_instruments("stock")
    if not rows:
        raise ProviderRequestError("标的清单探测: 返回空列表")
    if not rows[0].get("code"):
        raise ProviderRequestError("标的清单探测: 缺字段 code")
    return True


# capability → 探测函数 (顺序与 CAPABILITY_IDS 一致)
PROBES: dict[str, Callable[[MarketDataProvider], bool]] = {
    "instruments": probe_instruments,
    "daily": probe_daily,
    "adj_factor": probe_adj_factor,
    "minute": probe_minute,
    "realtime": probe_realtime,
}


# ----------------------------------------------------------------------
# 人类可读能力报告
# ----------------------------------------------------------------------

def _width(text: str) -> int:
    """字符串的终端显示宽度 (中文占 2 列)。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    """按终端显示宽度左对齐补空格 (中文字符占 2 列, len() 会算错)。"""
    return text + " " * max(0, width - _width(text))


def capability_report(probe: bool = False) -> str:
    """生成人类可读的能力表格文本。

    Args:
        probe: True 时先对所有已注册 provider 做一次真实探测再出表
               (会打网络, 约 10~60 秒); False 时直接读当前能力位 (默认)。

    Returns:
        多行字符串, 每行格式: 能力 | 生效源 | 是否可用 | 错误原因

    列宽固定 (按终端显示宽度计算, 中文占 2 列), 便于日志 / 飞书推送按行 diff。
    """
    # 局部 import 打破 capabilities ↔ registry 循环依赖
    from .registry import build_capability_matrix, get_probe_errors, probe_all

    if probe:
        probe_all()

    matrix = build_capability_matrix()
    errors = get_probe_errors()

    col = (14, 12, 10)
    header = " | ".join([
        _pad("能力", col[0]),
        _pad("生效源", col[1]),
        _pad("是否可用", col[2]),
        "错误原因",
    ])
    lines = [header, "-" * _width(header)]

    for cap_id in CAPABILITY_IDS:
        info = matrix.get(cap_id) or {}
        source = info.get("provider") or "-"
        usable = info.get("usable", False)
        err = "-"
        if not usable:
            # 优先展示该能力相关 provider 的探测错误
            for prov_name, cap_errors in errors.items():
                if cap_id in cap_errors:
                    err = f"{prov_name}: {cap_errors[cap_id]}"
                    break
            else:
                err = "无数据源提供该能力"
        lines.append(" | ".join([
            _pad(cap_id, col[0]),
            _pad(source, col[1]),
            _pad("可用" if usable else "不可用", col[2]),
            err,
        ]))
    return "\n".join(lines)

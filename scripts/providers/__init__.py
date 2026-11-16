"""
AAna 数据源 Provider 契约层 — 模块入口

版本: v1.0 (2026-11-16)

对外导出:
  base        — ProviderRequestError / ProviderCapabilities / AssetType / MarketDataProvider
  capabilities— 能力探测函数映射 + capability_report()
  registry    — 注册表 + 能力矩阵 + capability_gate() + probe_capabilities()
  tencent     — 腾讯财经适配器
  sina        — 新浪财经适配器
  eastmoney   — 东财数据中心适配器

用法:
  import sys; sys.path.insert(0, "scripts")
  from providers.registry import list_providers, build_capability_matrix
  from providers.capabilities import capability_report
  print(list_providers())
  print(capability_report())

⚠️ 本包只新增文件, 不修改 scripts/data_sources.py 及任何既有脚本。
"""

from .base import (  # noqa: F401
    CAPABILITY_IDS,
    AssetType,
    MarketDataProvider,
    ProviderCapabilities,
    ProviderRequestError,
)

__all__ = [
    "CAPABILITY_IDS",
    "AssetType",
    "MarketDataProvider",
    "ProviderCapabilities",
    "ProviderRequestError",
]

__version__ = "1.0"

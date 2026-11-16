"""
AAna 数据源 Provider 契约层 — 基础契约定义

版本: v1.0 (2026-11-16)

背景:
  AAna 历史上直接把 requests / data_sources.py 散落在各脚本里, 任何一个数据源
  挂掉都会静默降级成"空数据", 调用方无法区分"今天没数据"和"接口挂了"。
  本模块定义统一的 Provider 契约:

  1. ProviderRequestError  — 数据源明确失败必须抛出, 调用方须标记失败,
     禁止把失败转换成"成功的空数据"(这是本层最重要的语义)。
  2. ProviderCapabilities  — 每个数据源声明自己真实支持的能力位。
  3. MarketDataProvider    — 结构化 Protocol, 约束所有适配器的方法签名。

约定:
  - 返回值一律是普通 list[dict] (纯 Python), 不引入 polars / pandas 依赖。
  - 只用标准库 + 项目已有依赖 (requests)。
  - 本层不修改 scripts/data_sources.py 本体, 只做薄适配。
"""

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

__all__ = [
    "ProviderRequestError",
    "ProviderCapabilities",
    "AssetType",
    "MarketDataProvider",
    "CAPABILITY_IDS",
]


class ProviderRequestError(RuntimeError):
    """数据源明确请求失败; 调用方须标记失败, 不得转换成成功的空数据。

    触发场景:
      - 底层 HTTP 请求抛异常 (连接被重置 / 超时 / DNS 失败)
      - 响应结构不符合预期 (JSON 解析失败 / 字段缺失)
      - 请求成功但返回体被判定为无效 (空字典 / 空列表冒充成功)

    捕获方 **不得** 用 except ProviderRequestError: pass 的方式吞掉本异常,
    正确做法是向上冒泡或显式记录失败原因, 让上层能区分"失败"与"空数据"。
    """


@dataclass(frozen=True)
class ProviderCapabilities:
    """数据源能力位声明 (不可变)。

    每个字段都是布尔位, 表示该数据源 **真实支持** 的能力:
      instruments — 能提供标的清单 (股票 / 指数 / ETF 列表)
      daily      — 能提供日线 K 线
      adj_factor — 能提供复权因子
      minute     — 能提供分钟线
      realtime   — 能提供实时快照 (最新价 / 涨跌幅)
      depth5     — 能提供五档盘口
      financial  — 能提供财务指标
    """

    instruments: bool = False
    daily: bool = False
    adj_factor: bool = False
    minute: bool = False
    realtime: bool = False
    depth5: bool = False
    financial: bool = False

    def get(self, cap_id: str) -> bool:
        """按能力名读取能力位, 未知能力返回 False。"""
        return bool(getattr(self, cap_id, False))


# 资产类型字面量: 个股 / 指数 / ETF
AssetType = Literal["stock", "index", "etf"]

# 全部能力位名称 (顺序即报告展示顺序)
CAPABILITY_IDS = (
    "instruments",
    "daily",
    "adj_factor",
    "minute",
    "realtime",
    "depth5",
    "financial",
)


@runtime_checkable
class MarketDataProvider(Protocol):
    """市场数据源 Provider 协议。

    所有适配器 (tencent / sina / eastmoney) 必须满足:

      - name: 短名称, 全局唯一, 用于注册与查询
      - capabilities: 能力位声明 (可被探测结果更新)
      - get_instruments(asset_type) -> list[dict]
      - get_daily(symbols, start_time, end_time, asset_type) -> list[dict]
      - get_realtime(universes=None, symbols=None) -> list[dict]

    返回值统一为 list[dict] (普通 Python 容器), 禁止返回 polars / pandas 对象。
    """

    name: str
    capabilities: ProviderCapabilities

    def get_instruments(self, asset_type: AssetType) -> list[dict]:
        """返回标的清单列表, 每条至少含 code / name。"""
        ...

    def get_daily(
        self,
        symbols: list[str],
        start_time: str,
        end_time: str,
        asset_type: AssetType,
    ) -> list[dict]:
        """返回日线 K 线列表, 每条至少含 code / date / open / high / low / close / volume。"""
        ...

    def get_realtime(
        self,
        universes: list | dict | None = None,
        symbols: list[str] | None = None,
    ) -> list[dict]:
        """返回实时快照列表, 每条至少含 code / name / price。"""
        ...

"""
AAna 数据源 Provider 契约层 — 腾讯财经适配器

版本: v1.0 (2026-11-16)

职责:
  把既有 scripts/data_sources.py 的腾讯接口薄适配成 MarketDataProvider 契约。
  不修改 data_sources.py 本体, 只复用其函数。

数据源实况 (2026-11-16 本机实测):
  - 实时快照 : qt.gtimg.cn  → data_sources.tencent_quote()  **GBK 字节流**
  - 日线 K 线: web.ifzq.gtimg.cn/appstock/app/fqkline/get    (qfq 前复权)
  - 分钟 K 线: ifzq.gtimg.cn/appstock/app/kline/mkline       (m5)

能力位 (按实测真实支持声明):
  realtime  ✅  tencent_quote
  daily     ✅  fqkline day
  minute    ✅  mkline m5
  instruments / adj_factor / depth5 / financial ❌ (腾讯对外开放接口不含这些语义)

⚠️ GBK 坑 (来自 data_sources.py 的经验):
  腾讯行情接口返回的是 **GBK 编码的字节流**, 不是 UTF-8。直接 resp.text 会得到乱码,
  名称字段全部损坏。任何自己做 requests 的地方都必须:
      resp.content.decode("gbk", errors="replace")
  errors="replace" 不能省 —— 个别标的名称里含 GBK 生僻字/脏字节, 严格解码会抛
  UnicodeDecodeError, 把一条坏记录放大成整批失败。
"""

from __future__ import annotations

import requests

from .base import AssetType, ProviderCapabilities, ProviderRequestError

try:  # 常规路径: scripts/ 在 sys.path 上 (验收命令 / 直接跑脚本)
    import data_sources as _ds
except ImportError:  # pytest 路径: 项目根在 sys.path 上
    from scripts import data_sources as _ds

__all__ = ["TencentProvider"]

# 腾讯域名 (与 data_sources.py 保持一致, 这里只新增 K 线端点)
TENCENT_QUOTE_URL = _ds.TENCENT_QUOTE_URL
TENCENT_FQKLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"  # 日线(前复权)
TENCENT_MKLINE_URL = "https://ifzq.gtimg.cn/appstock/app/kline/mkline"      # 分钟线
UA = _ds.UA

# 探测用最小标的 (贵州茅台, 流动性最好, 基本不会停牌)
PROBE_SYMBOL = "600519"


def _decode_gbk(payload: bytes) -> str:
    """腾讯 GBK 字节流 → str。

    errors="replace" 是硬要求: 脏字节不能把整批行情带崩。
    """
    return payload.decode("gbk", errors="replace")


def _prefixed(code: str) -> str:
    """6 位代码 → 腾讯带市场前缀代码 (sh/sz/bj), 复用 data_sources 的前缀规则。"""
    bare = _ds.normalize_code(code)
    return f"{_ds.get_prefix(bare)}{bare}"


class TencentProvider:
    """腾讯财经 Provider 适配器 (realtime / daily / minute)。"""

    name = "tencent"
    capabilities = ProviderCapabilities(daily=True, realtime=True, minute=True)

    # ------------------------------------------------------------------
    # 实时快照
    # ------------------------------------------------------------------
    def get_realtime(
        self,
        universes: list | dict | None = None,
        symbols: list[str] | None = None,
    ) -> list[dict]:
        """腾讯实时快照 → 规范化 list[dict] (code/name/price/change_pct/...)。

        ⚠️ 复用 data_sources.tencent_quote 的已知缺陷: 它内部 except 掉所有异常并
        返回空字典, 调用方无法区分"接口挂了"和"没有数据"。本方法对此做两件事:
          1. 空结果一律 raise ProviderRequestError（禁止把失败当成功）
          2. 用一次原始 GBK 请求区分"网络失败"与"代码不存在", 让错误可归因
        """
        codes = self._collect_codes(universes, symbols)
        if not codes:
            raise ProviderRequestError("腾讯行情: 未提供任何标的代码")

        try:
            raw = _ds.tencent_quote(list(codes))
        except Exception as e:  # 底层异常一律转成契约异常
            raise ProviderRequestError(f"腾讯行情请求失败: {e}") from e

        if not raw:
            # 上一层把真实异常吞了, 这里重放一次原始请求拿到可归因的错误
            raw = self._raw_quote(codes)

        if not raw:
            raise ProviderRequestError("腾讯行情返回空结果, 疑似接口异常或被限流")

        return [self._normalize_row(code, item) for code, item in raw.items()
                if self._is_bare_code(code)]

    def _raw_quote(self, codes: list[str]) -> dict:
        """原始 GBK 请求兜底 (仅在 tencent_quote 返回空时使用, 让错误可归因)。"""
        url = TENCENT_QUOTE_URL + ",".join(_prefixed(c) for c in codes)
        try:
            resp = requests.get(url, headers={"User-Agent": UA}, timeout=10)
            text = _decode_gbk(resp.content)  # ← GBK 解码, errors="replace"
        except Exception as e:
            raise ProviderRequestError(f"腾讯行情原始请求失败: {e}") from e

        out: dict[str, dict] = {}
        for line in text.strip().split(";"):
            if "=" not in line or '"' not in line:
                continue
            key = line.split("=")[0].split("_")[-1]
            vals = line.split('"')[1].split("~")
            if len(vals) < 33:
                continue
            out[key[2:]] = {
                "name": vals[1],
                "price": _ds.safe_float(vals[3]) or 0,
                "last_close": _ds.safe_float(vals[4]) or 0,
                "change_pct": _ds.safe_float(vals[32]),
            }
        return out

    @staticmethod
    def _is_bare_code(key: str) -> bool:
        """tencent_quote 同时用 6 位码和带前缀码做 key, 这里只保留 6 位码避免重复。"""
        return len(key) == 6 and key.isdigit()

    @staticmethod
    def _normalize_row(code: str, item: dict) -> dict:
        """腾讯原始字段 → 契约规范化字段 (code/name/price ...)。"""
        return {
            "code": code,
            "name": item.get("name", ""),
            "price": item.get("price") or 0,
            "change_pct": item.get("change_pct"),
            "last_close": item.get("last_close"),
            "open": item.get("open"),
            "high": item.get("high"),
            "low": item.get("low"),
            "amount": (item.get("amount_wan") or 0) * 10000 if item.get("amount_wan") else None,
            "turnover_pct": item.get("turnover_pct"),
            "pe_ttm": item.get("pe_ttm"),
            "pb": item.get("pb"),
            "mcap_yi": item.get("mcap_yi"),
            "limit_up": item.get("limit_up"),
            "limit_down": item.get("limit_down"),
            "source": "tencent",
        }

    # ------------------------------------------------------------------
    # 日线
    # ------------------------------------------------------------------
    def get_daily(
        self,
        symbols: list[str],
        start_time: str,
        end_time: str,
        asset_type: AssetType = "stock",
    ) -> list[dict]:
        """腾讯 fqkline 日线 (前复权) → list[dict]。

        start_time / end_time 形如 "2026-01-01"; 传空串表示不限制。
        底层失败或返回空 → ProviderRequestError。
        """
        if not symbols:
            raise ProviderRequestError("腾讯日线: 未提供任何标的代码")

        rows: list[dict] = []
        for sym in symbols:
            code = _ds.normalize_code(sym)
            pref = _prefixed(code)
            param = f"{pref},day,{start_time or ''},{end_time or ''},320,qfq"
            try:
                resp = requests.get(
                    TENCENT_FQKLINE_URL,
                    params={"param": param},
                    headers={"User-Agent": UA, "Referer": "https://gu.qq.com/"},
                    timeout=10,
                )
                payload = resp.json()
            except Exception as e:
                raise ProviderRequestError(f"腾讯日线请求失败({code}): {e}") from e

            node = ((payload.get("data") or {}).get(pref) or {})
            bars = node.get("qfqday") or node.get("day") or []
            # 腾讯 bar 顺序: [date, open, close, high, low, volume] —— 不是 OHLC!
            for bar in bars:
                if len(bar) < 6:
                    continue
                date = str(bar[0])
                if start_time and date < start_time:
                    continue
                if end_time and date > end_time:
                    continue
                rows.append({
                    "code": code,
                    "date": date,
                    "open": _ds.safe_float(bar[1]),
                    "close": _ds.safe_float(bar[2]),
                    "high": _ds.safe_float(bar[3]),
                    "low": _ds.safe_float(bar[4]),
                    "volume": _ds.safe_float(bar[5]),
                    "source": "tencent",
                })

        if not rows:
            raise ProviderRequestError(
                f"腾讯日线返回空结果: symbols={symbols} {start_time}~{end_time}"
            )
        return rows

    # ------------------------------------------------------------------
    # 分钟线
    # ------------------------------------------------------------------
    def get_minute(self, symbols: list[str], count: int = 48) -> list[dict]:
        """腾讯 mkline 5 分钟线 → list[dict] (code/time/open/close/high/low/volume)。"""
        if not symbols:
            raise ProviderRequestError("腾讯分钟线: 未提供任何标的代码")

        rows: list[dict] = []
        for sym in symbols:
            code = _ds.normalize_code(sym)
            pref = _prefixed(code)
            try:
                resp = requests.get(
                    TENCENT_MKLINE_URL,
                    params={"param": f"{pref},m5,,{int(count)}"},
                    headers={"User-Agent": UA, "Referer": "https://gu.qq.com/"},
                    timeout=10,
                )
                payload = resp.json()
            except Exception as e:
                raise ProviderRequestError(f"腾讯分钟线请求失败({code}): {e}") from e

            node = ((payload.get("data") or {}).get(pref) or {})
            bars = node.get("m5") or []
            # 腾讯 m5 bar: [yyyymmddHHMM, open, close, high, low, volume, {}, pct]
            for bar in bars:
                if len(bar) < 6:
                    continue
                rows.append({
                    "code": code,
                    "time": str(bar[0]),
                    "open": _ds.safe_float(bar[1]),
                    "close": _ds.safe_float(bar[2]),
                    "high": _ds.safe_float(bar[3]),
                    "low": _ds.safe_float(bar[4]),
                    "volume": _ds.safe_float(bar[5]),
                    "source": "tencent",
                })

        if not rows:
            raise ProviderRequestError(f"腾讯分钟线返回空结果: symbols={symbols}")
        return rows

    # ------------------------------------------------------------------
    # 不支持的能力
    # ------------------------------------------------------------------
    def get_instruments(self, asset_type: AssetType = "stock") -> list[dict]:
        """腾讯不提供标的清单接口 → 明确失败 (不返回空列表冒充成功)。"""
        raise ProviderRequestError(
            f"腾讯行情不提供标的清单接口 (asset_type={asset_type}), 请改用 eastmoney"
        )

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _collect_codes(universes: list | dict | None, symbols: list[str] | None) -> list[str]:
        """合并 symbols 与 universes 里的代码, 去重保序。"""
        codes: list[str] = []
        if isinstance(universes, dict):
            for v in universes.values():
                codes.extend(str(x) for x in (v or []))
        elif isinstance(universes, (list, tuple, set)):
            for item in universes:
                if isinstance(item, (list, tuple, set)):
                    codes.extend(str(x) for x in item)
                else:
                    codes.append(str(item))
        if symbols:
            codes.extend(str(x) for x in symbols)

        seen, out = set(), []
        for c in codes:
            bare = _ds.normalize_code(c)
            if bare and bare not in seen:
                seen.add(bare)
                out.append(bare)
        return out

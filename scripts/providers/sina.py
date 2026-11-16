"""
AAna 数据源 Provider 契约层 — 新浪财经适配器

版本: v1.0 (2026-11-16)

职责:
  把既有 scripts/data_sources.py 的 sina_quote() 薄适配成 MarketDataProvider 契约,
  并补上新浪 K 线端点 (日线 / 分钟线) 供 daily/minute 能力使用。

数据源实况 (2026-11-16 本机实测):
  - 实时快照 : hq.sinajs.cn                        → data_sources.sina_quote()  **GBK**
  - 日线 K 线: money.finance.sina.com.cn/quotes_service/api/json_v2.php/
               CN_MarketData.getKLineData?scale=240
  - 分钟 K 线: 同上, scale=5  (5 分钟线)

能力位 (按实测真实支持声明):
  realtime ✅  sina_quote
  daily    ✅  getKLineData scale=240
  minute   ✅  getKLineData scale=5
  instruments / adj_factor / depth5 / financial ❌

⚠️ 两个已知坑:
  1. 新浪行情返回 GBK 字节流, 解码必须 .decode("gbk", errors="replace")。
  2. data_sources.sina_quote() 在底层异常时会 **返回占位记录** (name='', price=0),
     这是"用空数据冒充成功"的典型形态。本适配器把它识别为失败并抛
     ProviderRequestError —— 调用方必须能区分"真的 0 元"和"接口挂了"。
"""

from __future__ import annotations

import requests

from .base import AssetType, ProviderCapabilities, ProviderRequestError

try:  # 常规路径: scripts/ 在 sys.path 上
    import data_sources as _ds
except ImportError:  # pytest 路径: 项目根在 sys.path 上
    from scripts import data_sources as _ds

__all__ = ["SinaProvider"]

SINA_HQ_URL = _ds.SINA_HQ_URL
SINA_KLINE_URL = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                  "CN_MarketData.getKLineData")
PROBE_SYMBOL = "600519"

_SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://finance.sina.com.cn",
}


def _decode_gbk(payload: bytes) -> str:
    """新浪行情 GBK 字节流 → str (errors="replace" 必须保留)。"""
    return payload.decode("gbk", errors="replace")


class SinaProvider:
    """新浪财经 Provider 适配器 (realtime / daily / minute)。"""

    name = "sina"
    capabilities = ProviderCapabilities(daily=True, realtime=True, minute=True)

    # ------------------------------------------------------------------
    # 实时快照
    # ------------------------------------------------------------------
    def get_realtime(
        self,
        universes: list | dict | None = None,
        symbols: list[str] | None = None,
    ) -> list[dict]:
        """新浪实时快照 → 规范化 list[dict] (code/name/price/change_pct/...)。

        ⚠️ data_sources.sina_quote() 失败时返回 price=0 / name='' 的占位行。
        本方法把"全部行都是占位"判定为请求失败并 raise ProviderRequestError。
        """
        codes = self._collect_codes(universes, symbols)
        if not codes:
            raise ProviderRequestError("新浪行情: 未提供任何标的代码")

        try:
            raw = _ds.sina_quote(list(codes))
        except Exception as e:
            raise ProviderRequestError(f"新浪行情请求失败: {e}") from e
        if not raw:
            raise ProviderRequestError("新浪行情返回空结果, 疑似接口异常")

        rows = [self._normalize_row(code, item) for code, item in raw.items()]
        if self._all_placeholder(rows):
            raise ProviderRequestError(
                "新浪行情返回全部占位行(name为空/price=0), 判定为接口失败而非空数据"
            )
        return rows

    @staticmethod
    def _all_placeholder(rows: list[dict]) -> bool:
        """判断是否整批都是 sina_quote 的失败占位行。"""
        if not rows:
            return True
        for r in rows:
            if r.get("name") or (r.get("price") or 0) > 0:
                return False
        return True

    @staticmethod
    def _normalize_row(code: str, item: dict) -> dict:
        """新浪原始字段 → 契约规范化字段 (code/name/price ...)。"""
        return {
            "code": item.get("code") or code,
            "name": item.get("name", ""),
            "price": item.get("price") or 0,
            "change_pct": item.get("change_pct"),
            "change_amt": item.get("change_amt"),
            "last_close": item.get("yesterday_close"),
            "open": item.get("open"),
            "high": item.get("high"),
            "low": item.get("low"),
            "amount": item.get("amount"),
            "source": "sina",
        }

    # ------------------------------------------------------------------
    # 日线 / 分钟线
    # ------------------------------------------------------------------
    def get_daily(
        self,
        symbols: list[str],
        start_time: str,
        end_time: str,
        asset_type: AssetType = "stock",
    ) -> list[dict]:
        """新浪日线 (scale=240) → list[dict] (code/date/OHLC/volume)。"""
        if not symbols:
            raise ProviderRequestError("新浪日线: 未提供任何标的代码")

        rows: list[dict] = []
        for sym in symbols:
            code = _ds.normalize_code(sym)
            bars = self._kline(code, scale="240", datalen=1023)
            for bar in bars:
                date = str(bar.get("day", ""))[:10]
                if start_time and date < start_time:
                    continue
                if end_time and date > end_time:
                    continue
                rows.append({
                    "code": code,
                    "date": date,
                    "open": _ds.safe_float(bar.get("open")),
                    "high": _ds.safe_float(bar.get("high")),
                    "low": _ds.safe_float(bar.get("low")),
                    "close": _ds.safe_float(bar.get("close")),
                    "volume": _ds.safe_float(bar.get("volume")),
                    "source": "sina",
                })

        if not rows:
            raise ProviderRequestError(
                f"新浪日线返回空结果: symbols={symbols} {start_time}~{end_time}"
            )
        return rows

    def get_minute(self, symbols: list[str], count: int = 48) -> list[dict]:
        """新浪 5 分钟线 (scale=5) → list[dict] (code/time/OHLC/volume)。"""
        if not symbols:
            raise ProviderRequestError("新浪分钟线: 未提供任何标的代码")

        rows: list[dict] = []
        for sym in symbols:
            code = _ds.normalize_code(sym)
            bars = self._kline(code, scale="5", datalen=max(5, int(count)))
            for bar in bars:
                rows.append({
                    "code": code,
                    "time": str(bar.get("day", "")),
                    "open": _ds.safe_float(bar.get("open")),
                    "high": _ds.safe_float(bar.get("high")),
                    "low": _ds.safe_float(bar.get("low")),
                    "close": _ds.safe_float(bar.get("close")),
                    "volume": _ds.safe_float(bar.get("volume")),
                    "source": "sina",
                })

        if not rows:
            raise ProviderRequestError(f"新浪分钟线返回空结果: symbols={symbols}")
        return rows

    def _kline(self, code: str, scale: str, datalen: int) -> list[dict]:
        """调用新浪 getKLineData, 失败/空 → ProviderRequestError。"""
        pref = f"{_ds.get_prefix(code)}{code}"
        try:
            resp = requests.get(
                SINA_KLINE_URL,
                params={"symbol": pref, "scale": scale, "ma": "no", "datalen": str(datalen)},
                headers=_SINA_HEADERS,
                timeout=10,
            )
            bars = resp.json()
        except Exception as e:
            raise ProviderRequestError(f"新浪K线请求失败({code}, scale={scale}): {e}") from e
        if not isinstance(bars, list) or not bars:
            raise ProviderRequestError(
                f"新浪K线返回空结果({code}, scale={scale}), 疑似接口异常"
            )
        return [b for b in bars if isinstance(b, dict)]

    # ------------------------------------------------------------------
    # 不支持的能力
    # ------------------------------------------------------------------
    def get_instruments(self, asset_type: AssetType = "stock") -> list[dict]:
        """新浪不提供标的清单接口 → 明确失败。"""
        raise ProviderRequestError(
            f"新浪行情不提供标的清单接口 (asset_type={asset_type}), 请改用 eastmoney"
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

"""
AAna 数据源 Provider 契约层 — 东方财富适配器

版本: v1.0 (2026-11-16)

职责:
  把既有 scripts/data_sources.py 的 eastmoney_datacenter() 薄适配成
  MarketDataProvider 契约, 并复用其端点常量补齐日线 / 复权因子 / 实时快照。

数据源实况 (2026-11-16 本机实测):
  - 标的清单 : datacenter-web.eastmoney.com  reportName=RPT_HSF9_BASIC_ORGINFO  ✅
  - 财务指标 : datacenter-web.eastmoney.com  reportName=RPT_LICO_FN_CPD          ✅
  - 实时快照 : push2.eastmoney.com/api/qt/ulist.np/get                          🟡 间歇断连
  - 日线 K 线: push2his.eastmoney.com/api/qt/stock/kline/get (klt=101, fqt=1)   🟡 间歇断连
  - 复权因子 : 由同一 K 线端点的 fqt=0(不复权) 与 fqt=1(前复权) 收盘价求比值得出

能力位 (按实测真实支持声明):
  instruments ✅  RPT_HSF9_BASIC_ORGINFO
  daily       ✅  push2his kline klt=101
  adj_factor  ✅  fqt=0 / fqt=1 比值
  financial   ✅  RPT_LICO_FN_CPD
  realtime    ✅  push2 ulist.np
  minute / depth5 ❌ (本适配器不实现)

⚠️ 关键坑 (与 data_sources.py 一致):
  - eastmoney_datacenter() 内部 except 掉所有异常并返回 [], 无法区分"接口挂了"
    和"确实没数据"。本适配器把空结果统一判定为 ProviderRequestError, 并在错误
    消息里带上 reportName + filter, 让调用方能归因。
  - push2 / push2his 与 datacenter 是不同域名, 断连节奏不同: datacenter 常年可用,
    push2his 会连续 RemoteDisconnected。不要把两者的健康度混为一谈。
"""

from __future__ import annotations

import requests

from .base import AssetType, ProviderCapabilities, ProviderRequestError

try:  # 常规路径: scripts/ 在 sys.path 上
    import data_sources as _ds
except ImportError:  # pytest 路径: 项目根在 sys.path 上
    from scripts import data_sources as _ds

__all__ = ["EastmoneyProvider"]

# 复用 data_sources.py 的端点常量 (不修改其本体)
EM_DATACENTER = _ds.EM_DATACENTER
EM_PUSH2 = _ds.EM_PUSH2
EM_PUSH2HIS = _ds.EM_PUSH2HIS
EM_ULIST = "https://push2.eastmoney.com/api/qt/ulist.np/get"  # 批量快照
UA = _ds.UA

PROBE_SYMBOL = "600519"

# 标的清单报告 (datacenter)
REPORT_INSTRUMENTS = "RPT_HSF9_BASIC_ORGINFO"
# 财务指标报告 (datacenter)
REPORT_FINANCIAL = "RPT_LICO_FN_CPD"


def _secid(code: str) -> str:
    """6 位代码 → 东财 secid (1.=沪 / 0.=深京)。"""
    bare = _ds.normalize_code(code)
    market = 1 if bare.startswith(("6", "9", "5")) else 0
    return f"{market}.{bare}"


class EastmoneyProvider:
    """东方财富 Provider 适配器 (instruments / daily / adj_factor / financial / realtime)。"""

    name = "eastmoney"
    capabilities = ProviderCapabilities(
        instruments=True,
        daily=True,
        adj_factor=True,
        realtime=True,
        financial=True,
    )

    # ------------------------------------------------------------------
    # datacenter 通用查询
    # ------------------------------------------------------------------
    def _datacenter(self, report_name: str, filter_str: str = "", page_size: int = 50,
                    sort_columns: str = "", sort_types: str = "-1") -> list[dict]:
        """复用 data_sources.eastmoney_datacenter, 空结果 → ProviderRequestError。

        ⚠️ 兼容两种返回形态: 契约要求 dict, 实际 data_sources 返回 list。
           两种都接住, 统一成 list[dict]。
        """
        try:
            data = _ds.eastmoney_datacenter(
                report_name,
                columns="ALL",
                filter_str=filter_str,
                page_size=page_size,
                sort_columns=sort_columns,
                sort_types=sort_types,
            )
        except Exception as e:
            raise ProviderRequestError(
                f"东财 datacenter 请求失败(report={report_name}): {e}"
            ) from e

        if isinstance(data, dict):
            # 兼容 {"result": {"data": [...]}} / {"data": [...]} 形态
            node = data.get("result") if isinstance(data.get("result"), dict) else data
            rows = (node or {}).get("data") or []
        else:
            rows = data or []

        if not rows:
            raise ProviderRequestError(
                f"东财 datacenter 返回空结果 (report={report_name}, filter={filter_str!r})"
            )
        return list(rows)

    # ------------------------------------------------------------------
    # 标的清单
    # ------------------------------------------------------------------
    def get_instruments(self, asset_type: AssetType = "stock", limit: int = 500) -> list[dict]:
        """东财标的清单 (仅 stock) → list[dict] (code/name/market)。"""
        if asset_type != "stock":
            raise ProviderRequestError(
                f"东财标的清单仅支持 asset_type='stock' (收到 {asset_type!r})"
            )
        rows = self._datacenter(
            REPORT_INSTRUMENTS,
            filter_str='(LISTING_STATE="0")',
            page_size=limit,
            sort_columns="SECURITY_CODE",
            sort_types="1",
        )
        out = []
        for r in rows:
            code = str(r.get("SECURITY_CODE") or "").strip()
            if not code:
                continue
            out.append({
                "code": code,
                "name": r.get("SECURITY_NAME_ABBR") or r.get("ORG_NAME_ABBR") or "",
                "market": str(r.get("SECUCODE") or "")[-2:],
                "asset_type": "stock",
                "source": "eastmoney",
            })
        if not out:
            raise ProviderRequestError("东财标的清单解析后为空")
        return out

    # ------------------------------------------------------------------
    # 日线 / 复权因子
    # ------------------------------------------------------------------
    def get_daily(
        self,
        symbols: list[str],
        start_time: str,
        end_time: str,
        asset_type: AssetType = "stock",
    ) -> list[dict]:
        """东财日线 (klt=101, fqt=1 前复权) → list[dict] (code/date/OHLC/volume)。"""
        if not symbols:
            raise ProviderRequestError("东财日线: 未提供任何标的代码")

        rows: list[dict] = []
        for sym in symbols:
            code = _ds.normalize_code(sym)
            for parts in self._kline(code, fqt=1):
                date = parts[0]
                if start_time and date < start_time:
                    continue
                if end_time and date > end_time:
                    continue
                # 东财 kline 字段序: date,open,close,high,low,volume,amount,...
                rows.append({
                    "code": code,
                    "date": date,
                    "open": _ds.safe_float(parts[1]),
                    "close": _ds.safe_float(parts[2]),
                    "high": _ds.safe_float(parts[3]),
                    "low": _ds.safe_float(parts[4]),
                    "volume": _ds.safe_float(parts[5]),
                    "source": "eastmoney",
                })

        if not rows:
            raise ProviderRequestError(
                f"东财日线返回空结果: symbols={symbols} {start_time}~{end_time}"
            )
        return rows

    def get_adj_factor(
        self,
        symbols: list[str],
        start_time: str = "",
        end_time: str = "",
    ) -> list[dict]:
        """东财复权因子 → list[dict] (code/date/adj_factor)。

        算法: 同一标的取 fqt=0 (不复权) 与 fqt=1 (前复权) 两条 K 线,
        按日期对齐后 factor = qfq_close / raw_close。
        （前复权因子以最新价为基准, 因此等于两条序列的收盘价比。）
        """
        if not symbols:
            raise ProviderRequestError("东财复权因子: 未提供任何标的代码")

        rows: list[dict] = []
        for sym in symbols:
            code = _ds.normalize_code(sym)
            raw = {p[0]: _ds.safe_float(p[2]) for p in self._kline(code, fqt=0)}
            qfq = {p[0]: _ds.safe_float(p[2]) for p in self._kline(code, fqt=1)}
            for date in sorted(set(raw) & set(qfq)):
                if start_time and date < start_time:
                    continue
                if end_time and date > end_time:
                    continue
                base, adj = raw[date], qfq[date]
                if not base or adj is None:
                    continue
                rows.append({
                    "code": code,
                    "date": date,
                    "adj_factor": round(adj / base, 8),
                    "source": "eastmoney",
                })

        if not rows:
            raise ProviderRequestError(f"东财复权因子返回空结果: symbols={symbols}")
        return rows

    def _kline(self, code: str, fqt: int, lmt: int = 320) -> list[list[str]]:
        """push2his 日线原始行 (逗号切分后的 list), 失败/空 → ProviderRequestError。"""
        params = {
            "secid": _secid(code),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "fqt": str(fqt),
            "end": "20500101",
            "lmt": str(int(lmt)),
        }
        try:
            resp = requests.get(
                EM_PUSH2HIS,
                params=params,
                headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"},
                timeout=10,
            )
            payload = resp.json()
        except Exception as e:
            raise ProviderRequestError(f"东财K线请求失败({code}, fqt={fqt}): {e}") from e

        klines = ((payload.get("data") or {}) if isinstance(payload, dict) else {}).get("klines") or []
        parts = [str(line).split(",") for line in klines]
        parts = [p for p in parts if len(p) >= 6]
        if not parts:
            raise ProviderRequestError(
                f"东财K线返回空结果({code}, fqt={fqt}), 疑似 push2his 断连"
            )
        return parts

    # ------------------------------------------------------------------
    # 实时快照
    # ------------------------------------------------------------------
    def get_realtime(
        self,
        universes: list | dict | None = None,
        symbols: list[str] | None = None,
    ) -> list[dict]:
        """东财批量实时快照 (ulist.np) → list[dict] (code/name/price/change_pct)。"""
        codes = self._collect_codes(universes, symbols)
        if not codes:
            raise ProviderRequestError("东财快照: 未提供任何标的代码")

        params = {
            "secids": ",".join(_secid(c) for c in codes),
            "fields": "f12,f14,f2,f3,f4,f5,f6",
            "fltt": "2",
            "invt": "2",
        }
        try:
            resp = requests.get(
                EM_ULIST,
                params=params,
                headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"},
                timeout=10,
            )
            payload = resp.json()
        except Exception as e:
            raise ProviderRequestError(f"东财快照请求失败: {e}") from e

        diff = ((payload.get("data") or {}) if isinstance(payload, dict) else {}).get("diff") or []
        if isinstance(diff, dict):  # np=1 时返回 dict
            diff = list(diff.values())
        if not diff:
            raise ProviderRequestError("东财快照返回空结果, 疑似 push2 断连")

        rows = []
        for item in diff:
            if not isinstance(item, dict):
                continue
            rows.append({
                "code": str(item.get("f12") or ""),
                "name": item.get("f14") or "",
                "price": _ds.safe_float(item.get("f2")) or 0,
                "change_pct": _ds.safe_float(item.get("f3")),
                "change_amt": _ds.safe_float(item.get("f4")),
                "volume": _ds.safe_float(item.get("f5")),
                "amount": _ds.safe_float(item.get("f6")),
                "source": "eastmoney",
            })
        if not rows:
            raise ProviderRequestError("东财快照解析后为空")
        return rows

    # ------------------------------------------------------------------
    # 财务指标
    # ------------------------------------------------------------------
    def get_financial(self, code: str, page_size: int = 4) -> list[dict]:
        """东财财务指标 (RPT_LICO_FN_CPD) → list[dict]。"""
        bare = _ds.normalize_code(code)
        rows = self._datacenter(
            REPORT_FINANCIAL,
            filter_str=f'(SECURITY_CODE="{bare}")',
            page_size=page_size,
            sort_columns="REPORTDATE",
            sort_types="-1",
        )
        out = []
        for r in rows:
            out.append({
                "code": str(r.get("SECURITY_CODE") or bare),
                "name": r.get("SECURITY_NAME_ABBR") or "",
                "report_date": str(r.get("REPORTDATE") or "")[:10],
                "report_type": r.get("REPORT_TYPE") or "",
                "eps": _ds.safe_float(r.get("BASIC_EPS")),
                "revenue": _ds.safe_float(r.get("TOTAL_OPERATE_INCOME")),
                "net_profit": _ds.safe_float(r.get("PARENT_NETPROFIT")),
                "roe": _ds.safe_float(r.get("WEIGHTAVG_ROE")),
                "source": "eastmoney",
            })
        if not out:
            raise ProviderRequestError(f"东财财务指标解析后为空: code={code}")
        return out

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

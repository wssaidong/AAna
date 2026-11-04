"""
data/quotes.py — AAna 统一行情数据服务
=========================================
整合所有数据源，提供统一的行情接口，自动 fallback。

接口设计原则：
  1. 任意单一数据源失败不影响整体返回
  2. 所有方法返回 dict/DataFrame，永不抛出网络异常
  3. 字段命名统一（code/name/price/change_pct/vol/...）

使用方法：
  from data.quotes import QuoteService
  qs = QuoteService()
  qt = qs.realtime(["000001", "603906"])
  kl = qs.kline("603906", period="daily", count=60)
"""

import json
import os
import time
import warnings
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

try:  # XWI-80 P0-1: 本地日线库（store 优先、网络兜底）；缺库不阻塞行情
    from data import market_store
except Exception:  # pragma: no cover
    market_store = None

warnings.filterwarnings('ignore')

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# ── 数据源基础配置 ─────────────────────────────────────────
SINA_HQ     = "http://hq.sinajs.cn/list="
TENCENT_QT  = "https://qt.gtimg.cn/q="
TENCENT_KL  = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
# 2026-10-29: fqkline 被 WAF 拦 (HTTP 501) 时的降级端点 (不复权, 字段顺序同 fqkline)
TENCENT_KL_NOAJ = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
THS_HOT     = "http://zx.10jqka.com.cn/event/api/getharden/"
EM_PUSH2    = "https://push2.eastmoney.com/api/qt/stock/get"
EM_PUSH2IND = "https://push2.eastmoney.com/api/qt/clist/get"
EM_DATACENTER = "https://datacenter-web.eastmoney.com/api/data/v1/get"

TIMEOUT = (5, 10)  # (connect, read)


# ── 内部工具 ───────────────────────────────────────────────
def _req(url: str, params=None, headers=None, timeout=TIMEOUT) -> Optional[requests.Response]:
    try:
        h = {"User-Agent": UA}
        if headers:
            h.update(headers)
        r = requests.get(url, params=params, headers=h, timeout=timeout)
        return r
    except Exception:
        return None


def _retry_req(url: str, params=None, headers=None, timeout=TIMEOUT,
               retries: int = 2, backoff: float = 0.5) -> Optional[requests.Response]:
    """带指数退避重试的请求封装."""
    for attempt in range(retries + 1):
        resp = _req(url, params, headers, timeout)
        if resp is not None and resp.status_code == 200:
            return resp
        if attempt < retries:
            time.sleep(backoff * (2 ** attempt))
    return None


def _sf(v, default=None) -> Optional[float]:
    """安全转 float"""
    if v is None or v == '' or v == '--' or v == '-':
        return default
    try:
        return float(str(v).replace('%', '').replace(',', ''))
    except (ValueError, TypeError):
        return default


def _prefix(code: str) -> str:
    """6位代码 → sh/sz/bj 前缀"""
    c = code.strip()  # 先去除首尾空格
    if c.startswith('6') or c.startswith('9'):
        return 'sh' + c  # 上海主板 + 科创板（688）
    if c.startswith('8'):
        return 'bj' + c  # 北交所
    return 'sz' + c     # 深圳主板+创业板


# ── 主服务类 ───────────────────────────────────────────────
class QuoteService:
    """统一行情数据服务"""

    def realtime(self, codes: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        获取实时行情（新浪 → 腾讯 fallback）
        返回: {code: {code, name, price, change_pct, high, low, vol, amount, ...}}
        """
        if not codes:
            return {}

        # 1. 新浪（优先）
        result = self._sina_quote(codes)
        # 2. 腾讯补漏
        missing = [c for c in codes if c not in result or result[c].get('price', 0) == 0]
        if missing:
            fallback = self._tencent_quote(missing)
            result.update(fallback)
        return result

    def kline(self, code: str, period: str = "daily",
              count: int = 30, adjust: str = "qfq",
              allow_sina_fallback: bool = True) -> List[Dict[str, Any]]:
        """
        获取历史K线（XWI-80 P0-1 起：本地日线库 store 优先 → 腾讯 → 新浪 fallback）
        period: daily / weekly / monthly
        count: 获取K线根数
        adjust: qfq / hfq / ""（前复权/后复权/不复权）
        返回: [{date, open, high, low, close, vol}, ...]

        store 优先（data/market_store.py，仅 daily）：
          - 命中（库里该口径 >= count 根）→ 直接返回，零网络请求
          - 未命中/库存不足 → 走网络，成功后回写 store
          - 回写口径如实标注：新浪 fallback 与腾讯 NOAJ 降级拿到的是不复权
            价，一律按 raw 入库，绝不伪装成 qfq（qfq/raw 分行存储互不串）

        ⚠️ v2026-10-26 新增 allow_sina_fallback（默认 True = 保持原行为）:
        新浪 fallback 只提供**不复权**日线，腾讯 fqkline 提供**前复权**。
        两者混用会在除权日产生假跌幅（实测 002178: 腾讯 qfq 10-21→10-22 = 0.00%，
        新浪 raw = -3.73%，差 0.19 元 = 纯分红除权缺口）。
        计算**收益率**的场景必须传 allow_sina_fallback=False，拿不到前复权序列时
        宁可留空也不要用不复权价凑出脏收益率（见 feedback_loop._kline_cached）。
        """
        if period == "daily" and market_store is not None:
            try:
                cached = market_store.load_kline_cached(code, count=count, adjust=adjust)
                if cached:
                    return cached
            except Exception:
                pass  # store 故障不影响行情主链路

        kl, actual_adjust = self._tencent_kline(code, period, count, adjust,
                                                return_adjust=True)
        if not kl and allow_sina_fallback:
            kl = self._sina_kline_fallback(code, count)
            actual_adjust = 'raw'  # 新浪日线 = 不复权，绝不标成 qfq

        if kl and period == "daily" and actual_adjust and market_store is not None:
            try:
                market_store.save_kline_cached(code, kl, adjust=actual_adjust)
            except Exception:
                pass  # 回写失败不影响返回
        return kl

    def block_industry(self, top_n: int = 10) -> List[Dict[str, Any]]:
        """行业板块涨幅榜（东财 → 同花顺备用）"""
        data = self._em_industry(top_n)
        if not data:
            data = self._ths_hot_fallback()
        return data

    def hot_stocks(self, date_str: str = None) -> List[Dict[str, Any]]:
        """当日强势股（同花顺 → 东财热点备用）"""
        data = self._ths_hot(date_str)
        if not data:
            data = self._em_hot_fallback(date_str)
        return data

    def technical(self, code: str) -> Dict[str, Any]:
        """
        计算技术指标（基于K线）
        返回: {rsi, ma5, ma10, ma20, ma60, macd_dif, macd_dea, macd_hist,
               vol_ratio, change_pct, ...}

        XWI-81 P1-4 起指标计算整体委托 data/indicators.snapshot()：
        pandas rolling/ewm 向量化（禁 iterrows / Python 循环算均线），
        输出与旧实现逐字段一致 —— tests/test_indicators.py 以旧实现逐行
        拷贝为 oracle 锁定该契约（含旧口径的 MA 不足回退与 DEA 一阶滞后）。
        """
        klines = self.kline(code, count=60)
        if not klines:
            return {}
        from data import indicators
        return indicators.snapshot(klines, code=code)

    # ── 私有方法 ──────────────────────────────────────────────

    def _sina_quote(self, codes: List[str]) -> Dict[str, Dict[str, Any]]:
        try:
            joined = ','.join(_prefix(c) for c in codes)
            r = _retry_req(SINA_HQ + joined)
            if not r:
                return {}
            text = r.text.encode('gbk').decode('gbk') if r.content else ""
            result = {}
            for line in text.split('\n'):
                if '=' not in line:
                    continue
                raw_code = line.split('=')[0].split('_')[-1].strip()
                code = raw_code.lstrip('shszbj').strip()
                parts = line.split('=')[1].strip('";\n ').split(',')
                if len(parts) < 10:
                    continue
                name = parts[0]
                yc = _sf(parts[2])
                op = _sf(parts[1])
                price = _sf(parts[3])
                high = _sf(parts[4])
                low = _sf(parts[5])
                vol = _sf(parts[8])
                amount = _sf(parts[9])
                change_pct = round((price - yc) / yc * 100, 2) if yc and yc != 0 and price else 0
                result[code] = {
                    'code': code, 'name': name,
                    'price': price, 'open': op, 'high': high, 'low': low,
                    'yesterday_close': yc,
                    'change_pct': change_pct,
                    'vol': vol, 'amount': amount * 10000 if amount else 0,
                    'source': 'sina',
                }
            return result
        except Exception:
            return {}

    def _tencent_quote(self, codes: List[str]) -> Dict[str, Dict[str, Any]]:
        try:
            joined = ','.join(_prefix(c) for c in codes)
            r = _retry_req(TENCENT_QT + joined)
            if not r:
                return {}
            text = r.text
            result = {}
            for line in text.split('\n'):
                if '=' not in line:
                    continue
                raw = line.split('=')[0].strip()
                code = raw.lstrip('shszbj').strip()
                parts = line.split('=')[1].strip('";\n ').split('~')
                if len(parts) < 10:
                    continue
                name, price, yc, op, high, low, vol = parts[1], _sf(parts[3]), _sf(parts[4]), \
                    _sf(parts[5]), _sf(parts[33]), _sf(parts[34]), _sf(parts[36])
                change_pct = round((price - yc) / yc * 100, 2) if yc and price else 0
                result[code] = {
                    'code': code, 'name': name,
                    'price': price, 'open': op, 'high': high, 'low': low,
                    'yesterday_close': yc,
                    'change_pct': change_pct,
                    'vol': vol, 'amount': 0,
                    'source': 'tencent',
                }
            return result
        except Exception:
            return {}

    def _tencent_kline(self, code: str, period: str, count: int, adjust: str,
                       return_adjust: bool = False):
        """拉腾讯日K。return_adjust=True 时返回 (bars, 实际复权口径)：
        口径以 payload 实际键位为准（qfqday/hfqday 键 = 请求口径，裸 day 键
        = 'raw' 不复权）；NOAJ 降级端点恒 'raw'。默认返回 bars（向后兼容）。"""
        mkt = 'sh' if code.startswith(('6', '9')) else ('bj' if code.startswith(('8', '4', '3')) else 'sz')
        for url, params, forced in (
            (TENCENT_KL, {"param": f"{mkt}{code},day,,,{count},{adjust}"}, None),
            # 2026-10-29: fqkline qfq 端点被腾讯 WAF 拦 (HTTP 501) 时降级到
            # kline/kline 不复权端点 (与 scripts/deep_analysis_pm_20261026.py 同款降级)。
            # 两端点 bar 字段顺序一致 = [date, open, close, high, low, vol]。
            (TENCENT_KL_NOAJ, {"param": f"{mkt}{code},day,,,{count},"}, 'raw'),
        ):
            bars, used = self._parse_tencent_bars(url, params, mkt, code, adjust)
            if bars:
                return (bars, forced or used) if return_adjust else bars
        return ([], None) if return_adjust else []

    @staticmethod
    def _parse_tencent_bars(url: str, params: dict, mkt: str, code: str,
                            adjust: str) -> tuple[List[Dict[str, Any]], Optional[str]]:
        """拉取并解析腾讯日K bar，返回 (bars, 实际口径)。

        口径判定跟着 payload 键位走：{adjust}day 键 → 请求口径；裸 day 键
        → 'raw'。XWI-83 QA 修复：原实现从 fqkline 端点静默回退取裸 day
        (不复权) 数据，却仍被 _tencent_kline 推定标成 qfq —— 002178 的
        raw 冒充 qfq 入库、10-21→10-22 复现 -3.73% 假跌幅的根因。
        标签必须反映数据真实口径，不能推定。

        ⚠️ 2026-10-29 P0 字段错位修复:
          腾讯 fqkline 每根 bar 实际是 [date, open, close, high, low, vol]
          原实现写成 [date, open, high, low, close, vol] → 把「收盘价」当成
          「最低价」用, 把「最高价」当成「收盘价」用, 把「最低价」当成
          「最高价」用。三重错位, 且 low > high 物理不可能。
          证据 (2026-10-29 三重独立验证):
            1) 新浪实时 hq.sinajs.cn 逐项比对: 正确映射 14/14 匹配,
               错位映射 0/14
            2) 内部不变量 low <= open <= high: 正确映射 0% 违例,
               错位映射 99.4% 违例 (854 根 bar)
            3) 本仓库 scripts/deep_analysis_2026*.py 一直用 k[2]=close /
               k[3]=high / k[4]=low (正确顺序), 与本处原实现相互矛盾
          影响: 所有基于 close 的收益率/MA/MACD/RSI 全部偏移 (收-低 = 当日
               下跌幅度), 实测同批样本胜率 93% (错位) vs 50% (正确) ——
               直接污染 feedback_loop 胜率与 backtest 结论。
        """
        try:
            r = _retry_req(url, params)
            if not r:
                return [], None
            text = r.text.strip()
            if '=' in text:
                text = text.split('=', 1)[1]
            data = json.loads(text)
            node = data.get('data', {}).get(f'{mkt}{code}', {})
            day_data = node.get(f'{adjust}day', [])
            actual = adjust if adjust in ('qfq', 'hfq') else 'raw'
            if not day_data:
                day_data = node.get('day', [])
                actual = 'raw'
            bars = [
                {'date': item[0], 'open': _sf(item[1]),
                 'close': _sf(item[2]), 'high': _sf(item[3]),
                 'low': _sf(item[4]), 'vol': _sf(item[5])}
                for item in day_data if len(item) >= 6
            ]
            return bars, actual
        except Exception:
            return [], None

    def _sina_kline_fallback(self, code: str, count: int) -> List[Dict[str, Any]]:
        """新浪K线作为腾讯的降级方案（仅日线，不支持前复权）"""
        try:
            url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
            params = {
                "symbol": _prefix(code), "scale": 240,  # 240分钟=日K
                "ma": "no", "datalen": count
            }
            r = _retry_req(url, params)
            if not r:
                return []
            data = r.json()
            return [
                {'date': d['day'], 'open': _sf(d['open']),
                 'high': _sf(d['high']), 'low': _sf(d['low']),
                 'close': _sf(d['close']), 'vol': _sf(d['volume'])}
                for d in data if isinstance(d, dict) and 'day' in d
            ]
        except Exception:
            return []

    def _em_industry(self, top_n: int) -> List[Dict[str, Any]]:
        """东方财富行业板块涨幅榜"""
        try:
            url = EM_PUSH2IND
            params = {
                "pn": 1, "pz": top_n, "po": 1, "np": 1,
                "fltt": 2, "invt": 2,
                "fs": "m:90+t:2",
                "fields": "f2,f3,f4,f12,f14"
            }
            r = _retry_req(url, params)
            if not r:
                return []
            d = r.json().get('data', {}).get('diff', [])
            return [
                {'code': i.get('f12'), 'name': i.get('f14'),
                 'change_pct': _sf(i.get('f3')), 'source': 'em_industry'}
                for i in d if i.get('f12') and i.get('f14')
            ]
        except Exception:
            return []

    def _ths_hot(self, date_str: str = None) -> List[Dict[str, Any]]:
        """同花顺强势股"""
        try:
            dt = date_str or datetime.now().strftime('%Y-%m-%d')
            url = THS_HOT + f"date/{dt}/orderby/date/orderway/desc/charset/GBK/"
            r = _retry_req(url, headers={"Referer": "http://zx.10jqka.com.cn/"})
            if not r:
                return []
            data = r.json().get('data', []) or []
            return [
                {'code': str(h.get('code', '')),
                 'name': h.get('name', ''),
                 'change_pct': _sf(h.get('zhangfu')),
                 'reason': h.get('reason', ''),
                 'source': 'ths_hot'}
                for h in data if h.get('code')
            ]
        except Exception:
            return []

    def _ths_hot_fallback(self) -> List[Dict[str, Any]]:
        return self._ths_hot()

    def _em_hot_fallback(self, date_str: str = None) -> List[Dict[str, Any]]:
        """东财热点股备用（强势股API）"""
        try:
            dt = date_str or datetime.now().strftime('%Y%m%d')
            url = EM_DATACENTER
            params = {
                "sortColumns": "SECURITY_CODE",
                "sortTypes": "1",
                "pageSize": 20,
                "pageNumber": 1,
                "reportName": "RPT_HOT_A",
                "columns": "ALL",
                "filter": f'(TRADE_DATE%3D%27{dt}%27)',
            }
            r = _retry_req(url, params)
            if not r:
                return []
            d = r.json().get('result', {}).get('data', []) or []
            return [
                {'code': str(h.get('SECURITY_CODE', '')),
                 'name': h.get('SECURITY_NAME', ''),
                 'change_pct': _sf(h.get('CHANGE_RATE')),
                 'reason': h.get('HOT_REASON', ''),
                 'source': 'em_hot'}
                for h in d if h.get('SECURITY_CODE')
            ]
        except Exception:
            return []

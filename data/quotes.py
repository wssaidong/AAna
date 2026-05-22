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

import os
import json
import time
import warnings
import requests
from datetime import datetime, date
from typing import Optional, List, Dict, Any

warnings.filterwarnings('ignore')

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# ── 数据源基础配置 ─────────────────────────────────────────
SINA_HQ     = "http://hq.sinajs.cn/list="
TENCENT_QT  = "https://qt.gtimg.cn/q="
TENCENT_KL  = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
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
              count: int = 30, adjust: str = "qfq") -> List[Dict[str, Any]]:
        """
        获取历史K线（腾讯 → 新浪 fallback）
        period: daily / weekly / monthly
        count: 获取K线根数
        adjust: qfq / hfq / ""（前复权/后复权/不复权）
        返回: [{date, open, high, low, close, vol}, ...]
        """
        kl = self._tencent_kline(code, period, count, adjust)
        if not kl:
            kl = self._sina_kline_fallback(code, count)
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
        """
        klines = self.kline(code, count=60)
        if not klines:
            return {}
        closes = [k['close'] for k in klines]
        prices = klines[-1]
        vol_list = [k['vol'] for k in klines]

        ma = lambda n: sum(closes[-n:]) / n if len(closes) >= n else None

        # RSI
        def calc_rsi(c, p=14):
            if len(c) < p + 1:
                return None
            gains, losses = [], []
            for i in range(1, len(c)):
                d = c[i] - c[i-1]
                gains.append(max(d, 0))
                losses.append(max(-d, 0))
            ag = sum(gains[-p:]) / p
            al = sum(losses[-p:]) / p
            if al == 0:
                return 100.0
            return round(100 - 100 / (1 + ag / al), 2)

        # MACD (EMA式)
        def ema(d, p):
            k = 2 / (p + 1)
            e = d[0]
            for v in d[1:]:
                e = v * k + e * (1 - k)
            return e

        dif_list, dea_list = [], []
        if len(closes) >= 26:
            for i in range(25, len(closes)):
                d = closes[:i+1]
                dif = ema(d, 12) - ema(d, 26)
                dea = dif * 0.8 + (dif_list[-1] if dif_list else dif) * 0.2 if dif_list else dif
                dif_list.append(dif)
                dea_list.append(dea)

        macd_hist = [(dif_list[-1] - dea_list[-1]) * 2] if dif_list and dea_list else [0]

        # 量比
        vol_ratio = None
        if len(vol_list) >= 6:
            avg5 = sum(vol_list[-6:-1]) / 5
            vol_ratio = round(vol_list[-1] / avg5, 2) if avg5 else None

        # 涨跌
        yesterday_close = klines[-2]['close'] if len(klines) >= 2 else prices['close']
        change_pct = round((prices['close'] - yesterday_close) / yesterday_close * 100, 2) \
            if yesterday_close else 0

        return {
            'code': code,
            'name': prices.get('name', code),
            'price': prices.get('close') or prices.get('price'),
            'open': prices.get('open'),
            'high': prices.get('high'),
            'low': prices.get('low'),
            'close': prices.get('close') or prices.get('price'),
            'vol': prices.get('vol'),
            'change_pct': change_pct,
            'ma5': ma(5),
            'ma10': ma(10),
            'ma20': ma(20),
            'ma60': ma(60),
            'rsi': calc_rsi(closes),
            'macd_dif': round(dif_list[-1], 4) if dif_list else None,
            'macd_dea': round(dea_list[-1], 4) if dea_list else None,
            'macd_hist': round(macd_hist[-1], 4),
            'vol_ratio': vol_ratio,
        }

    # ── 私有方法 ──────────────────────────────────────────────

    def _sina_quote(self, codes: List[str]) -> Dict[str, Dict[str, Any]]:
        try:
            joined = ','.join(_prefix(c) for c in codes)
            r = _req(SINA_HQ + joined)
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
                change_pct = round((price - yc) / yc * 100, 2) if yc and price else 0
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
            r = _req(TENCENT_QT + joined)
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

    def _tencent_kline(self, code: str, period: str, count: int, adjust: str) -> List[Dict[str, Any]]:
        try:
            mkt = 'sh' if code.startswith(('6', '9')) else 'sz'
            url = TENCENT_KL
            params = {"param": f"{mkt}{code},day,,,{count},{adjust}"}
            r = _req(url, params)
            if not r:
                return []
            text = r.text.strip()
            if '=' in text:
                text = text.split('=', 1)[1]
            data = json.loads(text)
            day_data = (data.get('data', {})
                        .get(f'{mkt}{code}', {})
                        .get(f'{adjust}day', [])
                        or data.get('data', {}).get(f'{mkt}{code}', {}).get('day', []))
            return [
                {'date': item[0], 'open': _sf(item[1]),
                 'high': _sf(item[2]), 'low': _sf(item[3]),
                 'close': _sf(item[4]), 'vol': _sf(item[5])}
                for item in day_data if len(item) >= 6
            ]
        except Exception:
            return []

    def _sina_kline_fallback(self, code: str, count: int) -> List[Dict[str, Any]]:
        """新浪K线作为腾讯的降级方案（仅日线，不支持前复权）"""
        try:
            url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
            params = {
                "symbol": _prefix(code), "scale": 240,  # 240分钟=日K
                "ma": "no", "datalen": count
            }
            r = _req(url, params)
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
            r = _req(url, params)
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
            r = _req(url, headers={"Referer": "http://zx.10jqka.com.cn/"})
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
        """东财热点股备用"""
        return []  # 占位，后续可扩展

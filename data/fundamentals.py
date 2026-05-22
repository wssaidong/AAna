"""
data/fundamentals.py — Tushare基本面数据服务
============================================
FundamentalService：纯本地计算，不依赖网络（评分逻辑是规则）
token从环境变量 TUSHARE_TOKEN 读取，未设置时 get_score() 返回 None
"""

import os
from typing import Optional, Dict, Any

try:
    import tushare as ts
    TUSHARE_AVAILABLE = True
except ImportError:
    TUSHARE_AVAILABLE = False


class FundamentalService:
    """
    基本面数据服务
    - get_pe_pb(code)       -> {pe, pb, roe} 或 None
    - get_financial_growth(code, year) -> {revenue_growth, profit_growth}
    - get_score(code)       -> 0-40分 或 None（无token时）
    """

    def __init__(self, token: str = None):
        self.token = token or os.getenv("TUSHARE_TOKEN")
        self._pro = None
        if TUSHARE_AVAILABLE and self.token:
            self._pro = ts.pro_api(self.token)

    # ── 评分规则（纯本地计算）───────────────────────────────────

    @staticmethod
    def _pe_score(pe: float) -> float:
        """PE评分 0-15"""
        if pe is None or pe < 0:
            return 0
        if pe < 10:
            return 15
        if pe < 20:
            return 12
        if pe < 30:
            return 8
        if pe < 50:
            return 4
        return 0

    @staticmethod
    def _pb_score(pb: float) -> float:
        """PB评分 0-10"""
        if pb is None or pb < 0:
            return 0
        if pb < 2:
            return 10
        if pb < 4:
            return 7
        if pb < 6:
            return 4
        return 0

    @staticmethod
    def _roe_score(roe: float) -> float:
        """ROE评分 0-10"""
        if roe is None or roe < 0:
            return 0
        if roe < 5:
            return 2
        if roe < 10:
            return 5
        if roe < 20:
            return 8
        return 10

    @staticmethod
    def _growth_score(growth: float) -> float:
        """增速评分 0-5（revenue_growth 或 profit_growth）"""
        if growth is None:
            return 0
        if growth > 30:
            return 5
        if growth > 20:
            return 4
        if growth > 10:
            return 3
        if growth > 0:
            return 1
        return 0

    # ── 数据获取（需要tushare网络）──────────────────────────────

    def get_pe_pb(self, code: str) -> Optional[Dict[str, float]]:
        """
        获取 PE、PB、ROE
        返回 {pe, pb, roe} 或 None（无token/网络失败）
        """
        if not self._pro:
            return None
        try:
            df = self._pro.fina_indicator(
                ts_code=code, period_type="q",
                fields="ts_code, pe, pb, roe"
            )
            if df is None or df.empty:
                return None
            row = df.iloc[-1]
            return {
                "pe": float(row["pe"]) if row["pe"] is not None else None,
                "pb": float(row["pb"]) if row["pb"] is not None else None,
                "roe": float(row["roe"]) if row["roe"] is not None else None,
            }
        except Exception:
            return None

    def get_financial_growth(self, code: str, year: int) -> Optional[Dict[str, float]]:
        """
        获取年度营收/利润增速
        返回 {revenue_growth, profit_growth} 或 None
        """
        if not self._pro:
            return None
        try:
            df = self._pro.fina_indicator(
                ts_code=code,
                start_date=f"{year}0101",
                end_date=f"{year}1231",
                fields="ts_code, revenue_growth, profit_growth"
            )
            if df is None or df.empty:
                return None
            row = df.iloc[-1]
            return {
                "revenue_growth": float(row["revenue_growth"]) if row["revenue_growth"] is not None else None,
                "profit_growth": float(row["profit_growth"]) if row["profit_growth"] is not None else None,
            }
        except Exception:
            return None

    def get_score(self, code: str) -> Optional[float]:
        """
        综合基本面评分（0-40分）
        - PE  0-15
        - PB  0-10
        - ROE 0-10
        - 增速 0-5（取营收和利润增速的较高者）
        返回 None（无token/网络失败）
        """
        data = self.get_pe_pb(code)
        if not data:
            return None

        pe = data.get("pe")
        pb = data.get("pb")
        roe = data.get("roe")

        # 用最近一个财年计算增速
        from datetime import datetime
        year = datetime.now().year - 1
        growth_data = self.get_financial_growth(code, year)
        if growth_data:
            rev_g = growth_data.get("revenue_growth")
            prof_g = growth_data.get("profit_growth")
            best_growth = max(rev_g, prof_g) if (rev_g is not None and prof_g is not None) else (rev_g or prof_g)
        else:
            best_growth = None

        total = (
            self._pe_score(pe)
            + self._pb_score(pb)
            + self._roe_score(roe)
            + self._growth_score(best_growth)
        )
        return round(min(40, total), 1)


# ── 快捷实例 ────────────────────────────────────────────────
_fs: Optional[FundamentalService] = None

def _get_fs() -> FundamentalService:
    global _fs
    if _fs is None:
        _fs = FundamentalService()
    return _fs


def get_fundamental_score(code: str) -> Optional[float]:
    """快捷函数：返回基本面评分 0-40 或 None"""
    return _get_fs().get_score(code)

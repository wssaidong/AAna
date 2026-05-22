"""
tests/test_fundamentals.py
===========================
基本面评分模块测试
"""

import pytest
from data.fundamentals import FundamentalService


# ── 辅助 ────────────────────────────────────────────────────

def fs():
    return FundamentalService(token="dummy")  # 不依赖真实token


# ── PE 评分 ─────────────────────────────────────────────────

class TestPEScoring:
    @pytest.mark.parametrize("pe,expected", [
        (-1,    0),   # 负数 → 0
        (0,    15),   # 0 < 10 → 15
        (5,    15),   # 5 < 10 → 15
        (9.9,  15),
        (10,   12),
        (15,   12),
        (19.9, 12),
        (20,    8),
        (25,    8),
        (29.9,  8),
        (30,    4),
        (40,    4),
        (49.9,  4),
        (50,    0),
        (100,   0),
        (None,  0),
    ])
    def test_pe_score(self, pe, expected):
        assert fs()._pe_score(pe) == expected


# ── PB 评分 ─────────────────────────────────────────────────

class TestPBScoring:
    @pytest.mark.parametrize("pb,expected", [
        (-1,   0),   # 负数 → 0
        (0,   10),   # 0 < 2 → 10
        (1.9, 10),
        (2,    7),
        (3.9,  7),
        (4,    4),
        (5.9,  4),
        (6,    0),
        (10,   0),
        (None, 0),
    ])
    def test_pb_score(self, pb, expected):
        assert fs()._pb_score(pb) == expected


# ── ROE 评分 ─────────────────────────────────────────────────

class TestROEScoring:
    @pytest.mark.parametrize("roe,expected", [
        (-1,   0),   # 负数 → 0
        (0,    2),   # 0 < 5 → 2
        (4.9,  2),
        (5,    5),
        (9.9,  5),
        (10,   8),
        (19.9, 8),
        (20,  10),
        (30,  10),
        (None, 0),
    ])
    def test_roe_score(self, roe, expected):
        assert fs()._roe_score(roe) == expected


# ── 增速评分 ─────────────────────────────────────────────────

class TestGrowthScoring:
    @pytest.mark.parametrize("growth,expected", [
        (-50,   0),   # <=0 → 0
        (-1,    0),   # <=0 → 0
        (0,     0),   # <=0 → 0
        (0.1,   1),   # >0%  → 1
        (5,     1),   # >0%  → 1
        (10,    1),   # 不>10 → 1
        (15,    3),   # >10% → 3
        (20,    3),   # >10%但≤20 → 3
        (25,    4),   # >20% → 4
        (30,    4),   # >20% → 4（30不大于30，故归入>20档）
        (50,    5),   # >30% → 5
        (100,   5),   # >30% → 5
        (None,  0),
    ])
    def test_growth_score(self, growth, expected):
        assert fs()._growth_score(growth) == expected


# ── 综合评分范围 ─────────────────────────────────────────────

class TestTotalScoreRange:
    def test_best_case(self):
        """最优参数应得满分 40"""
        f = fs()
        # PE=5→15, PB=1→10, ROE=25→10, growth=40→5 → total=40
        s = f._pe_score(5) + f._pb_score(1) + f._roe_score(25) + f._growth_score(40)
        assert s == 40

    def test_worst_case(self):
        """最差参数应得 0"""
        f = fs()
        s = f._pe_score(-1) + f._pb_score(-1) + f._roe_score(-1) + f._growth_score(-10)
        assert s == 0

    def test_score_capped_at_40(self):
        """即使各维度都满分，也不超过 40"""
        f = fs()
        # 各维度最高: PE=15, PB=10, ROE=10, growth=5 = 40
        total = f._pe_score(5) + f._pb_score(1) + f._roe_score(30) + f._growth_score(50)
        assert total <= 40
        assert total == 40


# ── 无 token / 网络降级 ─────────────────────────────────────

class TestSafeGetHandlesMissing:
    def test_no_token_returns_none(self):
        """未设置 TUSHARE_TOKEN 时 get_score 返回 None（不抛异常）"""
        import os as _os
        # 临时清除 token
        saved = _os.environ.pop("TUSHARE_TOKEN", None)
        try:
            f = FundamentalService()  # 无 token
            assert f.get_score("000001.SZ") is None
            assert f.get_pe_pb("000001.SZ") is None
            assert f.get_financial_growth("000001.SZ", 2024) is None
        finally:
            if saved is not None:
                _os.environ["TUSHARE_TOKEN"] = saved

    def test_get_score_not_crash_without_network(self):
        """有token但无网络时，get_score 不抛异常"""
        f = FundamentalService(token="fake_token_12345")
        # 可能抛异常或返回None，都是安全行为
        try:
            result = f.get_score("000001.SZ")
            assert result is None or (isinstance(result, float) and 0 <= result <= 40)
        except Exception as e:
            pytest.fail(f"get_score raised unexpected exception: {e}")

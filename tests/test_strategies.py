"""
tests/test_strategies.py — 策略层测试
"""
import os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from strategies import (
    MomentumStrategy, TechnicalStrategy, ValueStrategy,
    CompositeStrategy, quick_score
)
from data.quotes import QuoteService

qs = QuoteService()

def test_momentum_strategy():
    strat = MomentumStrategy()
    # 用真实股票测试（腾讯K线充足）
    klines = qs.kline("000001", count=30)
    assert isinstance(klines, list)
    score = strat.score("000001", klines)
    assert 0 <= score <= 100
    print(f"  动量策略 000001: {score}")

def test_technical_strategy():
    strat = TechnicalStrategy()
    klines = qs.kline("000001", count=30)
    score = strat.score("000001", klines)
    assert 0 <= score <= 100
    print(f"  技术面策略 000001: {score}")

def test_composite_strategy():
    strat = CompositeStrategy(
        [MomentumStrategy(), TechnicalStrategy()],
        weights=[0.4, 0.6]
    )
    klines = qs.kline("000001", count=30)
    result = strat.score("000001", klines)
    assert 'composite' in result
    assert 0 <= result['composite'] <= 100
    print(f"  复合策略 000001: {result}")

def test_quick_score():
    result = quick_score("000001", strategy="composite")
    assert 'code' in result
    assert 'score' in result or 'composite' in result
    print(f"  quick_score 000001: {result.get('composite') or result.get('score')}")

def test_no_kline():
    """无效股票代码应返回 error 而非崩溃"""
    # 直接传空klines，不走qs（避免真实网络请求）
    strat = MomentumStrategy()
    # 空列表 → 策略应返回0而非崩溃
    score = strat.score("999999", [], {})
    assert 0 <= score <= 100

if __name__ == '__main__':
    print("Running strategy tests...")
    test_momentum_strategy()
    test_technical_strategy()
    test_composite_strategy()
    test_quick_score()
    test_no_kline()
    print("All strategy tests passed ✓")

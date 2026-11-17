"""回归测试: 数据源健康度 → 动态降阈值 (修复 #12)

背景: 10/1-10/6 多个交易日数据源全挂, K 线 fail 率 100%,
fallback score 47-49 < 阈值 65 → 0 推荐(用户发现 A 股 Top 10 表头是空的)。

修复: screen_afternoon_stocks 在循环外统计 K 线 ok/fail,
     fail 率 > 70% 时阈值降到 45, 让 fallback score 47-49 也能通过。
     同时把置信度提示通过 confidence_note 传给 generate_report 写到报告头部。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import inspect


def test_data_health_var_exists():
    """screen_afternoon_stocks 必须有 data_health 字典追踪"""
    from scripts.aana_afternoon_screen import screen_afternoon_stocks
    src = inspect.getsource(screen_afternoon_stocks)
    assert "data_health = {" in src, "必须初始化 data_health 字典"
    assert "'kline'" in src, "data_health 必须追踪 kline"


def test_threshold_adjusted_based_on_kline_fail_rate():
    """源码必须根据 kline fail 率动态调整阈值"""
    from scripts.aana_afternoon_screen import screen_afternoon_stocks
    src = inspect.getsource(screen_afternoon_stocks)
    assert "fail_rate_kline" in src, "必须计算 K 线 fail 率"
    assert "adjusted_threshold = 45" in src, "fail 率 > 70% 时阈值必须降到 45"
    assert "score_threshold = adjusted_threshold" in src, "必须用调整后的阈值替换原阈值"


def test_confidence_note_returned():
    """screen_afternoon_stocks 必须返回 confidence_note 给报告"""
    from scripts.aana_afternoon_screen import screen_afternoon_stocks, generate_report
    src = inspect.getsource(screen_afternoon_stocks)
    assert "return top_n," in src, "必须返回 (top_n, confidence_note) 二元组"
    sig = inspect.signature(generate_report)
    assert "confidence_note" in sig.parameters, "generate_report 必须接收 confidence_note"


def test_report_writes_confidence_warning():
    """generate_report 必须把 confidence_note 写到报告头部"""
    from scripts.aana_afternoon_screen import generate_report
    src = inspect.getsource(generate_report)
    assert "confidence_note" in src, "generate_report 必须使用 confidence_note 参数"
    assert "数据源异常" in src, "报告头部必须显式提示数据源异常"

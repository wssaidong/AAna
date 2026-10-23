"""
tests/test_afternoon_ice_point_guard.py
— P0 回归测试: 冰点守卫单一真源 + daily_v24_recommend 不得旁路 (v2026-10-22)

背景 (P0, 连续 3 日复发 10/17 + 10/21 + 10/22):
  冰点守卫原先只写在 aana_afternoon_screen.main() 内部, 而 launchd
  daily_v24_recommend.py 直接调 screen_afternoon_stocks() 且硬编码
  sentiment_score=50/position_ratio=0.5 (假装中性) → 冰点日逆势建 10 只
  纸面仓 + 写 10 行 rec_feedback/recommendations, 污染 rec_tuning 胜率统计。

覆盖:
  1. check_ice_point_guard() 存在且返回统一字段
  2. 冰点 → is_ice_point=True；正常/分歧 → False；fallback(-1) → 不误判冰点
  3. main() 与 daily_v24_recommend.py 共用同一守卫 (源码断言: 无重复判定)
  4. daily_v24_recommend.py 必须调 check_ice_point_guard 且不再硬编码 50/0.5
"""
import inspect
import os
import sys
import warnings

warnings.filterwarnings('ignore')

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
sys.path.insert(0, os.path.join(PROJECT, "scripts"))

import aana_afternoon_screen as aas


def _strip_comments(src: str) -> str:
    """去掉注释行与行内注释, 只留可执行代码 (用于源码断言, 避免误报注释里的历史 bug 说明)"""
    import io
    import tokenize
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                continue
            out.append(tok.string)
    except tokenize.TokenError:
        return "\n".join(
            ln.split('#')[0] for ln in src.splitlines()
        )
    return "\n".join(out)


# ───────────────── 1. 守卫函数契约 ─────────────────

def test_guard_function_exists_and_returns_contract():
    """check_ice_point_guard 必须存在并返回统一字段"""
    assert hasattr(aas, 'check_ice_point_guard'), "缺少 check_ice_point_guard 单一真源"
    fn = aas.check_ice_point_guard
    g = fn(sent={
        'label': '冰点', 'score': 20, 'zt_count': 5, 'dt_count': 2,
    })
    for key in ('is_ice_point', 'sentiment_label', 'sentiment_score',
                'position_ratio', 'data_source_fallback', 'reason'):
        assert key in g, f"守卫返回值缺少字段 {key}"
    assert isinstance(g['is_ice_point'], bool), "is_ice_point 必须是 bool"


# ───────────────── 2. 判定语义 ─────────────────

def test_ice_point_triggers_short_circuit():
    """冰点 → 短路; 仓位 < 10% → 短路"""
    g = aas.check_ice_point_guard(sent={
        'label': '冰点', 'score': 20, 'zt_count': 5, 'dt_count': 2,
    })
    assert g['is_ice_point'] is True, "冰点必须短路"
    assert g['sentiment_label'] == '冰点'
    assert g['reason'], "短路时必须给出原因 (写日志用)"

    # 极低仓位 (< 10%) 同样短路, 即使 label 不是冰点
    g2 = aas.check_ice_point_guard(sent={
        'label': '未知', 'score': 15, 'zt_count': 5, 'dt_count': 2,
    })
    assert g2['is_ice_point'] is True, "仓位 < 10% 必须短路"


def test_normal_sentiment_does_not_short_circuit():
    """分歧/回暖 → 不短路 (不能把正常日误杀)"""
    for label, score in (('分歧', 50), ('回暖', 65), ('亢奋', 85)):
        g = aas.check_ice_point_guard(sent={
            'label': label, 'score': score, 'zt_count': 60, 'dt_count': 3,
        })
        assert g['is_ice_point'] is False, f"{label}/{score} 不应短路"
        assert g['sentiment_label'] == label
        assert g['sentiment_score'] == score


def test_data_source_fallback_does_not_false_ice_point():
    """涨跌停数据 fallback (-1) 时不误判冰点 (v2.5.1 语义必须保留)"""
    g = aas.check_ice_point_guard(sent={
        'label': '冰点', 'score': 20, 'zt_count': -1, 'dt_count': -1,
    })
    assert g['data_source_fallback'] is True, "应识别出 fallback"
    assert g['is_ice_point'] is False, "fallback 时不应强制空仓 (避免单点脏数据误判)"
    assert g['position_ratio'] >= 0.3, "fallback 时仓位应抬到 30%+"


# ───────────────── 3. 单一真源 (无重复判定) ─────────────────

def test_main_uses_shared_guard():
    """main() 必须调 check_ice_point_guard, 不再内联重复判定"""
    src = inspect.getsource(aas.main)
    assert 'check_ice_point_guard()' in src, "main() 必须调用共享守卫"
    assert "sentiment_label in ('冰点'" not in src, \
        "main() 不应内联冰点判定 (会与守卫分裂)"


# ───────────────── 4. daily_v24_recommend 不得旁路 ─────────────────

def test_daily_v24_recommend_cannot_bypass_guard():
    """daily_v24_recommend 必须过守卫, 且不再硬编码 sentiment_score=50"""
    import daily_v24_recommend as d24
    src = inspect.getsource(d24.main)
    assert 'check_ice_point_guard' in src, \
        "daily_v24_recommend 必须调 check_ice_point_guard (否则冰点日旁路建仓)"
    assert 'is_ice_point' in src, "必须检查 is_ice_point 并短路"
    # 硬编码 50/0.5 = 假装中性, 是本次 P0 的直接成因
    # 只看**可执行代码**, 排除注释 (注释里保留原 bug 说明是刻意的)
    code = _strip_comments(src)
    assert 'sentiment_score=50' not in code, \
        "不得硬编码 sentiment_score=50 (假装中性, 会绕过情绪)"
    assert 'position_ratio=0.5' not in code, \
        "不得硬编码 position_ratio=0.5 (假装中性, 会绕过情绪)"
    # 守卫必须在 screen_afternoon_stocks 之前
    assert code.index('check_ice_point_guard') < code.index('screen_afternoon_stocks'), \
        "守卫调用必须早于 screen_afternoon_stocks (否则短路无效)"


def test_guard_call_precedes_position_creation():
    """守卫必须早于建仓 (record_buy)"""
    import daily_v24_recommend as d24
    code = _strip_comments(inspect.getsource(d24.main))
    assert code.index('check_ice_point_guard') < code.index('record_buy'), \
        "守卫必须早于 record_buy"


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-v']))

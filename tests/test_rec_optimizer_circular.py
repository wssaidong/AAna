"""回归测试: _rebuild_from_existing 的 record 必须标记 score_is_estimated=True

修复 #11 (v2026-10-07 review): 防止 calc_score_band_stats 把反推 score 当真分数
统计胜率, 形成循环论证 (60-70 分带 100% 胜率假象的根源)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.rec_optimizer import _rebuild_from_existing


def test_rebuild_marks_all_estimated():
    """_rebuild_from_existing 全部 record 应是 score_is_estimated=True,
    因为 _estimate_score(...actual_change) 是从结果反推的特征。"""
    recs = _rebuild_from_existing()
    # 跳过空数据场景 (tracking.csv 可能为空)
    if not recs:
        return
    bad = [r for r in recs if not r.score_is_estimated]
    assert not bad, (
        f"_rebuild_from_existing 漏标 score_is_estimated=True 的 record "
        f"数: {len(bad)}/{len(recs)} (前 3 个 code: {[r.code for r in bad[:3]]})"
    )

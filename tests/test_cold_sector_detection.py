#!/usr/bin/env python3
"""tests/test_cold_sector_detection.py — 冷启动盲区检测器单测

锁定 v2026-10-28 P0-4 修复后的不变量:

1. **中文名板块查得到样本** (核心回归):
   rec_tuning.sector_stats 的 key 是 rec_feedback.csv `sector` 列原值 =
   **中文行业名**。旧代码只用 enum 查 → 中文名板块 count 恒为 0 → 一律判成
   "冷启动" → 进 cold_sectors → 尾盘一票否决。
   实测误伤: 汽车零部件 (n=21 wr=95.2%) / 水泥制造 (n=4 wr=100%) /
   机械基础件 (n=3 wr=100%) —— 28 笔样本胜率 96.4%, 全是强势板块。
2. 真正的新板块 (n=0) 仍必须被判为冷启动 (不能过度修正)。
3. 已知但样本不足的板块 (n<3) 仍判为冷启动。
4. enum 键的历史板块仍能正确查到样本 (enum 兜底路径)。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from daily_root_cause import detect_冷启动盲区  # noqa: E402


def _tuning(sector_stats):
    return {"sector_stats": sector_stats}


class TestColdSectorDetection:
    def test_chinese_name_sector_with_enough_samples_not_cold(self):
        """核心回归: 中文名板块 n>=3 → 不是冷启动 (旧代码误判为冷启动)"""
        tuning = _tuning({
            "汽车零部件": {"count": 21, "win_rate": 95.2},
            "水泥制造": {"count": 4, "win_rate": 100.0},
            "机械基础件": {"count": 3, "win_rate": 100.0},
        })
        recs = [
            {"code": "002454", "name": "宗申动力", "sector": "汽车零部件", "ret_1d": "2.43"},
            {"code": "002233", "name": "塔牌集团", "sector": "水泥制造", "ret_1d": "3.55"},
            {"code": "002347", "name": "泰坦股份", "sector": "机械基础件", "ret_1d": "6.78"},
        ]
        res = detect_冷启动盲区(recs, tuning)
        assert res["hit"] is False, (
            f"有充分样本的中文名板块被误判为冷启动: {res.get('cold_sectors')}"
        )
        assert not res.get("cold_sectors")

    def test_brand_new_sector_still_cold(self):
        """真正的新板块 (n=0) 仍必须判为冷启动 (不能过度修正)"""
        tuning = _tuning({"汽车零部件": {"count": 21, "win_rate": 95.2}})
        recs = [
            {"code": "000001", "name": "甲", "sector": "全新板块甲", "ret_1d": "1.0"},
            {"code": "000002", "name": "乙", "sector": "全新板块乙", "ret_1d": "-1.0"},
        ]
        res = detect_冷启动盲区(recs, tuning)
        assert res["hit"] is True
        assert set(res["cold_sectors"]) == {"全新板块甲", "全新板块乙"}

    def test_known_but_under_sampled_still_cold(self):
        """已知但 n<3 的板块 → 仍是冷启动"""
        tuning = _tuning({"小样板块": {"count": 2, "win_rate": 50.0}})
        recs = [{"code": "000003", "name": "丙", "sector": "小样板块", "ret_1d": "1.0"}]
        res = detect_冷启动盲区(recs, tuning)
        assert res["hit"] is True
        assert "小样板块" in res["cold_sectors"]

    def test_enum_keyed_sector_still_resolves(self):
        """enum 键的历史板块仍走兜底路径查到样本 (2026-05 老数据)"""
        tuning = _tuning({"energy": {"count": 12, "win_rate": 90.0}})
        recs = [{"code": "000004", "name": "丁", "sector": "energy", "ret_1d": "1.0"}]
        res = detect_冷启动盲区(recs, tuning)
        assert res["hit"] is False, f"enum 板块被误判冷启动: {res.get('cold_sectors')}"

    def test_no_sector_info_skipped(self):
        """查不到任何板块信息 → 跳过 (不算冷启动)"""
        tuning = _tuning({"汽车零部件": {"count": 21, "win_rate": 95.2}})
        recs = [{"code": "000005", "name": "戊", "sector": "", "ret_1d": "1.0"}]
        res = detect_冷启动盲区(recs, tuning)
        assert res["hit"] is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

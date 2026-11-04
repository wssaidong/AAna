"""strategies/filters.py — 形态筛选层实现（XWI-81 P0-2 形态层 + P1-4 向量化）

Sequoia-X 式「返回选中代码列表」的形态过滤器落点：本文件被 strategies/__init__.py
的 pkgutil 自动发现 import，@register_filter 自注册——加新过滤器不改任何旧文件。
形态判定全部走 data/indicators 向量化指标，整池一次 snapshot_many（groupby）。
"""
from typing import Any

from data import indicators
from strategies.base import ShapeFilter, register_filter


@register_filter("ma_bull")
class MABullFilter(ShapeFilter):
    """均线多头形态筛选：MA5 > MA10 > MA20（借鉴 Sequoia-X ma_volume 的形态
    思路——均线多头 + 排列有序；判定用 AAna 自己的向量化指标层）。"""

    name = "均线多头"

    def run(self, codes: list[str],
            klines_map: dict[str, list[dict[str, Any]]]) -> list[str]:
        picked = [c for c in codes if klines_map.get(c)]
        if not picked:
            return []
        snap = indicators.snapshot_many({c: klines_map[c] for c in picked})
        out = []
        for c in picked:  # 输出组装循环（指标计算已整池向量化）
            s = snap.get(c, {})
            if (s.get("ma5") is not None and s.get("ma10") is not None
                    and s.get("ma20") is not None
                    and s["ma5"] > s["ma10"] > s["ma20"]):
                out.append(c)
        return out

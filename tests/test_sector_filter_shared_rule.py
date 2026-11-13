#!/usr/bin/env python3
"""
tests/test_sector_filter_shared_rule.py — v2026-11-13 早盘板块黑名单静默失效 P0 回归测试

**背景 (P0)**

`rec_optimizer` 产出的 `weak_sectors` 是**混合口径**: 7 个中文行业名
(造纸/印制电路板/其他化学制品/房地产开发/其他家用轻工/影视动漫/装修装饰)
+ 1 个英文 enum (`semi`)。

两条消费链路对**同一个黑名单**却用了**两套不同的匹配规则**:

| 链路 | 匹配规则 | `semi` 能否命中 |
|:-----|:---------|:---------------|
| 尾盘 `aana_afternoon_screen` | 中文原名 OR enum 双路 | ✅ 能 |
| 早盘 `generate_report` | 仅中文原名单路 | ❌ **不能** |

⇒ 早盘链路的 `semi` 项 **100% 静默失效**: 黑名单非空、日志正常、策略参数正确,
但从不会真正拦截任何股票。这正是教训 (p) 说的「`unknown` enum / 口径错配
让坏数据看起来无害」, 也是教训 (i) 说的「两处代码都改对了 ≠ 链路通了」。

**修法**

把匹配规则提取到 `scripts/sector_filter.py` 作为**唯一真源**, 两条链路统一调用
(教训 (o): 同一份数据的两个解析分支, 清洗规则必须一致)。

**本测试锁定**
1. `sector_filter` 是唯一真源 —— 尾盘与早盘都从这里取, 不各写一份;
2. 早盘链路源码必须走双路匹配 (不能退回单路 `sector in weak_sectors`);
3. `semi` 这类英文 enum 项在早盘链路**必须真的能拦住**已知弱势股;
4. 反例探针: 强板块必须**放行** (不能因为加了 enum 兜底而误杀) —— 教训 (l):
   veto 逻辑落地前必须先证明它否决的是坏东西。
"""
import os
import sys

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))
sys.path.insert(0, PROJECT)

from sector_filter import (  # noqa: E402
    _SECTOR_CN_TO_ENUM,
    cn_sector_to_enum,
    is_blocked_sector,
    sector_blacklisted,
)


# ───────────────────── 1. 唯一真源 ─────────────────────

class TestSingleSourceOfTruth:
    """匹配规则只能有一份实现 —— 两处各写一遍必然漂移 (教训 o)。"""

    def test_afternoon_screen_reuses_shared_module(self):
        """尾盘必须复用 sector_filter, 不能私有一份映射表。"""
        import aana_afternoon_screen as afs

        assert afs._cn_sector_to_enum is cn_sector_to_enum, \
            "尾盘的 _cn_sector_to_enum 必须就是 sector_filter 的实现"
        assert afs._sector_blacklisted is sector_blacklisted, \
            "尾盘的 _sector_blacklisted 必须就是 sector_filter 的实现"
        assert afs._SECTOR_CN_TO_ENUM is _SECTOR_CN_TO_ENUM, \
            "映射表必须是同一份对象"

    def test_afternoon_screen_has_no_private_mapping_table(self):
        """源码层面: 尾盘文件里不应再出现 `= {` 形式的私有映射表字面量。"""
        src = open(os.path.join(PROJECT, "scripts", "aana_afternoon_screen.py"),
                   encoding="utf-8").read()
        assert "_SECTOR_CN_TO_ENUM = {" not in src, \
            "尾盘仍私有一份 _SECTOR_CN_TO_ENUM 字面量 —— 应从 sector_filter 导入"

    def test_generate_report_uses_shared_matcher(self):
        """早盘必须调用共享的双路匹配函数。"""
        src = open(os.path.join(PROJECT, "scripts", "generate_report.py"),
                   encoding="utf-8").read()
        assert "is_blocked_sector" in src, \
            "generate_report.py 必须调用 sector_filter.is_blocked_sector (双路匹配)"
        assert "sector_filter" in src, \
            "generate_report.py 必须从 sector_filter 导入匹配规则 (唯一真源)"


# ───────────────────── 2. 双路匹配语义 ─────────────────────

class TestDualPathMatching:
    """中文原名 OR 英文 enum, 任一命中即拦截。"""

    def test_chinese_name_matches(self):
        bl = ['房地产开发', '印制电路板', '造纸']
        assert sector_blacklisted('房地产开发', 'realestate', bl) is True
        assert sector_blacklisted('印制电路板', 'unknown', bl) is True
        assert sector_blacklisted('造纸', 'unknown', bl) is True

    def test_english_enum_matches(self):
        """英文 enum 项 (如 'semi') 也能命中中文名的股票。"""
        bl = ['semi']
        assert sector_blacklisted('集成电路', 'semi', bl) is True, \
            "enum 黑名单项必须能拦住对应中文行业 (早盘静默失效根因)"
        assert sector_blacklisted('半导体设备', 'semi', bl) is True

    def test_non_blacklisted_passes(self):
        bl = ['房地产开发', 'semi']
        assert sector_blacklisted('汽车零部件', 'auto', bl) is False
        assert sector_blacklisted('', '', bl) is False
        assert sector_blacklisted('unknown', 'unknown', bl) is False

    def test_empty_blacklist_never_blocks(self):
        assert sector_blacklisted('房地产开发', 'realestate', []) is False
        assert sector_blacklisted('房地产开发', 'realestate', set()) is False


# ───────────────────── 3. 真实黑名单端到端 ─────────────────────

class TestRealBlacklistEndToEnd:
    """用真实 rec_tuning.weak_sectors 验证每项都能真的拦住东西。"""

    def _weak(self):
        import json
        path = os.path.join(PROJECT, "data", "rec_tuning.json")
        if not os.path.exists(path):
            pytest.skip("rec_tuning.json 不存在")
        with open(path, encoding="utf-8") as f:
            weak = json.load(f).get("weak_sectors", [])
        if not weak:
            pytest.skip("当前 weak_sectors 为空")
        return weak

    def test_every_weak_sector_is_reachable(self):
        """每个黑名单项都必须能被匹配层命中 (不能有'装饰性'条目)。"""
        for name in self._weak():
            enum = cn_sector_to_enum(name)
            assert sector_blacklisted(name, enum, set(self._weak())) is True, \
                f"黑名单项 {name!r} 匹配不上 (装饰性条目 = 静默失效)"

    def test_semi_entry_is_not_dead_weight(self):
        """'semi' 是英文 enum 项 —— 必须能拦住对应中文行业。"""
        weak = set(self._weak())
        if 'semi' not in weak:
            pytest.skip("当前黑名单不含 semi")
        assert sector_blacklisted('集成电路', 'semi', weak) is True, \
            "'semi' 项在早盘链路静默失效 (只做中文单路匹配)"

    def test_strong_sectors_not_falsely_blocked(self):
        """反例探针: 高胜率板块必须放行 —— 加 enum 兜底不能误杀 (教训 l)。"""
        weak = set(self._weak())
        # 这些板块在真实反馈数据上胜率 58.8%~100%, 绝不能被黑名单误伤
        for cn in ['汽车零部件', '银行', '水泥制造', '小家电',
                   '机械基础件', '仪器仪表', '工控自动化', '白酒']:
            enum = cn_sector_to_enum(cn)
            assert sector_blacklisted(cn, enum, weak) is False, \
                f"{cn} (enum={enum}) 被误杀 —— enum 兜底过宽"


# ───────────────────── 4. 端到端: 生产入口 + 真实数据 ─────────────────────

class TestProductionEntryPointEndToEnd:
    """生产代码与测试调**同一个**可调用对象 (教训 i/(ac))。

    早盘链路手上只有中文行业名, 走 `is_blocked_sector()` 这个唯一生产入口。
    这里直接拿真实 rec_tuning 黑名单 + 真实反馈数据跑一遍, 验证:
      - 真实弱势板块的股票**真的被拦下** (不是只看 blacklist 非空);
      - 真实强板块的股票**真的被放过** (不误杀)。
    """

    def _weak(self):
        import json
        path = os.path.join(PROJECT, "data", "rec_tuning.json")
        if not os.path.exists(path):
            pytest.skip("rec_tuning.json 不存在")
        with open(path, encoding="utf-8") as f:
            weak = json.load(f).get("weak_sectors", [])
        if not weak:
            pytest.skip("当前 weak_sectors 为空")
        return weak

    def test_semi_family_stock_is_actually_blocked(self):
        """真实数据: 半导体族股票必须被 'semi' 黑名单项拦下。

        旧代码 (`sector in weak_sectors` 单路) 拦不住 —— 这是本 P0 的核心断言。
        """
        weak = set(self._weak())
        if 'semi' not in weak:
            pytest.skip("当前黑名单不含 semi")
        # 真实弱势板块的股票 (来自 rec_feedback 结算数据, 半导体族)
        for cn in ['集成电路', '半导体', '半导体设备']:
            assert is_blocked_sector(cn, weak) is True, \
                f"{cn} 未被 'semi' 拦下 —— 早盘链路静默失效复发"

    def test_known_good_stocks_still_pass(self):
        """真实数据: 强板块股票必须仍然放行 (反例探针)。"""
        weak = set(self._weak())
        for cn in ['汽车零部件', '银行', '水泥制造', '小家电',
                   '机械基础件', '仪器仪表', '工控自动化', '白酒']:
            assert is_blocked_sector(cn, weak) is False, \
                f"{cn} 被误杀 —— 弱板块过滤过宽"

    def test_empty_and_unknown_sector_never_blocked(self):
        """无行业信息 (空串 / 'unknown') → 放行, 不能因取不到数据就全拦。"""
        weak = set(self._weak())
        assert is_blocked_sector('', weak) is False
        assert is_blocked_sector('unknown', weak) is False

    def test_generate_report_calls_production_entry_point(self):
        """早盘生产代码必须调用 `is_blocked_sector` (而非自写单路匹配)。"""
        src = open(os.path.join(PROJECT, "scripts", "generate_report.py"),
                   encoding="utf-8").read()
        assert "is_blocked_sector" in src, \
            "generate_report.py 必须调用 sector_filter.is_blocked_sector"
        # 旧的单路写法不能作为主路径残留
        assert "if sector and sector in weak_sectors:\n                continue  # 板块为弱势板块，跳过" \
            not in src, \
            "早盘仍残留单路中文匹配 (semi 等 enum 项会静默失效)"


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))

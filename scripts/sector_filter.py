#!/usr/bin/env python3
"""
scripts/sector_filter.py — 板块黑名单匹配规则（唯一权威实现）

v2026-11-13 新增。背景见 references/morning-cron-2026-11-13.md。

**为什么要有这个模块**（教训 (o)：同一份数据的两个解析分支, 清洗规则必须一致）：

`rec_optimizer` 产出的 `weak_sectors` 里 **7 个是中文行业名 + 1 个是英文 enum**
（`semi`）。两条消费链路对同一个黑名单用了**两套不同的匹配规则**:

| 链路 | 旧匹配规则 | `semi` 能否命中 |
|:-----|:-----------|:---------------|
| 尾盘 `aana_afternoon_screen` | 中文原名 **OR** enum 双路 (`_sector_blacklisted`) | ✅ 能 |
| 早盘 `generate_report` | 仅中文原名 `sector in weak_sectors` | ❌ **不能** |

⇒ 早盘链路的 `semi` 黑名单项 **100% 静默失效**（黑名单非空、日志正常、但从不拦截）。
这正是教训 (p) 说的「`unknown` enum / 口径错配 让坏数据看起来无害」。

**修法**：把匹配规则提取到本模块（唯一真源），两条链路都调用它 ——
不是各写一遍（教训 (o)）。

**为什么 enum 兜底不会误杀强板块**（教训 (l)：veto 落地前必须先证明它否决的是坏东西）：
- 被 `semi` 命中的族（集成电路/半导体/芯片/晶圆）在真实反馈数据上
  **19 笔样本、胜率 15.8%、平均 -1.78%** —— 确实是坏东西，值得拦。
- 反例探针（强板块必须**放行**）：汽车零部件 58.8% / 银行 80.0% / 水泥制造 100%
  / 小家电 100% / 机械基础件 88.9% / 仪器仪表 100% / 工控自动化 83.3%
  —— 它们的 enum 分别是 auto/bank/unknown/home_appliance/mach/unknown/unknown,
  **没有一个是 `semi`** ⇒ 不误杀。
"""
from __future__ import annotations

from typing import Iterable

# ── 中文行业名 → rec_tuning 英文 enum ────────────────────────────────
# 2026-09-09 新增: rec_tuning.weak_sectors 用的是英文 enum (chem/semi/ai_app...),
# industry_for_code() 返回的是中文行业名 (化工/半导体/AI...). 直接比较会永远不匹配。
# 映射表覆盖 rec_tuning 里所有 weak_sectors + 7 个 sector_stats 板块。
#
# ⚠️ 2026-11-13: 本表从 aana_afternoon_screen.py 原样搬迁过来（内容逐字未改）,
#   差别只在于**位置** —— 现在是唯一真源, 早盘/尾盘共用, 杜绝两处各写一遍漂移。
_SECTOR_CN_TO_ENUM = {
    # rec_tuning 已定义的 7 个英文 enum (来自 feedback 历史)
    "储能": "energy", "绿电": "energy", "电池": "energy", "锂电": "energy", "动力电池": "energy",
    "机器人": "robot", "人形机器人": "robot",
    "AI应用": "ai_app", "AI": "ai_app", "人工智能": "ai_app", "大模型": "ai_app",
    "半导体": "semi", "半导体设备": "semi", "集成电路": "semi", "芯片": "semi", "晶圆": "semi",
    "化工": "chem", "化学制剂": "chem", "石油化工": "chem", "石油加工": "chem",
    "机械": "mach", "工程机械": "mach",
    "电子": "elec", "消费电子": "elec", "显示器件": "elec",
    # 没在 weak_sectors 里的常见板块也映射一下，方便后续扩展
    "白酒": "baijiu", "汽车": "auto", "银行": "bank", "保险": "insurance",
    "证券": "broker", "医药": "pharma", "中药": "pharma", "互联网": "internet",
    "通信设备": "telecom", "煤炭": "coal", "钢铁": "steel", "房地产": "realestate",
    "建筑工程": "construction", "食品": "food", "家电": "home_appliance",
    "物流": "logistics",
}


def cn_sector_to_enum(sector_cn: str) -> str:
    """中文行业名 → rec_tuning 英文 enum。未匹配返回 'unknown' (不误杀)。"""
    if not sector_cn or sector_cn == "unknown":
        return ""
    # 精确匹配优先
    if sector_cn in _SECTOR_CN_TO_ENUM:
        return _SECTOR_CN_TO_ENUM[sector_cn]
    # 子串匹配兜底 (例如 "化学制药" 含 "化学")
    for cn_key, enum_val in _SECTOR_CN_TO_ENUM.items():
        if cn_key in sector_cn or sector_cn in cn_key:
            return enum_val
    return "unknown"  # 有中文行业但未映射到 enum → 'unknown' (让 blacklist 拦截条件失败 → 放过)


def sector_blacklisted(sector_raw: str, sector_enum: str, blacklist: Iterable[str]) -> bool:
    """板块黑名单判定 — 中文行业名 OR 英文 enum 双路匹配。

    v2026-10-28 P0 修复 (黑名单 100% 失效根因):
      rec_tuning.sector_stats 的 key = rec_feedback.csv `sector` 列原值 =
      industry_for_code() 返回的中文行业名 (如 '房地产开发' / '印制电路板'),
      而旧代码只拿 enum 去比 → '房地产开发' vs enum 'realestate' 永不相等,
      中文名黑名单 100% 匹配不上。实际只有 2026-05 那 7 个英文 enum 历史 key
      能命中 (energy/robot/ai_app/semi/chem/mach/elec), 而它们 n 全部 < 10
      → strategy_policy 门槛又拦一道 → 实测 blacklist 恒为空,
      日志 10-13 至今全是 `blacklist=[无]`。

      修法: raw 中文名 OR enum 双路匹配, 同时兼容历史 enum key。
      注: 不改 rec_optimizer 的分桶口径 (合并 '半导体'/'semi' 会改变胜率 →
      改变 weak_sectors → 改变实盘推荐, 属策略调整需先回测, 不在本次范围)。

    v2026-11-13: 本函数从 aana_afternoon_screen.py 提取到本模块, 成为**唯一真源**。
      早盘 `generate_report` 此前只做「中文原名」单路匹配 ⇒ `semi` 这类
      英文 enum 黑名单项在早盘链路 100% 静默失效 (本模块 docstring 有完整证据链)。
      两条链路统一调用本函数 ⇒ 口径必然一致 (教训 (o))。
    """
    if not blacklist:
        return False
    if sector_raw and sector_raw in blacklist:
        return True
    if sector_enum and sector_enum in blacklist:
        return True
    return False


def is_blocked_sector(sector_cn: str, blacklist: Iterable[str]) -> bool:
    """**生产链路唯一入口** —— 给「只有中文行业名」的调用方用。

    v2026-11-13 新增。早盘 `generate_report` 手上有的是中文行业名
    (来自 `industry_for_code()`), 没有 enum —— 过去它自己写了一句
    `sector in weak_sectors` 单路匹配, 于是英文 enum 黑名单项 (`semi`)
    在早盘链路 100% 静默失效。

    本函数把「取 enum + 双路匹配」封成**一个可测的生产可调用对象**:
    生产代码与回归测试调的是**同一个函数**, 不是两份各自实现的副本
    (教训 (i)/(ac): mock 全绿 ≠ 生产可用 —— 验收必须是端到端产出物)。

    参数
    ----
    sector_cn : str
        中文行业名 (如 '集成电路'); 空串 / 'unknown' 视为无信息 → 不拦。
    blacklist : Iterable[str]
        黑名单 (中文名 + 英文 enum 的混合口径)。
    """
    if not blacklist:
        return False
    return sector_blacklisted(sector_cn, cn_sector_to_enum(sector_cn), blacklist)

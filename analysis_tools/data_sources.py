"""
analysis_tools/data_sources.py — 兼容 shim (Phase 4A v2026-08-23)

历史代码:`from analysis_tools.data_sources import tencent_quote` 等仍可工作,
因为本 shim 把所有调用 forward 到 `scripts/data_sources`。

⚠️ 新代码请直接 `from scripts.data_sources import ...`(直接 import,不经过本 shim)。

迁移时间线:
  - 2026-08-23 Phase 4A: scripts/data_sources.py 成为权威实现
  - 未来: 验证无外部 import 后,删除本 shim
"""
import os
import sys

# 优先指向 scripts/data_sources
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DATA_SOURCES = os.path.join(_HERE, "..", "scripts", "data_sources.py")
_SCRIPTS_DATA_SOURCES = os.path.abspath(_SCRIPTS_DATA_SOURCES)

if not os.path.exists(_SCRIPTS_DATA_SOURCES):
    raise ImportError(
        f"data_sources.py migrated to scripts/data_sources.py — "
        f"but missing at {_SCRIPTS_DATA_SOURCES}"
    )

# 让 `from analysis_tools.data_sources import X` 真实工作时:
# 把 scripts/ 加到 sys.path,然后 import scripts.data_sources 当作 analysis_tools.data_sources
if os.path.dirname(_SCRIPTS_DATA_SOURCES) not in sys.path:
    sys.path.insert(0, os.path.dirname(_SCRIPTS_DATA_SOURCES))

# 全部 from-data_sources 调用 forward 到 scripts.data_sources
from scripts.data_sources import *  # noqa: F401, F403
from scripts.data_sources import (  # noqa: F401
    safe_float,
    get_prefix,
    normalize_code,
    eastmoney_datacenter,
    tencent_quote,
    sina_quote,
    ths_hot_reason,
    industry_comparison,
    _northbound_cache_path,
    hsgt_realtime,
    save_northbound_snapshot,
    load_northbound_history,
    baidu_concept_blocks,
    baidu_fund_flow_realtime,
    baidu_fund_flow_history,
    daily_dragon_tiger,
    margin_trading,
    holder_num_change,
    dividend_history,
    stock_fund_flow_120d,
    cls_telegraph,
    eastmoney_global_news,
    eastmoney_stock_info,
    cninfo_announcements,
    forward_pe,
    pe_digestion,
    calc_peg,
    get_enhanced_quotes,
    full_stock_research,
)

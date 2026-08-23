"""
scripts/_config.py — AAna 项目统一配置中心

v2026-08-23 Phase 6C:

历史:
  - KEEP_DAYS 散落在 eastmoney_portfolio.py + eastmoney_cleanup_old_groups.py + agents/cleanup.py (3 处)
  - FEISHU_USER_ID 散落在 daily_v24_recommend.py + daily_v24_sell.py + run_afterhours.py (3 处)
  - _HOLIDAY_2026 散落在 generate_report.py (1 处,主路径)
  - 各脚本硬编 cookie 路径 / 报告路径 / data 路径

策略:
  - 不引入 Pydantic (避免新依赖)
  - 用 dataclass 单点定义 + 每个脚本 import use
  - 提供 override 通过环境变量 (Phase 6C 后续)

用法:
    from _config import FEISHU_USER_ID, KEEP_DAYS, AANA_DIR, EASTMONEY_GROUPS_PATH

⚠️ 迁移规则: 新代码必须从 _config 读,不再硬编;老代码下一次触碰时改用 _config。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

# ── 路径常量 ────────────────────────────────────────────────────────────────
AANA_DIR: Final[Path] = Path(os.environ.get("AANA_DIR", Path(__file__).parent.parent)).resolve()
DATA_DIR: Final[Path] = AANA_DIR / "data"
REPORTS_DIR: Final[Path] = AANA_DIR / "reports"
STATE_DIR: Final[Path] = AANA_DIR / "state"

# 东财组合文件路径
EASTMONEY_GROUPS_PATH: Final[Path] = Path(
    os.environ.get(
        "EASTMONEY_GROUPS_PATH",
        "~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json",
    )
).expanduser()
EASTMONEY_COOKIE_PATH: Final[Path] = Path(
    os.environ.get(
        "EASTMONEY_COOKIE_PATH",
        "~/.hermes/skills/a-stock/eastmoney-portfolio-api/references/cookie.json",
    )
).expanduser()

# ── 用户身份 ────────────────────────────────────────────────────────────────
FEISHU_USER_ID: Final[str] = os.environ.get(
    "FEISHU_USER_ID",
    "ou_5d0124d26ed21365f74764fcb9fa01b7",
)

# ── 业务常量 ────────────────────────────────────────────────────────────────
KEEP_DAYS: Final[int] = int(os.environ.get("AANA_KEEP_DAYS", "3"))

AANA_PYTHON: Final[str] = os.environ.get(
    "AANA_PYTHON",
    os.path.join(AANA_DIR, ".venv", "bin", "python"),
)


@dataclass(frozen=True)
class Holidays2026:
    """2026 A 股节假日集合 — generate_report.is_trading_day() 用"""
    dates: frozenset[str] = frozenset({
        # 元旦
        "2026-01-01", "2026-01-02", "2026-01-03",
        # 春节
        "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20",
        "2026-02-21", "2026-02-22", "2026-02-23",
        # 清明
        "2026-04-04", "2026-04-05", "2026-04-06",
        # 劳动节
        "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
        # 端午
        "2026-06-19", "2026-06-20", "2026-06-21", "2026-06-22",
        # 中秋+国庆
        "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
        "2026-10-05", "2026-10-06", "2026-10-07",
    })

    def is_holiday(self, date_str: str) -> bool:
        return date_str[:10] in self.dates


# 单实例
HOLIDAYS_2026 = Holidays2026()


if __name__ == "__main__":
    # Self-test: 验证默认值 & 路径解析
    import sys
    print(f"AANA_DIR = {AANA_DIR}")
    print(f"DATA_DIR = {DATA_DIR}")
    print(f"REPORTS_DIR = {REPORTS_DIR}")
    print(f"EASTMONEY_GROUPS_PATH = {EASTMONEY_GROUPS_PATH}")
    print(f"FEISHU_USER_ID = {FEISHU_USER_ID}")
    print(f"KEEP_DAYS = {KEEP_DAYS}")
    print(f"AANA_PYTHON = {AANA_PYTHON}")
    print(f"HOLIDAYS_2026 dates (sample): {sorted(HOLIDAYS_2026.dates)[:3]}...")
    assert HOLIDAYS_2026.is_holiday("2026-06-19"), "端午 holiday"
    assert not HOLIDAYS_2026.is_holiday("2026-06-18"), "端午前一天"
    print("✅ _config self-test PASS")

# AAna Phase 4-10 整改完成清单

> **生成时间**: 2026-08-23 (周日) **Fix 版本**: Phase 4-10
> **Git commit**: 6866993 (Phase 10 策略闭环) · 48f49a0 (Phase 8 DB) · 7d0722c (Phase 9 周报)
> **关联 SKILL**: `~/.hermes/skills/a-stock/a-stock-system/SKILL.md`

---

## ✅ Phase 4-7 (基础架构, 已完成)

详见 git history (`f7184a2` Phase 1-3, `9b99c32` Phase 4-7)
- 删除死模块 -1222 行 (analysis_tools/stock_screener / valuation_calculator / daily_screen)
- 数据源单点化 (scripts/data_sources.py 36KB + shim)
- agents/ → scripts/agents/ 迁移
- safe_io + logger 基础设施
- 153 passed + 1 skipped

---

## ✅ Phase 8 — 数据库能力 (DuckDB)

**Commit**: 48f49a0

### 新增文件
| 文件 | 用途 |
|:---|:---|
| `scripts/analytics_query.py` (250 行) | 7 个 query 函数 (winrate / sector / dow / hold / trend) + CLI |
| `tests/test_analytics_query.py` (220 行) | pandas vs DuckDB A/B 交叉验证 |
| `NOTES_db_intro.md` | 设计决策 (DuckDB vs SQLite vs PostgreSQL) |
| `pyproject.toml` | + `duckdb>=1.0.0` 依赖 |

### 修复问题 (Phase 8 验证发现)
- 🔴 循环论证: 97% rec_feedback 的 score 是从 ret_1d 反推, score_band_stats 是假象
  → Phase 10 加重修 (`score_is_estimated` 标记 + 真实 score 才进统计)
- 🟡 sector 数据覆盖率仅 13.6% (历史) → FEEDBACK_FIELDS 加 sector + 双表落地
- 🟡 crosscheck 假警报 (口径不一致) → 双方都用 30 日窗口全量

---

## ✅ Phase 9 — 周报三维度 (板块/星期/持有期)

**Commit**: 7d0722c

### 新增
- `scripts/weekly_review.py` (220 行) — 4 维度 markdown 报告
- `reports/weekly_review-latest.md` — 固定名给 x-compass 拉
- `tests/test_weekly_review.py` (180 行, 9 项单测)
- Cron: 周六 09:00 自动跑 + git push

### 真实洞察 (8/23 数据)
- **T+5 胜率 41.4% > T+1 16.1%** — 当前 T+1 快卖策略过早, 可回测 T+3/T+5
- 前半程 8.6% → 后半程 15.0% (📈 改善 +6.4pp)
- 周二推荐胜率最高 (20.0%, n=15)

### x-compass 第 7 tab「📅 周报」
- Commit `c975fd1` (x-compass v3.1)
- parsers/weekly.js (170 行) + app.js renderWeekly + styles.css 条形图
- 部署: https://x-compass.pages.dev

---

## ✅ Phase 10 — 数据驱动推荐策略闭环

**Commit**: 6866993

### 新增
| 文件 | 用途 |
|:---|:---|
| `scripts/strategy_policy.py` (220 行) | rec_tuning → 当日策略参数 (阈值/黑名单/持有) |
| `tests/test_strategy_policy.py` (180 行, 13 项单测) | 安全规则全锁定 |

### 修改
- `scripts/rec_optimizer.py`:
  - `FeedbackRecord.score_is_estimated` 字段 (防循环论证)
  - `calc_score_band_stats` 跳过估算 score
  - `find_optimal_score_threshold` 加 MIN_BAND_SAMPLES=30 门槛
- `scripts/aana_afternoon_screen.py`:
  - 接 `strategy_policy.get_today_policy()`
  - 板块黑名单过滤 + 拦截数统计
  - 阈值从硬编码 65 改为动态

### 当前策略 (8/23 数据)
- 阈值 65 (真实 score 样本不足保持默认)
- 黑名单: ai_app / semi / chem / mach / elec (样本≥10 且胜率<35%)
- robot n=33 wr=36% 逃过 35% 线, **不被误杀**

---

## 🔧 Phase 11 — 深度评审修复 (本次)

**Commit**: (本次待推送)

| # | 严重度 | 问题 | 修复 |
|:-:|:---:|:---|:---|
| 1 | 🔴P0 | `eastmoney_scraper.py:70` token 硬编码进 git | 改 `os.environ.get('EASTMONEY_SEARCH_TOKEN', fallback)`,加 `import os` |
| 2 | 🔴P0 | `scripts/agents/*.py` 6 个文件 `from agents.*` (旧路径) → `main_agent` 完全无法 import | sed 批量替换 → `from scripts.agents.*` |
| 3 | 🔴P0 | `pyproject.toml` entry `main_agent:main` 但实际函数是 `run()` | 改为 `:run` (旧 aana CLI 启动就 AttributeError) |
| 4 | 🟠P1 | `tests/test_weekly_review.py` 上轮 commit 漏文件 | 重新 git add + commit |
| 5 | 🟠P1 | `scripts/eastmoney_cleanup.py` 工作区残留 D | rm (git 已删) |
| 6 | 🟡P2 | analytics_query 新 query (data_quality / weekly_trend) 无单测 | 补 4 项 (含 ISO 格式断言) |
| 7 | 🟡P2 | NOTES 文档只到 Phase 4-7 | 全面同步到 Phase 11 |
| 8 | 🟡P3 | ret 计算不对称审计 (ret_5d=822 > ret_3d=435) | 文档化 (backfill 逻辑选择性) |
| 9 | 🟡P3 | paper_trades/portfolio 数据陈旧 | 文档化 (8/14 后非交易周末触发) |

---

## 🧪 测试基线

- 修复前: 186 passed, 1 skipped
- 修复后: 190 passed (+4 analytics_query 新), 1 skipped
- 集成验证: scripts.agents.main_agent 加载成功 (P0-2 修复实证)

---

## 📝 用户手工同步项

更新 `~/.hermes/skills/a-stock/a-stock-system/SKILL.md` 时需追加:
- Phase 8/9/10/11 章节 (按本文档结构)
- scripts/strategy_policy.py 调用约定
- Cron `0 9 * * 6` AAna 每周复盘任务
- x-compass v3.1 第 7 tab「📅 周报」说明
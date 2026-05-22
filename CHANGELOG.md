# Changelog

All notable changes to AAna will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `backtest/` — 回测引擎，基于 backtrader
  - `backtest/engine.py` — BacktestEngine + ScoreSignalStrategy（将 strategies/ 评分转为买卖信号）
  - `backtest/runner.py` — 命令行回测入口，读取 recommendations.csv 按推荐日次日买入、持有N天卖出
  - `backtest/runner.py --hold 5` — 持有5天到期卖出
  - `backtest/runner.py --codes 603906 605566` — 指定股票回测
  - 支持止损（stop_loss_pct）、夏普比率、胜率统计、JSON 输出
- `data/quotes.py` — 统一行情服务（新浪→腾讯 fallback）
- `data/持久化层` — 文件持久化层（CSV append-only），统一存储推荐和追踪记录
- `data/recommendations.csv` — append-only 推荐日志
- `data/tracking.csv` — 追踪记录（次日 outcome 更新）
- `data/recommendations/` — JSON 快照兼容旧格式
- `data/summaries/` — 每日综合报告 JSON
- `migrate_from_state()` — 从 state/ 迁移历史数据
- `get_win_rate()` / `get_stock_history()` — 统一查询 API
- `aana_afternoon_screen.py` 接入 data 层

### Changed
- 尾盘推荐写入 data 层，不再写入 `state/recommendations/`

### Deprecated
- `state/recommendations/stock_stats.json` — 逐步迁移到 `data/tracking.csv`

### Fixed
- 修复 `get_win_rate()` 中 `datetime.timedelta` import 错误

## [v0.1.0] — 2026-05-01

### Added
- 盘前 Agent（07:00–09:28）：健康检测、盘前简报、竞价推送
- 盘中 Agent（09:30–14:57）：持仓异动监控
- 盘后 Agent（21:30–21:45）：复盘评分、明日策略
- 尾盘选股脚本（14:45）：综合打分 Top5
- 东方财富自选股组合同步
- Hermes cron 定时任务（盘中监控、尾盘同步、盘后战报、周末备战）
- A股智能投研助手完整投研周期

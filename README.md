# AAna — A股智能投研助手

AAna 是一个围绕 A股交易周期设计的自动化智能投研系统，覆盖**盘前 → 盘中 → 盘后 → 周末**全链路。

---

## 系统架构

```
agents/
├── main_agent.py          # 总调度，任务分发与状态管理
├── premarket_agent.py     # 盘前子Agent（07:00–09:28）
├── intraday_agent.py      # 盘中子Agent（09:30–14:57）
├── postmarket_agent.py    # 复盘子Agent（21:30–21:45）
└── cleanup.py             # 状态清理

scripts/
├── aana_afternoon_screen.py    # 尾盘选股脚本
├── eastmoney_portfolio.py      # 东方财富自选股组合同步
├── eastmoney_scraper.py        # 东方财富数据抓取
├── dynamic_stocks.py           # 动态股票池管理
└── technical_filter.py         # 技术面过滤

analysis_tools/
├── data_fetcher.py            # 多源数据获取（新浪/腾讯/东财/同花顺）
├── stock_screener.py          # 选股筛选器
├── financial_analyzer.py       # 财务分析
├── valuation_calculator.py     # 估值计算
├── recommendation_tracker.py   # 推荐追踪
└── daily_screen.py             # 每日筛选

docs/
├── stock.md                    # 股票知识库
├── stock-indicators-classification.md  # 技术指标分类
├── 选股模板.md                 # 选股报告模板
└── 复盘模板.md                 # 复盘报告模板
```

---

## 核心功能

### 盘前（07:00–09:28）
- **健康检测**：系统自检、数据源连通性
- **盘前简报**：隔夜外盘回顾、宏观要闻、大盘情绪预判
- **竞价推送**：集合竞价异动个股

### 盘中（09:30–14:57）
- **持仓异动监控**：涨跌幅突破、量比异动、均线突破/跌破、MACD金叉/死叉
- **动态持仓调整**：根据实时信号调整关注池
- **尾盘选股**：14:30 启动综合打分，输出 Top5 明日候选

### 盘后（15:30 / 21:30–21:45）
- **盘后战报**（15:30）：行业全貌、候选池命中率分析、新晋异动 Top5
- **复盘评分**（21:30）：当日策略有效性、风险控制评估
- **明日策略**（21:45）：基于当日复盘输出下一交易日操作计划

### 周末备战（周日 20:00）
- **5因子打分模型**：估值、动量、资金面、技术面、基本面
- **下周重点观察池**：5–10 只候选股
- **仓位节奏建议**：根据大盘环境给出仓位配置建议

---

## 数据源

| 数据类型 | 主数据源 | 备用数据源 |
|---|---|---|
| 实时行情 | 新浪财经 | 腾讯K线 |
| K线数据 | 腾讯财经 | 新浪财经 |
| 行业板块 | 东方财富 | 同花顺 |
| 强势股 | 同花顺 | 东财热点 |
| 财务数据 | AKShare | 东方财富 |
| 自选股组合 | 东方财富组合API | — |

---

## 东方财富组合同步

尾盘选股结果自动同步至东方财富自选股组合，命名规则：**日期+PP**（如 `20260522PP`）。

手动同步命令：
```bash
cd ~/code/AAna/scripts
python3 eastmoney_portfolio.py
```

---

## 定时任务（Cron）

| 任务 | Cron | Skill |
|---|---|---|
| 盘中异动监控 | `0 9,10,11,13,14,15 * * 1-5` | a-stock-monitor |
| 尾盘选股同步 | `45 14 * * 1-5` | — |
| 盘后战报 | `30 15 * * 1-5` | a-stock-afterhours |
| 周末备战 | `0 20 * * 0` | a-stock-weekend |

---

## 目录结构

```
AAna/
├── agents/            # Agent 核心逻辑
├── analysis_tools/    # 数据分析与工具
├── scripts/           # 可执行脚本
├── docs/             # 知识库与模板
├── reports/          # 每日报告输出（自动生成）
│   └── YYYY-MM-DD/
│       ├── 选股报告.md
│       ├── 复盘评分.md
│       └── 明日策略.md
├── state/            # 状态与推荐追踪
└── prompts/          # Agent 提示词模板
```

---

## 快速开始

```bash
# 安装依赖
pip install akshare pandas requests

# 运行盘前
python agents/premarket_agent.py

# 运行尾盘选股
python scripts/aana_afternoon_screen.py

# 运行复盘
python agents/postmarket_agent.py
```

---

## 技术栈

- **语言**：Python 3.9+
- **数据获取**：AKShare、requests、pandas
- **定时任务**：cron + Hermes Agent
- **报告输出**：Markdown
- **版本管理**：Git + GitHub

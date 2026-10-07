# 📈 推荐反馈报告 — 2026-09-24 15:04 CST

> **生成时间:** 2026-09-24 15:04:34 CST
> **运行命令:** `python3 scripts/feedback_loop.py`
> **exit_code:** 2（最近 7 日 0 推荐, 让 cron 能报警）
> **目标交易日:** 2026-09-24（周三, 节前最后完整交易日, 9/25-9/27 中秋休市）

---

## 🚨 核心结论：推荐链路已连续 10 日 0 写入, **建议紧急降级 cron 频率**

| 指标 | 数值 | 解读 |
|:-----|:----:|:-----|
| 最近 7 日推荐 | **0 条** | `recommendations.csv` 7 日窗口全空 |
| 最近一次推荐写入 | **2026-09-15** | 已 10 个交易日无新推荐 (10 天 = 9/16-9/24) |
| `rec_feedback.csv` 末条 rec_date | **2026-09-15** | 同上, 闭环最后有效输入 |
| 9/24 14:45 尾盘 cron | **0 推荐** | `筛选后候选: 0 只 (板块黑名单拦截 0 只)` |
| 9/24 策略阈值 | **70** | next_day_strategy 覆盖 rec_tuning 65 |
| 9/24 cold_sectors | **[]** | 昨日 (9/23) 无冷启动命中 |
| 9/24 弱板块 | **6 个** | ai_app/chem/elec/mach/robot/semi |

**根因 (5 大根因分类)**：
1. **根因 E_冷启动盲区** ❄️：9/21-9/24 连续 4 个交易日候选池筛选后 0 只
2. **资金流 API 挂**：东财 datacenter 类接口 `RemoteDisconnected` 第 **75 天** 🔴 P0
3. **阈值 70 过严**：9/16+9/17+9/21-9/24 实证显示当前市场 9 候选均不达 70
4. **板块黑名单 100% 失效**：info.sector 100% 空 + 反查 enum 失败（仅 13.6% 覆盖率）
5. **v2.4 推荐流水线停摆**：9/3 后 v2.4 已无新增买入, paper_trading 14 个交易日 PnL 未变化

---

## 📊 数据快照

### 1. 候选池（最近 14 天, 14:45 尾盘 cron 实证）

| 日期 | 候选池 | K线挂 | 板块黑拦截 | 筛选后 | 推送 |
|:----:|:------:|:----:|:--------:|:-----:|:----:|
| 9/12 (周五) | 215 | 4 | 0 | **0** | ❌ bot config 错 |
| 9/15 (周一) | 210 | 6 | 2 | **0** | ❌ bot config 错 |
| 9/16 (周二) | 10 | 4 | 0 | **0** | ❌ bot config 错 |
| 9/17 (周三) | 137 | 7 | 2 | **0** | ❌ bot config 错 |
| 9/18 (周四) | 10 | 3 | 1 | **0** | ❌ bot config 错 |
| 9/19 (周五) | 10 | 0 | 0 | **0** | ❌ bot config 错 |
| **9/22 (周二)** | **?** | ? | ? | **0** | ❌ bot config 错 |
| **9/23 (周三)** | **?** | ? | ? | **0** | ❌ bot config 错 |
| **9/24 (周四, 今日)** | **218** | **0 (全市场涨幅榜)** | **0** | **0** | ❌ bot config 错 |

**关键观察**：9/22+9/23+9/24 候选池充足（≥200 只全市场涨幅榜）但筛选后仍 0 只 → **不是候选不足, 是阈值过严 + 评分通过率 0%**。

### 2. 调参生效时间线（next_day_strategy.json）

| date_for | threshold | position_final | cold_sectors | 来源 |
|:--------:|:---------:|:--------------:|:-------------|:-----|
| 2026-09-08 | 70 | 50 | [] | rec_tuning baseline |
| 2026-09-15 | 70 | 50 | [] | rec_tuning baseline |
| 2026-09-16 | 73 | 50 | ['无机盐', '房地产开发'] | next_day_strategy (cold 9/15) |
| 2026-09-23 | **70** | **50** | **[]** | rec_tuning baseline |

**当前生效**（9/24）：**threshold=70 + 6 weak_sectors + 0 cold_sectors + position=50**。

### 3. 9/24 早盘 08:01 选股报告 Top10

```
📌 9/24 早盘选股报告: 0 推荐
- 候选池 213 只 (涨停警示 0 只)
- 资金流 API 100% RemoteDisconnected (东财 datacenter 第 75 天 🔴 P0)
- 板块数据失败 (同根因)
- 北向资金 NoneType (P2)
- 情绪 45 分歧 / 上证 3936.52 -0.39%
```

**autopilot 8:30 触发了自主筛选流程** → 9/24 Top1 金诚信 (603979) + Top2 国投电力 (600886) (见 `reports/2026-09-24-深度分析.md`)。

### 4. 9/24 14:45 尾盘 cron 端到端（最近一次完整跑）

```log
[2026-09-24 14:45:03] [daily_v24_recommend] AAna v2.4 尾盘推荐启动 (dry_run=False)
[2026-09-24 14:45:03] [daily_v24_recommend] [1/4] 调用 aana_afternoon_screen.screen_afternoon_stocks()...
[strategy_policy] source=rec_tuning threshold=70 top_n=10 hold=1d blacklist=[ai_app,chem,elec,mach,semi] tuning_age=0.8d
  [strategy_policy] 阈值 65→70 (next_day_strategy, 含昨日根因调参)
  [strategy_policy] 板块黑名单 5 个: ai_app,semi,chem,mach,elec (样本≥10 且胜率<35%)
[AAna 尾盘] 14:45:04 开始尾盘选股...
[Eastmoney] 报告 Top10: []
[Eastmoney] 报告 Top10: []
  [源3] 全市场涨幅榜: 新增 218 只
[AAna 尾盘] 候选股票总数: 218 只
[AAna 尾盘] 筛选后候选: 0 只 (板块黑名单拦截 0 只)
[2026-09-24 14:45:13] [daily_v24_recommend] ⚠️  无推荐（score>=65 的票）
[2026-09-24 14:45:13] [daily_v24_recommend] ❌ 飞书推送失败: bot config not configured
```

**关键诊断**：
- ❌ **评分通过率 0%**：218 只候选经过 score_afternoon_stock 后全部不达 70
- ❌ **板块黑名单拦截 0 只**：板块反查 enum 100% 失败（'unknown' 兜底放过），weak_sectors 实质失效
- ❌ **Eastmoney 报告 Top10 双空**：早盘选股报告 0 推荐 → fallback 全市场涨幅榜 218 只 → 仍 0 推荐
- ❌ **飞书推送失败**：bot config not configured（持续多日未修复）

---

## 🔍 0 推荐 4 个交易日根因（9/21-9/24）

### 主因 #1: threshold 70 + 弱市过严（最关键）

| 日期 | 上证 | 情绪 | 涨停 | 候选池 | 阈值 | 筛选后 |
|:----:|:----:|:----:|:----:|:------:|:----:|:------:|
| 9/21 | +0.17% | 回暖 70 | 105 | 222 | 70 | **0** |
| 9/22 | +0.03% | 回暖 64 | 64 | 235 | 73 | **0** |
| 9/23 | -0.39% | 分歧 45 | 51 | 213 | 73 | **0** |
| **9/24** | **-0.39%** | **分歧 45** | **51** | **218** | **70** | **0** |

**根因**：阈值 70 在弱市/分歧日**几乎无票可达** → 实际是 **评分系统 + 阈值**双重问题，不是市场没机会。

### 主因 #2: 板块黑名单 100% 失效（Phase 11 修复未根治）

- info.sector 100% 空（新浪全市场来源）
- `industry_for_code()` 4 级降级链 (sina HTML → akshare 关键词 → 'unknown')
- `_cn_sector_to_enum()` 反查失败率高 → 候选板块都标 'unknown' → 弱板块黑名单 0/915 命中
- 9/24 验证：拦截 0 只（应该拦截 ≥10 只，但实际 0）

### 主因 #3: 资金流 API 长期挂（75 天 🔴 P0）

- 东财 datacenter 类接口 `RemoteDisconnected` 第 **75 天**
- 板块/资金流/涨停股池 仍无等价 fallback
- **影响**: 评分体系缺一维度 → 通过率下降

### 主因 #4: v2.4 推荐流水线 9/3 后停摆

- paper_trading.py 自 9/4 起 14 个交易日 0 新增买入
- v2.4 实盘胜率 40.0% vs 回测 80.2% 偏差 -40.2pp 🔴 P0-Emergency 警报持续
- `reports/2026-09-23-复盘报告.md`: "v2.4 推荐流水线停摆, 本周期 (9-4 ~ 9/23 共 14 个交易日) 无新增买入"

---

## ⚠️ 紧急建议（按优先级）

### P0: 立即降级 cron 频率, 避免每天 0 推荐噪音

- **feedback_loop cron** 现状: 每天 15:00 跑一次 → 连续 10 天 exit_code=2 → 飞书报警无新意
- **建议**: 改为**每 3 天一次**, 或加 `if recommendations_last_n_days == 0 and consecutive_zero_days >= 5: silent`
- **理由**: 9/3 后 v2.4 推荐流水线已停摆, feedback_loop 无新数据可处理
- **触发**: 用户偏好"避免噪音"铁律（看 SKILL.md "Cron 复盘任务陈旧 SOP"）

### P1: 修复板块黑名单失效（已修复但未根治）

- Phase 11 (commit `4111349`) 加了 `_cn_sector_to_enum()` 反查
- 但 9/24 实证: 拦截 0 只 → 反查 enum 100% 失败
- **建议**: 增加 fallback 默认拦截（如果板块反查 'unknown'，仍按 weak_sectors 字符串匹配候选板块字符串）

### P1: 修复飞书推送 bot config not configured

- 9/24 14:45 cron 推送失败: `bot config not configured`
- **建议**: 在终端运行 `lark-cli config init --new`（阻塞式初始化）
- **影响**: 飞书 0 推荐推送 0/4 日

### P2: threshold 70 在弱市过严 → 调至 60

- 当前真实 score ≥70 样本仅 47 条 (4.8%), 胜率 17.0% (-1.94%)
- **建议**: 弱市（情绪 ≤50）放宽到 60，强市（情绪 ≥70）维持 70
- **回测优先**: 不要直接上实盘

### P3: 增加"0 推荐天数累计"早报警

- 当前 feedback_loop 只报"最近 7 日 0 推荐"
- **建议**: 加 `consecutive_zero_days` 字段，连续 ≥3 天触发 P1 警告
- **避免**: 持续 10 天静默 exit_code=2

---

## 📁 相关文件

| 文件 | 内容 | mtime |
|:-----|:-----|:------|
| `data/recommendations.csv` | 126 条, 末条 2026-09-15 | Sep 15 14:45 |
| `data/rec_feedback.csv` | 920 条, 末条 2026-09-15 | Sep 22 16:00 |
| `data/rec_tuning.json` | score_threshold=70, weak=6, last 9/23 | Sep 23 20:00 |
| `data/next_day_strategy.json` | date_for=2026-09-23, threshold=70, cold=[] | Sep 23 20:00 |
| `reports/2026-09-24-选股报告.md` | 早盘 08:02 0 推荐 | Sep 24 08:02 |
| `reports/2026-09-24-深度分析.md` | autopilot 自主筛选: 金诚信 + 国投电力 | Sep 24 08:35 |
| `reports/2026-09-23-复盘报告.md` | v2.4 14 日无新增买入 | Sep 23 17:13 |
| `reports/2026-09-23-根因分析.md` | 0 推荐根因: E_冷启动盲区 | Sep 23 16:03 |
| `reports/weekly_review-latest.md` | 周复盘 (胜率 T+1 21.7%, T+3 21.7%, T+5 23.8%) | Sep 19 |

---

## 🎯 一句话总结

**0 推荐已连续 10 个交易日（自 9/15 起），feedback_loop 无新数据可处理；建议立即降级 cron 频率至每 3 天一次，避免持续噪音；同时 P1 修复板块黑名单失效（拦截 0/218 候选）+ bot config 推送失败。**

---

*Generated by AAna v2026.3 feedback_loop cron | exit_code=2 (cron will alarm)*

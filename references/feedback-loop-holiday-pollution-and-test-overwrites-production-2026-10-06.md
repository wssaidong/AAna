# 2026-10-06 feedback_loop cron 实战 — 国庆假期数据污染 + 测试覆写生产数据双 P0

> 生成时间: 2026-10-06 15:40 CST | 触发: 每日 feedback_loop cron

## 一、事件链 (两个 P0 串联)

### P0-A: 国庆假期日 (10/02) 误写入 11 条推荐污染

**发现路径**: feedback_loop cron 输出 "最近7日推荐: 10 条" + rec_tuning 出现 `60-70` band 0/11 0% 胜率伪统计。

**证据链**:
1. `_HOLIDAY_2026` (scripts/_config.py:82-83) 明确 10-01~10-07 国庆假期
2. 腾讯 ifzq 日K 确认上证最后交易日 = 2026-09-30 (10/01-10/06 无任何交易日)
3. 10/02 08:01-08:02 写入 recommendations.csv 11 条 + rec_feedback.csv 11 条
   (含 1 条空 code 幽灵行: `2026-10-02 08:01:21,,,2026-10-02,...`)
4. 报告 `reports/2026-10-02-尾盘选股.md` 引用 9/30 收盘数据 + 自认 "热点: ⚠️获取失败(fallback_empty)" — 数据源失败仍落推荐
5. ret_1d 全空 → rec_optimizer v2 分支 `actual_change = float(ret_1d_raw) if ret_1d_raw else 0.0` → 全计亏损

**污染量化**:
- rec_tuning: total 920→931 (+11), score_band 出现假 `60-70: 0/11 0%`
- weak_sectors 多出 `汽车零部件` (n=3, 不足样本门槛, 纯污染伪影)
- overall_win_rate 28.80%→28.46%

**清理**: 删 11+11 条 (备份 `*.bak.pre_holiday_clean`), rec_optimizer 重算 → 920 条, 28.80%, `60-70` 假 band 消失, weak_sectors 恢复 6 板块。

### P0-B: test_phase12_root_cause.py 覆写生产 rec_tuning.json

**发现路径**: 清理后重跑 rec_optimizer, 发现磁盘 rec_tuning.json 只剩 3 键 (`recommended_score_threshold/weak_sectors/sector_stats`), `generated_at`/`score_band_stats`/`hold_days_stats` 全丢 → `test_get_tuning_config_reads_json` 失败 (`len(cfg.generated_at) >= 10` → 0)。

**根因** (scripts/test_phase12_root_cause.py:197-200):
```python
data_dir = Path("/Users/cai/Code/AAna/data")   # ⚠️ 大写 Code + 绝对路径
(data_dir / "rec_tuning.json").write_text(json.dumps(test_tuning, ...))  # mock 3 键!
```
- macOS 文件系统**大小写不敏感** → `/Users/cai/Code` 与 `/Users/cai/code` 同一目录 (inode 实测相同: 15958480)
- **无恢复逻辑** (无 finally/备份/还原) → 测试跑完生产 rec_tuning.json 永久变 3 键 mock
- 该测试脚本在 SKILL.md 被标注 "改前必跑 37/37 PASS" — 但它本身就是生产数据污染源

**恢复**: git checkout + rec_optimizer → daily_root_cause 9/30 → auto_tune_next_day 全链重算。

## 二、修复落地 (3 commits, 已 push)

| commit | 内容 |
|:-------|:-----|
| `34b90fa` | 清理 11+11 条假期污染 + rec_tuning 重算 |
| `b0b3cb2` | ① `aana_afternoon_screen.py main()` 加假期守卫 (非交易日 return [] 不写推荐) ② 数据恢复 + daily_root_cause 刷新至 9/30 |
| `d4b5712` | `test_basic_returns_ok` 改 tmp_path mock 隔离 (不再依赖生产 CSV 近 7 日有数据) |

**假期守卫代码** (aana_afternoon_screen.py main() 入口):
```python
from generate_report import is_trading_day
is_trade, non_trade_reason = is_trading_day()
if not is_trade:
    print(f"[AAna 尾盘] 📅 今日非交易日 ({non_trade_reason}), 跳过选股, 不写任何推荐/反馈")
    return []
```

**最终验证**: pytest 208 passed / 1 skipped; pytest 后 rec_tuning.json keys=10 未被污染 (因 pytest 不跑 scripts/test_phase12*.py)。

## 三、通用教训 (写进 SKILL.md 候选)

1. **测试脚本写生产数据路径 = 定时炸弹**: mock 数据必须 `tmp_path`/tempfile, 绝对路径写 `data/` 即使"大小写不同"也不行 (macOS/Windows 大小写不敏感)。**测试结束必须恢复原文件** (finally + 备份)。
2. **假期守卫必须在 main() 入口第一行**, 不是 cron prompt 层职责 (cron prompt 会漂移, 9/1 沉淀的第 2 层污染源同理)。generate_report.py 有守卫 (L688) 但 aana_afternoon_screen.py 没有 — 兄弟脚本守卫不对齐。
3. **空 ret_1d 被当 0 计亏损** (rec_optimizer v2 分支 `else 0.0`): 全表 234 条空 ret 记录全按 0% 计 → 整体胜率被系统性低估。正确做法: 空 ret 记录跳过统计 (sample 不够就不够, 不要造数据)。本次未修 (P1 待办)。
4. **数据污染核查三角**: cron 输出异常统计 → 查原始 CSV 当日记录 → 对照权威日历/行情源 (腾讯 ifzq) 验证当日是否交易日。
5. **"测试 vs 生产基线漂移"再添一例**: test_basic_returns_ok 断言 `n>0` 依赖生产 CSV 近 7 日有推荐 — 假期/0 推荐期必挂。SKILL 审计方法论 (c) "测试断言避免硬编码历史快照" 的动态化不够, 还要**数据源 mock 隔离**。

## 四、遗留待办

| 优先级 | 事项 |
|:------|:-----|
| P1 | test_phase12_root_cause.py 的 tmp 隔离修复 (本次只清了数据污染, 测试本身还会再写生产文件!) |
| P1 | rec_optimizer 空 ret_1d 跳过统计 (234 条被当 0% 计) |
| P2 | 同类守卫排查: daily_v24_recommend.py / run_afterhours.py 等兄弟脚本是否缺 is_trading_day 守卫 |
| P2 | `data/rec_feedback.csv.bak.pre_holiday_clean` 等 3 个 .bak 留在磁盘 (git 未跟踪, 建议观察 1 周后删) |

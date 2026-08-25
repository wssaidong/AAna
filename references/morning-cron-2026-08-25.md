# 2026-08-25 早盘 cron 实战

**事件**：早盘 cron 端到端实战 — 情绪 **30 冰点** + 上证 **-0.59%** (4 大指数均跌) / 涨停 48 / 跌停 5 / 大盘均涨跌 **-1.78%** / 建议仓位 **10%** / **停止交易** / 🆕 **冰点日 Top<10 不凑数 SOP 第 5 次实战** (候选仅 2 只 603876/601088, 不凑数) + 4 信号 SOP 第 18 次实战 (样本不足 4 信号仅参考) + 价格印证 Top2 **2/2 0 差异** + 东财 `gid=1416` 含 **2/2** + 飞书推送 `om_x100b67f98e8860b0b145b2179361f31` 落地验证 + git commit `8a020eb` 已 push。

## ⏱ 时间线

| 步骤 | 时间 | 详情 |
|:----:|:----:|:----|
| 报告生成 | 08:02:13 | generate_report.py 跑通, 涨停 48 / 跌停 5 / 上证 -0.59% / 4 大指数均跌 / 情绪 30 冰点 / 建议仓位 10% |
| Cookie 加载 | 08:03:xx | ✅ load_cookie() OK |
| groups.json 预检 | 08:03:xx | ✅ 6 条含今日 (20260825), cutoff=20260818, 待删 0 |
| get_or_create_group | 08:03:xx | ✅ `20260825` → gid=1416 |
| add_stocks | 08:03:xx | ✅ add_stocks(gid=1416, codes=[603876, 601088]) |
| gstkinfos 验证 | 08:03:xx | ✅ 服务端含 2 只 [601088, 603876] |
| groups.json 写回 | 08:03:xx | ✅ 双 SOP (备份+位置参数+写后校验+gstkinfos 真实 codes) — 6 条 (含今日) |
| Cleanup | 08:03:xx | cutoff=20260818, 待删 0 (连续运行) |
| 价格印证 | 08:03:xx | ✅ 2/2 0 差异 (腾讯 qt.gtimg.cn GBK 解码 8/21 SOP) |
| 飞书推送 | 08:04:20 | message_id `om_x100b67f98e8860b0b145b2179361f31` (bot, msg_type=post) |
| mget 验证落地 | 08:04:xx | ✅ `--message-ids` 复数 flag OK |
| git commit | 08:04:xx | `8a020eb` 已 push main |

## 决策依据

### 冰点日 Top<10 不凑数 SOP 触发

**5 次实战时间线**：

| 日期 | 情绪 | 候选数 | 大盘 | 决策 | 结果 |
|:----:|:----:|:----:|:----:|:----:|:----:|
| 7/14 | 冰点 | 9 | 暴跌 | 不凑数 | ✅ Top9 |
| 7/23 | 冰点 | 7 | 暴跌 | 不凑数 | ✅ Top7 (zombie 第 12 次) |
| 7/29 | 冰点 | 5 | 暴跌 | 不凑数 | ✅ Top5 (zombie 第 14 次) |
| 8/20 | 20 | 5 | -4.14% | 不凑数 | ✅ gid=1361 5/5 |
| **8/25** | **30** | **2** | **-1.78%** | **不凑数** | **✅ gid=1416 2/2** |

8/25 是 SOP 第 5 次实战 — 与 7-14/7-23/7-29/8-20 同模式,**候选不足 10 不强凑**。

### 价格印证 2/2 0 差异

| 代码 | 报告价 | 腾讯 parts[3] | 报告涨幅 | 腾讯 parts[32]/100 |
|:----:|:----:|:----:|:----:|:----:|
| 603876 | ¥23.22 | 23.22 | +1.09% | +1.09% |
| 601088 | ¥46.89 | 46.89 | +1.03% | +1.03% |

差异均为 0 → 价格印证通过(但**不构成跟单建议**,情绪 30 + 建议仓位 10% + 停止交易)。

### 4 信号 SOP 第 18 次实战 — 样本不足仅参考

| # | 信号 | 状态 | 判定 |
|:-:|:----|:----:|:----:|
| 1 | 涨跌幅窄区间 | ⚠️ 仅 2 只 +1.03~+1.09% | 样本不足, 仅参考 |
| 2 | 技术分重复 | ⚠️ Top2 全 78 | 冰点日样本 2, 仅参考 |
| 3 | 信号文字重复 | ⚠️ 全 MA多头MACD金叉 | 冰点日样本 2, 仅参考 |
| 4 | 指数显示 | ❌ 4 大指数均正常 | 放行 |

### 用户决策建议

**不跟单** — 情绪 30 冰点 + 4 大指数普跌 -1.78% + 建议仓位 10% + 停止交易 → 候选仅 2 只推荐记录同步,不构成跟单建议 → **用户应暂停加仓, 等待大盘企稳信号 (建议仓位 10% 仅防守性配置)**。

## 关键沉淀

### 🆕 冰点日 Top<10 不凑数 SOP 第 5 次实战 (2026-08-25 验证)

- **5 次实证** (7-14/7-23/7-29/8-20/**8-25**): 情绪 ≤ 30 + 候选 < 10 → **不强凑**, 实际候选数 (9/7/5/5/**2**) 完全合规
- 飞书推送表格里**写实际有几只** (8/25: **2/2** 而非虚标 10/10)
- groups.json 同步**只 add_stocks 实际候选数** (8/25: **2/2**)
- 4 信号 SOP 仍执行但**样本不足仅参考** (信号 1/2/3 因 2 只样本失效)
- 与"数据脏阻断"区分: 冰点日 K线正常, 候选池正常运行但评分过滤掉; 数据脏阻断 K线 RemoteDisconnected

### 🆕 `add_stocks` 返回 `int` 而非 dict 边界 — 8/25 第一次踩到

**事件**: 8/25 execute_code 调 `ep.add_stocks(gid, codes)` → 返回 `int` (add 成功个数), 不是 `{'added': 0, 'skipped': 0}` dict → `int.get('added',0)` 抛 AttributeError。

**根因**:
- `eastmoney_portfolio.add_stocks()` 的返回值是**统计成功调用次数的 int** (如 `2`), 不是 dict
- 之前调用都没取返回值, **8/25 是第一次尝试 `add_result.get('added',0)`**

**修正**:
```python
# ❌ 错 (8/25 第一次踩)
add_result = ep.add_stocks(gid, codes)
print(f"add_stocks 结果: added={add_result.get('added',0)}")  # AttributeError

# ✅ 对 (8/25 修正)
print(f"add_stocks 调用成功: {add_result} (返回值是成功个数 int)")  # → 2
```

**触发场景**: 任何想要"获取 add_stocks 详细结果 (added/skipped/failed)" 的脚本 → **目前 add_stocks 不返回详细 result**, 只返回 int。

**未来 P1 待修**: `eastmoney_portfolio.add_stocks()` 应返回 `{'added': [...], 'skipped': [...], 'failed': [...]}` dict, 与 `cleanup()` 风格统一。但目前**不是阻塞性**, 因为已经有 `gstkinfos` 验证兜底 (8/25: 服务端 2/2 = 实际候选)。

### 🆕 lark-cli 推送落地 mget 验证完整实战 (8/25 第 X 次, 累计 +1)

**事件**: 飞书推送成功后, 用 `lark-cli im +messages-mget --message-ids "om_xxx"` 验证落地 → 拿到完整 content (markdown → post 类型自动渲染), 字段 `create_time`, `chat_id`, `sender.id_type=app_id` 都完整。

**关键细节**:
- 推送时 `lark-cli im +messages-send --markdown` → 服务端实际存储为 **`msg_type=post`** (飞书富文本), **不是 markdown**
- mget 返回的 `data.messages[0].content` 是字符串, 不是嵌套 `body.content`(8/24 沉淀)
- 落地验证后 fields: `message_id`, `chat_id`, `create_time`, `deleted=false`, `updated=false`, `sender={id, id_type, sender_type, tenant_key}`

**8/25 实战结果**: ✅ 飞书消息落地验证 OK, msg_type=post, sender=app bot (id_type=app_id, sender_type=app)

### 稳定运行项 (与 8/24 同保持)

- ✅ **groups.json 写回双 SOP 实战** (8/7 + 8/13 集成: 备份+try/except+位置参数+写后校验+gstkinfos 真实 codes)
- ✅ **`get_or_create_group()` 实战无 hang** (连续 8 天无 hang: 8/13+8/14+8/17+8/18+8/20+8/21+8/24+**8/25** → P1 累计 +8 样本稳定)
- ✅ **lark-cli `--message-ids` 复数 flag** (8/14+8/17+8/18+8/20+8/21+8/24+**8/25** 累计 7 次实战无崩)
- ✅ **lark-cli `--user-id` 推 P2P** (8/18+8/20+8/21+8/24+**8/25** 累计 5 次实战)
- ✅ **价格印证 GBK 解码** (8/21 沉淀, 8/24+**8/25** 累计 3 次实战)
- ✅ **冰点日 Top<10 不凑数 SOP** (5 次实战, 7-14/7-23/7-29/8-20/**8-25**)
- ✅ **4 信号 SOP** (18 次实战, **8/25 第 18 次样本不足仅参考**)

## 🆕 稳定性事件累计 (8/25 第 70 天)

| 事件 | 起始 | 持续 | 优先级 | 状态 |
|:----|:----:|:----:|:----:|:--|
| 东财 datacenter 类接口 RemoteDisconnected | 6/12 | **70 天** | 🔴 P0 | 涨跌停同花顺接管 |
| groups.json 缓存污染 (zombie 模式) | 6/11 | **70 天 (19 次实战)** | 🔴 P0 | ✅ SOP 完全稳定 |
| baostock 慢路径 50+ login/logout | 6/17 | 69 天 | 🔴 P0 | ✅ 7/8 修 |
| 北向资金 NoneType 无 sanity check | 7/10 | **37 天** | P2 | ❌ 待修 |
| v2.4 实盘胜率 ~38-43% vs 回测 80.2% 背离 | 6/30 | **38 天** | 🔴 P0-Emergency | 8/23 三口径透明化 + Phase 10 闭环上线 |
| 14:45 盘中 → 15:00 收盘 时点差 > 2pp | 7/7+...+8/25 | **30+ 天** | 🔴 P0 | ❌ 未修 |
| `sync_top10_v9.py` 60s timeout 但内部成功 | 7/27+...+8/25 | **9 次同现象** | 🔴 P0 | ❌ 不能在 cron wrapper 依赖返回值 |
| 涨价热点主线 stale data "数据获取中" | 6/12+...+**8/25** | **75 天 (11 次)** | 🔴 P0 | ❌ 板块 fallback → stale 4 月 |
| **`get_or_create_group()` 手工调用无 hang** | 8/13+8/14+8/17+8/18+8/20+8/21+8/24+**8/25** | 连续 8 天 | P1 趋于稳定 | ✅ P1 缓解 |
| **`api_call` tuple 返回值解构** | 8/14+8/17+...+**8/25** | 7 次实战 | P1 | ✅ 已解构 `r, _ = api_call(url)` 缓解 |
| **`lark-cli im +messages-mget` 必须用 `--message-ids` 复数** | 8/14+...+**8/25** | 7 次实战 | P2 | ✅ 已成默认 |
| **`lark-cli im +messages-send` 必须用 `--user-id`** | 8/18+...+**8/25** | 5 次实战 | P2 | ✅ P2P 推送落地 |
| **腾讯 qt.gtimg.cn GBK 编码** | 8/21+8/24+**8/25** | 3 次实战 | P1 | ✅ `raw_bytes.decode('gbk')` 缓解 |
| **🆕 冰点日 Top<10 不凑数 SOP** | 7-14+7-23+7-29+8-20+**8-25** | **5 次实战** | ✅ P2 | ✅ 候选不足 10 不强凑 |
| **`sync_portfolio_to_eastmoney([])` cleanup 用空 stocks 覆盖今日条目** | 8/13 | ⚠️ P1 | ✅ 立即加 SOP + 根因修复待做 |
| **cleanup 只看 groups.json 漏服务端孤儿组合** | 8/13+8/14 | P0 第 1/2 次 | ✅ 修复 SOP 验证 |
| **🆕 `add_stocks()` 返回 int 不返回 dict** | **8/25** | **第 1 次** P3 | ⚠️ 边界踩坑, 修正后 OK; 根因待修 (返回详细 dict) |
| **🔴 `aana_afternoon_screen.py` 末尾自动同步走错路径** | 7/1+7/14+8/18 | **3 次** P0 | ❌ 仍未修 |

## 总结

8/25 早盘 cron 端到端实战 OK,**冰点日 Top<10 不凑数 SOP 第 5 次实证**。核心决策: 候选仅 2 只不强凑, 飞书推送照常发出 (作为记录), 不构成交易建议。用户应**暂停加仓, 等待大盘企稳信号** (建议仓位 10% 仅防守性配置)。完整执行: ✅ 报告生成 → ✅ 候选提取 → ✅ 东财同步 (gid=1416) → ✅ gstkinfos 验证 2/2 → ✅ groups.json 写回 → ✅ 价格印证 0 差异 → ✅ 飞书推送落地 → ✅ git commit 8a020eb push。

**完整数据** + `om_x100b67f98e8860b0b145b2179361f31` 飞书 message_id + gid=1416 + git commit `8a020eb`。

# Sequoia-X 吸收笔记（NOTES_sequoia_x_absorption）

> 逐阶段记录：吸收了什么 / 借鉴 Sequoia-X 哪个文件哪几行 / 没吸收什么及原因 / 真实耗时或行数对比。
> 参考仓库：`/Users/cai/code/Sequoia-X`（无 LICENSE 文件 → 只借鉴设计，未复制任何代码）。
> 主任务：XWI-79。

## P0-1 本地日线库 market_store + 增量同步 + 复权口径显式化（XWI-80, S1/5）

**交付**：`data/market_store.py`（SQLite 本地日线库）+ `data/quotes.py` kline() store 优先改造 + `tests/test_market_store.py`（24 用例）+ `tests/conftest.py`（全局临时库隔离）。

### 吸收了什么（借鉴点 → Sequoia-X 源位置）

| 吸收点 | Sequoia-X 位置 | AAna 落地 |
|---|---|---|
| `stock_daily` 表 `UNIQUE(symbol,date)` + `idx_symbol_date` 索引 | `sequoia_x/data/engine.py:14-31` | `data/market_store.py` `_CREATE_TABLE_SQL`；UNIQUE 扩为 `(symbol,date,adjust)`（见下） |
| 写入前按日期先 DELETE 再 append（幂等重跑安全） | `engine.py:149-153`（按 date 全局 DELETE） | `save_bars()` 按 `(symbol, adjust, date)` 精细 DELETE——多口径、多股票互不误删（Sequoia-X 口径单一故可全局删，AAna 不行） |
| 已入库自动 skip，断点续传 | `engine.py:191-197`（`_get_last_date` 比较） | `symbols_with_bar(date, adjust)` 集合差集，skip 判定发生在任何网络请求之前 |
| 单只失败指数退避重试 | `engine.py:219-253`（`2 ** (attempt + 1)` 秒退避） | `sync_day()` 内 `1.0 * 2**attempt`（1s/2s/4s），单测锁定退避序列 |
| 批量同步 worker 复用会话，不是每只股票建一次 | `engine.py:34-53`（每 worker 一次 baostock login 批量拉） | ThreadPoolExecutor 共享同一个 `QuoteService` 实例（无状态、线程安全），网络层在线程池、写库统一回主线程（无 SQLite 跨线程锁冲突） |
| CLI 增量入口 | `main.py` argparse（日常增量 / --backfill） | `python -m data.market_store --sync --date YYYY-MM-DD --stats` |

### AAna 侧的新增（Sequoia-X 没有的，本阶段核心价值）

1. **复权口径显式化**：`adjust`（qfq/hfq/raw）进表结构、进 UNIQUE、进所有查询 API。Sequoia-X 是单一 hfq 口径无此问题；AAna 的数据源链路（腾讯 qfq / 新浪 raw / 腾讯 NOAJ 降级 raw）天然多口径，002178 3.73pp 假跌幅事故（`data/quotes.py` kline docstring）就是混用造成。落地规则：
   - 分行存储：同 `(symbol,date)` 的 qfq 与 raw 是两行，互不覆盖；
   - 如实标注：新浪 fallback 与 NOAJ 降级拿到的数据一律按 raw 入库，绝不伪装 qfq；
   - 宁缺毋滥：`sync_day --adjust qfq` 拿到 raw（降级）→ 计 missing 不入库；`kline()` 缓存不足 count 根 → 返回空走网络，不返回截断序列。
2. **当日未收盘 bar 不回写**：`kline()` 盘中回写过滤当日 bar（盘中快照脏），收盘后 `--sync` 幂等覆盖为最终值（DELETE 再 INSERT）。
3. **默认关注池**：`groups.json` 最新组 ∪ `rec_feedback.csv` 近 14 天 ∪ `recommendations.csv` 近 7 天，无需显式传 symbols。
4. **store 故障不拖垮行情**：`kline()` 里 store 读写全部 try/except 吞掉，`AANA_MARKET_STORE_DB=off` 可一键禁用（逃生门）。

### 没吸收什么及原因

| Sequoia-X 做法 | 不吸收原因 |
|---|---|
| baostock 作为数据源（engine.py 全文） | AAna 已弃用 baostock（`scripts/generate_report.py:193` 记录 50 只 50 次 login/logout 慢路径 5+ 分钟）；学的是它的架构（本地库+增量+断点续传），数据源仍走 AAna 腾讯/新浪链路 |
| `multiprocessing.Pool` 多进程 | AAna 同步走 HTTP（requests 线程安全 + 连接池），GIL 下网络 IO 线程池等价且更轻；baostock 那种重 login 会话才需要进程隔离 |
| 后复权 hfq 口径（`adjustflag="1"`） | AAna 主链路统一 qfq（与现有 `kline()` 默认、backtest、feedback_loop 一致），口径切换成本远大于收益；hfq 作为可查口径保留 |
| `pandas.DataFrame` 中转 + `df.to_sql` | 单日增量每只 1 行，原生 sqlite3 executemany 足够，省一个 DataFrame 序列化层 |
| 每 200 只重连（`reconnect_interval`） | baostock 长连接专属问题；HTTP 无状态无此需求 |

### 真实数据对比（2026-11-04 盘前实测）

| 指标 | 改造前 | 改造后 |
|---|---|---|
| `kline()` 单次调用 | 每次网络请求（腾讯/新浪） | 命中本地库零网络；未命中走网络并回写 |
| 同日二次全池同步 | 不存在该能力（每次全网络） | 第 1 次 77 只 1.34s（fetched=76）；第 2 次 0.22s（skipped=76、**inserted=0、零新增行**，stats rows=88 两次一致） |
| 单只网络失败 | `_retry_req` 层 2 次退避 | 网络层原有退避 + sync 层单只 3 次指数退避（1s/2s/4s），耗尽计 failed 下次续传 |
| 口径混用风险 | qfq/raw 混用无防线（002178 事故） | 表级隔离 + 查询级隔离 + 回写如实标注，24 个单测锁定（含“raw 绝不冒充 qfq 命中”） |
| 行数 | — | `data/market_store.py` 425 行 vs Sequoia-X `engine.py` 333 行（多出的 ~90 行 = 口径显式化 + CLI + 默认池；Sequoia-X 的 baostock 依赖 ~150 行被 AAna 腾讯/新浪链路复用替代，未计入） |

### 遗留 / 交接给后续阶段

- 腾讯 fqkline 对个别股票（实测 300750）间歇返回空，新浪兜底数据是 raw：`kline(adjust='qfq')` 仍会返回该数据（向后兼容，调用方拿到的与改造前一致），但 store 中如实标 raw、qfq 查询不会命中——口径不再静默混淆，但「qfq 请求经降级拿到 raw 仍返回给调用方」这一行为留给 S5 评审决定是否收紧。
- 全市场回填（backfill 全 A 股历史）未在本阶段范围，`--symbols` 可显式扩池；RPS 横截面（P0-3/S3）可直接读本库。
- cron 收盘后自动 `--sync`（替代/配合现有盘后流程）待 S4/S5 排期。

## P0-2 策略插件化拆分（XWI-81, S2/5）

**交付**：`strategies/` 一策略一文件（`base.py` / `momentum.py` / `technical.py` / `value.py` / `composite.py` / `filters.py`）+ `__init__.py` 自动发现注册 + `tests/test_strategies.py` 发现式测试（15 用例，parametrize 注册表自动生成）。原 9961 字节单文件 `__init__.py`（4 策略全挤在一起、文件头 docstring 声称的目录结构实际不存在）→ 7 个文件，docstring 与实现重新一致。

### 吸收了什么（借鉴点 → Sequoia-X 源位置）

| 吸收点 | Sequoia-X 位置 | AAna 落地 |
|---|---|---|
| `BaseStrategy(ABC)` + `@abstractmethod` 定死契约 | `sequoia_x/strategy/base.py:15-45` | `strategies/base.py` 双契约：`BaseStrategy.score()`（评分制，**保留不退回二值**）+ `ShapeFilter.run() -> list[str]`（形态筛选层，独立于评分层） |
| 一策略一文件 | `strategy/` 7 个形态策略各一文件 | momentum/technical/value/composite 各一文件，逻辑原样搬迁零行为变化 |
| `run() -> list[str]`「返回选中代码列表」 | `base.py:37-44` | `ShapeFilter` 形态层 + `filter_and_score()` 组合入口（先筛形态再打分排名）；首个实现 `filters.py MABullFilter`（均线多头，借鉴 `ma_volume` 思路，判定走 AAna 自己的指标层） |
| 主流程只维护策略列表 | `main.py` 一个 strategies 列表 | `__init__.py` pkgutil 自动发现 + `@register_strategy`/`@register_filter` 装饰器自注册：**新增策略只加新文件，不改任何旧文件**（filters.py 落地时 `__init__.py` 代码零改动，仅 docstring 加一行，即验证） |
| 「向量化，严禁 iterrows」纪律注释 | 各 strategy 文件头 | `data/indicators.py` 模块头同款纪律 |

### 没吸收什么及原因

| Sequoia-X 做法 | 不吸收原因 |
|---|---|
| 策略只返回 `list[str]`（二值选中/不选中） | AAna 评分制（0-100 + 深度排名 + 铁律校验）信息量更大，是核心资产；`run() -> list[str]` 降级为评分层**之前**的形态筛选层，两者组合而非替代 |
| `BaseStrategy.__init__(engine, settings)` 依赖注入 | AAna 用 `_get_qs()` 延迟单例已够用；注入 DataEngine/Settings 会把 pydantic-settings 一起带进来（S1 已记录为反面教材） |
| `webhook_key` 每策略路由不同机器人 | AAna lark-cli 统一推送 + message_id 回读校验已更优（P2-6 结论，S1 已记录） |
| hypothesis 属性测试 | 属 P1-5/S3 范围，本阶段先用注册表 parametrize 做发现式不变量测试（「任意注册策略输出必在 0-100」），S3 再引入 hypothesis |

## P1-4 向量化指标层（XWI-81, S2/5）

**交付**：`data/indicators.py`（MA/RSI/MACD/波动率/量比，全部 pandas `rolling()/shift()/ewm()`，宽表批量 `snapshot_many`）+ `data/quotes.py technical()` 整体委托（**输出与旧实现逐字段一致**）+ `tests/test_indicators.py` 24 用例（oracle = 旧 `technical()` 指标数学逐行拷贝，锁定 17 种输入形态含 1~250 根/平盘/单调/零成交量的逐字段 parity）。

### 吸收了什么（借鉴点 → Sequoia-X 源位置）

| 吸收点 | Sequoia-X 位置 | AAna 落地 |
|---|---|---|
| 所有滚动窗口用 `rolling()/shift()/groupby()`，禁 iterrows | 各 strategy 源码注释（如 `strategy/rps_breakout.py`） | `data/indicators.py`；病灶清除：`quotes.py` 的 `lambda n: sum(closes[-n:])/n` MA 与 O(n²) 前缀重算 MACD、策略层列表推导抽收盘价序列，全部改为向量化 |
| 横截面一次算全池（`groupby('symbol')` 后向量化） | `strategy/rps_breakout.py`（120 日窗全市场一次算） | `snapshot_many()` 宽表实现（列=代码）：**同长度分组建一个 DataFrame，每类指标全池一次 rolling/ewm**。实测 groupby.rolling 按组分发的固定开销在 300 组 × ~20 次分组操作下达 588ms，宽表方案 118ms（5×），故选宽表 |
| 宁缺毋滥（数据不足返回空而非凑数） | `strategy/*.py` 各形态的最低 bar 数守卫 | snapshot 沿用旧口径（不足根数回退全样本均值 / RSI None / MACD None），不新增行为 |

### 真实耗时对比（M1 Pro / Python 3.11.15 / pandas 3.0.5，合成K线固定种子零网络，3 轮取最小；打点脚本与日志 `~/.aana/s2/`）

| workload | 旧实现 | 向量化后 | 倍数 |
|---|---|---|---|
| W1 指标层 50 只×60bar（technical 逐只，生产候选池形态） | 14.0 ms | 79.4 ms | **慢 5.7×** |
| W2 指标层 300 只×60bar（technical 逐只） | 90.2 ms | 483.9 ms | 慢 5.4× |
| W3 候选池评分全流程 50 只（kline+technical+4 策略评分） | 15.7 ms | 81.9 ms | 慢 5.2× |
| W4 指标层 300 只×60bar（snapshot_many 宽表批量） | —（90.2 ms 旧逐只） | 118.3 ms | 与旧逐只基本持平 |
| W5 指标层 300 只×250bar（旧逐只 vs 新逐只） | 1572.3 ms | 555.5 ms | **快 2.8×** |
| W6 指标层 300 只×250bar（snapshot_many 宽表批量） | 1572.3 ms | 167.1 ms | **快 9.4×** |

**诚实结论（重要，给 S4/S5 评审）**：向量化不是免费午餐。60 根 bar 的单只小数据上，pandas 每次调用 ~50-100µs 的固定开销（微基准：`rolling(5).mean()` 106µs、`ewm(12)` 82µs、`clip` 377µs、`from_records+to_numeric×5` 1165µs）摊不掉，旧标量实现（~0.28ms/只）反而是下限；**收益在 bar 数变长（≥~150 根，旧 MACD 的 O(n²) 前缀重算显形：60bar 0.28ms → 250bar 5.2ms/只）与整池批量时兑现**（W6 9.4×）。工程取舍：
1. 病灶（lambda MA / 列表推导 / O(n²) MACD）按 issue 红线清除，指标口径逐字段不变（oracle 测试锁定），评分输出零变化（bench sanity: composite=70.4 前后一致）；
2. 单只 60bar 路径付出 ~5× 指标层耗时（生产全流程 +66ms/50 只），相对流程内的 store 读与网络 I/O 可接受，但这是**已知的真实退化**，如实打点上报；
3. S3 RPS（120 日窗 × 全市场）与任何池级批量应走 `snapshot_many` 宽表路径（60bar 持平、250bar 9.4× 快），不要在循环里逐只 `snapshot()`——已写进 `data/indicators.py` 模块头注释。

### 刻意保留的旧口径（quirk 清单，是否修正由 S5 评审决定）

1. **MA 不足 n 根回退全样本均值**（非 None）——旧 `ma = lambda n: ... sum(closes)/len(closes)`；
2. **MACD DEA = 0.8·dif[i] + 0.2·dif[i−1]**（dif 一阶滞后加权），**不是教科书 EMA9 递推**——旧实现的写法如此，向量化按原式 `shift(1)` 复刻保逐位一致（`macd()` docstring 有标注）；
3. RSI 为 SMA 口径（近 14 日简单平均涨跌幅比），窗口零下跌 → 100.0（平盘 quirk）；
4. 量比 = 当日量/前 5 日均量（`shift(1)` 排除当日），均量 0 → None。

### 遗留 / 交接给后续阶段

- 60bar 单只路径的 ~5× 指标层退化：如 S5 认为不可接受，备选方案是池级调用方迁移 `snapshot_many`（S3 一并做）或给 `technical()` 加进程内 LRU（按 code+最后bar日期），本阶段不动调用方（红线：`scripts/feedback_loop.py` 等生产路径向后兼容）。
- `ruff check .` 全仓库仍有 ~1.9k 历史违规（基线即如此）；本阶段新增/重写文件（strategies/ 7 个、data/indicators.py、2 个测试文件）ruff 全绿，`quotes.py` 的 31 个（UP006×28 等）全部为 S1 之前就存在的注解风格问题，未清（不混入本阶段 diff）。
- hypothesis 属性测试（P1-5）在 S3：届时 `tests/test_strategies.py` 的注册表 parametrize 结构可直接复用。

# K线数据源熔断设计文档

## 背景

`Router.sync_kline_db` 串行遍历约 5207 只票，每只调 `_fetch_kline_online`，按
腾讯 → mootdx → akshare → baostock 顺序降级。同一份代码的实测耗时波动达 28 倍：

| 日期 | synced | failed | 耗时 | 折算 |
|---|---|---|---|---|
| 2026-08-18 | 5191 | 16 | 575s | 0.11s/只 |
| 2026-08-19 | 5195 | 12 | 1710s | 0.33s/只 |
| 2026-08-17 | 4436 | 586 | 4006s | 0.77s/只 |
| 2026-08-20 | 4742 | 103 | **16367s** | **3.14s/只** |

波动的唯一变量是上游可用性，不是代码结构。腾讯健康时一次 HTTP 就返回（0.11s/只）；
腾讯限流时每只票要白等 10s 超时（`data_hub/sources/tencent_kline.py:60`
`timeout=10`），再串完 mootdx（当日大量 `Broken pipe`）、akshare、baostock。

关键约束：**四个 kline 源全部只支持单只票查询**，无批量端点。Sina/腾讯的快照接口
支持批量（600/50 只一批）但那是另一组接口。所以 5207 次请求省不掉，只能降低
"每次请求的期望成本"。

本次只做源级熔断：**当某个源在本轮内连续失败达阈值，就在本轮剩余部分跳过它**。
不引入并发（见范围外）。

## 需求场景与处理逻辑

单一场景：一轮 `sync_kline_db` 执行期间，某个上游整体不可用。

现状：该源对每只票都被调用一次，每次都付满超时/失败成本，5207 次全部白付。
目标：前 N 只票用于探测，确认该源不可用后，本轮剩余约 5200 只票直接跳过它。

熔断是**每轮独立**的：`sync_kline_db` 开始时重置，结束时丢弃。不跨轮持久化——
上游可用性是分钟级波动的，跨轮记忆只会让下一轮误判。这与 R4 的 `failed_codes`
（跨轮持久化的死码名单）是两个不同维度：`failed_codes` 记的是"这只票取不到"，
熔断记的是"这个源现在不通"。

### 熔断状态机

每个源三种状态，按轮次维护：

- `closed`（正常）：正常调用。成功则把连续失败计数归零。
- `open`（熔断）：直接跳过，不发请求。
- `half_open`（试探）：每隔 `probe_interval` 只票放一次请求过去；成功则回到
  `closed`，失败则退回 `open` 并重新计时。

`open` 与 `half_open` 的切换由"距上次探测过了多少只票"驱动，不用时间戳——
串行循环里用计数比用墙钟更可预测，也便于测试。

判定"失败"的口径：`_fetch_kline_online` 内 `_try(...)` 返回 `None`。这里刻意
**不区分异常与空数据**。理由：退市票在所有源上都返回空，若把空数据也计入失败，
连续遇到一批退市票会误熔断健康的源。因此只有**抛异常**才计入连续失败计数，
返回空 DataFrame 不计入。这一点与 R4 的 `empty_from_all_sources` 判定保持一致。

### 判定口径修正（2026-08-23，基于 08-21 实测）

上述"只有抛异常才计失败"的口径经实测**不成立**，需要修正。

2026-08-21 盘后同步实测：`synced=3888 failed=1319 elapsed=56101.4s`（15.6 小时），
但熔断**一次都没触发**——日志中 `breaker` 相关输出 0 条。原因是这天的失败模式与
08-20 完全不同：

| 日期 | 失败模式 | `取数异常` 出现次数 | 熔断是否触发 |
|---|---|---|---|
| 08-20 | 腾讯限流抛 `AttributeError` | 每票 1 次 | 会触发（设计有效） |
| 08-21 | mootdx 静默超时后返回空 | **0 次** | 不触发（设计失效） |

08-21 整段同步里 `取数异常` 出现 0 次，而 mootdx 的
`服务器连接失败`/`Broken pipe`/`接收数据异常` 有 **2388** 次——这些是 mootdx
库内部自己打印并吞掉的，对外只返回空或 `None`（见 `mootdx_source.py:58-63`
的 `except Exception: return None`）。于是每只票都走 `on_success()`，
`consecutive_fails` 被反复清零，熔断条件永远不满足。

结论：**"是否抛异常"不是可靠的健康信号**，因为各源都在内部吞掉了异常。

修正方案：改用**耗时**作为判定维度。正常成功的调用是毫秒级（08-18 全程
575s/5207 只 ≈ 0.11s/只，含四源降级与落库），静默超时是秒级。以"单次调用耗时
≥ `slow_call_s`（默认 3.0s）"作为失败信号：

- 抛异常 → 计失败（保留原逻辑）
- 未抛异常但耗时 ≥ 3.0s → **计失败**（捕获静默超时）
- 未抛异常且耗时 < 3.0s → 计成功（含返回空的情况）

这个口径同时解决了原先的顾虑：退市票返回空是**快速**返回，不会被误判为失败，
所以连续扫到一批退市票仍不会误熔断健康的源。判定入口收敛为一个方法：

```python
    def on_call(self, elapsed: float, raised: bool):
        """按"是否抛异常 + 单次耗时"判定本次调用的健康度。"""
        if raised or elapsed >= self.slow_call_s:
            self.on_error()
        else:
            self.on_success()
```

注意一个细节：耗时超阈值但**成功返回了数据**时，数据照常使用（不能丢），
只是同时把这次调用记为失败信号。取数正确性与源健康度是两件独立的事。


## 架构与技术方案

在 `data_hub/router.py` 内新增一个轻量状态容器，不引入新模块、不改源类。

```python
class _SourceBreaker:
    """单个数据源的轮内熔断状态。仅在一轮 sync 内有效。"""

    def __init__(self, name: str, fail_threshold: int = 20, probe_interval: int = 200):
        self.name = name
        self.fail_threshold = fail_threshold
        self.probe_interval = probe_interval
        self.consecutive_fails = 0
        self.tripped = False          # 是否已熔断
        self.calls_since_probe = 0    # 熔断后又跳过了多少只
        self.skipped = 0              # 本轮跳过次数（统计用）
        self.probes = 0               # 本轮试探次数（统计用）

    def should_skip(self) -> bool:
        """熔断期内是否跳过本次调用；到达试探间隔时放行一次。"""
        if not self.tripped:
            return False
        self.calls_since_probe += 1
        if self.calls_since_probe >= self.probe_interval:
            self.calls_since_probe = 0
            self.probes += 1
            return False              # half_open：放行一次试探
        self.skipped += 1
        return True

    def on_success(self):
        if self.tripped:
            print(f"  [breaker] {self.name} 恢复，解除熔断")
        self.consecutive_fails = 0
        self.tripped = False
        self.calls_since_probe = 0

    def on_error(self):
        self.consecutive_fails += 1
        if not self.tripped and self.consecutive_fails >= self.fail_threshold:
            self.tripped = True
            self.calls_since_probe = 0
            print(f"  [breaker] {self.name} 连续失败 {self.consecutive_fails} 次，"
                  f"本轮熔断（每 {self.probe_interval} 只试探一次）")
```

`_fetch_kline_online` 改为按"源列表 + 对应 breaker"顺序尝试，把四段近似重复的
代码收敛成一个循环：

```python
    def _fetch_kline_online(self, code: str, start: str, end: str,
                            breakers: Optional[dict] = None) -> Optional[pd.DataFrame]:
        # 腾讯HTTP日K(443端口，最稳) -> mootdx -> akshare -> baostock 兜底
        for name, src, need_login in self._kline_source_chain():
            br = (breakers or {}).get(name)
            if br is not None and br.should_skip():
                continue
            if need_login and not self._ensure_login(name, src):
                continue
            try:
                df = src.get_kline(code, start, end)
            except Exception as e:
                print(f"  [{code}] {name} 取数异常，降级: {type(e).__name__}: {e}")
                if br is not None:
                    br.on_error()
                continue
            if br is not None:
                br.on_success()       # 未抛异常即视为该源可用
            if df is not None and not df.empty:
                return df
        return None
```

要点：
- `br.on_success()` 在"未抛异常"时调用，即使返回空 DataFrame——空数据说明链路
  是通的，只是这只票没数据。
- `breakers=None` 时行为与当前完全一致，保证 `sync_kline_db` 之外的调用方
  （`get_kline` 的按需补拉路径）不受影响。

`sync_kline_db` 内每轮新建 breakers 并在结果里带出统计：

```python
        breakers = {
            'tencent': _SourceBreaker('tencent'),
            'mootdx':  _SourceBreaker('mootdx'),
            'akshare': _SourceBreaker('akshare'),
            'baostock': _SourceBreaker('baostock'),
        }
        ...
            df = self._fetch_kline_online(code, real_start, end, breakers=breakers)
        ...
        return {'synced': ..., 'failed': ..., 'skipped_dead': ...,
                'breaker': {n: {'tripped': b.tripped, 'skipped': b.skipped,
                                'probes': b.probes} for n, b in breakers.items()},
                'failed_codes': failed[:20], 'elapsed_s': ...}
```

### 参数取值依据

- `fail_threshold=20`：连续 20 只票在同一源上抛异常，几乎不可能是巧合。按 08-20
  腾讯 10s 超时算，探测成本约 200s，占原 16367s 的 1.2%。
- `probe_interval=200`：5207 只票约产生 26 次试探。若上游中途恢复，最多浪费
  200 只票的降级成本；试探自身的成本约 26 × 10s = 260s，可接受。

两个参数都做成 `sync_kline_db` 的入参并透传到 `api.py`，便于调参而无需改代码。

## 影响文件

- `data_hub/router.py`（修改）
  - 新增 `_SourceBreaker` 类（模块级，放在 `_try_login` 之后）。
  - 新增 `Router._kline_source_chain()` 与 `Router._ensure_login(name, src)`，
    把现有四段 `if not self._xx_logged_in` 的登录态管理收敛到一处。
  - 改写 `_fetch_kline_online()`（当前 153-184 行）为循环形式，新增
    `breakers` 参数。
  - `sync_kline_db()` 新增 `breaker_fail_threshold` / `breaker_probe_interval`
    两个入参，构建 breakers 并透传，返回值新增 `breaker` 统计。
- `data_hub/api.py`（修改）：`sync_kline_db()` 透传两个新参数。
- `data_hub/__main__.py`（修改）：打印熔断摘要（哪些源熔断了、跳过多少次）。

不改动 `data_hub/sources/` 下任何源实现。

## 边界条件与异常处理

- **全部四源都熔断**：`_fetch_kline_online` 返回 `None`，该票走 R4 的
  `mark_failed(code, 'empty_from_all_sources')`。行为退化为"整轮剩余全部失败"，
  但耗时接近 0，比现状（全部失败且耗时 4.5 小时）严格更优。
- **误熔断健康源**：`probe_interval` 保证最长 200 只票后必然重试，不会永久封锁。
  且因为只有抛异常才计数，连续遇到退市票不会误触发。
- **`breakers=None`（非 sync 路径）**：`should_skip` 不被调用，逻辑与现状等价。
  `daily_select.py` 候选池按需补拉走的是 `hub.get_kline`，不受影响。
- **mootdx 登录失败**：现有 `_try_login` 返回 `False` 后该源被跳过，这与熔断是
  两条独立路径，不冲突。需确认登录失败不会被计入 `consecutive_fails`——登录与
  取数是两个阶段，登录失败只 `continue`，不调 `on_error`。
- **单只票的多源顺序不变**：熔断只做"跳过"，不重排优先级。腾讯恢复后仍是首选。
- **统计口径**：`skipped` 只统计真正跳过的次数，不含试探放行的次数，两者分列。

## 数据流（改造后）

```text
sync_kline_db(start, end, full=False)
  ├─ 构建 breakers = {tencent, mootdx, akshare, baostock}      [每轮新建]
  ├─ 读 failed_codes → skip_set（跨轮死码名单）                 [R4.2 既有]
  └─ for code in codes:
       ├─ code in skip_set → skipped_dead += 1, continue        [R4.2 既有]
       └─ _fetch_kline_online(code, breakers=breakers)
            for (name, src) in [腾讯, mootdx, akshare, baostock]:
              ├─ breaker.should_skip() → continue（不发请求）    [本次新增]
              ├─ 抛异常 → breaker.on_error(); continue          [本次新增]
              │    └─ 连续失败 ≥20 → tripped=True，本轮熔断
              ├─ breaker.on_success()（含返回空的情况）          [本次新增]
              └─ 有数据 → return df
       ├─ 有数据 → upsert_kline + clear_failed                   [R4.1 既有]
       └─ 全源无数据 → mark_failed(empty_from_all_sources)       [R4.1 既有]
```

## 预期结果

以 08-20 为基准场景（腾讯整轮不可用）：

- 腾讯在前 20 只票内熔断，本轮剩余约 5187 只不再调用它，省掉约 5187 × 10s
  的超时等待（理论上限 14.4 小时量级的等待，实际受其他源耗时约束）。
- 日志出现 `[breaker] tencent 连续失败 20 次，本轮熔断（每 200 只试探一次）`。
- 同步结果新增 `breaker={'tencent': {'tripped': True, 'skipped': ~5160, 'probes': ~26}, ...}`。
- 腾讯健康的日子（如 08-18 的 575s）行为与现状完全一致，`tripped` 全为 `False`，
  无额外开销。

耗时改善幅度无法先验给出——取决于降级后 mootdx/akshare/baostock 的实际速度，
这三个源在 08-20 也不健康。需在验证阶段用真实数据量化。

## 验证方式

1. **单元：状态机**。构造 `_SourceBreaker(fail_threshold=3, probe_interval=5)`，
   断言：连续 3 次 `on_error` 后 `tripped=True`；随后 4 次 `should_skip()` 返回
   `True`、第 5 次返回 `False`（试探放行）；试探后 `on_success()` 使
   `tripped=False` 且计数归零。
2. **单元：不误熔断**。交替 `on_error`/`on_success`（模拟零星失败），断言
   `tripped` 始终为 `False`。
3. **集成：熔断生效**。用 `object.__new__(Router)` 注入四个假源，令腾讯每次抛
   异常、baostock 正常返回，跑 300 只票；断言腾讯的实际调用次数约等于
   `20 + 300/200` 而非 300，且每只票最终都拿到数据。
4. **集成：空数据不计入**。令腾讯始终返回空 DataFrame（不抛异常），跑 100 只票；
   断言 `tripped=False`、腾讯被调用 100 次。
5. **回归：非 sync 路径**。`breakers=None` 调 `_fetch_kline_online`，断言降级
   顺序与返回值同现状一致；跑一次 `daily_select.py --date`（用已有 prefilter
   缓存）确认候选与评分不变。
6. **真实观测**：下一次 launchd 增量同步，记录 `breaker` 统计与 `elapsed_s`，
   与 575s / 1710s / 4006s / 16367s 四个历史点对比后写入 summary。

## 范围外（本次不做）

- **不引入并发**。四个源全部共享可变状态：腾讯共用一个 `requests.Session`
  （`tencent_kline.py:40`）、mootdx 共用一个 TCP `Quotes` 客户端
  （`mootdx_source.py:46`）、baostock 是模块级全局登录态且每 500 次调用重连
  （`baostock.py:43-49`）、akshare 走全局模块。直接套 `ThreadPoolExecutor` 会出
  连接池竞争与 TCP 协议错乱；要做需给每线程各建一套源实例，工程量比熔断大一个
  量级。仓库现无任何 `ThreadPoolExecutor`/`asyncio` 用法，无既有约定可循。
  先上熔断，观察数日后再评估。
- 不改各源的 timeout 值与内部重试（`baostock.py:55-76` 的 2 次重试 + 0.2s
  退避保持原样）。
- 不做跨轮的源健康度持久化。
- 不调整源的优先级顺序。
- 不碰选股策略、评分权重与 `failed_codes` 的死码跳过逻辑。

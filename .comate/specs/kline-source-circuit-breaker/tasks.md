# K线数据源熔断任务计划

先把状态机做成可单测的独立单元，再改造调用链，最后接进 `sync_kline_db` 并透传参数。
每个任务独立可验证；Task 2 有意在不接入 breaker 的前提下先完成结构重构，
这样"重构"与"新行为"分开验证，出问题时容易定位。

- [✓] Task 1: 实现 `_SourceBreaker` 轮内熔断状态机
    - 1.1: 在 `data_hub/router.py` 的 `_try_login` 之后新增模块级 `_SourceBreaker` 类
    - 1.2: 实现 `should_skip()`：未熔断返回 False；熔断期内按 `probe_interval` 放行一次试探
    - 1.3: 实现 `on_success()` / `on_error()`，维护 `consecutive_fails` / `tripped` / `calls_since_probe`
    - 1.4: 熔断与恢复各打印一行日志，便于在 daily.log 里追溯
    - 1.5: 单测状态机：`fail_threshold=3` 时连续 3 次 `on_error` → `tripped=True`
    - 1.6: 单测试探节奏：`probe_interval=5` 时前 4 次 `should_skip()` 为 True、第 5 次为 False
    - 1.7: 单测恢复：试探后 `on_success()` → `tripped=False` 且计数归零
    - 1.8: 单测不误熔断：交替 `on_error`/`on_success` 时 `tripped` 恒为 False

- [✓] Task 2: 重构 `_fetch_kline_online` 为源链循环（不接 breaker）
    - 2.1: 新增 `Router._kline_source_chain()`，按腾讯 → mootdx → akshare → baostock 返回 (name, src, need_login)
    - 2.2: 新增 `Router._ensure_login(name, src)`，把现有四段 `self._xx_logged_in` 登录态收敛到一处
    - 2.3: 改写 `_fetch_kline_online` 为遍历源链，保留每源单独兜异常的行为
    - 2.4: 登录失败只 `continue`，不得计入后续的失败计数（登录与取数是两个阶段）
    - 2.5: 回归：注入假源验证降级顺序、返回值、空 DataFrame 处理与改造前一致
    - 2.6: 回归：跑一次 `daily_select.py --date 2026-08-20`（命中现有 prefilter 缓存），确认候选仍为 2 只且评分不变

- [✓] Task 3: 将 breaker 接入取数链路
    - 3.1: `_fetch_kline_online` 新增 `breakers: Optional[dict] = None` 参数
    - 3.2: 调用前 `br.should_skip()` 为真则跳过该源，不发请求
    - 3.3: 抛异常 → `br.on_error()` 后降级；未抛异常 → `br.on_success()`（含返回空的情况）
    - 3.4: 确认 `breakers=None` 时逻辑与 Task 2 完成态完全等价
    - 3.5: 集成测试：腾讯每次抛异常、baostock 正常，跑 300 只票，断言腾讯调用次数约 `20 + 300/200` 而非 300，且每只票都拿到数据
    - 3.6: 集成测试：腾讯始终返回空 DataFrame（不抛异常），跑 100 只票，断言 `tripped=False` 且腾讯被调用 100 次

- [✓] Task 4: `sync_kline_db` 构建 breakers 并透出统计
    - 4.1: `sync_kline_db` 新增 `breaker_fail_threshold=20` / `breaker_probe_interval=200` 入参
    - 4.2: 每轮新建四个 breaker（不跨轮持久化），传入 `_fetch_kline_online`
    - 4.3: 返回值新增 `breaker` 字段：每源的 `tripped` / `skipped` / `probes`
    - 4.4: 确认与 R4.2 的 `skip_set` 死码跳过互不干扰（两者维度不同）
    - 4.5: 集成测试：跑一轮注入假源的 `sync_kline_db`，断言 `breaker` 统计正确且 `mark_failed` 仍在全源无数据时被调用

- [✓] Task 5: 参数透传与 CLI 输出
    - 5.1: `data_hub/api.py` 的 `sync_kline_db()` 透传两个新参数
    - 5.2: `data_hub/__main__.py` 打印熔断摘要（哪些源熔断、各跳过多少次、试探多少次）
    - 5.3: 验证 `python -m data_hub sync_today` 在无熔断时输出不变（不新增噪音行）

- [✓] Task 6: 真实观测与生成 summary.md
    - 6.1: 触发一次真实增量同步，记录 `breaker` 统计与 `elapsed_s`
    - 6.2: 与历史数据点对比（575s / 1710s / 4006s / 16367s / 56101s），说明本次落在哪个可用性区间
    - 6.3: 核对 `failed_codes` 的变化，确认熔断没有把健康票误判为失败
    - 6.4: 撰写 `summary.md`：改动、验证结果、实测耗时对比、以及是否值得继续做并发的判断依据

- [✓] Task 7: 判定口径改为"异常 + 耗时"（基于 08-21 实测修正）
    - 7.1: `_SourceBreaker.__init__` 增加 `slow_call_s: float = 3.0`
    - 7.2: 新增 `on_call(elapsed, raised)`：抛异常或耗时 ≥ 阈值判失败，否则判成功
    - 7.3: `_fetch_kline_online` 对每次源调用计时，异常路径与正常路径都走 `on_call`
    - 7.4: 耗时超阈值但成功返回数据时，数据照常使用，仅把该次调用记为失败信号
    - 7.5: `sync_kline_db` 增加 `breaker_slow_call_s` 入参并透传到 `api.py`
    - 7.6: 单测：`on_call(0.1, False)` 判成功；`on_call(5.0, False)` 判失败；`on_call(0.1, True)` 判失败
    - 7.7: 单测：连续 20 次慢调用（不抛异常）应触发熔断——这是 08-21 失效场景的回归
    - 7.8: 单测：连续 100 次快速空返回（模拟退市票）不应触发熔断
    - 7.9: 集成：慢源 + 快源混合，断言慢源被熔断且每只票仍从快源拿到数据
    - 7.10: 回归：08-20 的抛异常场景仍能触发熔断（腾讯调用次数仍约为 21）


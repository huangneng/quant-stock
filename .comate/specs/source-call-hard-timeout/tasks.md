# 取数调用硬超时任务计划

时间约束：今天 16:15 launchd 会跑批，必须在那之前完成并验证。
所以顺序按「先拿到保护、再补周边」排：Task 1~3 是核心保护，
Task 4 是参数透传与可观测性，Task 5 是跑批前的实盘验证。

看门狗本身用假源就能完整验证，不依赖上游可用性——这是它能在今天完成的前提。

- [✓] Task 1: 新增 `SourceCallTimeout` 异常
    - 1.1: `data_hub/sources/base.py` 定义 `SourceCallTimeout(Exception)`
    - 1.2: docstring 说明它与 `SourceUnavailable` 的分界：一次卡住 ≠ 整个源不可用
    - 1.3: 确认不影响既有抽象方法签名与 `SourceUnavailable` 行为

- [✓] Task 2: `_CallTimeout` 看门狗
    - 2.1: `data_hub/router.py` 新增模块级 `_CallTimeout` 上下文管理器
    - 2.2: 基于 `signal.setitimer(ITIMER_REAL)`，超时抛 `SourceCallTimeout`
    - 2.3: 无 `SIGALRM`（Windows）或非主线程时静默退化为无超时，不让取数失败
    - 2.4: `__exit__` 无条件清零 itimer 并恢复原 handler，避免污染全局信号状态
    - 2.5: `seconds <= 0` 表示关闭看门狗
    - 2.6: 单测：`sleep(3)` 配 1s 超时，断言约 1s 内抛 `SourceCallTimeout`
    - 2.7: 单测：正常快速调用不受影响，退出后 itimer 归零、handler 复原
    - 2.8: 单测：非主线程中使用不抛异常、也不设超时
    - 2.9: 单测：调用体自己抛异常时，itimer 与 handler 同样被正确恢复

- [✓] Task 3: 接入 `_fetch_kline_online`
    - 3.1: 每次 `src.get_kline` 套 `_CallTimeout(self.source_call_timeout_s)`
    - 3.2: `Router.__init__` 新增 `source_call_timeout_s: float = 30.0`
    - 3.3: 超时走 `on_call(raised=True)`，与既有异常分支一致
    - 3.4: 超时打印一行告警（含源名、代码、超时秒数），不刷屏
    - 3.5: 统计每源超时次数，纳入 `breaker.stats()` 或单独计数
    - 3.6: 单测：假源 `sleep(60)`，断言在约超时值内返回并降级到下一个源
    - 3.7: 单测：连续超时达 20 次后该源熔断
    - 3.8: 单测：`breakers=None` 的按需补拉路径同样受超时保护

- [✓] Task 4: 参数透传与 CLI 输出
    - 4.1: `sync_kline_db` 新增 `source_call_timeout_s` 并传给取数层
    - 4.2: `data_hub/api.py` 同步透传
    - 4.3: `data_hub/__main__.py` 在有超时发生时打印各源超时次数
    - 4.4: 确认无超时发生时输出不新增噪音行

- [✓] Task 5: 跑批前实盘验证
    - 5.1: 编译与导入检查，复跑既有七套单测
    - 5.2: 探测各源当前可用性，记录基线
    - 5.3: 跑一轮真实增量同步（限定少量代码），确认看门狗不误杀正常取数
    - 5.4: 确认 16:15 前 launchd 两个任务仍为 loaded 状态
    - 5.5: 撰写 `summary.md`

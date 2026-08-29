# 熔断判定补全任务计划

先做异常类型与源侧抛出（Task 1-2），再改熔断器判定（Task 3），
最后才是参数透传与真实观测。这个顺序保证每一步都能单独验证：
Task 2 做完时熔断行为已经修好一半（腾讯会跳了），Task 3 是独立的恢复语义。

节流值调整放在最后（Task 5），它只是一个默认值，且真实跑批前改比改早了更容易回退。

- [✓] Task 1: 新增 `SourceUnavailable` 异常类型
    - 1.1: `data_hub/sources/base.py` 定义 `SourceUnavailable(Exception)`
    - 1.2: docstring 明确「返回 None = 该票无数据」与「抛异常 = 本源不可用」的分界
    - 1.3: 确认不影响 `DataSource` / `SnapshotSource` 既有抽象方法签名

- [✓] Task 2: 腾讯 WAF 分支改为抛异常
    - 2.1: `tencent_kline.get_kline` 的 WAF 命中分支由 `return None` 改为 `raise SourceUnavailable`
    - 2.2: 保留源侧那句 WAF 告警（含 HTTP 状态码），异常消息带上同样信息
    - 2.3: 确认 WAF 判定仍只覆盖 501 / 响应体含 `waf.tencent.com`，不扩大到解析失败
    - 2.4: `_fetch_kline_online` 的 except 分支对 `SourceUnavailable` 不再打印「取数异常，降级」
    - 2.5: 单测：WAF 501 抛 `SourceUnavailable`，且异常携带状态码
    - 2.6: 单测：`json.loads` 失败仍返回 `None`（不升级为源级故障）
    - 2.7: 单测：正常响应解析不受影响

- [✓] Task 3: 熔断器判定与恢复语义
    - 3.1: `_SourceBreaker.__init__` 新增 `recover_threshold=3` 与 `consecutive_successes`
    - 3.2: `on_error` 重置 `consecutive_successes`
    - 3.3: `on_success` 累计连续成功；未达阈值时把 `calls_since_probe` 置为 `probe_interval`，让下一只票继续试探
    - 3.4: 达到阈值才解除熔断并打印恢复日志
    - 3.5: `stats()` 增加 `recovered` 计数
    - 3.6: 单测：连续 20 次源级故障后熔断，第 21 次起 `should_skip` 为真
    - 3.7: 单测：熔断后单次成功不解除，连续 3 次才解除
    - 3.8: 单测：试探成功后紧邻的下一只票也能试探（不必再等 200 只）
    - 3.9: 单测：试探成功一次后再失败，`consecutive_successes` 归零且仍处熔断

- [✓] Task 4: 空返回不得被判为源故障（回归）
    - 4.1: 单测：源持续返回 `None`（模拟退市票扎堆）500 次，断言熔断器不跳
    - 4.2: 单测：`breakers=None` 路径遇 `SourceUnavailable` 仍正常降级、不外泄异常
    - 4.3: 确认慢调用（≥3s）判定与 `slow_calls` 统计行为不变
    - 4.4: 确认失败率记账（自锁防护）与早停行为不变

- [✓] Task 5: 参数透传、节流默认值与 CLI 输出
    - 5.1: `sync_kline_db` 新增 `breaker_recover_threshold`，`api.py` 同步透传
    - 5.2: `Router.__init__` 的 `min_request_interval_s` 默认值 0.1 → 0.3
    - 5.3: `__main__.py` 的熔断统计输出加 `recovered`
    - 5.4: 编译检查与导入检查通过

- [✓] Task 6: 真实观测
    - 6.1: 单只票试探腾讯，记录当前封禁状态（不跑批）
    - 6.2: 跑一轮同步，重点看腾讯是否在前 20~30 只内熔断、全轮耗时、`recovered` 次数
    - 6.3: 与 44752s / 575s 两个参照点对比
    - 6.4: 确认腾讯熔断后请求数收敛（预期 ~26 次而非 5207 次）
    - 6.5: 达标则 `launchctl load` 恢复两个任务；未达标则保持 unloaded 并记录原因
    - 6.6: 撰写 `summary.md`

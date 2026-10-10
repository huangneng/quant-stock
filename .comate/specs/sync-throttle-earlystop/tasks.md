# 同步节流与整轮早停任务计划

节流与早停彼此独立，可分别验证。WAF 识别放最前面——它只加日志不改控制流，
风险最低，而且做完之后后续任何一次试探都能立刻看出是否仍在封禁中。

- [✓] Task 1: 腾讯 WAF 拦截识别与告警
    - 1.1: `tencent_kline.get_kline` 在 `json.loads` 之前检查 HTTP 501 或响应体含 `waf.tencent.com`
    - 1.2: 命中则打印明确告警（提示 IP 可能被限流封禁、建议停止同步），返回 `None`
    - 1.3: 仅加日志，不改控制流——后续源降级行为保持不变
    - 1.4: 单测：伪造 HTTP 501 响应，断言返回 `None` 且打印告警
    - 1.5: 单测：伪造含 `waf.tencent.com` 的 200 响应，断言同样识别
    - 1.6: 单测：正常响应不受影响，仍能正确解析出数据

- [✓] Task 2: 按源节流
    - 2.1: `data_hub/router.py` 新增模块级 `_Throttle` 类，实现 `wait()`
    - 2.2: `Router.__init__` 新增 `min_request_interval_s: float = 0.1`，为每个源建一个节流器
    - 2.3: `_fetch_kline_online` 在每次 `src.get_kline` 之前 `wait()`
    - 2.4: 确认被熔断跳过的源不走 `wait()`，不产生延迟成本
    - 2.5: 单测：`min_interval=0.05` 连续 10 次 `wait()`，总耗时 ≥ 0.45s
    - 2.6: 单测：`min_interval=0` 时 10 次 `wait()` 耗时约为 0（可关闭节流）
    - 2.7: 单测：两个不同源各自独立计时，互不影响

- [✓] Task 3: 整轮早停
    - 3.1: `sync_kline_db` 新增 `early_stop_min_samples=300` / `early_stop_fail_rate=0.9`
    - 3.2: 循环内每只票处理后检查，`attempted >= min_samples` 且失败率 > 阈值则 `break`
    - 3.3: 记录 `aborted` 原因字符串并打印，返回值带上 `aborted`
    - 3.4: 早停时**不写** `last_sync_date`，避免后续增量误判起点
    - 3.5: 确认 `skipped_dead` 不计入 `attempted`，不稀释失败率
    - 3.6: 单测：全失败假源 500 只票，断言在 300~310 只之间中止，源调用次数远小于 500
    - 3.7: 单测：失败率 50%、500 只票，断言跑满全程且 `aborted` 为 `None`
    - 3.8: 单测：仅 200 只票全失败，断言样本不足不早停、跑满全程
    - 3.9: 单测：早停后 `meta_get('last_sync_date')` 未更新；正常跑完则更新

- [✓] Task 4: 参数透传与 CLI 输出
    - 4.1: `data_hub/api.py` 透传 `early_stop_min_samples` / `early_stop_fail_rate`
    - 4.2: `data_hub/__main__.py` 在 `aborted` 非空时打印中止原因
    - 4.3: 确认正常跑完时输出不新增噪音行

- [✓] Task 5: 回归验证
    - 5.1: 失败率记账逻辑（自锁防护）行为不变——早停场景下 `marked_failed` 必为 0
    - 5.2: 熔断统计与 `skipped_dead` 行为不变
    - 5.3: `breakers=None` 的按需补拉路径不受节流与早停影响
    - 5.4: 编译检查与导入检查通过

- [✓] Task 6: 封禁试探与真实观测
    - 6.1: 单只票试探腾讯接口，确认 501 是否解除（每次只发一个请求，不跑批）
    - 6.2: 若已解除，跑一轮同步，记录耗时 / `aborted` / `fail_rate`
    - 6.3: 与 575s 健康日基线对比，确认节流未造成明显退化
    - 6.4: 确认无误早停后，`launchctl load` 恢复两个 launchd 任务
    - 6.5: 撰写 `summary.md`：改动、验证结果、封禁起止时间、恢复自动跑批的时点

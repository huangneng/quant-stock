# 熔断判定补全 — 实施总结

## 结论

腾讯被封时，源侧请求数从 5207 收敛到 24（模拟 1000 只票场景）。
真实观测轮把 08-21~08-28 全部补到 **99.7%**，与健康日基线（08-18 的 5196 行）齐平。
`failed_codes` 从 244 行降到 15 行。两个 launchd 任务已恢复 loaded。

## 改动清单

| 文件 | 改动 |
|---|---|
| `data_hub/sources/base.py` | 新增 `SourceUnavailable` 异常，docstring 明确「返回 None = 该票无数据」与「抛异常 = 本源不可用」的分界 |
| `data_hub/sources/tencent_kline.py` | WAF 分支由 `return None` 改为 `raise SourceUnavailable`；判定移到 `try` 块外 |
| `data_hub/router.py` | `_SourceBreaker` 新增 `recover_threshold=3` / `consecutive_successes` / `recovered`；`on_success` 改为连续成功才解除熔断；`on_error` 重置成功计数；`_fetch_kline_online` 对 `SourceUnavailable` 不打降级日志；节流默认 0.1s → 0.3s；`sync_kline_db` 新增 `breaker_recover_threshold` |
| `data_hub/api.py` | 透传 `breaker_recover_threshold` |
| `data_hub/__main__.py` | 熔断统计输出新增 `breaker_recovered` 行 |

选股策略逻辑（cond1/cond2、25 亿成交额预筛）未改动。

## 关键设计取舍

**没有采用「空返回一律计为失败」**。降级链是短路的——腾讯成功的票根本不会调到
baostock，所以 baostock 只收到「前三个源都失败」的硬骨头，大多是退市/停牌票，
本来就该返回空。健康日下这批票扎堆落到 baostock，连续空返回轻易超过 20，
会把好源无故熔断。

正确的区分维度不是「有没有数据」，而是**「拿不到数据的原因在源侧还是标的侧」**，
这个信息只有源自己知道，必须由源显式表达——所以用异常类型而非返回值来承载。

实现坑：WAF 判定必须放在 `try` 块外面。原有的 `try/except Exception: return None`
会把新抛的 `SourceUnavailable` 当场吞掉，改动等于无效。

## 单测结果（全通过）

- WAF 501 与「200 但响应体含 waf 域名」都抛 `SourceUnavailable`，异常消息带状态码
- `json.loads` 失败 / `data` 节点是字符串 / 请求本身抛异常 → 仍返回 `None`，不升级为源级故障
- 正常响应解析不受影响，且不打印任何日志
- 20 次源级故障后熔断，之后 199 次全部跳过
- 熔断后单次成功不解除；连续 3 次才解除并打印恢复日志，`recovered=1`
- 试探成功后紧邻的下一只票也能试探（不必再等 200 只）
- 试探成功 1 次后再失败 → `consecutive_successes` 归零且仍处熔断
- **500 次快速空返回，熔断器不跳**（退市票扎堆不误伤好源）
- 1000 只票 + WAF 源：源侧被调用 **24 次**（原为 1000），健康兜底源未被误熔断
- `breakers=None` 的按需补拉路径遇 `SourceUnavailable` 正常降级、不外泄异常
- 慢调用判定与 `slow_calls` 统计不变；早停 / 节流 / 失败率记账全部复跑通过

## 真实观测（2026-08-29，按最后一个交易日 08-28 跑）

今天是周六，`sync_today` 会用 `end=2026-08-29` 这个非交易日，全市场都取不到新数据、
失败率接近 100%（早停会正确中止但测不出东西），所以按 08-28 跑。

```
synced=230 failed=15 fail_rate=6.1% marked_failed=15 aborted=None elapsed=3064.9s
tencent  {'tripped': False, 'skipped': 0, 'probes': 0, 'slow_calls': 0,  'recovered': 0}
baostock {'tripped': False, 'skipped': 0, 'probes': 0, 'slow_calls': 15, 'recovered': 0}
```

- **全程 0 次 WAF 拦截**，腾讯没有被封（0.3s 节流下 245 次请求）
- 已有 08-28 数据的 4962 只被 `last >= end` 快速跳过，不发请求
- 3005s 花在前 49 只已尝试的票上，剩余 196 只只用了约 60s（0.3s 节流地板）

**熔断器本轮没跳，因为失败只有 15 只，没到 `fail_threshold=20`。**
那 3005s 就是这 15 只退市票每只走完整条降级链的代价（约 200s/只，
baostock 15 次慢调用 + mootdx 静默超时）。这批票会在 `retry_cnt` 攒到 5 之后
被 `skip_retry_gte` 整体跳过，跨轮自愈路径已经存在，本次不额外处理。

## 数据现状

| 日期 | 行数 | 覆盖率 |
|---|---|---|
| 2026-08-21 | 5193 | 99.7% |
| 2026-08-24 | 5192 | 99.7% |
| 2026-08-25 | 5192 | 99.7% |
| 2026-08-26 | 5193 | 99.7% |
| 2026-08-27 | 5193 | 99.7% |
| 2026-08-28 | 5192 | 99.7% |

`failed_codes` 15 行（`retry_cnt` 1×1 / 2×14），`last_sync_date=2026-08-28`。

## 封禁时间线

| 时间 | 状态 |
|---|---|
| 08-27 ~ 08-28 白天 | 501，重试风暴打出来的封禁 |
| 08-28 18:33 | 200，解封 |
| 08-28 跑批中（约第 1600 只） | 501，重新被封 |
| 08-29 07:01 | 501 |
| 08-29 15:5x | 200，再次解封 |
| 08-29 观测轮全程 | 200，无拦截 |

封禁是**限流型临时封锁、会自行轮换解除**，不是永久黑名单。
0.3s 节流下 245 次请求没有触发新封禁，但样本量不足以证明 5207 次也安全。

## launchd

两个任务已 `launchctl load` 恢复：`com.huangneng.quant`（16:15 盘后）与
`com.huangneng.quant.intraday`。恢复依据是三层防护都已到位：WAF 会被识别并熔断、
上游整体不可用会早停且不推进 `last_sync_date`、失败率超阈值不写 `failed_codes`。

## 遗留

1. 单只退市票走完降级链要约 200s，15 只就是 50 分钟。跨轮靠 `skip_retry_gte=5`
   自愈，但首次遇到一批新退市票时仍会吃这个成本。
2. 0.3s 节流在全量 5207 请求下是否仍能避开 WAF，未经验证。
3. 快照通道（`hq.sinajs.cn`，600 只/请求，5207 → 9 请求/天）仍是更彻底的解法，
   但只能取当日收盘、无法回补历史，需要重写取数模型。

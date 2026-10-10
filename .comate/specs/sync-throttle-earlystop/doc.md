# 同步节流与整轮早停设计文档

## 背景

2026-08-28 诊断确认：腾讯日K接口返回 **HTTP 501**，响应体是 `waf.tencent.com` 的拦截页，
本机 IP 已被腾讯 WAF 封禁。baostock 同时报 `error_code=10002007 网络接收错误` 并伴随
`Broken pipe`。三个依赖库均正常（`HAS_MOOTDX/HAS_AK/HAS_BS` 全为 `True`），
Sina 快照通道（`hq.sinajs.cn`）不受影响——所以不是依赖问题，也不是四家同时故障。

封禁是我们自己打出来的。近一周的请求量：

| 日期 | 同步轮次 | 每轮请求规模 |
|---|---|---|
| 08-21 | 1 | 5207 只 × 最多 4 源 |
| 08-24 | 1 | 同上 |
| 08-25 | 1 | 5207 只全失败仍全量重试 |
| 08-26 | 1（跑满 17 小时被终止） | 同上 |
| 08-27 | **3**（launchd + 两次手动） | 同上 |
| 08-28 | **2** | 同上 |

失败后换源重试、整轮失败后下一轮再全量重试一遍，形成重试风暴。已卸载
`com.huangneng.quant` 与 `com.huangneng.quant.intraday` 两个 launchd 任务止血。

本次只做两件事：**请求节流**与**整轮早停**，目标是封禁解除后不再被封。
不改取数架构（见范围外）。

## 需求场景与处理逻辑

### 场景一：单位时间请求过密

现状 `_fetch_kline_online` 对每只票立即发起请求，无任何间隔。健康日实测
0.11s/只（08-18，575s/5207 只），瞬时 QPS 约 9。这个速率本身 WAF 容忍了很多天，
真正致命的是叠加重试后的**日总量**，但仍需一道 QPS 上限兜住突发。

处理：按**源**维度限速。每个源记录上次请求时刻，不足最小间隔则先 sleep。
按源而非全局，是因为四个源是不同的 host，各自的限流策略独立，
不该因为腾讯要限速而拖慢 baostock。

默认 `min_request_interval_s = 0.1`。选这个值是因为健康日的自然间隔已经是 0.11s，
默认值不会让正常日子变慢，只在降级重试导致请求变密时起作用。

### 场景二：上游整体不可用时仍打满全场

现状即使前 300 只票全部失败，仍会把剩余 4900 只逐一撞完。08-28 那轮
`synced=303 failed=4904`，花了 4 小时，其中绝大部分是 baostock 每只 75 秒的超时等待，
且每一次请求都在加深封禁。

处理：累计尝试数达到 `early_stop_min_samples` 后开始检查失败率，
超过 `early_stop_fail_rate` 即**中止本轮**，返回 `aborted` 标记与原因。

默认 `early_stop_min_samples = 300`、`early_stop_fail_rate = 0.9`。
300 只的样本量足以区分"上游全挂"与"开头恰好撞上一批退市票"——健康日失败率仅
0.2~0.3%，即 300 只里约 1 只。阈值取 0.9 而非 0.5，是为了避免误杀"部分源可用"
的半健康状态（如 08-24 的 49.3%，那天仍然补进了 2482 只，有价值）。

### 场景三：被 WAF 封禁时无法从日志识别

现状腾讯返回 501 拦截页后，`json.loads` 抛异常被 try 吞掉，只返回 `None`，
日志里看不出是限流封禁还是普通取数失败。08-28 之所以查了很久才定位，就是因为这个。

处理：在 `tencent_kline.get_kline` 中识别 WAF 特征（HTTP 501 或响应体含
`waf.tencent.com`），打印一行明确的告警。仅日志，不改控制流。

## 架构与技术方案

### 节流

`data_hub/router.py` 新增模块级节流器，按源实例持有：

```python
class _Throttle:
    """按源限速：保证同一源的两次请求间隔不小于 min_interval 秒。"""

    def __init__(self, min_interval: float = 0.1):
        self.min_interval = min_interval
        self._last = 0.0

    def wait(self):
        if self.min_interval <= 0:
            return
        gap = time.time() - self._last
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last = time.time()
```

`Router.__init__` 里为每个源建一个，`_fetch_kline_online` 在调用前 `wait()`：

```python
        self._throttles = {}   # __init__ 中初始化为空，按需建
        ...
        # _fetch_kline_online 内，紧邻 src.get_kline 之前
        th = self._throttles.get(name)
        if th is not None:
            th.wait()
```

节流器在 `Router` 上而非 breaker 上，因为它是跨轮的连接卫生，与轮内熔断无关。
`min_request_interval_s` 作为 `Router.__init__` 参数，默认 0.1。

### 整轮早停

`sync_kline_db` 循环内每只票处理完后检查：

```python
            attempted = synced + len(failed)
            if (attempted >= early_stop_min_samples
                    and len(failed) / attempted > early_stop_fail_rate):
                aborted = (f'失败率 {len(failed)/attempted:.1%} 超过 '
                           f'{early_stop_fail_rate:.0%}（已尝试 {attempted} 只），'
                           f'判定上游不可用，中止本轮以免加深限流')
                print(f"  [sync] 早停：{aborted}")
                break
```

`aborted` 初始为 `None`，返回值带上它。注意早停后**仍走轮末的失败率判定**，
因此 `marked_failed` 必然为 0——早停条件（>90%）严格强于记账条件（≤20%），
两者不会冲突。

`meta_set('last_sync_date', end)` 在早停时**不应写入**：本轮并未覆盖全市场，
写入会让后续增量误判起点。这是与现有行为的一处差异，需显式处理。

### WAF 识别

`data_hub/sources/tencent_kline.py` 的 `get_kline` 内，`json.loads` 之前：

```python
            resp = self._sess.get(KLINE_URL, params={'param': param}, timeout=10)
            if resp.status_code == 501 or 'waf.tencent.com' in resp.text[:500]:
                print(f"  [tencent] 请求被 WAF 拦截（HTTP {resp.status_code}），"
                      f"IP 可能已被限流封禁，建议停止同步等待解封")
                return None
            data = json.loads(resp.text)
```

## 影响文件

- `data_hub/router.py`（修改）
  - 新增模块级 `_Throttle` 类。
  - `Router.__init__` 新增 `min_request_interval_s: float = 0.1` 参数，构建 `self._throttles`。
  - `_fetch_kline_online` 在每次源调用前 `wait()`。
  - `sync_kline_db` 新增 `early_stop_min_samples: int = 300` /
    `early_stop_fail_rate: float = 0.9`；循环内早停检查；早停时不写
    `last_sync_date`；返回值新增 `aborted`。
- `data_hub/sources/tencent_kline.py`（修改）：WAF 特征识别与告警。
- `data_hub/api.py`（修改）：透传两个早停参数。
- `data_hub/__main__.py`（修改）：早停时打印 `aborted` 原因。

## 边界条件与异常处理

- **`min_request_interval_s = 0` 或负数** → `wait()` 直接返回，等价于无节流，
  便于测试与临时关闭。
- **节流不叠加到熔断跳过的源**：`should_skip()` 为真时直接 `continue`，
  不会走到 `wait()`，被熔断的源不产生任何延迟成本。
- **早停样本量不足** → `attempted < 300` 时不检查，避免小盘子误判。
- **`codes` 总数少于 300**（如手动指定少量票补拉）→ 永远不触发早停，
  行为与现状一致。
- **早停与 `skipped_dead` 的关系**：`skipped_dead` 不计入 `attempted`
  （它们没发起请求），不会稀释失败率。
- **早停后 `last_sync_date` 不更新** → 下一轮仍从原起点增量，不会跳过未同步的日期。
- **健康日不受影响**：失败率 0.2~0.3%，早停永不触发；节流间隔 0.1s 低于自然间隔
  0.11s，不增加耗时。需在验证阶段实测确认。

## 数据流（改造后）

```text
sync_kline_db(start, end, full=False)
  ├─ 读 failed_codes → skip_set                                   [R4.2 既有]
  ├─ 构建 breakers（每轮新建）                                     [熔断 既有]
  └─ for code in codes:
       ├─ code in skip_set → skipped_dead += 1, continue（不计入 attempted）
       ├─ _fetch_kline_online:
       │    for (name, src) in 源链:
       │      ├─ breaker.should_skip() → continue（无节流开销）      [熔断 既有]
       │      ├─ throttle.wait()（按源限速）                        [本次新增]
       │      ├─ WAF 特征 → 告警并返回 None                         [本次新增]
       │      └─ breaker.on_call(elapsed, raised)                   [熔断 既有]
       ├─ 成功 → upsert_kline + clear_failed
       ├─ 失败 → failed.append(code)
       └─ attempted >= 300 且失败率 > 90% → 早停 break              [本次新增]
  └─ 轮末：
       ├─ 失败率 <= 20% → 批量 mark_failed                          [自锁防护 既有]
       ├─ 早停 → 不写 last_sync_date                                [本次新增]
       └─ 返回 {..., aborted}                                       [本次新增]
```

## 预期结果

以 08-28 那轮回放：前 300 只票失败率已达约 96%（`synced=303` 是整轮 5207 只的结果，
开头 200 只时 `synced=192 failed=8`——需按实际序列重算，但结束时 94.2% 说明主体是失败），
早停会在 300~600 只之间触发，本轮耗时从 **14361 秒降到几百秒**，
对腾讯与 baostock 的请求量降到约十分之一。

日志将出现：
```
  [tencent] 请求被 WAF 拦截（HTTP 501），IP 可能已被限流封禁，建议停止同步等待解封
  [sync] 早停：失败率 96.0% 超过 90%（已尝试 300 只），判定上游不可用，中止本轮以免加深限流
```

健康日（如 08-18 的 575s）行为不变：失败率 0.3%，早停不触发；节流 0.1s 不高于
自然间隔，耗时基本不变。

## 验证方式

1. 单测 `_Throttle`：`min_interval=0.05` 连续 `wait()` 10 次，断言总耗时 ≥ 0.45s；
   `min_interval=0` 时 10 次耗时 ≈ 0。
2. 单测早停：注入全失败假源、500 只票，断言在 300~310 只之间 `break`，
   源被调用次数远小于 500，返回值含 `aborted`。
3. 单测不误早停：失败率 50%、500 只票，断言跑满全程、`aborted` 为 `None`。
4. 单测样本量保护：200 只票全失败，断言不早停（样本不足）、跑满全程。
5. 单测 `skipped_dead` 不稀释失败率：预置死码使其被跳过，断言早停判定只看真实尝试。
6. 单测早停不写 `last_sync_date`：早停后断言 `meta_get('last_sync_date')` 未被更新；
   正常跑完则更新。
7. 单测 WAF 识别：伪造 HTTP 501 与含 `waf.tencent.com` 的响应体，
   断言返回 `None` 且打印告警；正常响应不受影响。
8. 回归：熔断被跳过的源不产生节流延迟（`should_skip` 为真时 `wait()` 不被调用）。
9. 回归：失败率记账逻辑（自锁防护）与 `skipped_dead` 行为不变。
10. 真实观测：封禁解除后跑一轮，记录耗时与 `aborted`，与 575s 基线对比确认健康日无退化。

## 范围外（本次不做）

- **不改取数架构**。日K逐只查询（5207 只 × 每日一轮）是请求量的根源，
  Sina 快照能一次拿 600 只，若日常增量只需当日一根K线，改用快照通道逐日累积
  可把请求量从 5207 次降到 9 次。这是更彻底的方案，但需先确认快照字段
  （open/high/low/close/volume/amount）是否满足 `detect_today_signal` 与特征提取，
  改动面也大得多。用户 2026-08-28 决定先只做节流与早停。
- **不改熔断的 `on_success` 语义**。当前单次成功即解除熔断，导致间歇性慢的源
  （如 08-28 的 baostock）无法稳定熔断。早停在很大程度上覆盖了这个损失
  （不再打满全场），故本次不动。若恢复后仍观察到反复熔断/解除，再单独处理。
- 不给 breaker 统计增加全源输出（当前只打印 tripped 的源）。
- 不引入并发（用户已明确不做）。
- 不调整各源 timeout 与内部重试。
- 不恢复 launchd 任务——待封禁解除并验证本次改动后再手动 `launchctl load`。
- 不碰选股策略与评分权重。

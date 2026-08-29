# 熔断判定补全：区分「源不可用」与「这只票没数据」

## 问题

2026-08-28 的一轮同步跑了 44752s（12.4 小时），是健康日基线 575s 的 78 倍。
根因不是节流，也不是早停阈值设得不对，而是**熔断器判定漏了一整类失败**。

`_SourceBreaker.on_call(elapsed, raised)`（`data_hub/router.py:89`）只认两种失败：

- `raised=True`：源抛了异常
- `elapsed >= slow_call_s`（3.0s）：源慢

腾讯被 WAF 拦截时返回 HTTP 501，实测耗时 **0.07s**，既不抛异常也不慢，
于是落到 `on_success()` 分支。后果：

1. 腾讯 100% 不可用，熔断器一次没跳，5207 只票逐个照常请求被封端点
2. 每只票在腾讯空手而归 → 全部下沉 mootdx / akshare / baostock，
   12 小时耗在这条降级链上（慢区间 43268s，占全轮 97%）
3. 持续打 WAF 端点让封禁自我延续——本轮开跑前刚探到 200，
   跑到第 1600 只左右重新被封，跑完再探仍是 501

第二个独立缺陷：baostock 到第 8.9 小时才熔断一次。`on_success()` 一次快速调用
就把 `tripped` 和 `consecutive_fails` 全清零，而 baostock 的失败形态是
「慢失败夹杂快速空返回」，连续计数永远攒不到 20。

## 技术方案

### 为什么不用「空返回一律计为失败」

这是最直观的改法，但会误伤。降级链是短路的——腾讯成功的票根本不会调用
baostock，所以 baostock 只会收到「前三个源都失败」的硬骨头，这些大多是
退市/长期停牌票，本来就该返回空。健康日下这批票扎堆落到 baostock，
连续空返回轻易超过 20，baostock 会被无故熔断。

正确的区分维度不是「有没有数据」，而是**「拿不到数据的原因是源侧还是标的侧」**。
这个信息只有源自己知道，必须由源显式表达。

### 方案：源侧显式抛 `SourceUnavailable`

在 `data_hub/sources/base.py` 新增异常类型：

```python
class SourceUnavailable(Exception):
    """源整体不可用（被封禁 / 限流 / 认证失效），与「这只票没数据」是两件事。

    返回 None 表示"该标的在本源查无数据"，是正常业务结果；
    抛本异常表示"本源现在谁都查不了"，应立即计入熔断。
    """
```

`tencent_kline.get_kline` 的 WAF 分支由 `return None` 改为 `raise SourceUnavailable(...)`。
`_fetch_kline_online` 已有的 except 分支会捕获它 → `on_call(raised=True)` →
连续 20 次后熔断，之后每 200 只只试探一次。

异常路径上要避免日志刷屏——本轮日志里同一句 WAF 告警印了 380+ 次。
熔断后调用就停了，条数天然收敛到 ~20 条，但 `_fetch_kline_online` 的
`取数异常，降级` 那行对 `SourceUnavailable` 应改为不打印（源自己已经打过告警了）。

### 恢复判定：要求连续多次成功才解除熔断

`_SourceBreaker` 新增 `recover_threshold: int = 3` 与 `consecutive_successes` 计数：

```python
    def on_success(self):
        self.consecutive_fails = 0
        self.consecutive_successes += 1
        if not self.tripped:
            return
        if self.consecutive_successes >= self.recover_threshold:
            print(f"  [breaker] {self.name} 连续 {self.consecutive_successes} 次成功，解除熔断")
            self.tripped = False
            self.calls_since_probe = 0
        else:
            # 试探成功但还不够判定恢复：让紧邻的下一只票继续试探，
            # 形成一小段连续探测。真健康时几只票就能恢复，
            # 时好时坏的源则会在这里被挡住，不会靠单次侥幸解除熔断
            self.calls_since_probe = self.probe_interval

    def on_error(self):
        self.consecutive_successes = 0
        self.consecutive_fails += 1
        if not self.tripped and self.consecutive_fails >= self.fail_threshold:
            self.tripped = True
            self.calls_since_probe = 0
            print(...)
```

`stats()` 增加 `recovered` 次数，便于事后判断是"跳了就没再起来"还是"反复抖动"。

### 节流间隔从 0.1s 提到 0.3s

0.1s（10 req/s）没能避开再次封禁——本轮跑到第 1600 只左右腾讯就重新返回 501。
封禁与请求速率的因果关系没有直接证据（也可能是前几天封禁的余波未过），
但提到 0.3s（3.3 req/s）的代价很小：全轮理论下限从 520s 增至 1560s（26 分钟），
而全轮真正的耗时瓶颈在降级链而非腾讯。这是便宜的保险。

## 影响文件

| 文件 | 改动类型 | 涉及函数 |
|---|---|---|
| `/Users/huangneng/ComateProjects/QuackStock/data_hub/sources/base.py` | 新增 | `SourceUnavailable` 异常类 |
| `/Users/huangneng/ComateProjects/QuackStock/data_hub/sources/tencent_kline.py` | 修改 | `TencentKlineSource.get_kline` WAF 分支改为 raise |
| `/Users/huangneng/ComateProjects/QuackStock/data_hub/router.py` | 修改 | `_SourceBreaker.__init__` / `on_success` / `on_error` / `stats`；`_fetch_kline_online` 的 except 分支；`Router.__init__` 默认节流值；`sync_kline_db` 新增 `breaker_recover_threshold` |
| `/Users/huangneng/ComateProjects/QuackStock/data_hub/api.py` | 修改 | `sync_kline_db` 透传 `breaker_recover_threshold` |
| `/Users/huangneng/ComateProjects/QuackStock/data_hub/__main__.py` | 修改 | 熔断统计输出加 `recovered` |

选股策略逻辑（cond1/cond2、25 亿成交额预筛）不动。

## 边界与异常

- `SourceUnavailable` 必须只在**源级**故障时抛。腾讯当前只有 WAF 一处判定，
  不要顺手把 `json.loads` 失败也归进来——那可能只是单只票的脏数据。
- 熔断是轮内状态，不跨轮持久化，本次不改这一点。跨轮的"死码"名单仍归
  `failed_codes` 负责，两者维度不同。
- `recover_threshold` 的连续探测会让熔断源在恢复期连续吃到 `probe_interval`
  被置满的效果，需确认 `should_skip` 的自增逻辑不会把 `skipped` 统计算歪。
- `breakers=None` 的按需补拉路径（`get_kline` 单只票场景）行为必须完全不变，
  `SourceUnavailable` 在那里应被 except 吞掉并正常降级。
- 空返回仍然是正常业务结果，退市票不得因此被判为源故障。

## 数据流

```
sync_kline_db
  └─ 每只 code → _fetch_kline_online(code, breakers)
       └─ 遍历 tencent → mootdx → akshare → baostock
            ├─ breaker.should_skip()?  → 跳过（不付节流成本）
            ├─ throttle.wait()
            ├─ src.get_kline()
            │    ├─ 正常 DataFrame        → on_call(elapsed, raised=False) → on_success
            │    ├─ None（该票无数据）     → on_call(elapsed, raised=False) → on_success  ← 保持
            │    └─ SourceUnavailable     → on_call(elapsed, raised=True)  → on_error    ← 新增
            └─ 慢调用（≥3s）              → on_error（已有）
```

## 预期结果

腾讯被封时，第 20 只票就熔断，之后 5187 只只发 26 次试探请求，
而不是 5207 次。全轮耗时回到降级链本身的量级，且不再持续给 WAF 喂请求。
baostock 这类时好时坏的源不会再靠单次快速调用解除熔断。

## 不在本次范围

改走快照通道（`hq.sinajs.cn`，600 只/请求，5207 请求/天 → 9 请求/天）是
真正的架构解法，但它只能拿当日收盘数据，无法回补历史空洞，且要重写
`sync_kline_db` 的取数模型。等本次熔断修完、观察一轮真实耗时后再决定。


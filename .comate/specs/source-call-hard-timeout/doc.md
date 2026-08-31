# 取数调用硬超时：让永不返回的源无法挂死流水线

## 问题

2026-08-29 20:18 起跑的存量修复进程，在 22:02 之后彻底挂死，
到 08-31 09:26 被杀掉时已空转 **35 小时**，累计 CPU 时间只有 **8.38 秒**。

`lsof` 显示该进程持有：

```
TCP 192.168.1.15:59700->114.94.20.92:10030 (CLOSED)
```

10030 是通达信端口。连接已经 `CLOSED`，而进程仍阻塞在 `recv` 上。
`mootdx_source.py:59` 调用 `self.client.bars(...)` 没有任何超时参数，
mootdx 内部也没有给 socket 设超时，所以半关闭的连接会让读操作永久阻塞。

**熔断器对此完全无效。** `_SourceBreaker.on_call(elapsed, raised)` 只能评估
**已完成**的调用；一个永不返回的调用连 `on_call` 都进不去，
`consecutive_fails` 不会增加，`tripped` 永远不会置位。
之前做的节流、早停、WAF 识别、失败率记账全都建立在「调用会返回」这个前提上。

风险是现实的：`run_daily.sh` 在 16:15 调用 `python -m data_hub sync_today`，
若撞上同样的半关闭连接，`sync_today` 会挂死，后面的 `daily_select.py`
永不执行，也就没有邮件和 ServerChan 推送——而且不会有任何报错，
只是安静地什么都不发生。

## 为什么不逐个源加超时

`tencent_kline.py` 有 `timeout=10`，但另外三个源的超时能力不受我们控制：

- mootdx 的 `bars()` 不接受 timeout 参数，内部 socket 也没设
- akshare 内部大量端点用 `requests` 且不传 timeout
- baostock 是自己实现的 socket 协议

逐个源去改要么改不到（第三方库内部），要么得魔改依赖。
需要一个**与源无关、位置更外层**的兜底。

## 技术方案

在 `_fetch_kline_online` 里给每次 `src.get_kline(...)` 套一个基于
`signal.setitimer` 的硬超时。SIGALRM 会打断阻塞的系统调用，
Python 随即在调用点抛出异常，落进已有的 `except Exception` 分支，
按现有逻辑降级到下一个源，并让熔断器记一次失败。

```python
class _CallTimeout:
    """给单次取数调用套硬超时。

    signal.setitimer 只能在主线程用，且依赖 SIGALRM（Windows 没有）。
    不满足条件时退化为无超时——不能因为拿不到看门狗就让取数整体失败。
    """

    def __init__(self, seconds: float):
        self.seconds = seconds
        self.armed = False

    def __enter__(self):
        if self.seconds <= 0 or not hasattr(signal, 'SIGALRM'):
            return self
        if threading.current_thread() is not threading.main_thread():
            return self
        self._old = signal.signal(signal.SIGALRM, self._fire)
        signal.setitimer(signal.ITIMER_REAL, self.seconds)
        self.armed = True
        return self

    def _fire(self, sig, frm):
        raise SourceCallTimeout(f'取数调用超过 {self.seconds}s 未返回')

    def __exit__(self, *exc):
        if self.armed:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self._old)
        return False
```

超时值取 `source_call_timeout_s = 30`：腾讯自身 timeout=10，
baostock 最慢的正常调用实测 75s 属于病态（早已被 `slow_call_s=3.0` 判为慢调用），
30s 足够宽松，不会误杀正常取数。

超时抛出的 `SourceCallTimeout` 单独定义，不复用 `SourceUnavailable`：
一次超时说明「这次调用卡住了」，不等于「整个源不可用」。
但它同样走 `on_call(raised=True)`，连续 20 次就会熔断——
判定交给熔断器，不在这里下结论。

## 影响文件

| 文件 | 改动类型 | 涉及函数 |
|---|---|---|
| `/Users/huangneng/ComateProjects/QuackStock/data_hub/sources/base.py` | 新增 | `SourceCallTimeout` 异常 |
| `/Users/huangneng/ComateProjects/QuackStock/data_hub/router.py` | 修改 | 新增 `_CallTimeout`；`_fetch_kline_online` 套用；`sync_kline_db` 新增 `source_call_timeout_s` 并透传 |
| `/Users/huangneng/ComateProjects/QuackStock/data_hub/api.py` | 修改 | 透传 `source_call_timeout_s` |
| `/Users/huangneng/ComateProjects/QuackStock/data_hub/__main__.py` | 修改 | 输出超时次数统计 |

选股策略逻辑（cond1/cond2、25 亿预筛）不改。

## 边界与异常

- 非主线程调用时静默退化为无超时。`tracker_report` 用了 tqdm，
  若将来有线程化的调用点，不能因此让取数直接失败。
- 嵌套使用会互相覆盖 itimer。当前 `_fetch_kline_online` 是唯一使用点，
  且不递归，但 `__exit__` 必须无条件恢复原 handler，避免污染全局。
- 超时后被打断的源可能留下坏连接（mootdx 的 client 是复用的）。
  这一点不在本次处理：熔断器会在连续失败 20 次后跳闸跳过该源，
  比重建连接更保守。作为遗留记录。
- 超时计入 `slow_calls` 与 `consecutive_fails`，与既有慢调用判定一致。
- `signal.setitimer` 的精度是秒级，不需要更细。

## 数据流

```
_fetch_kline_online(code)
  └─ 逐源:
       ├─ breaker.should_skip()?      → 跳过
       ├─ throttle.wait()
       ├─ with _CallTimeout(30):
       │     src.get_kline(code, ...)
       │       ├─ 正常返回              → on_call(elapsed, raised=False)
       │       ├─ 抛异常                → on_call(elapsed, raised=True)
       │       └─ 30s 未返回 → SIGALRM → SourceCallTimeout
       │                                → on_call(elapsed, raised=True)  ← 新增
       └─ 全源失败 → 返回 None
```

## 预期结果

任何单次取数调用的墙钟耗时上限为 30s。挂死 35 小时这种情况不再可能发生。
连续超时的源会在 20 次（最多 600s）内被熔断，之后每 200 只只试探一次。

## 验证方式

用一个 `get_kline` 里 `time.sleep(60)` 的假源，断言：
调用在约 30s 内返回、抛出 `SourceCallTimeout`、降级到下一个源、
熔断器记到一次失败、itimer 与 SIGALRM handler 被正确恢复。

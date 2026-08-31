# 取数调用硬超时 — 实施总结

## 结论

给每次 `src.get_kline(...)` 套上基于 `signal.setitimer` 的硬超时（默认 30s），
任何单次取数调用的墙钟耗时都有上限。挂死 35 小时那种情况不再可能。

验证：假源 `sleep(60)` 配 1s 超时，实测 1.02s 内抛出 `SourceCallTimeout`
并降级到下一个源取到数据；连续超时 60 只票时，该源被调用 20 次后熔断，
健康的兜底源未被误熔断。

launchd 两个任务仍为 loaded，今天 16:15 的跑批已受保护。

## 根因

`mootdx_source.py:59` 的 `self.client.bars(...)` 不接受 timeout 参数，
mootdx 内部也没给 socket 设超时，半关闭的连接会让 `recv` 永久阻塞。
`lsof` 抓到挂死进程持有 `->114.94.20.92:10030 (CLOSED)`——通达信端口，
连接已关闭而进程仍卡在读上，37 小时累计 CPU 只有 8.38 秒。

**熔断器对此完全无效**：`on_call(elapsed, raised)` 只能评估已完成的调用，
一个永不返回的调用连 `on_call` 都进不去，`consecutive_fails` 不增长，
`tripped` 永远不置位。此前做的节流、早停、WAF 识别、失败率记账
全都建立在「调用会返回」这个前提上。

逐个源加超时行不通：mootdx 的 `bars()` 不收 timeout，akshare 内部
大量端点不传 timeout，baostock 是自实现 socket 协议。只能在取数层统一兜底。

## 改动清单

| 文件 | 改动 |
|---|---|
| `data_hub/sources/base.py` | 新增 `SourceCallTimeout` 异常 |
| `data_hub/router.py` | 新增 `_CallTimeout` 上下文管理器；`Router.__init__` 新增 `source_call_timeout_s=30.0` 与 `_timeouts`；`_fetch_kline_online` 套用看门狗并统计超时；`sync_kline_db` 新增同名参数、返回值带 `timeouts`；baostock 预登录也套超时 |
| `data_hub/api.py` | 透传 `source_call_timeout_s`，docstring 补 `timeouts` |
| `data_hub/__main__.py` | 有超时发生时打印 `call_timeouts=源(x次数)` |

选股策略逻辑（cond1/cond2、25 亿预筛）未改动。

## 为什么用 SIGALRM 而不是线程

`signal.setitimer` 打断阻塞系统调用，Python 随即在调用点抛异常，
落进已有的 `except` 分支，天然复用现有的降级与熔断逻辑。
线程方案需要 `ThreadPoolExecutor` + `future.result(timeout=)`，
但挂死的线程会泄漏，且各源共享可变状态（mootdx 复用 client、
baostock 是模块级全局），线程化本身就不安全。

代价是 SIGALRM 只能在主线程用，Windows 也没有。不满足条件时
**静默退化为无超时**——不能因为拿不到看门狗就让取数整体失败。

`__exit__` 无条件清零 itimer 并恢复原 handler：调用体自己抛异常时也必须清掉，
否则闹钟会在后续任意位置炸开，污染全局信号状态。这一点单独有单测覆盖。

## 超时值 30s 的依据

腾讯自身 `timeout=10`；baostock 最慢的正常调用实测 75s 已属病态，
早就被 `slow_call_s=3.0` 判为慢调用并计入熔断。30s 足够宽松不误杀，
又能保证连续超时的源在 20 次（最多 600s）内被熔断。

超时抛 `SourceCallTimeout` 而不复用 `SourceUnavailable`：
一次调用卡住不等于整个源已死，源可能只是某只票的连接坏了。
判定交给熔断器，不在这里下结论。

## 单测结果（全通过，共九套）

看门狗本身：

- `sleep(3)` 配 1s 超时 → 1.00s 抛 `SourceCallTimeout`
- 超时后 itimer 归零、SIGALRM handler 复原
- 正常快速调用不受影响，退出后状态干净
- 调用体自己抛异常时，itimer 与 handler 同样被恢复
- `seconds <= 0` 关闭看门狗
- 非主线程中不抛异常、也不设超时
- 模拟无 `SIGALRM` 平台时静默退化

接入后：

- 挂死源 `sleep(60)` + 1s 超时 → 1.02s 降级成功，超时计数 1，熔断连续失败 1
- 60 只票连续超时 → 该源被调用 20 次后熔断，健康源未被误熔断
- `breakers=None` 的按需补拉路径同样受保护（1.01s 返回）
- 正常源不产生超时计数
- CLI：无超时时输出不新增行；有超时时打印 `call_timeouts=mootdx(x23) baostock(x4)`

既有七套（WAF、熔断恢复、空返回、节流、早停、akshare 单位、半截 K 线守卫）
复跑全部通过。

## 验证中发现并修掉的额外缺陷

`sync_kline_db` 开头有一句无条件的 baostock 预登录。实测 10 只票的小规模同步
墙钟 82.1s，而循环内部 `elapsed_s` 只有 6.7s——**75s 花在进入循环之前的
baostock 登录上**，而看门狗只包了 `get_kline`，管不到这里。
baostock 若在登录时永久阻塞，`sync_today` 会在循环开始前就挂死。

已给预登录也套上 `_CallTimeout`。同样的 10 只票再跑：墙钟 16.1s，
`1.61s/只`（原 `4.11s/只`）。

## 实盘验证（2026-08-31 10:0x，盘中）

各源可用性基线：

| 源 | 状态 |
|---|---|
| 腾讯日K | 200，2.88s，无 WAF |
| 新浪快照 | 200，0.06s |
| akshare | **已恢复** |
| baostock | 仍不可用（`error_code=10002007`） |
| mootdx | 仍不可用（连不上任何 TDX 服务器） |

10 只票增量同步（`end` 取今天 08-31，盘中）：

```
synced=0 failed=0 skipped_unsettled=10 aborted=None timeouts={} elapsed_s=5.0
库内 08-31 行数 = 0
```

`skipped_unsettled=10` 且库内没有 08-31 行——盘中不落库当日 K 线的守卫按预期工作。
无超时发生，说明 30s 阈值不会误杀当前可用的源。

## 遗留

1. **超时打断后源可能留下坏连接**。mootdx 的 client 是复用的，
   被 SIGALRM 打断后连接状态未知。本次不处理：熔断器会在连续失败 20 次后
   跳过该源，比盲目重建连接更保守。
2. **akshare 已恢复**，可以用它取历史精确成交额来补 08-25 ~ 08-27 三天的选股
   （`scripts/backfill_prefilter_cache.py` 目前只用 baostock，而 baostock 仍挂）。
3. mootdx 的 `vol` 单位仍未验证（源不可用），且库中至今没有 mootdx 写入的行。
4. 备份库 `kline.db.bak_before_volfix_*`、`kline.db.bak_before_partialfix_*`、
   `kline.db.bak_20260715` 均未纳入版本控制，确认无误后可删除。

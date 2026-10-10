# failed_codes 自锁防护设计文档

## 背景

R4.2 的死码跳过机制正在把全市场推向自锁。08-26 盘前采集的 `failed_codes` 状态：

| retry_cnt | 只数 |
|---|---|
| 1 | 2690 |
| 2 | 2118 |
| 3 | 374 |
| 4 | **25** |
| 合计 | **5207（= 全市场每一只票）** |

跳过阈值是 `skip_retry_gte=5`。最大值已到 4，**再来一个上游中断的交易日就会有票达到 5**，
此后增量同步会在 7 天窗口内跳过它们，且达标的票会持续增多。

### 状态更新（2026-08-27 盘前复核）

**自锁已经开始。** 08-26 盘后同步之后：

| retry_cnt | 只数 |
|---|---|
| 1 | 929 |
| 2 | 2356 |
| 3 | 378 |
| 4 | 18 |
| 5 | **7 ← 已达跳过阈值** |
| 合计 | 3688 |

已有 7 只票 `retry_cnt=5`，下一轮增量同步就会跳过它们。总行数从 5207 降到 3688，
是因为 08-26 有 1519 只票取数成功触发了 `clear_failed`——这也印证了
`clear_failed` 是自锁的唯一出口，必须保持即时调用。

同时发现 08-26 的同步至今（08-27 09:26）**仍在运行**，已持续超过 17 小时
（PID 46255，16:17 启动），导致 08-26 的选股完全没跑，`.last_run_date` 仍停在
`2026-08-24`。`kline` 覆盖：08-24 = 2790、08-25 = 1517、08-26 = 1518，
连续三个交易日数据严重不全。

结论不变，紧急程度上升。


更糟的是会形成自锁：被跳过的票不再发起取数，也就永远不会有成功记录去调
`clear_failed`，`retry_cnt` 只能停在原地等 7 天窗口过期。最坏情况是整轮同步跳过全市场。

根因：`sync_kline_db` 在每只票四源全无数据时无条件调 `mark_failed`，
隐含假设"连续失败 = 这只票本身有问题"，没有区分：

- **标的死了**（退市/长期停牌）→ 该记账，跳过它有收益
- **上游挂了**（数据源不可用）→ 不该记账，这是全市场性质的问题

历史数据清楚地区分了这两种情形。定义 `attempted = synced + failed`，失败率如下：

| 日期 | synced | failed | 失败率 | 性质 |
|---|---|---|---|---|
| 08-18 | 5191 | 16 | **0.3%** | 上游健康，16 只是真死码 |
| 08-19 | 5195 | 12 | **0.2%** | 上游健康 |
| 08-20 | 4742 | 103 | 2.1% | 上游基本健康 |
| 08-17 | 4436 | 586 | 11.7% | 腾讯不稳 |
| 08-21 | 3888 | 1319 | 25.3% | mootdx 静默超时 |
| 08-24 | 2482 | 2416 | **49.3%** | 上游大面积不可用 |
| 08-25 | 0 | 5207 | **100%** | 全链路中断 |

真死码在健康日只有 12–16 只，占比不到 0.3%。失败率上到两位数一定是上游问题。

## 需求场景与处理逻辑

单一场景：一轮增量同步结束时，判断本轮的失败该不该记进 `failed_codes`。

处理逻辑：**把 `mark_failed` 从循环内延后到轮末，按本轮整体失败率决定是否落库。**

- 失败率 ≤ `mark_failed_max_fail_rate`（默认 0.2）→ 视为"上游健康、这些票确实有问题"，
  正常记账。
- 失败率 > 阈值 → 视为上游故障，**整轮不写 `failed_codes`**，只打印告警。

`clear_failed` 保持在循环内即时调用不变——取数成功是无歧义的好信号，
越早清零越好，且它是自锁的唯一出口，不能延后。

阈值取 0.2 的依据：健康日失败率 ≤ 0.3%，与 0.2 之间有近两个数量级的余量；
而最轻微的上游异常（08-17 的 11.7%）已经接近这个量级，08-21 的 25.3% 会被正确拦下。
取 0.2 而非更紧的 0.05，是为了容忍单个源短暂抖动的日子仍能正常记账。

## 架构与技术方案

`sync_kline_db` 内改两处。

第一处，循环内不再直接写库，只累积到已有的 `failed` 列表：

```python
            df = self._fetch_kline_online(code, real_start, end, breakers=breakers)
            if df is None or df.empty:
                failed.append(code)          # 仅累积，落库延后到轮末统一判定
                continue
            df = df.copy()
            df['code'] = code
            self.db.upsert_kline(df)
            self.db.clear_failed(code)       # 成功即清零，保持即时——这是自锁的唯一出口
            synced += 1
```

第二处，轮末按失败率决定是否落库：

```python
        attempted = synced + len(failed)
        fail_rate = (len(failed) / attempted) if attempted else 0.0
        marked = 0
        if failed and fail_rate <= mark_failed_max_fail_rate:
            for code in failed:
                self.db.mark_failed(code, 'empty_from_all_sources')
            marked = len(failed)
        elif failed:
            print(f"  [sync] 失败率 {fail_rate:.1%} > {mark_failed_max_fail_rate:.0%}，"
                  f"判定为上游故障而非个股问题，本轮 {len(failed)} 只失败不计入 failed_codes")
        self.db.meta_set('last_sync_date', end)
        return {'synced': synced, 'failed': len(failed), 'skipped_dead': skipped_dead,
                'fail_rate': round(fail_rate, 4), 'marked_failed': marked,
                'breaker': {n: b.stats() for n, b in breakers.items()},
                'failed_codes': failed[:20], 'elapsed_s': round(time.time() - t0, 1)}
```

副作用：`mark_failed` 由 5207 次单条写入变为轮末批量写入，WAL 下开销更低。

## 影响文件

- `data_hub/router.py`（修改）：`sync_kline_db()` 新增 `mark_failed_max_fail_rate: float = 0.2`
  入参；`mark_failed` 调用点从循环内移到轮末；返回值新增 `fail_rate` / `marked_failed`。
- `data_hub/api.py`（修改）：透传新参数。
- `data_hub/__main__.py`（修改）：打印 `fail_rate` 与 `marked_failed`，让日志能看出
  本轮失败是否被记账。

## 存量数据清理

现有 5207 行记录基本都是上游故障期间误记的，无法逐条甄别真伪。方案：**清空
`failed_codes` 表**。

风险评估：该表是纯派生数据，不影响 `kline` 主数据，清空不丢任何行情。真死码会在
后续健康日重新累积——按每天 12–16 只、阈值 5 次计算，约 5 个交易日恢复到有效状态。
代价是这 5 天内不跳过死码，即每轮多花约 16 只票的取数时间，可忽略。

这是一次性运维动作，不写进代码。执行前会先备份该表内容到文件，便于事后追溯。

## 边界条件与异常处理

- `attempted == 0`（全部票都已是最新、直接 `continue`）→ `fail_rate` 定义为 0.0，
  `failed` 也为空，不写库，无异常。
- 失败率恰好等于阈值 → 记账（用 `<=`），边界归入"健康"一侧。
- 单只票在一轮内只会失败一次，`failed` 列表无重复，批量写入不会重复累加 `retry_cnt`。
- 上游故障日不写库 → `retry_cnt` 不增长，已在表中的记录也不会被推过阈值，
  自锁风险随之消除。
- `full=True` 的全量回补同样适用该判定；全量模式本就不读 `skip_set`，
  不受跳过逻辑影响。
- 与熔断互不干扰：熔断管"本轮内跳过哪个源"，本次改动管"本轮失败是否记账"。

## 数据流（改造后）

```text
sync_kline_db(start, end, full=False)
  ├─ 读 failed_codes → skip_set（retry_cnt>=5 且 7 日内）                [R4.2 既有]
  ├─ 构建 breakers（每轮新建）                                          [熔断 既有]
  └─ for code in codes:
       ├─ code in skip_set → skipped_dead += 1, continue
       ├─ 取数成功 → upsert_kline + clear_failed（即时，自锁出口）        [既有]
       └─ 全源无数据 → failed.append(code)（仅累积，不落库）              [本次改动]
  └─ 轮末：
       ├─ fail_rate = len(failed) / (synced + len(failed))
       ├─ fail_rate <= 0.2 → 批量 mark_failed                           [本次改动]
       └─ fail_rate >  0.2 → 打印告警，不落库                            [本次改动]
```

## 预期结果

以历史七天回放：

| 日期 | 失败率 | 改造后是否记账 |
|---|---|---|
| 08-18 / 08-19 / 08-20 | 0.2% ~ 2.1% | 记账（真死码正常累积） |
| 08-17 | 11.7% | 记账 |
| 08-21 | 25.3% | **不记账** |
| 08-24 | 49.3% | **不记账** |
| 08-25 | 100% | **不记账** |

即 08-21 之后的三天一条都不会写入，`failed_codes` 不会膨胀到 5207 行，
`retry_cnt` 也不会被推到 4。自锁不会发生。

## 验证方式

1. 单测：注入假源令失败率为 5%，断言 `marked_failed == len(failed)` 且表中行数正确。
2. 单测：失败率 100%（模拟 08-25），断言 `marked_failed == 0` 且表中行数为 0。
3. 单测：失败率 50%（模拟 08-24），断言不记账并打印告警。
4. 单测：失败率恰好 20%，断言记账（边界归健康侧）。
5. 单测：`clear_failed` 仍即时生效——先写入一批失败记录，再让取数成功，
   断言对应行立即被删除，不受轮末判定影响。
6. 回归：`attempted == 0` 的空轮不抛异常、`fail_rate` 为 0.0。
7. 回归：熔断统计与 `skipped_dead` 行为不变。
8. 存量清理后核对表为 0 行，且备份文件已生成。
9. 真实观测：08-26 盘后同步记录 `fail_rate` / `marked_failed`，确认与当日上游状态相符。

## 范围外（本次不做）

- 不调整 `skip_retry_gte=5` 与 `skip_window_days=7` 两个阈值本身。
- 不做"整轮早停"（连续 N 只全失败即中止本轮并告警）——那是耗时优化，与本次的
  数据正确性问题相互独立。
- 不改推送脚本，不区分"0 只候选"与"上游挂了"的通知文案。
- 不引入并发，不改各源 timeout。
- 不碰选股策略与评分权重。

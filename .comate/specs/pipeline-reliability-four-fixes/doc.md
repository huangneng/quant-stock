# 跑批可靠性四修：推送日期、耗时护栏、停牌零值、成交额精度不被覆盖

## 四个问题都是这几天实跑撞出来的，不是设想

| # | 问题 | 实测代价 |
|---|---|---|
| 1 | 跑批跨午夜后推送找错日期 | 09-01、09-03 两次通知丢失 |
| 2 | 「慢而不失败」的同步无人拦 | 09-03 单轮 16 小时 46 分 |
| 3 | 真停牌被当成坏缓存 | 09-03 预筛白重扫一遍 |
| 4 | 近似成交额覆盖精确值 | 09-01/02/03 连续三天手工修 3467+246+109 行 |

## 问题一：推送日期算错（优先级最高）

`run_daily.sh:20` 在脚本开头固定 `today=$(date '+%Y-%m-%d')`，
第 66 行把它传给 `daily_select.py --date "$today"`。但第 75、78 行的两个
推送脚本没有收到这个日期，它们各自去算：

`scripts/push_email.py:159` / `scripts/push_serverchan.py:90`：

```python
date_iso = os.environ.get('PUSH_DATE', '').strip() or date.today().strftime('%Y-%m-%d')
```

09-03 那轮 16:26 启动、次日 09:12 才走到推送，于是：

```
[2026-09-04 09:12:09] >>> push_email.py
[push_email] 跳过：CSV 不存在 stock_research/output/daily_selections_2026-09-04.csv
```

结果在 `..._2026-09-03.csv`，它去找 09-04。**只要跑批跨过午夜，通知必丢。**

顺带更正我之前的一个判断：09-01 推送失败我归因于网络，现在看是同一个原因。

修法：`run_daily.sh` 里 `export PUSH_DATE="$today"`。脚本已经支持这个变量，
不需要改 Python。

## 问题二：「慢而不失败」没有护栏

09-03 那轮同步的进度：

```
 200/5207  synced=196   elapsed=2077s
2000/5207  synced=1953  elapsed=34793s
3200/5207  synced=3039  elapsed=59171s   ← 16.4 小时
```

**成功率 95%**，所以早停（`early_stop_fail_rate=0.9`）永远不触发；
每次调用都在 30 秒硬超时内返回，所以 `_CallTimeout` 也不触发。
两道现有防线对「每只票平均 18 秒」这种形态完全无效。

按 18 秒/票外推，5207 只要 26 小时——比之前修掉的 mootdx 挂死
（37 小时）只好一点，而且这次是「正常工作」着拖过去的。

修法：加一条按耗时的护栏，两个维度都要，因为它们防的是不同东西：

```python
# 整轮墙钟上限：跑批有 16:15 的时间窗，拖过次日开盘就毫无意义
if max_round_seconds > 0 and time.time() - t0 > max_round_seconds:
    aborted = f'time_budget: 整轮已耗时 {…}，超过 {max_round_seconds}s 预算，剩余 {…} 只跳过'
    break
# 单票均耗时上限：早期就能识别「这轮注定跑不完」，不用等烧完预算
if attempted_now >= slow_min_samples:
    avg = (time.time() - t0) / attempted_now
    if avg > slow_avg_seconds:
        aborted = f'too_slow: 单票均耗时 {avg:.1f}s > {slow_avg_seconds}s，判定上游劣化'
        break
```

中止走既有的 `aborted` 路径，因此 `last_sync_date` 自动不推进——
这一点已经由 `lastsync-and-selection-backfill` 那个 spec 建立好了。

默认值建议：`max_round_seconds=7200`（2 小时）、`slow_avg_seconds=3.0`、
`slow_min_samples=200`。3 秒/票 × 5207 ≈ 4.3 小时仍算能接受的坏天气，
18 秒/票必须拦。

## 问题三：真停牌被判成坏缓存

`daily_select.py:65-99` 的 `_prefilter_cache_has_bad_zero_amount`：
零值抽样后若近 5 日有高成交额，就判定整份缓存不可信并删除重扫。

09-03 的缓存里有 6 只零成交额，全是真停牌：

```
sh.600929 雪天盐业   sh.688432 有研硅    sz.002731 ST萃华
sz.002870 香山股份   sz.301139 *ST元道   sz.301266 宇邦新材
```

它们停牌前成交额确实不低，于是守卫判定"缓存把高成交股写成 0"→
删缓存 → 重扫 5207 只。**守卫的逻辑没错，错在它无法区分
「数据源把有成交的票写成 0」和「这只票今天真的停牌」。**

修法：判定为异常之前先确认目标日当天是否真的有成交。零值票在
目标日的 K 线若同样是 0 成交（或该日无行）→ 真停牌，放过；
若 K 线显示当日有成交额 → 缓存确有问题，才删。

现有实现已经在调 `hub.get_kline`，改的是判据：从"近 5 日最高成交额"
改为"目标日当日成交额"。近 5 日那个判据必然把停牌股全部误判。

## 问题四：近似成交额覆盖精确值（改动最大）

`data_hub/store/kline_db.py:78-82`：

```python
c.executemany(
    f"INSERT OR REPLACE INTO kline ({','.join(cols)}) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
```

`INSERT OR REPLACE` 没有任何来源概念。腾讯不返回成交额，
`amount` 是 `均价×volume` 估的；每次 `daily_select` / 生成报告触发
按需补拉，就会把新浪或 baostock 的精确值改写成腾讯的近似值。

实测连续三天都要手工修：

| 日期 | 被改写行数 | 偏差 P50 | 偏差 max |
|---|---|---|---|
| 09-01 | 246 | +0.64% | 4.63% |
| 09-02 | 109 | +0.41% | 2.84% |
| 09-03 | 3221 | +0.06% | 3.79% |

我现在靠「跑完选股和报告再补一次」人工兜，但这个兜法有硬窗口——
新浪快照在次日 09:00 左右就翻页，过了就补不回来了（09-04 实测
`日期不符占比 99.75%`，守卫正确拦下）。人工兜不可靠。

修法：给 `kline` 表加一列记录成交额精度，写入时按优先级决定是否覆盖。

```sql
ALTER TABLE kline ADD COLUMN amt_src TEXT;   -- 'exact' / 'approx' / NULL(历史未知)
```

```python
# 精确源（新浪快照 / baostock / akshare 都直接返回成交额）写入时无条件覆盖；
# 近似源（腾讯 / mootdx 的 均价×volume）只在目标行的 amount 不是 exact 时才写。
# 其余字段（OHLC/volume）不受此限制，照常覆盖——近似只发生在 amount 上。
INSERT INTO kline (...) VALUES (...)
ON CONFLICT(code, date) DO UPDATE SET
    open=excluded.open, high=excluded.high, low=excluded.low,
    close=excluded.close, volume=excluded.volume, turn=excluded.turn,
    pctChg=excluded.pctChg,
    amount = CASE
        WHEN excluded.amt_src = 'exact' THEN excluded.amount
        WHEN kline.amt_src = 'exact'    THEN kline.amount
        ELSE excluded.amount END,
    amt_src = CASE
        WHEN excluded.amt_src = 'exact' THEN 'exact'
        WHEN kline.amt_src = 'exact'    THEN 'exact'
        ELSE excluded.amt_src END
```

各源的标注：

| 源 | amount 来源 | amt_src |
|---|---|---|
| sina 快照 | 响应第 9 位，元 | exact |
| baostock | 接口字段 | exact |
| akshare | 东财「成交额」，元 | exact |
| tencent | 均价×volume 估算 | approx |
| mootdx | 待确认（该源从未写入过一行） | approx（保守） |

## 影响文件

| 文件 | 改动 |
|---|---|
| `run_daily.sh` | 导出 `PUSH_DATE="$today"` |
| `data_hub/router.py` | 同步耗时护栏；调用 upsert 时带上 `amt_src` |
| `data_hub/api.py` | 新参数透传 |
| `data_hub/__main__.py` | 打印中止原因 |
| `data_hub/store/kline_db.py` | 加 `amt_src` 列 + 迁移 + 按优先级 upsert |
| `daily_select.py` | 零值判据改为「目标日当日成交额」 |

**选股策略逻辑不改**：cond1/cond2、25 亿阈值、评分权重全部不动。

## 边界与异常

- `amt_src` 迁移必须幂等：`ALTER TABLE` 在列已存在时会报错，需先查
  `PRAGMA table_info`。历史 31 万行的 `amt_src` 为 NULL，语义是"未知"，
  按"可被覆盖"处理——不能当成 exact，否则近似值再也刷不掉了。
- 改 upsert 前先备份库。这是全库写路径，改错影响所有数据。
- 耗时护栏的中止必须与早停共用 `aborted`，否则 `last_sync_date` 会谎报。
- 耗时预算不能太紧：正常轮次实测约 30 分钟，2 小时预算有 4 倍余量。
- 零值判据改动后要确认那 6 只停牌股确实被放过，且人为造一个
  「有成交却写成 0」的坏缓存仍能被删掉。
- `PUSH_DATE` 改动要覆盖「当天跑完」和「跨午夜跑完」两种情形。

## 预期结果

跨午夜的跑批不再丢通知。劣化的上游在 2 小时内被中止而不是拖 16 小时，
且不谎报 `last_sync_date`。真停牌不再触发全市场重扫。精确成交额一旦入库
就不会被近似值覆盖，不再需要每天手工修。

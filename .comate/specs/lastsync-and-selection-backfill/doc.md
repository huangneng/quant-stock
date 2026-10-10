# last_sync_date 谎报修正 + 历史选股回补通路

## 先修正我上一条消息里的一个过度断言

**我说「akshare 已恢复」，这是从单次成功调用得出的结论，站不住。**
10:05 那一次确实成功了，但 10:2x 再试，连续 5 次重试全部
`ConnectionError: RemoteDisconnected`。东财现在是间歇可用甚至基本不可用，
不能作为今天回补的依据。

顺带一个有用的发现：`akshare/stock_feature/stock_hist_em.py:992` 是
`requests.get(url, params=params, timeout=timeout)`——这个端点**是**接受
超时参数的。之前笼统说「akshare 内部大量端点不传 timeout」对这个端点不准确。

## 问题一：`last_sync_date` 谎报

现在库内 `last_sync_date = 2026-08-31`，而 08-31 一行数据都没有。

`sync_kline_db` 在非早停时无条件写 `last_sync_date`：

```python
if aborted is None:
    self.db.meta_set('last_sync_date', end)
```

盘中跑同步时，所有票的当日行都被「未定型」守卫拦掉，`skipped_unsettled`
等于尝试总数、`synced` 为 0，什么都没落库——但 `last_sync_date` 照样前进。

影响有限（真正的增量起点是逐票查 `get_last_date`，不读这个字段），
但这是一条谎报的状态。早停那个 spec 已经确立了「没跑完就不推进」的原则，
同样的原则应该覆盖「跑完了但什么都没写」。

修法：`synced == 0 且 skipped_unsettled > 0` 时不推进。
不能简单用 `synced == 0` 就不推进——全市场都已是最新、确实无事可做的
正常轮次也是 `synced == 0`，那种情况该推进。

## 问题二：08-25 ~ 08-27 选股缺失/不可信

| 日期 | 数据 | 选股现状 |
|---|---|---|
| 08-25 | 完整 | 缺 |
| 08-26 | 完整 | 有，但当时数据只有 46% 完整 |
| 08-27 | 完整 | 有，但当天 426 只票价格字段是错的 |

回补历史日期的预筛需要精确成交额。可用性现状：
baostock 挂（`10002007`）、东财间歇失败、新浪快照只有当日、
腾讯日K 可用但**不返回成交额**（只有 `[date,open,close,high,low,volume]`）。

### 关键测量：半截行修好之后，腾讯近似成交额已经够用了

`amount` 由 `均价×volume` 算出。之前 volume 是错的，所以 amount 也错。
volume 修好之后重新测量（08-28，5,192 只，参照新浪精确值）：

| 分位 | 相对误差 |
|---|---|
| P1 | -2.150% |
| P50 | **-0.157%** |
| P99 | +1.115% |

`|误差| > 5%` 的比例是 **0.00%**。

用库内近似成交额做 25 亿预筛，与用精确值对比：

```
精确入池 146 只
一致入池 143 | 漏选 3 | 误入 0
```

漏选的 3 只全部卡在阈值边缘（24.6~25.0 亿 vs 真实 25.0~25.2 亿），
偏差都在 2.3% 以内。**误入 0**——不会把不该进池的票放进来。

**这里要更正我之前的另一个说法。** 我说过「用库内 amount 做预筛会漏选 12/146」，
那是在 volume 还错着的时候测的。volume 修好后是 3/146。

## 技术方案

### 修 `last_sync_date`

```python
# 盘中跑批时所有票的当日行都被守卫拦掉，什么都没落库——
# 这种轮次不能推进 last_sync_date，否则状态谎报。
# 但「全市场已是最新、确实无事可做」也是 synced==0，那种要推进，
# 所以必须靠 skipped_unsettled 区分。
wrote_nothing = synced == 0 and skipped_unsettled > 0
if aborted is None and not wrote_nothing:
    self.db.meta_set('last_sync_date', end)
```

### 回补脚本增加两条取数通路

`scripts/backfill_prefilter_cache.py` 现在只走 baostock。改为 `--source` 可选：

- `baostock`（默认，精确，当前不可用）
- `akshare`（精确，间歇可用，带重试与退避）
- `klinedb`（近似，**当前唯一可用**，直接读本地库的 amount，秒级完成）

`klinedb` 通路不发任何网络请求，从 `kline` 表按日期取 `amount`，
覆盖率与库一致（99.7%）。这是今天能把三天选股跑出来的唯一途径。

### 用 klinedb 通路回补三天

生成 `prefilter_amount_2026-08-25.csv` / `-26` / `-27`，
再逐日跑 `daily_select.py --date`，最后刷新总览页。

## 影响文件

| 文件 | 改动类型 | 说明 |
|---|---|---|
| `/Users/huangneng/ComateProjects/QuackStock/data_hub/router.py` | 修改 | `sync_kline_db` 结尾的 `last_sync_date` 推进条件 |
| `/Users/huangneng/ComateProjects/QuackStock/scripts/backfill_prefilter_cache.py` | 修改 | 新增 `--source {baostock,akshare,klinedb}` 三条通路 |

选股策略逻辑（cond1/cond2、25 亿阈值）不改。预筛阈值不动——
`klinedb` 通路只是换了成交额的来源，不调阈值。

## 边界与异常

- `klinedb` 通路必须校验覆盖率 ≥95%，不足则不写缓存（沿用现有逻辑）。
- `klinedb` 通路要跳过 `amount <= 0` 的行（停牌），不写 0 值进缓存——
  `_prefilter_cache_has_bad_zero_amount` 会因为异常 0 值删掉整个缓存。
- akshare 通路需重试 + 退避；连续失败则不写该日缓存，不写半份。
- akshare 的 `成交量` 单位是手，但预筛只用 `成交额`（元），不涉及换算。
- 三天的选股结果会带有「基于近似成交额」的性质，需在 summary 里记录，
  日后 baostock/东财恢复时可用精确通路重跑对比。

## 预期结果

`last_sync_date` 回到 `2026-08-28`（与库内实际最新数据一致）。
08-25 / 08-26 / 08-27 三天产出选股结果，08-26 与 08-27 的旧结果被覆盖。
预筛入池数与精确值的差异预期在 3/146 量级，且只会漏选、不会误入。

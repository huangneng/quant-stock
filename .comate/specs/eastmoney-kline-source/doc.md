# 接入东方财富 push2his 直连日K源

## 背景

现有日K降级链（`router.py:374`）是 `腾讯 → mootdx → akshare → baostock`。
这几天的实跑暴露两个结构性问题：

1. **腾讯不返回成交额**，`amount` 由 `均价×volume` 估算，是 `approx`。
   每次同步/补数后都要再跑一轮 baostock 回标才能得到精确成交额——
   09-11~09-17 这一周就这么"先同步 approx、再回标 exact"来回折腾了多次。
2. **腾讯是 WAF 重灾区**，一被拦整条链就慢下来（mootdx 此环境 7709 端口
   不通、akshare 爬东财同样常被限流），真正能兜底的只剩 baostock，而它
   逐票又慢又常断流。

调研结论（已排除 Tushare 等需注册的源，只用纯免费无 token）：
**东方财富 push2his 是当前环境可用、且能直接返回精确成交额的最佳补充。**

## 已实测确认的事实

端点 `https://push2his.eastmoney.com/api/qt/stock/kline/get`，本机 HTTP 443 可通：

```
secid=1.600000  klt=101  fqt=1  fields2=f51..f57
-> 2026-09-16,9.17,9.10,9.20,9.00,723404,656348140.00
   即 [日期, 开, 收, 高, 低, 成交量(手), 成交额(元)]
```

关键点：
- **成交额是接口直接给的精确值**（元），不是估算。→ 标 `amt_src='exact'`，
  同步时一步到位，不再需要事后 baostock 回标。
- **支持前复权**：`fqt=1` 返回前复权（实测 9.17/9.10 与 qfq 口径一致），
  `fqt=0` 不复权、`fqt=2` 后复权。与现有腾讯源的 qfq 口径一致。
- **成交量单位是手**，需 ×100 转股，与 `tencent_kline.py` 的 vol_multiplier 同理。
- 是**独立于腾讯的服务商**：腾讯被 WAF 拦时它大概率仍可用，降级链才算
  真有一条独立备用。

## 技术方案

新增 `data_hub/sources/eastmoney_kline.py`，类 `EastmoneyKlineSource`，
接口与其他 `DataSource` 一致（`login()` / `get_kline(code, start, end)`），
返回统一 schema（`UNIFIED_COLS`）。以 `tencent_kline.py` 为模板。

请求参数：

```python
secid  = f'{market}.{code}'   # market: sh->1, sz->0, bj->0（需 Task 验证 bj）
params = {
    'secid': secid,
    'klt': '101',             # 日K
    'fqt': '1',               # 前复权，与腾讯源口径对齐
    'beg': start.replace('-',''),
    'end': end.replace('-',''),
    'fields1': 'f1',
    'fields2': 'f51,f52,f53,f54,f55,f56,f57',
}
```

解析：`data.klines` 是逗号分隔字符串数组，按
`[date, open, close, high, low, vol(手), amount(元)]` 拆，`volume=vol*100`，
`pctChg` 用 `close.pct_change()` 现算（与 tencent 源一致），`turn=0`。

异常处理（照搬 tencent 源的经验）：
- HTTP 非 200 或 `data` 为 null / `klines` 为空 → 返回 None（该票查无数据，降级）。
- 东财也有反爬（实测限流约 600ms/次、500次/日量级），被限流时可能返回
  空或异常结构 → 返回 None 降级，交给熔断器按票数统计；**不抛
  `SourceUnavailable`**，因为东财限流是软性的、不像腾讯 WAF 那样返回明确的
  501 拦截页，无法可靠区分"限流"与"这只票没数据"。这一点与腾讯不同，
  doc 里显式记录，避免误判把健康源熔断。

### 接入降级链

把 eastmoney 放到链首（腾讯之前）：

```python
return [
    ('eastmoney', self.em_kline, None, False),   # 精确成交额 + qfq，优先
    ('tencent',   self.tx_kline, None, False),   # 近似成交额，兜底
    ('mootdx',    self.mootdx,   '_mootdx_logged_in', True),
    ('akshare',   self.ak,       '_ak_logged_in',     False),
    ('baostock',  self.bs,       '_bs_logged_in',     False),
]
```

`_AMT_SRC_BY_SOURCE` 增加 `'eastmoney': 'exact'`。这样正常同步命中 eastmoney
时直接落精确成交额，`amt_src=exact`，后续近似值不会覆盖它，也基本不需要
再单独回标。

## 影响文件

| 文件 | 改动 |
|---|---|
| `data_hub/sources/eastmoney_kline.py` | 新增源 |
| `data_hub/router.py` | `__init__` 实例化；`_kline_source_chain` 置于链首；`_AMT_SRC_BY_SOURCE` 加 eastmoney |

**选股策略逻辑不改**：cond1/cond2、25 亿阈值、评分权重不动。
只改"数据从哪个源取、成交额精度标记"。

## 边界与异常

- **secid 的市场前缀**：sh→1、sz→0 已知；bj（8xxxxx/4xxxxx）需 Task 实测确认
  是 0 还是别的，取不到就让它降级到下一个源，不能静默写错。
- **东财限流**：加了 eastmoney 到链首后，全市场同步会把 5207 次请求打向东财，
  可能触发它的日限流。需复用现有节流（`_Throttle`）与熔断（`_SourceBreaker`）；
  一旦被限流，熔断器会跳过它、自动落到腾讯，不会卡死——这套机制已就绪。
- **半截 K 线**：盘中调用会返回当日未定型行，由现有 `_drop_unsettled` 守卫处理，
  本源不额外处理。
- **口径一致性**：`fqt=1` 必须与腾讯源的前复权口径一致，否则同一只票在两个源
  之间切换会产生价格跳变。Task 里要做交叉验证。
- **不改变"快照优先"**：当日盘后的全市场预筛仍走新浪快照（批量、秒级），
  本源只作用于逐票的 K 线取数（历史补数 + 增量同步）。

## 预期结果

正常增量同步与历史补数命中 eastmoney 时，直接得到**前复权 OHLC + 精确成交额**，
`amt_src=exact`。这消除了"先同步近似、再 baostock 回标"的两步流程，也给降级链
增加了一条独立于腾讯 WAF 的链路。腾讯退居兜底，baostock 仍作最终精确校验。

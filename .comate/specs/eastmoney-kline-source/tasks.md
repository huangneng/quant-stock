# 接入东方财富 push2his 直连日K源

- [✓] Task 1: 验证 push2his 接口关键语义 —— ⚠️ 发现致命阻断，方案暂停
    - 1.1: 实测约 12 次请求后，本机 IP 被东财封禁：push2his.eastmoney.com
      TCP 443 变为不通，API 返回 RemoteDisconnected，停 20s 未恢复
    - 1.2: 对照确认腾讯/新浪同一时刻 HTTP 200 正常——是东财单方面封 IP，非本机断网
    - 1.3: 结论：push2his 反爬远比调研资料（500次/日）激进，十几次即封；
      作为需 5207 次/日的链首源不可行，会在同步头一分钟被封、全部降级到腾讯
    - 1.4: 待用户决策是否改用"低频精确补充"的窄用法，或放弃本源

- [~] Task 2（因 Task 1 否决，不执行）: 新增 `EastmoneyKlineSource`
    - 2.1: 以 `tencent_kline.py` 为模板建 `data_hub/sources/eastmoney_kline.py`
    - 2.2: 实现 `login()` 返回 True、`get_kline(code,start,end)` 返回 `UNIFIED_COLS`
    - 2.3: code→secid 映射（含 bj），非法代码返回 None
    - 2.4: 解析 klines，`volume=vol*100`、`amount` 原样、`pctChg` 现算、`turn=0`
    - 2.5: 日期区间过滤，空/异常结构返回 None（不抛 SourceUnavailable，注释写明与腾讯的区别）

- [~] Task 3（因 Task 1 否决，不执行）: 接入降级链与精度标记
    - 3.1: `router.__init__` 实例化 `self.em_kline`
    - 3.2: `_kline_source_chain` 把 eastmoney 置于链首（腾讯之前）
    - 3.3: `_AMT_SRC_BY_SOURCE` 增加 `'eastmoney': 'exact'`
    - 3.4: 确认 `_last_amt_src` 命中 eastmoney 时返回 exact

- [~] Task 4（因 Task 1 否决，不执行）: 为新源补单元测试
    - 4.1: mock 正常响应，断言字段解析、vol×100、pctChg、区间过滤正确
    - 4.2: mock data=null / klines 空，断言返回 None（降级）
    - 4.3: 断言 sh/sz/bj 的 secid 映射，非法代码返回 None
    - 4.4: 断言返回列严格等于 UNIFIED_COLS

- [~] Task 5（因 Task 1 否决，不执行）: 端到端联调
    - 5.1: 真实取 3~5 只（含 sh/sz，若 bj 可用则含 bj），核对与东财网页一致
    - 5.2: 走 `_fetch_kline_online` 验证命中 eastmoney 时 `_last_amt_src()` 为 exact
    - 5.3: 用一只票经 `get_kline` 落库，确认 `amt_src='exact'` 且不被后续 approx 覆盖
    - 5.4: 交叉验证 eastmoney 与 baostock 的成交额一致（抽样，偏差应 ≈0）

- [~] Task 6（因 Task 1 否决，不执行）: 小范围同步验证
    - 6.1: 取一个近期交易日、限一小批代码走 `sync_kline_db`，确认优先命中 eastmoney
    - 6.2: 对比该批 `amt_src` 分布：应以 exact 为主，不再需要事后回标
    - 6.3: 确认节流/熔断对 eastmoney 生效（被限流时能跳过并降级到腾讯）

- [~] Task 7（因 Task 1 否决，不执行）: 回归与提交
    - 7.1: 重跑本会话相关测试脚本，确认无回归
    - 7.2: 确认 `daily_select` 与报告生成路径不受影响
    - 7.3: 提交并推送
    - 7.4: 生成 summary.md，记录实测语义、口径一致性结论与东财限流的应对

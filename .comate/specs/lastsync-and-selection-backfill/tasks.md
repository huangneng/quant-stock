# last_sync_date 谎报修正 + 08-25~08-27 选股回补

- [x] Task 1: 修正 `sync_kline_db` 的 `last_sync_date` 推进条件
    - 1.1: 在 `data_hub/router.py` 轮次结尾计算 `wrote_nothing = synced == 0 and skipped_unsettled > 0`
    - 1.2: 推进条件改为 `aborted is None and not wrote_nothing`，注释写清为何不能只看 `synced == 0`
    - 1.3: 轮次返回值中输出该判定（便于 `__main__` 与日志排查状态不推进的原因）
    - 1.4: `data_hub/__main__.py` 在未推进时打印一行提示，避免看日志时误认为已同步到 `end`

- [x] Task 2: 为 `last_sync_date` 判定补单元测试
    - 2.1: 构造「盘中轮次」——所有票被未定型守卫拦掉，断言 `last_sync_date` 不变
    - 2.2: 构造「无事可做轮次」——`synced == 0 且 skipped_unsettled == 0`，断言推进到 `end`
    - 2.3: 构造「正常写入轮次」——`synced > 0`，断言推进
    - 2.4: 回归早停路径：`aborted` 非空时无论如何都不推进

- [x] Task 3: 把库内实际状态与 `last_sync_date` 对齐
    - 3.1: 校验 `kline` 表最新有数据的交易日（预期 2026-08-28）
    - 3.2: 将 `meta.last_sync_date` 改回该日期，改前打印旧值
    - 3.3: 复查改后取值，确认与实际最新数据一致

- [x] Task 4: `backfill_prefilter_cache.py` 抽出取数通路抽象
    - 4.1: 增加 `--source {baostock,akshare,klinedb}` 参数（默认 `baostock`），日期改为位置参数
    - 4.2: 把现有 baostock 逻辑原样搬进 `fetch_baostock(stock_list, dates)`，返回 `(buckets, missing)`
    - 4.3: 覆盖率校验、零成交额统计、写缓存、退出码逻辑抽成与通路无关的公共段
    - 4.4: 更新模块 docstring，说明三条通路的精确性差异与适用场景

- [x] Task 5: 实现 `klinedb` 与 `akshare` 两条新通路
    - 5.1: `fetch_klinedb`——按日期区间一次性查 `kline` 表的 `code,date,amount`，零网络请求
    - 5.2: `klinedb` 通路跳过 `amount <= 0` 的行，避免触发 `_prefilter_cache_has_bad_zero_amount` 删缓存
    - 5.3: `fetch_akshare`——逐票拉历史行情取精确 `amount`，带重试与指数退避
    - 5.4: akshare 通路连续失败达阈值即整体中止，不写半份缓存
    - 5.5: 缓存文件名沿用 `prefilter_amount_{date}.csv`，格式与 `daily_select` 自写的一致

- [x] Task 6: 为三条通路补测试
    - 6.1: `klinedb` 通路用临时库验证：正常行入池、`amount <= 0` 行被剔除
    - 6.2: 覆盖率不足时断言不写缓存文件、退出码非 0
    - 6.3: mock akshare 连续异常，断言中止且未产生任何缓存文件
    - 6.4: 回归 `baostock` 通路的参数装配未被重构破坏

- [x] Task 7: 生成 08-25 / 08-26 / 08-27 预筛缓存
    - 7.1: 以 `--source klinedb` 跑三个日期，记录各日行数、覆盖率、≥25亿 只数
    - 7.2: 校验缓存文件能通过 `daily_select` 的缓存有效性检查（覆盖率、零成交额）
    - 7.3: 与 08-28 的精确参照做一次抽样比对，确认偏差量级仍在预期内

- [x] Task 8: 逐日重跑选股并校验
    - 8.1: 依次执行 `daily_select.py --date 2026-08-25 / -26 / -27`
    - 8.2: 确认三日均命中缓存、未回落到 baostock 逐票查询
    - 8.3: 对比 08-26 / 08-27 覆盖前后的选股结果差异，记录变化的标的与评分
    - 8.4: 确认 `selections.json` 三日记录完整、字段齐全

- [x] Task 9: 刷新总览页并提交
    - 9.1: 重新生成 tracker 报告，确认 index 页含 08-25~08-27
    - 9.2: 检查 `git status`，只提交代码与 spec 变更（缓存与 output 已 gitignore）
    - 9.3: 按约定提交

- [x] Task 10: 生成 summary.md
    - 10.1: 记录 `last_sync_date` 修正与库内状态对齐结果
    - 10.2: 记录三条通路的实现与各自精确性边界
    - 10.3: 明确标注三天选股「基于近似成交额」，日后精确源恢复可重跑对比

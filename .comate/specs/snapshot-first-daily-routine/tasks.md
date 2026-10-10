# 例行任务改为「收盘后快照优先」

- [x] Task 1: 量化快照口径与库内前复权的差异（先验证再动手）
    - 1.1: 取一批有成交的 code，比对同日快照不复权价与腾讯前复权价的差异分布
    - 1.2: 统计差异来源——确认分歧只发生在历史窗口内有除权的票，且幅度可接受
    - 1.3: 结论写回 doc：确认"当日快照不复权 + 历史前复权"混用可接受，否则加换算

- [x] Task 2: 抽出可复用的 `fill_from_snapshot()`
    - 2.1: 把 `fill_kline_from_snapshot.py` 的取数/collect/守卫/写库逻辑抽成函数
    - 2.2: 返回 `{wrote, rows, coverage, bad_date, halted, aborted_reason}`
    - 2.3: `main()` 改为调用该函数，保持 CLI 行为与退出码不变
    - 2.4: 守卫原样保留：日期不符>1% 中止、覆盖率<95% 不写、停牌跳过、amt_src='exact'

- [x] Task 3: `sync_today` 改为快照优先
    - 3.1: 先调 `fill_from_snapshot(today)`，成功则推进 last_sync_date=today
    - 3.2: 快照成功后对仍缺当日行的少量 code 走 bounded 腾讯逐票（紧预算+熔断，非致命）
    - 3.3: 快照整体失败时退回现有 `sync_kline_db` 腾讯逐票全量（兜底，不比现状差）
    - 3.4: last_sync_date 推进沿用谎报防护：覆盖不足/日期不符不推进
    - 3.5: 打印清晰的路径与结果（走了快照还是兜底、覆盖率、是否推进）

- [x] Task 4: 为 `sync_today` 编排补测试
    - 4.1: mock 快照成功（覆盖率达标）→ 断言走快照、推进 last_sync_date、不触发全量兜底
    - 4.2: mock 快照为空/日期不符 → 断言退回腾讯逐票兜底
    - 4.3: mock 快照覆盖率不足 95% → 断言不推进 last_sync_date 并走兜底
    - 4.4: 断言零头补拉被紧预算约束、失败非致命

- [x] Task 5: 为 `fill_from_snapshot()` 补测试
    - 5.1: 正常快照 → 断言 collect 行数、exact 标记、覆盖率计算
    - 5.2: 大面积日期不符 → 断言中止不写
    - 5.3: 覆盖率不足 → 断言中止不写
    - 5.4: 停牌行（价/量/额≤0）被跳过
    - 5.5: 回归 CLI `python scripts/fill_kline_from_snapshot.py <date>` 行为不变

- [x] Task 6: 盘后真实联调（在快照窗口内）
    - 6.1: 在收盘后窗口跑一次 `python -m data_hub sync_today`，确认走快照、秒级、exact
    - 6.2: 确认 last_sync_date 推进到当日、覆盖率≥95%
    - 6.3: 跑 `daily_select` + 报告，确认与手动快照补数结果一致
    - 6.4: 构造快照不可用场景，确认能退回腾讯兜底

- [x] Task 7: 回归与提交
    - 7.1: 重跑本会话相关测试脚本，确认无回归
    - 7.2: 确认 `run_daily.sh` 无需改动（或仅注释说明快照优先）
    - 7.3: 提交并推送
    - 7.4: 生成 summary.md，记录口径结论、路径设计与预期的运维负担下降

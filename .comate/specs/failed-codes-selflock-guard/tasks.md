# failed_codes 自锁防护任务计划

注意：doc.md 的存量数据描述（5207 行、`retry_cnt` 最大 4）采集于 08-26 盘前，
而 08-26 的盘后同步已经跑过。若当日上游仍不健康，`retry_cnt` 可能已达 5 并开始跳过。
因此 Task 1 先重新核对实际状态，再决定清理方式与紧急程度。

- [✓] Task 1: 重新核对 failed_codes 当前状态与自锁是否已发生
    - 1.1: 统计 `failed_codes` 行数与 `retry_cnt` 分布，确认最大值是否已达 5
    - 1.2: 从 `logs/daily.log` 取 08-26 同步的 `synced` / `failed` / `skipped_dead` 与失败率
    - 1.3: 若 `skipped_dead > 0`，确认被跳过的是真死码还是被误判的正常票
    - 1.4: 核对 `kline` 表 08-26 的覆盖数，判断当日上游健康度
    - 1.5: 据实际状态更新 doc.md 的存量数据一节（用 Edit，保留原始采集时点的说明）

- [✓] Task 2: mark_failed 延后到轮末并按失败率判定
    - 2.1: `sync_kline_db` 新增 `mark_failed_max_fail_rate: float = 0.2` 入参
    - 2.2: 循环内移除 `self.db.mark_failed(...)`，只保留 `failed.append(code)`
    - 2.3: 保持 `clear_failed` 在循环内即时调用（自锁的唯一出口，不可延后）
    - 2.4: 轮末计算 `fail_rate = len(failed) / (synced + len(failed))`，`attempted == 0` 时取 0.0
    - 2.5: 失败率 ≤ 阈值则批量 `mark_failed`，否则打印告警且整轮不落库
    - 2.6: 返回值新增 `fail_rate` 与 `marked_failed`

- [✓] Task 3: 参数透传与 CLI 输出
    - 3.1: `data_hub/api.py` 透传 `mark_failed_max_fail_rate`
    - 3.2: `data_hub/__main__.py` 打印 `fail_rate` 与 `marked_failed`
    - 3.3: 确认告警场景下日志能一眼看出"本轮失败未被记账"

- [✓] Task 4: 单测与回归
    - 4.1: 失败率 5% → 断言 `marked_failed == len(failed)`，表中行数正确
    - 4.2: 失败率 100%（模拟 08-25）→ 断言 `marked_failed == 0`，表中 0 行
    - 4.3: 失败率 50%（模拟 08-24）→ 断言不记账并打印告警
    - 4.4: 失败率恰好 20% → 断言记账（边界归健康侧）
    - 4.5: `clear_failed` 即时性：先写入失败记录，再让取数成功，断言对应行立即被删
    - 4.6: 批量写入不重复累加 `retry_cnt`（同一轮内单只票只失败一次）
    - 4.7: `attempted == 0` 的空轮不抛异常且 `fail_rate == 0.0`
    - 4.8: 回归熔断统计与 `skipped_dead` 行为不变

- [✓] Task 5: 存量数据清理
    - 5.1: 先把 `failed_codes` 全表导出备份到文件，便于事后追溯
    - 5.2: 清空 `failed_codes` 表
    - 5.3: 核对表为 0 行、备份文件内容完整，且 `kline` 主数据未受影响
    - 5.4: 确认下一轮同步不会误跳过任何票（`skip_set` 为空）

- [✓] Task 6: 真实观测与生成 summary.md
    - 6.1: 08-27 盘后同步记录 `fail_rate` / `marked_failed` / `skipped_dead`
    - 6.2: 确认记账行为与当日上游健康度相符（健康日应只记十几只真死码）
    - 6.3: 撰写 `summary.md`：改动、验证结果、存量清理记录、以及死码名单重新累积的进度

# 盘后流水线缺陷修复任务计划（R1 → R2 → R3 → R4）

按影响面从大到小推进，每个任务独立可验证、可单独回滚。R1/R3 先做是因为它们直接影响每日产出；R2 会改变评分口径，需单独对比；R4 涉及数据层写入，放最后并用临时 DB 验证。

- [x] Task 1: 修复 push_email.py 的 f-string 花括号转义（R1）
    - 1.1: 读取 `scripts/push_email.py` 的 `render_html()`，确认第 104 行起 f-string 的边界与 120-124 行的原始内容
    - 1.2: 将 `.star-na` / `tbody tr:hover` / `.empty` / `.more` / `.footer` 五行的单花括号改为双花括号
    - 1.3: 通读整段模板，确认 105-119 行之外没有其他遗漏的单花括号
    - 1.4: 用 `daily_selections_2026-08-17.csv` 调 `render_html('2026-08-17', df)`，断言返回非空且含字面量 `.star-na { color:#8c959f; }`
    - 1.5: 用空 DataFrame 走一遍无候选分支，确认同样渲染成功
    - 1.6: 确认无 SMTP 环境变量时渲染不受影响（不触发真实发信）

- [x] Task 2: 打通 is_limit_up 字段链路（R2 之前先做，避免评分变化干扰字段验证）
    - 2.1: 在 `daily_select.py` 的 `select()` 内 `rows.append(...)` 补 `'is_limit_up': bool(sig['is_limit_up'])`
    - 2.2: 保留 `update_selections_json` 第 521 行的 `s.get('is_limit_up', sig == 'one_word')` 兜底，用于历史无该列的旧 CSV
    - 2.3: 不改 `_SIGNAL_TO_TRACKER`，`limit_up → breakthrough` 的降级维持现状
    - 2.4: 验证：以 `--date 2026-08-17` 重跑，确认 CSV 新增 `is_limit_up` 列且 `sz.002437` 为 True
    - 2.5: 验证：`selections.json` 中 `sz.002437` 的 `is_limit_up` 为 `true`，`signal_type` 仍为 `breakthrough`
    - 2.6: 回归：确认 CSV 新增列不影响 `push_email.py` 与 `push_serverchan.py` 的渲染

- [x] Task 3: 权重加载兼容多余键（R2）
    - 3.1: 读取 `stock_research/recommender.py` 的 `_load_weights()` 与 `DEFAULT_WEIGHTS`，确认 7 个维度键名
    - 3.2: 按 doc.md 方案重写 `_load_weights()`：必需键齐全即接受，多余键忽略并在来源串中标注
    - 3.3: 归一化只对 7 个已知维度求和，确保 `score()` 第 161 行的 `sum(dims[k] * WEIGHTS[k] for k in WEIGHTS)` 不会 KeyError
    - 3.4: 保留缺键 / 负值 / 总和≤0 / 非法 JSON 四个回退分支，各自带可区分的来源字符串
    - 3.5: 验证：运行后日志为 `weights=learned(ignored:auction) thresholds=learned`
    - 3.6: 验证：断言归一化后 `new_high ≈ 0.021`、`upper_short ≈ 0.289`
    - 3.7: 用 0817 誉衡药业的维度特征对比新旧 `score`/`star`，记录差异待写入 summary

- [x] Task 4: KlineDB 失败明细落库（R4.1）
    - 4.1: 读取 `data_hub/store/kline_db.py`，确认 `failed_codes` 表结构与 `_lock` / `_conn()` 的既有用法
    - 4.2: 新增 `mark_failed(code, err)`，用 `ON CONFLICT(code) DO UPDATE` 累加 `retry_cnt`，`last_err` 截断 200 字符
    - 4.3: 新增 `clear_failed(code)` 与 `get_failed(min_retry=1)`
    - 4.4: 用临时 DB 验证 `mark_failed` 幂等累加、`clear_failed` 清零、`get_failed` 按 `min_retry` 过滤

- [x] Task 5: 增量同步跳过死码并透出计数（R4.2）
    - 5.1: `data_hub/router.py` 的 `sync_kline_db()` 增加 `skip_retry_gte=5` / `skip_window_days=7` 参数
    - 5.2: 仅当 `full=False` 时构建 `skip_set`（`retry_cnt≥阈值` 且 `updated_at` 在窗口内）
    - 5.3: 取数四源全空时调 `mark_failed(code, 'empty_from_all_sources')`，成功时调 `clear_failed(code)`
    - 5.4: 返回值补 `skipped_dead` 与 `failed_codes[:20]`
    - 5.5: `data_hub/api.py` 的 `sync_kline_db()` 透传新参数
    - 5.6: `data_hub/__main__.py` 的同步结果打印补 `skipped_dead`
    - 5.7: 确认全量入口走 `full=True`，跳过逻辑不会阻断强制回补
    - 5.8: 验证：`failed_codes` 为空时行为与现状一致（不误跳过）；阈值达到但超窗口时会重试一次

- [x] Task 6: 端到端回归与生成 summary.md
    - 6.1: 以 `--date 2026-08-18` 走一遍完整链路（选股 → CSV → selections.json → 报告），确认无异常
    - 6.2: 确认 `push_email.py` 与 `push_serverchan.py` 渲染均正常
    - 6.3: 观察一次真实增量同步的 `skipped_dead` 与 `elapsed_s`，与 0817 的 `failed=586 / 4006.4s` 对比
    - 6.4: 撰写 `summary.md`：R1-R4 的改动与验证结果、R2 评分口径变化的新旧对比、`new_all_time_high` 窗口口径遗留问题

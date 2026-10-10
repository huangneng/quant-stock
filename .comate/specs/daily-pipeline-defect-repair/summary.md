# 盘后流水线缺陷修复 — 完成总结

feature: `daily-pipeline-defect-repair` ｜ 完成日期 2026-08-20

## 结果概览

| 编号 | 缺陷 | 状态 | 关键验证 |
|---|---|---|---|
| R1 | `push_email.py` f-string 花括号未转义 | 已修 | 有候选/无候选两分支均渲染成功 |
| R2 | 学习权重被严格键校验丢弃 | 已修 | 日志变为 `weights=learned(ignored:auction)` |
| R3 | `selections.json` 的 `is_limit_up` 恒为 false | 已修 | 0817/0818 均落为 `true` |
| R4 | 同步失败无明细、无跳过策略 | 已修 | `failed_codes` 落库 + 增量跳过死码 |

改动文件：`scripts/push_email.py`、`stock_research/recommender.py`、`daily_select.py`、
`data_hub/store/kline_db.py`、`data_hub/router.py`、`data_hub/api.py`、`data_hub/__main__.py`。

## R1 邮件模板转义

把 `render_html()` 中 `.star-na` / `tbody tr:hover` / `.empty` / `.more` / `.footer` 五行的单花括号
改为双花括号。此前 Python 把 `{ color:#8c959f; }` 当表达式求值，抛 `NameError: name 'color' is not defined`，
且 `run_daily.sh` 把 `push_email` 失败当非致命处理，导致邮件推送连续多日静默失败（0817、0819 日志均可见）。

验证：用 0817 CSV 与空 DataFrame 各渲染一次，均返回完整 HTML（2595 / 1971 字符），
输出含字面量 `.star-na { color:#8c959f; }`；渲染路径不依赖 SMTP 配置。

## R2 权重加载

改为"必需键齐全即接受，多余键忽略并在来源串中标注"。`recommender_weights.json` 的第 8 个键
`auction` 全仓无实现，不能进权重字典（否则 `score()` 会 KeyError），现在被忽略并记入日志。

**与 doc.md 的一处偏离**：doc.md 方案把学习权重归一化到 1.0（预期 `new_high≈0.021`、`upper_short≈0.289`）。
实测这样不可取——`DEFAULT_WEIGHTS` 之和是 0.88，余下 0.04 是留给 `signal_bonus` 的头寸，
且 `recommender_calibration.json` 的 `train_score_stats.max=0.8183` 表明学习阈值就是在 0.88 尺度上标定的。
归一化到 1.0 会让 `base_total` 单独就能顶到 clamp 上限，`signal_bonus` 失效、星级普遍虚高。
因此改为归一化到 `sum(DEFAULT_WEIGHTS)=0.88`，实际权重：

| 维度 | 默认 | 学习（0.88 尺度） |
|---|---|---|
| upper_short | 0.220 | 0.254 |
| body_long | 0.176 | 0.227 |
| volume_amp | 0.132 | 0.136 |
| new_high | 0.088 | **0.018** |
| ma_dev_health | 0.088 | 0.091 |
| pre3_setup | 0.088 | 0.091 |
| pre3_vol_slope | 0.088 | 0.064 |

标定结论是"创新高维度几乎无区分度"（0.088 → 0.018），这个口径变化以前一直没生效。

回退分支逐个验证：缺键 → `default(missing:new_high)`；负值/零和 → `default(non_positive)`；
非 dict → `default(invalid_file)`；非法 JSON → `default(parse_error)`。

### 评分口径变化（实测）

| 日期 | 标的 | 旧（默认权重） | 新（学习权重） |
|---|---|---|---|
| 0817 | 誉衡药业 | 0.7658 / 5★ | 0.7564 / 5★ |
| 0818 | 中石科技 | 0.5042 / 3★ | 0.4749 / **2★** |

中石科技降级的原因：它的 `body_long` 维度只有 0.0393（实体极短），而学习权重把 `body_long` 从
0.176 提到 0.227，同时 `new_high`（该股为 1.0）从 0.088 砍到 0.018，两头相抵后跌破 3★ 阈值 0.496。
这是标定结论生效后的预期行为，不是回归。

## R3 `is_limit_up` 字段链路

在 `select()` 的 `rows.append(...)` 补 `'is_limit_up': bool(sig['is_limit_up'])`，字段随 DataFrame
流到 CSV 和 `update_selections_json`。`update_selections_json` 第 521 行的
`s.get('is_limit_up', sig == 'one_word')` 兜底保留，用于历史无该列的旧 CSV。

`_SIGNAL_TO_TRACKER` 的 `limit_up → breakthrough` 降级是设计意图，未改动，`signal_type` 仍为 `breakthrough`。

验证（`--date 2026-08-17` / `2026-08-18` 重跑）：CSV 新增 `is_limit_up` 列且两只均为 `True`；
`selections.json` 中 `sz.002437` / `sz.300684` 的 `is_limit_up` 为 `true`。
回归：`push_email.render_html` 与 `push_serverchan.render_markdown` 对新增列均正常渲染。

顺带影响：`stock_research/data_loader.py:56` → `feature_extractor.py:37` 会从 `selections.json`
读这个字段。此前所有普通涨停都被当作 `False`，后续重新标定/训练时这批标签会自动修正。

## R4 同步失败可追溯 + 死码跳过

`KlineDB` 新增 `mark_failed` / `clear_failed` / `get_failed`：`failed_codes` 表此前只建表不写入，
586 只失败码事后无从查证。`last_err` 截断 200 字符，`retry_cnt` 通过 `ON CONFLICT` 累加。

`sync_kline_db` 新增 `skip_retry_gte=5` / `skip_window_days=7`：增量模式下跳过"连续失败≥5 次
且 7 日内仍在失败"的码（多为退市/长期停牌），取数成功即 `clear_failed` 归零。返回值新增
`skipped_dead` 与 `failed_codes[:20]`，`python -m data_hub sync_today` 一并打印。

临时 DB 全分支验证通过：
- `failed_codes` 为空 → `skipped_dead=0`，不误跳过
- 累加到 4 次仍会重试，达 5 次后增量跳过（`_fetch_kline_online` 不再被调用）
- `full=True` 不跳过，强制回补可用
- `retry_cnt` 达阈值但 `updated_at` 超出 7 日窗口 → 重新尝试一次，不会永久黑名单
- 恢复取数后 `failed_codes` 清空

**待观察**：耗时收益要等下一次真实增量同步才能量化，对比基线是 0817 的
`synced=4436 failed=586 elapsed=4006.4s`。当前真实 `failed_codes` 表仍是 0 行，需要连续 5 个交易日
才会积累出可跳过的死码，所以收益是渐进的。

## 遗留与范围外

- `new_all_time_high` 只是本地窗口内高点（KlineDB 对多数码只存约 41 根滚动窗口，`sz.002437`
  本地仅 149 根、起自 2026-01-06），标签口径偏乐观。本次未改，仅记录。
- 未调整 `cond1/cond2` 选股条件与 25 亿预筛阈值。
- 未给 `_fetch_kline_online` 引入并发，先用死码跳过换耗时收益。
- 未改星级阈值与 `_SIGNAL_TO_TRACKER` 映射。
- 代码里目前没有 `full=True` 的调用入口，全量回补需手动调 `hub.sync_kline_db(..., full=True)`。
- 回跑历史日期依赖 `stock_data/cache/prefilter_amount_{date}.csv`（非 `_final`）。本次为 0817/0818
  从 `_final` 复制了一份；若缺失会退化为 5000+ 只的 baostock 逐只扫描，很慢。

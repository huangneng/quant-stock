# 盘后流水线缺陷修复设计文档

## 背景

2026-08-17 盘后复盘（`logs/daily.log`、`stock_data/selections.json`、`stock_research/output/daily_selections_2026-08-17.csv`）暴露 4 个工程缺陷，其中 2 个直接影响当日产出。本次只修缺陷，不调整选股策略逻辑（`cond1/cond2` 的创新高要求属于策略设计，另行讨论）。

按影响面排定顺序：

| 编号 | 缺陷 | 当日实际后果 |
|---|---|---|
| R1 | `push_email.py` f-string 花括号未转义 | 0817 邮件推送失败，`NameError` |
| R2 | 学习权重被严格键校验丢弃 | 评分一直用默认权重，标定产物未生效 |
| R3 | `selections.json` 的 `is_limit_up` 恒为 false | 跟踪页丢失涨停标记，与 CSV 不一致 |
| R4 | 同步失败无明细、无跳过策略 | 586 只失败无迹可查，单次同步 4006 秒 |

## R1 邮件模板 f-string 转义

### 现象与根因

`scripts/push_email.py:104` 起的 `return f"""..."""` 中，第 105-119 行 CSS 规则均已用 `{{ }}` 转义，但 120-124 行漏了：

```python
.star-na { color:#8c959f; }          # ← 被当作 f-string 表达式
tbody tr:hover { background:#f6f8fa; }
.empty { padding:24px; ... }
.more { display:inline-block; ... }
.footer { color:#8c959f; ... }
```

Python 把 `{ color:#8c959f; }` 解析为表达式并求值 `color` 这个名字，抛 `NameError: name 'color' is not defined`。这是渲染期必然触发的错误，与数据无关——只要走到有候选或无候选的任一分支都会失败。

### 方案

把这 5 行的单花括号改为双花括号，与上方 105-119 行保持一致的写法。

```python
        .star-na {{ color:#8c959f; }}
        tbody tr:hover {{ background:#f6f8fa; }}
        .empty {{ padding:24px; background:#f6f8fa; border-radius:6px; text-align:center; color:#57606a; }}
        .more {{ display:inline-block; margin-top:20px; padding:10px 18px; background:#1f6feb; color:#fff !important; text-decoration:none; border-radius:6px; font-weight:600; }}
        .footer {{ color:#8c959f; font-size:12px; margin-top:20px; text-align:right; }}
```

### 影响文件

- `scripts/push_email.py`（修改）：`render_html()`，行 120-124。

### 边界条件

- 空候选分支（`df is None or df.empty`）同样走这段模板，两个分支都要验证。
- 无 SMTP 环境变量时 `send_email()` 静默跳过，验证渲染不依赖推送配置。

### 预期结果

`render_html('2026-08-17', df)` 与 `render_html('2026-08-17', empty_df)` 都能返回完整 HTML，输出中包含字面量 `.star-na { color:#8c959f; }`。

## R2 学习权重加载兼容多余键

### 现象与根因

0817 日志首行：`[recommender] weights=default(invalid_file) thresholds=learned`。

`stock_research/recommender.py:67` 用集合全等校验键名：

```python
if not isinstance(d, dict) or set(d.keys()) != set(DEFAULT_WEIGHTS.keys()):
    return DEFAULT_WEIGHTS, 'default(invalid_file)'
```

而 `output/recommender_weights.json` 有 8 个键，比 `DEFAULT_WEIGHTS` 的 7 个多一个 `auction`：

```json
{"upper_short":0.28,"body_long":0.25,"volume_amp":0.15,"new_high":0.02,
 "ma_dev_health":0.1,"pre3_setup":0.1,"pre3_vol_slope":0.07,"auction":0.03}
```

全仓 `.py` 检索确认 `auction` 无任何实现：`score()` 产出的 `dims` 里没有该维度，`feature_extractor` 也不生成。它是历史遗留键。因此不能把 `auction` 纳入权重字典——`recommender.py:161` 的 `sum(dims[k] * WEIGHTS[k] for k in WEIGHTS)` 会 `KeyError`。

真实影响：`new_high` 学习权重为 0.02（远低于默认 0.088），说明标定结论是"创新高维度几乎无区分度"，而线上一直按 0.088 打分。0817 誉衡药业的 5★/0.7629 即为默认权重结果。

### 方案

改为"必需键齐全即接受，多余键忽略并告警"，归一化只在已知维度上做：

```python
def _load_weights():
    p = _OUTPUT_DIR / 'recommender_weights.json'
    if not p.exists():
        return DEFAULT_WEIGHTS, 'default'
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        if not isinstance(d, dict):
            return DEFAULT_WEIGHTS, 'default(invalid_file)'
        missing = set(DEFAULT_WEIGHTS) - set(d)
        if missing:
            return DEFAULT_WEIGHTS, f'default(missing:{",".join(sorted(missing))})'
        extra = sorted(set(d) - set(DEFAULT_WEIGHTS))
        vals = {k: float(d[k]) for k in DEFAULT_WEIGHTS}
        s = sum(vals.values())
        if s <= 0 or any(v < 0 for v in vals.values()):
            return DEFAULT_WEIGHTS, 'default(non_positive)'
        src = 'learned' if not extra else f'learned(ignored:{",".join(extra)})'
        return {k: v / s for k, v in vals.items()}, src
    except Exception:
        return DEFAULT_WEIGHTS, 'default(parse_error)'
```

要点：归一化分母为 7 个已知维度之和（0.97），不含被忽略的 `auction`；来源字符串保留被忽略键名，便于日志追溯。

### 影响文件

- `stock_research/recommender.py`（修改）：`_load_weights()`，行 61-74。

### 边界条件

- 缺必需键 → 回退默认并在来源里列出缺失键名，不静默。
- 值含负数或总和 ≤0 → 保持原 `default(non_positive)` 行为。
- 非法 JSON / 非 dict → 保持原回退分支。
- 星级阈值加载（`_load_thresholds`）当前工作正常，不改动。

### 预期结果

日志变为 `[recommender] weights=learned(ignored:auction) thresholds=learned`；权重归一化后 `new_high` 约 0.021，`upper_short` 约 0.289。评分口径变化属预期行为改变，需在验证阶段用 0817 样本对比新旧分值并记录。

## R3 打通 `is_limit_up` 字段

### 现象与根因

CSV 中 `sz.002437` 的 `signal_type=limit_up`，而 `selections.json` 里 `"signal_type":"breakthrough","is_limit_up":false`。

`signal_type` 的降级是设计意图（`daily_select.py:489` 注释明确"普通涨停降级为突破标签，一字才显示一字涨停"），**不改**。真正的 bug 在字段丢失链路：

1. `daily_select.py:429-435` 的 `sample` 里有 `is_limit_up`；
2. `daily_select.py:442-453` 组装写入 CSV 的 `rows` 时**没带这个字段**；
3. `daily_select.py:521` 因此走兜底 `s.get('is_limit_up', sig == 'one_word')`，而 `limit_up` 已映射成 `breakthrough` → 恒为 `False`。

结果：所有普通涨停在跟踪页都失去涨停标记，只有一字板才是 `True`。

### 方案

在 `rows` 中补 `'is_limit_up': bool(sig['is_limit_up'])`，让字段随 DataFrame 流到 CSV 和 `update_selections_json`。兜底表达式保留，用于历史无该列时的向后兼容。

```python
        rows.append({
            'code': code,
            'name': name,
            'signal_type': sig['signal_type'],
            'signal_subtypes': sig['signal_subtypes'],
            'is_limit_up': bool(sig['is_limit_up']),
            'price': round(sig['price'], 2),
            ...
        })
```

### 影响文件

- `daily_select.py`（修改）：`select()` 内 `rows.append(...)`，行 442-453。

### 边界条件

- CSV 新增一列 `is_limit_up`。`scripts/push_email.py` 与 `push_serverchan.py` 按列名取值，新增列不影响渲染，但需实际验证一遍。
- 历史 CSV 无该列，重跑旧日期时 `s.get(...)` 兜底仍生效，不报错。
- `signal_subtypes` 中 `new_all_time_high` 只是本地窗口内高点（`sz.002437` 本地仅 149 根、起自 2026-01-06），属标签口径问题，本次不改，在 summary 中记录。

## R4 同步失败可追溯 + 死码跳过

### 现象与根因

0817 同步结果：`synced=4436 failed=586 elapsed=4006.4s`（67 分钟）。

`data_hub/router.py:220-250` 的 `sync_kline_db`：

```python
df = self._fetch_kline_online(code, real_start, end)
if df is None or df.empty:
    failed.append(code)
    continue
```

问题有两层：

1. `failed` 只在内存里累加计数，函数返回 `{'synced':..,'failed':586,..}` 后即丢弃。`kline_db.py:39` 已建好 `failed_codes` 表（`code / last_err / retry_cnt / updated_at`），但全仓无任何写入代码，表始终为空。事后无法知道哪 586 只失败、失败多久。
2. `_fetch_kline_online`（`router.py:144-166`）串行降级四个数据源（腾讯 → mootdx → akshare → baostock）。一只彻底取不到数据的股票要跑完四个源才判失败，其中含网络超时。586 只 × 四源重试是 4006 秒耗时的主要构成。这类码多为长期停牌/已退市标的，每天重试没有收益。

注意 `df.empty` 不等于"出错"：已退市股票在增量区间内本就无数据。所以记录时区分错误类型，而不是一律当异常。

### 方案

**R4.1 落库失败明细**：在 `KlineDB` 增加两个方法，`sync_kline_db` 成功时清除记录、失败时累加计数。

```python
    # kline_db.py
    def mark_failed(self, code: str, err: str):
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO failed_codes (code,last_err,retry_cnt,updated_at) "
                "VALUES (?,?,1,?) "
                "ON CONFLICT(code) DO UPDATE SET "
                "last_err=excluded.last_err, retry_cnt=retry_cnt+1, updated_at=excluded.updated_at",
                (code, err[:200], datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
            )

    def clear_failed(self, code: str):
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM failed_codes WHERE code=?", (code,))

    def get_failed(self, min_retry: int = 1) -> pd.DataFrame:
        with self._conn() as c:
            return pd.read_sql_query(
                "SELECT code,last_err,retry_cnt,updated_at FROM failed_codes "
                "WHERE retry_cnt>=? ORDER BY retry_cnt DESC", c, params=(min_retry,))
```

**R4.2 增量同步跳过死码**：连续失败达到阈值且近期仍在失败的码，在增量模式下跳过；`full=True` 时不跳过，保证可强制回补。

```python
    def sync_kline_db(self, start, end, codes=None, full=False,
                      skip_retry_gte: int = 5, skip_window_days: int = 7):
        ...
        skip_set = set()
        if not full and skip_retry_gte > 0:
            fdf = self.db.get_failed(min_retry=skip_retry_gte)
            cutoff = (pd.Timestamp(end) - pd.Timedelta(days=skip_window_days)).strftime('%Y-%m-%d')
            skip_set = {r.code for r in fdf.itertuples() if str(r.updated_at)[:10] >= cutoff}
        skipped_dead = 0
        for i, code in enumerate(codes):
            if code in skip_set:
                skipped_dead += 1
                continue
            ...
            if df is None or df.empty:
                failed.append(code)
                self.db.mark_failed(code, 'empty_from_all_sources')
                continue
            ...
            self.db.clear_failed(code)
        return {'synced': synced, 'failed': len(failed),
                'skipped_dead': skipped_dead, 'failed_codes': failed[:20],
                'elapsed_s': round(time.time() - t0, 1)}
```

`data_hub/__main__.py:16` 的打印同步补上 `skipped_dead`，让 `run_daily.sh` 的日志能看出跳过量。

### 影响文件

- `data_hub/store/kline_db.py`（修改）：新增 `mark_failed` / `clear_failed` / `get_failed`。
- `data_hub/router.py`（修改）：`sync_kline_db()`，行 220-250。
- `data_hub/__main__.py`（修改）：同步结果打印，行 16。
- `data_hub/api.py`（修改）：`sync_kline_db()` 透传新参数，行 40。

### 边界条件

- 首次运行 `failed_codes` 为空，行为与现状完全一致，不会误跳过。
- 一只码恢复上市/复牌后成功同步 → `clear_failed` 归零，下次不再跳过。
- `retry_cnt` 达阈值但 `updated_at` 超出窗口（7 天）→ 重新尝试一次，避免永久黑名单。
- `mark_failed` 每只失败码一次写库。586 次单条写入在 WAL 模式下开销可接受，无需批量化。
- 跳过逻辑只作用于增量；`python -m data_hub` 的全量入口需确认走 `full=True`。

## 数据流（修复后）

```text
run_daily.sh
  ├─ data_hub sync_today
  │    router.sync_kline_db(full=False)
  │      ├─ 读 failed_codes（retry_cnt≥5 且 7 日内）→ skip_set，直接跳过   [R4.2]
  │      ├─ 取数成功 → upsert_kline + clear_failed                        [R4.1]
  │      └─ 四源全空 → mark_failed(code,'empty_from_all_sources')         [R4.1]
  ├─ daily_select.py --date YYYY-MM-DD
  │    recommender._load_weights() → learned(ignored:auction)             [R2]
  │    select() → rows 带 is_limit_up                                     [R3]
  │      ├─ write_csv         → daily_selections_YYYY-MM-DD.csv（新增列）
  │      └─ update_selections_json → is_limit_up 真值写入 selections.json
  └─ push_email.py
       render_html() 正常渲染并发信                                        [R1]
```

## 验证方式

1. R1：分别用 0817 的 CSV 与空 DataFrame 调 `render_html()`，断言返回非空且含 `.star-na { color:#8c959f; }`。
2. R2：运行后确认日志为 `weights=learned(ignored:auction)`，并用 0817 特征对比新旧 `score`/`star`，把差异记入 summary。
3. R3：以 `--date 2026-08-17` 重跑选股，检查 CSV 含 `is_limit_up=True`、`selections.json` 中 `sz.002437` 的 `is_limit_up` 为 `true` 且 `signal_type` 仍为 `breakthrough`。
4. R4：构造临时 DB 验证 `mark_failed` 幂等累加、`clear_failed` 清零、`get_failed` 过滤；观察下一次真实增量同步的 `skipped_dead` 与耗时变化。
5. 回归：`push_serverchan.py` 渲染不受 CSV 新增列影响。

## 范围外（本次不做）

- 不调整 `cond1/cond2` 选股条件与 25 亿预筛阈值——0817 只出 1 只票是策略与市场结构的匹配问题，需要先做回测再谈改动。
- 不修 `new_all_time_high` 的窗口口径问题，仅记录。
- 不为 `_fetch_kline_online` 引入并发，先用死码跳过换耗时收益，观察效果后再评估。
- 不改星级阈值与 `_SIGNAL_TO_TRACKER` 映射。


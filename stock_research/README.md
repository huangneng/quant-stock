# 选股后走势归因研究

研究目标：从入选日及之前的量价、涨停、形态、相对位置等特征，挖掘区分**强势 / 破位 / 震荡 / 偏弱**四类后续走势的先行因子。

## 跑法

```bash
python stock_research/pipeline.py            # 全跑
python stock_research/pipeline.py --refresh  # 清缓存重跑
```

产物在 `stock_research/output/`：

- `labels.parquet` - 每个样本的入选信息 + 走势标签
- `features.parquet` - 特征宽表
- `feature_ranking.csv` - Kruskal-Wallis 单因子区分度排名
- `tree_rules.txt` - 决策树可读规则
- `report.html` - 可视化总览

## 走势标签定义（30 个交易日）

| 标签 | 规则 |
|---|---|
| `strong` 强势 | 最大回撤 < 5% 且 30 日收益 > 15% |
| `breakdown` 破位 | 期间触发 -10% 止损（相对买入价） |
| `oscillate` 震荡 | 收益绝对值 < 8% 且最大回撤 5%~10% |
| `weak` 偏弱 | 兜底分类 |
| `pending` 数据不足 | 入选日距今不满 30 个交易日 |

阈值见 `config.py`，可随时调整。

## 第一轮发现（2026-06-04）

### 样本分布（91 个入选样本）

| 标签 | 数量 | 说明 |
|---|---|---|
| pending | 33 | 入选日距今不满 30 个交易日 |
| breakdown | 28 | 期间触发 -10% 止损 |
| weak | 25 | 兜底分类（小幅下行 / 不满足强势条件） |
| strong | 4 | 30 日内 ret>8% 且最大回撤<8% |
| oscillate | 1 | |

**关键观察**：91 只票里只有 4 只走出"强势"，大量样本（28 只）跌破止损。即便放宽阈值（max_dd<8% 且 ret>8%），强势样本依然稀少。

### Top 区分因子（Kruskal-Wallis）

| 因子 | p 值 | strong 中位数 | breakdown 中位数 | weak 中位数 |
|---|---|---|---|---|
| upper_shadow_pct（入选日上影线/开盘价）| 0.003 | 0.001 | 0.023 | 0.002 |
| body_pct（入选日实体长度/开盘价）| 0.016 | 0.082 | 0.025 | 0.060 |
| amount_5d_avg_yi（入选前 5 日均成交额，亿）| 0.072 | 47.6 | 34.8 | 48.5 |

**初步规律**：
1. **强势组的入选 K 线几乎没有上影线**（中位数 0.1%），而破位组的上影线明显大（2.3%）→ 上影线意味着上涨乏力 / 抛压释放
2. **强势组实体明显更长**（8.2% vs 破位组 2.5%）→ 选中那天就是大阳线，而非小阳线 / 十字星
3. **5 日均成交额没有显著区分度**——单日量能可能比累计量能更重要

### 决策树（max_depth=3）

- 训练集准确率：0.737
- 时间切分测试集（≥2026-05-15 入选）准确率：0.400
- **明显过拟合**——样本太少（merged 仅 58 个有效样本），决策树容易过拟合，测试集表现差

### 后续迭代方向

1. **样本扩充**：等积累到 200+ 样本（约 1-2 个月）再重跑
2. **特征精化**：
   - 加入「上影线/实体比例」组合特征
   - 加入入选前最近一次涨停的封板时长
   - 加入板块协同度（同期同行业其他股票表现）
3. **阈值调参**：扩大 strong/oscillate 边界至更平衡分布
4. **模型替代**：样本量上来后试 RandomForest / XGBoost 看是否更稳

### 个人解读

**入选时不要碰带上影线的票**——这是当前 91 样本里最显著的信号，上影线长意味着上涨过程中遇到抛压释放，后续容易破位。把这条加进选股过滤条件可能立竿见影。

---

## 多维回测（multi_backtest）

把历史所有入选样本铺开，按持有期 / 板块 / 信号类型 / 量能 / 形态 / 推荐星级 等多维度切片，叠加 HS300 超额、风险指标、Cohort 月度漂移、Top 5 关键发现，一次跑完出一份 Tokyo Night 风格 HTML。

### 跑法

```bash
python -m stock_research.multi_backtest          # 单独跑
python -m stock_research.pipeline                # 主管线末尾会自动接上
```

### 产物（output/）

| 文件 | 说明 |
|---|---|
| `holdings_matrix.parquet` | 多持有期收益矩阵（5/10/20/30/60 日 ret/max_high/max_dd/win + days_to_peak/days_to_stop） |
| `alpha_30.csv` | 每只票相对 HS300 的 excess_5/10/20/30/60 |
| `slice_*.csv` | 9 个单维度切片（signal_type / amount_tier / sector / is_60d_high / is_120d_high / body_pct_tier / upper_shadow_filter / pre3_red_tier / star） |
| `cross_*__*_ret_30_mean.csv` | 4 组关键二维交叉（star×amount/star×signal/shadow×sector/body×pre3_red） |
| `risk_metrics.csv` | 胜率 / 盈亏比 / Sharpe 近似 / Breakdown 比例 / α / 止损命中率 |
| `cohort_monthly.csv` | 月度 cohort（含 underperform 标记） |
| `top_findings.txt` | 自动提炼 Top 5 关键发现 |
| `multi_backtest_report.html` | 单页 Tokyo Night HTML 报告（摘要卡 + 发现 + 切片 + 热图 + cohort） |

### 当前样例发现（2026-06-04）

1. `[pre3_red_tier]` 2阳 (n=28) vs 3阳 (n=31) ret_30 84.5% vs -16.5% (Δ +101pp) — 入选前已连涨 3 日反而后劲不足
2. `[upper_shadow_filter]` filtered vs excluded ret_30 50.5% vs 1.8% (Δ +48.7pp) — 上影线过滤继续验证有效
3. `[star]` 4★ vs 2★ ret_30 52.4% vs -15.6% (Δ +68pp) — 推荐星级仍呈单调
4. `[signal_type]` breakthrough vs gap ret_30 42.7% vs -15.6% — 跳空买入显著弱于平台突破
5. `[sector]` 沪市主板 (53.3%) > 深市主板 (16.2%)

> 注：30 日窗口已结算样本仅 5 例（多数入选日距今不满 30 个交易日），breakdown 比例偏高是当前数据窗口偏向最近活跃区间所致，等样本累积到 30+ 后重读会更稳。

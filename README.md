# Quant Stock：A 股动量突破选股与跟踪系统

一个面向 A 股市场的自动化量化选股项目，覆盖 **实时数据接入 → 每日选股 → 推荐评分 → 持仓跟踪 → HTML 报告 → 邮件/微信推送 → 回测研究** 的完整闭环。

项目目标不是预测短期涨跌，而是把「高成交额 + 强动量 + 新高/突破」这类人工盯盘逻辑工程化，形成可复现、可追踪、可持续迭代的选股研究系统。

> 风险提示：本项目仅用于量化策略研究、工程实践和比赛/作品展示，不构成任何投资建议。股票市场有风险，历史样本和回测结果不代表未来收益。

## 在线展示

- 跟踪报告：https://huangneng.github.io/quant-stock/tracker_report/

报告页会展示每日入选股票、推荐星级、评分、持仓动作、止损/止盈状态和历史走势跟踪。

## 核心能力

- **全市场自动扫描**：覆盖沪深 A 股，过滤指数、ETF、B 股等非普通股票。
- **实时成交额预筛**：优先使用 Sina 实时快照，并用 Tencent 快照补齐缺失，对高成交额股票做第一层过滤。
- **信号识别**：识别涨停、跳空、平台突破等动量突破形态。
- **多维推荐评分**：结合形态、量能、新高、均线偏离、前 3 日走势等特征输出 `score` 和 1~5 星推荐等级。
- **统一数据层**：`data_hub` 封装 KlineDB、Baostock、mootdx、Akshare、Sina、Tencent，实现数据源路由和降级；东方财富接口统一限流重试。
- **跟踪报告**：自动生成 `tracker_report/index.html`，持续跟踪历史入选股票表现。
- **推送通知**：支持 SMTP 邮件和 Server酱微信推送。
- **研究闭环**：`stock_research` 支持特征归因、多维切片、风险指标、cohort 分析和推荐器回测。

## 系统架构

```text
Sina / Tencent / Baostock / mootdx / Akshare / Eastmoney
          ↓
       data_hub
          ↓
     daily_select.py
          ↓
feature_extractor + recommender
          ↓
CSV / selections.json / tracker_report
          ↓
Email / Server酱 / GitHub Pages
          ↓
stock_research 多维回测与特征归因
```

## 目录结构

```text
.
├── data_hub/                 # 统一数据层：KlineDB / Baostock / mootdx / Akshare / Sina / Tencent
├── daily_select.py           # 每日盘后选股入口
├── quant_backtest/           # 回测框架、跟踪页生成、策略验证
├── scripts/                  # 交易日检查、邮件推送、Server酱推送
├── stock_data/               # selections.json、交易日历、本地缓存和 KlineDB
├── stock_research/           # 特征工程、推荐评分、多维回测、研究报告
├── tracker_report/           # GitHub Pages 静态跟踪报告
├── run_daily.sh              # launchd/本地定时任务入口
├── quant.env.example         # 推送环境变量示例
└── requirements.txt          # Python 依赖
```

## 数据流

1. `daily_select.py` 获取全市场股票列表。
2. 使用 `data_hub.get_market_snapshot()` 拉取实时行情快照，按成交额进行预筛。
3. 对预筛股票拉取近 60 日 K 线，识别涨停、跳空、突破等信号。
4. `stock_research.feature_extractor` 提取入选日与前序走势特征。
5. `stock_research.recommender` 计算推荐分数和星级。
6. 结果写入 CSV、`stock_data/selections.json`，并刷新 `tracker_report/index.html`。
7. `scripts/push_email.py` 和 `scripts/push_serverchan.py` 推送当日结果。
8. `stock_research` 后续对历史入选样本做多维回测和归因分析。

## 快速开始

### 1. 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置推送环境变量（可选）

```bash
cp quant.env.example ~/.quant.env
chmod 600 ~/.quant.env
```

`~/.quant.env` 中可配置：

```bash
export SMTP_HOST=smtp.qq.com
export SMTP_PORT=465
export SMTP_USER=your_qq@qq.com
export SMTP_PASS=your_smtp_authcode
export MAIL_TO=your_qq@qq.com
export SERVERCHAN_KEY=SCTxxxxxx
```

如果未配置推送变量，选股和报告仍可正常运行，推送脚本会静默跳过。

### 3. 运行每日选股

```bash
python daily_select.py
```

生成：

- `stock_research/output/daily_selections_YYYY-MM-DD.csv`
- `stock_research/output/daily_selections_latest.csv`
- `stock_data/selections.json`
- `tracker_report/index.html`

### 4. 同步本地 KlineDB

```bash
python -m data_hub sync_today
```

`data_hub` 会尽量从本地 SQLite KlineDB 读取历史 K 线，缺失时回退在线数据源。

## 常用命令

| 命令 | 说明 |
|---|---|
| `python daily_select.py` | 盘后选股并刷新报告 |
| `python scripts/push_email.py` | 推送当日盘后选股邮件 |
| `python scripts/push_serverchan.py` | Server酱微信推送 |
| `python -m data_hub sync_today` | 同步最近交易日 K 线到本地库 |
| `python -m stock_research.pipeline` | 跑特征研究与多维回测主管线 |
| `python -m stock_research.multi_backtest` | 单独跑多维回测 |

## 自动化任务

`run_daily.sh` 封装了本地定时执行逻辑：

```bash
./run_daily.sh           # 盘后任务：16:15 后执行，带防重复 stamp
```

盘后任务流程：

1. 检查是否交易日。
2. 读取 `~/.quant.env`。
3. 同步本地 KlineDB（失败不阻塞主流程）。
4. 运行 `daily_select.py`。
5. 推送邮件和 Server酱。
6. 写入 `stock_data/.last_run_date` 防止当天重复执行。

## 输出产物

| 文件 | 说明 |
|---|---|
| `stock_research/output/daily_selections_YYYY-MM-DD.csv` | 每日盘后选股结果 |
| `stock_data/selections.json` | 历史入选记录，供跟踪页读取 |
| `tracker_report/index.html` | 静态跟踪报告，可部署到 GitHub Pages |
| `stock_research/output/multi_backtest_report.html` | 多维回测研究报告 |
| `stock_research/output/feature_ranking.csv` | 单因子区分度排名 |
| `stock_research/output/risk_metrics.csv` | 风险收益指标 |

## 选股与评分逻辑

每日选股的核心逻辑在 `daily_select.py`：

- 先按成交额过滤，减少全市场扫描噪音。
- 再识别强动量信号：涨停、跳空、平台突破。
- 对候选股票提取特征并交给推荐器评分。
- 推荐器输出 `score` 和 `star`，星级用于排序和展示，不是买入指令。

推荐星级由 `stock_research/recommender.py` 计算，默认阈值大致为：

| 分数区间 | 星级 |
|---|---|
| `score >= 0.80` | 5★ |
| `score >= 0.60` | 4★ |
| `score >= 0.45` | 3★ |
| `score >= 0.30` | 2★ |
| `< 0.30` | 1★ |

推送消息会将所有候选放在同一张表中，默认按星级和评分降序排列。

## 持仓跟踪逻辑

`tracker_report/index.html` 会对历史入选股票持续跟踪：

- 建仓：入选当日。
- 持有：未触发明显加减仓或清仓条件。
- 加仓：入选后短窗口内收益、冲高和阳线数量满足强势延续条件。
- 减仓：短窗口收益和回撤转弱。
- 清仓：触发止损或显著回撤条件。

该逻辑用于跟踪和复盘，不构成交易建议。

## 回测与研究

`stock_research/` 负责把每日入选样本沉淀为研究数据：

- `feature_extractor.py`：提取量价、形态、新高、均线偏离等特征。
- `label_generator.py`：根据未来 30 个交易日走势打标签。
- `multi_backtest.py`：按持有期、板块、信号类型、成交额、星级等维度做切片分析。
- `risk_metrics.py`：计算胜率、盈亏比、Sharpe 近似、止损命中率等指标。
- `report_builder.py` / `multi_report.py`：生成 HTML 研究报告。

更多研究说明见 `stock_research/README.md`。

## 数据层设计

统一通过 `data_hub.api` 获取数据：

```python
from data_hub import api as hub

df = hub.get_kline('sh.600519', '2026-04-01', '2026-05-30', require_today=True)
snapshot = hub.get_market_snapshot()
status = hub.check_completeness(['sh.600519'], '2026-06-10')
```

核心能力：

- `get_universe()`：获取股票池。
- `get_kline()`：获取日线数据，自动路由 KlineDB → Baostock → Akshare。
- `get_market_snapshot()`：获取 Sina 实时行情快照。
- `check_completeness()`：检查本地库完整性。
- `sync_kline_db()`：同步本地 SQLite KlineDB。

## 技术栈

- Python 3
- pandas / numpy
- requests
- Baostock
- Akshare
- Sina 实时行情接口
- SQLite KlineDB
- HTML/CSS 静态报告
- SMTP 邮件推送
- Server酱微信推送
- GitHub Pages 静态展示

## 项目亮点

1. **工程闭环完整**：不是单脚本选股，而是包含数据、策略、评分、报告、推送、复盘的完整系统。
2. **数据源解耦**：业务代码统一依赖 `data_hub.api`，便于切换和降级。
3. **实时 + 历史结合**：今日行情使用实时快照补齐，历史 K 线走本地库和在线源。
4. **可解释评分**：推荐星级来自明确特征和阈值，便于复盘调参。
5. **持续研究迭代**：每天新增样本都会进入 `selections.json`，用于后续多维回测和因子分析。
6. **适合公开展示**：静态 HTML 报告可直接部署到 GitHub Pages。

## 注意事项

- A 股实时行情、交易日历和历史 K 线受数据源稳定性影响，网络异常时可能降级或跳过部分数据。
- 推荐星级只是候选优先级，不代表收益保证。
- 请勿将真实 SMTP 授权码、Server酱 Key 等敏感信息提交到仓库。

## 免责声明

本项目仅用于量化策略研究、软件工程实践和比赛/作品展示，不构成任何投资建议、荐股建议或收益承诺。股票市场存在较高风险，历史回测、历史样本统计和自动化评分均不能代表未来表现。使用者应自行承担投资决策风险。

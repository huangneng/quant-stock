# quant_backtest：策略与跟踪报告

当前保留每日选股主流程实际用到的模块（原独立回测框架已移除，回测研究统一走 `stock_research/`）。

## 目录结构

```
quant_backtest/
├── data.py            # 数据获取（经 data_hub 路由）
├── strategy.py        # 动量突破策略（信号判定口径与 daily_select.py 一致）
├── daily_tracker.py   # 历史入选股票跟踪
├── tracker_report.py  # tracker_report/index.html 报告生成
└── README.md
```

## 用法

报告生成通常由 `daily_select.py` 在每日选股后自动调用，也可单独刷新：

```bash
python3 -c "from quant_backtest.tracker_report import generate_full_report; generate_full_report()"
```

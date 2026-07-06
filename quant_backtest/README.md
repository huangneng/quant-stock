# 量化策略回测框架

一个轻量级的A股量化策略回测工具，支持自定义策略开发。

## 快速开始

```bash
cd quant_backtest
python main.py
```

## 目录结构

```
quant_backtest/
├── data.py       # 数据获取模块（akshare免费数据源）
├── strategy.py   # 策略模块（内置策略 + 自定义模板）
├── backtest.py   # 回测引擎（绩效计算、可视化）
├── main.py       # 主程序入口
└── README.md     # 使用说明
```

## 如何自定义策略

编辑 `strategy.py` 中的 `CustomStrategy` 类：

```python
class CustomStrategy(BaseStrategy):
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        
        # 你的策略逻辑
        # df['close'] - 收盘价
        # df['open'] - 开盘价
        # df['high'] - 最高价
        # df['low'] - 最低价
        # df['volume'] - 成交量
        
        # 生成信号
        df['signal_final'] = 0
        df.loc[买入条件, 'signal_final'] = 1   # 买入
        df.loc[卖出条件, 'signal_final'] = -1  # 卖出
        
        return df
```

## 内置策略

| 策略 | 说明 | 参数 |
|------|------|------|
| DoubleMAStrategy | 双均线交叉 | short_window, long_window |
| RSIStrategy | RSI超买超卖 | period, oversold, overbought |
| BollingerBandsStrategy | 布林带突破 | period, std_dev |
| CustomStrategy | 自定义策略 | - |

## 回测指标

- 总收益率 / 年化收益率
- 最大回撤
- 夏普比率
- 胜率 / 盈亏比
- 交易次数

## 数据层

项目已统一使用 [data_hub](https://github.com/huangneng/quant/tree/main/data_hub) 数据层：

- 智能路由：KlineDB（SQLite 本地库）→ Baostock → Akshare；今日 K 线走 Sina 实时快照
- 自动降级：Baostock 超时（15s）自动切 Akshare
- KlineDB 每日 16:00 通过 launchd 增量同步

所有调用方应仅依赖 `data_hub.api`，禁止直接 import baostock/akshare/requests。

```python
from data_hub import api as hub
df = hub.get_kline('sh.600519', '2026-04-01', '2026-05-30', require_today=True)
snap = hub.get_market_snapshot()  # 全市场实时快照 ~1.5s
report = hub.check_completeness(codes, '2026-06-09')
```

## 下一步

1. 运行 `python main.py` 测试内置策略
2. 在 `CustomStrategy` 中实现你的策略
3. 对比不同参数的回测结果
4. 优化策略，提高夏普比率，降低最大回撤
"""
量化策略回测框架 v1.0
支持：A股数据获取、策略定义、回测分析、可视化
"""

import akshare as ak
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from abc import ABC, abstractmethod

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False


class DataFetcher:
    """数据获取模块"""
    
    @staticmethod
    def get_stock_data(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取A股日线数据
        
        Args:
            symbol: 股票代码，如 '000001' 或 'sz000001'
            start_date: 开始日期，格式 '20230101'
            end_date: 结束日期，格式 '20231231'
        
        Returns:
            DataFrame with columns: date, open, high, low, close, volume
        """
        try:
            # 统一股票代码格式
            if symbol.startswith('sz') or symbol.startswith('sh'):
                code = symbol[2:]
            else:
                code = symbol
            
            # 使用 akshare 获取数据
            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq"  # 前复权
            )
            
            # 重命名列
            df = df.rename(columns={
                '日期': 'date',
                '开盘': 'open',
                '最高': 'high',
                '最低': 'low',
                '收盘': 'close',
                '成交量': 'volume'
            })
            
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
            
            print(f"成功获取 {symbol} 数据：{len(df)} 条记录")
            return df[['open', 'high', 'low', 'close', 'volume']]
            
        except Exception as e:
            print(f"获取数据失败：{e}")
            return None


class BaseStrategy(ABC):
    """策略基类 - 继承此类实现自己的策略"""
    
    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """
        生成交易信号
        
        Args:
            data: 包含 open, high, low, close, volume 的DataFrame
        
        Returns:
            Signal Series: 1=买入, 0=持有/空仓, -1=卖出
        """
        pass
    
    def get_strategy_name(self) -> str:
        return self.__class__.__name__


class DoubleMAStrategy(BaseStrategy):
    """示例策略：双均线交叉"""
    
    def __init__(self, fast_period: int = 5, slow_period: int = 20):
        self.fast_period = fast_period
        self.slow_period = slow_period
    
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=data.index)
        
        # 计算均线
        fast_ma = data['close'].rolling(window=self.fast_period).mean()
        slow_ma = data['close'].rolling(window=self.slow_period).mean()
        
        # 生成信号
        signals[fast_ma > slow_ma] = 1   # 金叉买入
        signals[fast_ma < slow_ma] = -1  # 死叉卖出
        
        return signals


class RSIStrategy(BaseStrategy):
    """示例策略：RSI超买超卖"""
    
    def __init__(self, period: int = 14, oversold: float = 30, overbought: float = 70):
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
    
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=data.index)
        
        # 计算RSI
        delta = data['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(window=self.period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        # 生成信号
        signals[rsi < self.oversold] = 1    # 超卖买入
        signals[rsi > self.overbought] = -1  # 超买卖出
        
        return signals


class BacktestEngine:
    """回测引擎"""
    
    def __init__(self, initial_capital: float = 100000, commission: float = 0.0003):
        """
        Args:
            initial_capital: 初始资金
            commission: 手续费率（单边）
        """
        self.initial_capital = initial_capital
        self.commission = commission
    
    def run(self, data: pd.DataFrame, signals: pd.Series) -> dict:
        """
        运行回测
        
        Returns:
            回测结果字典，包含收益曲线、交易记录等
        """
        # 初始化
        capital = self.initial_capital
        position = 0  # 持仓数量
        shares = 0    # 持仓股数
        
        # 记录
        portfolio_value = []
        trades = []
        
        # 遍历每个交易日
        for i in range(len(data)):
            date = data.index[i]
            close = data['close'].iloc[i]
            signal = signals.iloc[i]
            
            # 买入信号且空仓
            if signal == 1 and position == 0:
                # 计算可买入股数（以100股为单位）
                max_shares = int(capital / close / 100) * 100
                if max_shares > 0:
                    cost = max_shares * close * (1 + self.commission)
                    capital -= cost
                    shares = max_shares
                    position = 1
                    trades.append({
                        'date': date,
                        'type': 'BUY',
                        'price': close,
                        'shares': shares,
                        'capital': capital
                    })
            
            # 卖出信号且持仓
            elif signal == -1 and position == 1:
                revenue = shares * close * (1 - self.commission)
                capital += revenue
                trades.append({
                    'date': date,
                    'type': 'SELL',
                    'price': close,
                    'shares': shares,
                    'capital': capital
                })
                shares = 0
                position = 0
            
            # 记录当日资产总值
            total_value = capital + shares * close
            portfolio_value.append({
                'date': date,
                'value': total_value,
                'cash': capital,
                'position_value': shares * close
            })
        
        # 转换为DataFrame
        portfolio_df = pd.DataFrame(portfolio_value).set_index('date')
        trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
        
        # 计算绩效指标
        metrics = self._calculate_metrics(portfolio_df, data)
        
        return {
            'portfolio': portfolio_df,
            'trades': trades_df,
            'metrics': metrics
        }
    
    def _calculate_metrics(self, portfolio: pd.DataFrame, data: pd.DataFrame) -> dict:
        """计算回测绩效指标"""
        returns = portfolio['value'].pct_change().dropna()
        
        # 总收益率
        total_return = (portfolio['value'].iloc[-1] / self.initial_capital - 1) * 100
        
        # 年化收益率
        days = len(portfolio)
        annual_return = (portfolio['value'].iloc[-1] / self.initial_capital) ** (252 / days) - 1
        annual_return *= 100
        
        # 最大回撤
        cummax = portfolio['value'].cummax()
        drawdown = (portfolio['value'] - cummax) / cummax
        max_drawdown = drawdown.min() * 100
        
        # 夏普比率（假设无风险利率3%）
        rf = 0.03 / 252
        excess_returns = returns - rf
        sharpe = np.sqrt(252) * excess_returns.mean() / excess_returns.std() if excess_returns.std() != 0 else 0
        
        # 基准收益（买入持有）
        benchmark_return = (data['close'].iloc[-1] / data['close'].iloc[0] - 1) * 100
        
        return {
            '总收益率(%)': round(total_return, 2),
            '年化收益率(%)': round(annual_return, 2),
            '最大回撤(%)': round(max_drawdown, 2),
            '夏普比率': round(sharpe, 2),
            '基准收益率(%)': round(benchmark_return, 2),
            '交易天数': days
        }
    
    def plot_results(self, result: dict, data: pd.DataFrame, strategy_name: str):
        """可视化回测结果"""
        fig, axes = plt.subplots(3, 1, figsize=(14, 12))
        
        # 1. 资产曲线
        ax1 = axes[0]
        ax1.plot(result['portfolio'].index, result['portfolio']['value'], 
                label='策略资产', color='blue', linewidth=1.5)
        # 基准曲线
        benchmark = data['close'] / data['close'].iloc[0] * self.initial_capital
        ax1.plot(benchmark.index, benchmark.values, 
                label='买入持有', color='gray', linestyle='--', linewidth=1)
        ax1.set_title(f'{strategy_name} - 资产曲线')
        ax1.set_ylabel('资产价值')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # 标注买卖点
        trades = result['trades']
        if not trades.empty:
            for _, trade in trades.iterrows():
                color = 'green' if trade['type'] == 'BUY' else 'red'
                marker = '^' if trade['type'] == 'BUY' else 'v'
                ax1.scatter(trade['date'], trade['capital'] + trade['shares'] * trade['price'] if trade['type'] == 'BUY' else trade['capital'],
                           color=color, marker=marker, s=100, zorder=5)
        
        # 2. 价格走势与信号
        ax2 = axes[1]
        ax2.plot(data.index, data['close'], label='收盘价', color='black', linewidth=1)
        ax2.set_title('价格走势')
        ax2.set_ylabel('价格')
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        
        # 3. 回撤曲线
        ax3 = axes[2]
        cummax = result['portfolio']['value'].cummax()
        drawdown = (result['portfolio']['value'] - cummax) / cummax * 100
        ax3.fill_between(drawdown.index, drawdown.values, 0, 
                        color='red', alpha=0.3, label='回撤')
        ax3.set_title('回撤曲线')
        ax3.set_ylabel('回撤(%)')
        ax3.set_xlabel('日期')
        ax3.legend()
        ax3.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig('backtest_result.png', dpi=150)
        plt.show()
        print("图表已保存至 backtest_result.png")


def run_backtest(
    symbol: str,
    strategy: BaseStrategy,
    start_date: str = None,
    end_date: str = None,
    initial_capital: float = 100000
):
    """
    一键运行回测
    
    Args:
        symbol: 股票代码
        strategy: 策略实例
        start_date: 开始日期，默认一年前
        end_date: 结束日期，默认今天
        initial_capital: 初始资金
    """
    # 设置默认日期
    if end_date is None:
        end_date = datetime.now().strftime('%Y%m%d')
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=365)).strftime('%Y%m%d')
    
    print(f"\n{'='*50}")
    print(f"股票代码: {symbol}")
    print(f"策略: {strategy.get_strategy_name()}")
    print(f"回测区间: {start_date} ~ {end_date}")
    print(f"初始资金: {initial_capital:,.0f} 元")
    print(f"{'='*50}\n")
    
    # 获取数据
    data = DataFetcher.get_stock_data(symbol, start_date, end_date)
    if data is None:
        return
    
    # 生成信号
    signals = strategy.generate_signals(data)
    
    # 运行回测
    engine = BacktestEngine(initial_capital=initial_capital)
    result = engine.run(data, signals)
    
    # 打印结果
    print("\n📊 回测绩效:")
    print("-" * 40)
    for key, value in result['metrics'].items():
        print(f"{key}: {value}")
    
    # 打印交易记录
    if not result['trades'].empty:
        print(f"\n📋 交易记录 (共 {len(result['trades'])} 笔):")
        print("-" * 60)
        print(result['trades'].to_string(index=False))
    
    # 绘图
    engine.plot_results(result, data, strategy.get_strategy_name())
    
    return result


# ============================================================
# 在这里定义你自己的策略！
# ============================================================

class MyCustomStrategy(BaseStrategy):
    """
    自定义策略模板 - 在这里实现你的选股策略
    
    策略逻辑：
    1. 买入条件：???
    2. 卖出条件：???
    """
    
    def __init__(self, param1=10, param2=20):
        self.param1 = param1
        self.param2 = param2
    
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """
        实现你的策略逻辑
        
        可用数据：
        - data['close']  收盘价
        - data['open']   开盘价
        - data['high']   最高价
        - data['low']    最低价
        - data['volume'] 成交量
        
        常用指标计算示例：
        - 移动平均: data['close'].rolling(window=20).mean()
        - 标准差: data['close'].rolling(window=20).std()
        - 涨跌幅: data['close'].pct_change()
        - 最大值: data['high'].rolling(window=20).max()
        - 最小值: data['low'].rolling(window=20).min()
        """
        signals = pd.Series(0, index=data.index)
        
        # ===== 在这里写你的策略逻辑 =====
        # 示例：价格突破20日高点买入，跌破20日低点卖出
        high_20 = data['high'].rolling(window=self.param1).max()
        low_20 = data['low'].rolling(window=self.param1).min()
        
        # 买入信号
        signals[data['close'] > high_20.shift(1)] = 1
        
        # 卖出信号  
        signals[data['close'] < low_20.shift(1)] = -1
        
        # =================================
        
        return signals


if __name__ == "__main__":
    # ==================== 使用示例 ====================
    
    # 示例1：使用双均线策略
    run_backtest(
        symbol='000001',  # 平安银行
        strategy=DoubleMAStrategy(fast_period=5, slow_period=20),
        start_date='20240101',
        end_date='20241231',
        initial_capital=100000
    )
    
    # 示例2：使用RSI策略
    # run_backtest(
    #     symbol='600519',  # 贵州茅台
    #     strategy=RSIStrategy(period=14, oversold=30, overbought=70),
    #     start_date='20240101',
    #     end_date='20241231'
    # )
    
    # 示例3：使用自定义策略
    # run_backtest(
    #     symbol='000858',  # 五粮液
    #     strategy=MyCustomStrategy(param1=20, param2=60),
    #     start_date='20240101',
    #     end_date='20241231'
    # )

# -*- coding: utf-8 -*-
"""
回测引擎 - 执行策略回测并计算绩效指标
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime


class BacktestEngine:
    """
    回测引擎
    """
    
    def __init__(self, initial_capital: float = 100000, commission: float = 0.0003):
        """
        初始化回测引擎
        
        Args:
            initial_capital: 初始资金，默认10万
            commission: 交易手续费率，默认万分之三
        """
        self.initial_capital = initial_capital
        self.commission = commission
        self.results = None
    
    def run(self, data: pd.DataFrame, strategy) -> dict:
        """
        运行回测
        
        Args:
            data: 原始行情数据
            strategy: 策略实例
        
        Returns:
            回测结果字典
        """
        # 生成信号
        signals = strategy.generate_signals(data)
        
        # 初始化回测变量
        capital = self.initial_capital
        position = 0  # 持仓数量
        cash = capital
        portfolio_value = []
        trades = []
        
        # 遍历每个交易日
        for i in range(len(signals)):
            date = signals.index[i]
            close = signals['close'].iloc[i]
            signal_raw = signals['signal_final'].iloc[i] if 'signal_final' in signals.columns else signals['signal'].iloc[i]
            signal = int(signal_raw) if pd.notna(signal_raw) else 0
            
            # 买入信号
            if signal == 1 and position == 0:
                shares = int(cash * 0.95 / close / 100) * 100  # 买入手数(整数手)，保留5%现金
                if shares > 0:
                    cost = shares * close * (1 + self.commission)
                    if cost <= cash:
                        position = shares
                        cash -= cost
                        trades.append({
                            'date': date,
                            'type': 'BUY',
                            'price': close,
                            'shares': shares,
                            'capital': cash + position * close
                        })
            
            # 卖出信号
            elif signal == -1 and position > 0:
                revenue = position * close * (1 - self.commission)
                cash += revenue
                trades.append({
                    'date': date,
                    'type': 'SELL',
                    'price': close,
                    'shares': position,
                    'capital': cash
                })
                position = 0
            
            # 记录当日账户价值
            portfolio_value.append({
                'date': date,
                'cash': cash,
                'position': position,
                'position_value': position * close,
                'total': cash + position * close
            })
        
        # 整理结果
        results_df = pd.DataFrame(portfolio_value)
        results_df = results_df.set_index('date')
        
        self.results = {
            'portfolio': results_df,
            'trades': trades,
            'signals': signals,
            'strategy_name': strategy.name
        }
        
        return self.results
    
    def calculate_metrics(self) -> dict:
        """
        计算回测绩效指标
        """
        if self.results is None:
            return {}
        
        portfolio = self.results['portfolio']
        
        # 收益率序列
        portfolio['returns'] = portfolio['total'].pct_change()
        
        # 总收益率
        total_return = (portfolio['total'].iloc[-1] - self.initial_capital) / self.initial_capital
        
        # 年化收益率
        days = (portfolio.index[-1] - portfolio.index[0]).days
        annual_return = (1 + total_return) ** (365 / days) - 1 if days > 0 else 0
        
        # 最大回撤
        cummax = portfolio['total'].cummax()
        drawdown = (portfolio['total'] - cummax) / cummax
        max_drawdown = drawdown.min()
        
        # 夏普比率 (假设无风险利率为3%)
        risk_free_rate = 0.03 / 252  # 日无风险利率
        excess_returns = portfolio['returns'] - risk_free_rate
        sharpe_ratio = np.sqrt(252) * excess_returns.mean() / excess_returns.std() if excess_returns.std() > 0 else 0
        
        # 交易统计
        trades = self.results['trades']
        buy_trades = [t for t in trades if t['type'] == 'BUY']
        sell_trades = [t for t in trades if t['type'] == 'SELL']
        
        win_trades = 0
        total_profit = 0
        total_loss = 0
        
        for i in range(len(sell_trades)):
            buy_price = buy_trades[i]['price']
            sell_price = sell_trades[i]['price']
            profit = (sell_price - buy_price) * sell_trades[i]['shares']
            if profit > 0:
                win_trades += 1
                total_profit += profit
            else:
                total_loss += abs(profit)
        
        win_rate = win_trades / len(sell_trades) if sell_trades else 0
        profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')
        
        return {
            'total_return': f"{total_return * 100:.2f}%",
            'annual_return': f"{annual_return * 100:.2f}%",
            'max_drawdown': f"{max_drawdown * 100:.2f}%",
            'sharpe_ratio': f"{sharpe_ratio:.2f}",
            'total_trades': len(trades),
            'win_rate': f"{win_rate * 100:.2f}%",
            'profit_factor': f"{profit_factor:.2f}",
            'final_capital': f"¥{portfolio['total'].iloc[-1]:,.2f}"
        }
    
    def plot_results(self, save_path: str = None):
        """
        绘制回测结果图表
        """
        if self.results is None:
            print("请先运行回测")
            return
        
        portfolio = self.results['portfolio']
        signals = self.results['signals']
        trades = self.results['trades']
        
        fig, axes = plt.subplots(3, 1, figsize=(14, 12))
        
        # 设置中文字体
        plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'STHeiti']
        plt.rcParams['axes.unicode_minus'] = False
        
        # 子图1：价格和交易点
        ax1 = axes[0]
        ax1.plot(signals.index, signals['close'], label='收盘价', color='black', alpha=0.7)
        
        # 标记买卖点
        buy_dates = [t['date'] for t in trades if t['type'] == 'BUY']
        buy_prices = [t['price'] for t in trades if t['type'] == 'BUY']
        sell_dates = [t['date'] for t in trades if t['type'] == 'SELL']
        sell_prices = [t['price'] for t in trades if t['type'] == 'SELL']
        
        ax1.scatter(buy_dates, buy_prices, marker='^', color='red', s=100, label='买入', zorder=5)
        ax1.scatter(sell_dates, sell_prices, marker='v', color='green', s=100, label='卖出', zorder=5)
        ax1.set_title(f'{self.results["strategy_name"]} - 价格走势与交易信号', fontsize=14)
        ax1.legend(loc='upper left')
        ax1.grid(True, alpha=0.3)
        
        # 子图2：账户价值曲线
        ax2 = axes[1]
        ax2.plot(portfolio.index, portfolio['total'], label='账户总价值', color='blue', linewidth=2)
        ax2.axhline(y=self.initial_capital, color='gray', linestyle='--', label='初始资金')
        ax2.fill_between(portfolio.index, self.initial_capital, portfolio['total'], 
                         where=portfolio['total'] >= self.initial_capital, 
                         color='green', alpha=0.3)
        ax2.fill_between(portfolio.index, self.initial_capital, portfolio['total'], 
                         where=portfolio['total'] < self.initial_capital, 
                         color='red', alpha=0.3)
        ax2.set_title('账户价值曲线', fontsize=14)
        ax2.legend(loc='upper left')
        ax2.grid(True, alpha=0.3)
        
        # 子图3：回撤
        ax3 = axes[2]
        cummax = portfolio['total'].cummax()
        drawdown = (portfolio['total'] - cummax) / cummax * 100
        ax3.fill_between(drawdown.index, drawdown, 0, color='red', alpha=0.5)
        ax3.set_title('策略回撤', fontsize=14)
        ax3.set_ylabel('回撤 (%)')
        ax3.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            print(f"图表已保存至: {save_path}")
        
        plt.show()
    
    def print_summary(self):
        """打印回测摘要"""
        metrics = self.calculate_metrics()
        
        print("\n" + "="*50)
        print(f"  回测结果摘要 - {self.results['strategy_name']}")
        print("="*50)
        for key, value in metrics.items():
            print(f"  {key:15s}: {value}")
        print("="*50 + "\n")
# -*- coding: utf-8 -*-
"""
策略模块 - 定义策略基类和示例策略
"""
import pandas as pd
import numpy as np
from abc import ABC, abstractmethod


class BaseStrategy(ABC):
    """
    策略基类 - 所有自定义策略需要继承此类
    """
    
    def __init__(self, name: str = "BaseStrategy"):
        self.name = name
        self.params = {}
    
    def set_params(self, **kwargs):
        """设置策略参数"""
        self.params.update(kwargs)
    
    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易信号 - 子类必须实现
        
        Args:
            data: 股票历史数据 DataFrame
        
        Returns:
            DataFrame，包含 'signal' 列：
                1 = 买入信号
                0 = 持有/观望
                -1 = 卖出信号
        """
        pass


class DoubleMAStrategy(BaseStrategy):
    """
    双均线策略示例
    
    参数:
        short_window: 短期均线周期，默认5
        long_window: 长期均线周期，默认20
    """
    
    def __init__(self, short_window: int = 5, long_window: int = 20):
        super().__init__("双均线策略")
        self.set_params(short_window=short_window, long_window=long_window)
    
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        short_window = self.params.get('short_window', 5)
        long_window = self.params.get('long_window', 20)
        
        # 计算均线
        df['ma_short'] = df['close'].rolling(window=short_window).mean()
        df['ma_long'] = df['close'].rolling(window=long_window).mean()
        
        # 判断趋势方向
        df['trend'] = 0
        df.loc[df['ma_short'] > df['ma_long'], 'trend'] = 1   # 多头
        df.loc[df['ma_short'] < df['ma_long'], 'trend'] = -1  # 空头
        
        # 检测交叉点：趋势变化
        df['trend_change'] = df['trend'].diff()
        
        # 生成交易信号
        df['signal_final'] = 0
        # 金叉：趋势从空头(或中性)转为多头
        df.loc[(df['trend_change'] > 0) & (df['trend'] == 1), 'signal_final'] = 1
        # 死叉：趋势从多头转为空头
        df.loc[(df['trend_change'] < 0) & (df['trend'] == -1), 'signal_final'] = -1
        
        # 处理 NaN
        df['signal_final'] = df['signal_final'].fillna(0).astype(int)
        
        return df


class RSIStrategy(BaseStrategy):
    """
    RSI策略示例
    
    参数:
        period: RSI周期，默认14
        oversold: 超卖阈值，默认30
        overbought: 超买阈值，默认70
    """
    
    def __init__(self, period: int = 14, oversold: int = 30, overbought: int = 70):
        super().__init__("RSI策略")
        self.set_params(period=period, oversold=oversold, overbought=overbought)
    
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        period = self.params.get('period', 14)
        oversold = self.params.get('oversold', 30)
        overbought = self.params.get('overbought', 70)
        
        # 计算RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # 生成信号
        df['signal_final'] = 0
        df.loc[df['rsi'] < oversold, 'signal_final'] = 1   # RSI超卖，买入
        df.loc[df['rsi'] > overbought, 'signal_final'] = -1  # RSI超买，卖出
        
        return df


class BollingerBandsStrategy(BaseStrategy):
    """
    布林带策略示例
    
    参数:
        period: 周期，默认20
        std_dev: 标准差倍数，默认2
    """
    
    def __init__(self, period: int = 20, std_dev: int = 2):
        super().__init__("布林带策略")
        self.set_params(period=period, std_dev=std_dev)
    
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        period = self.params.get('period', 20)
        std_dev = self.params.get('std_dev', 2)
        
        # 计算布林带
        df['ma'] = df['close'].rolling(window=period).mean()
        df['std'] = df['close'].rolling(window=period).std()
        df['upper'] = df['ma'] + std_dev * df['std']
        df['lower'] = df['ma'] - std_dev * df['std']
        
        # 生成信号：价格触及下轨买入，触及上轨卖出
        df['signal_final'] = 0
        df.loc[df['close'] <= df['lower'], 'signal_final'] = 1
        df.loc[df['close'] >= df['upper'], 'signal_final'] = -1
        
        return df


class CustomStrategy(BaseStrategy):
    """
    自定义策略模板 - 在这里实现你自己的选股/交易策略
    """
    
    def __init__(self):
        super().__init__("自定义策略")
    
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        在这里实现你的策略逻辑
        
        示例：你可以使用 data 中的 open, high, low, close, volume 等字段
        计算 any 指标，然后生成买入(1)或卖出(-1)信号
        """
        df = data.copy()
        
        # ============================================
        # 在这里编写你的策略逻辑
        # ============================================
        
        # 示例：简单的动量策略 - 过去N天涨幅超过X%则买入
        df['return_5d'] = df['close'].pct_change(5)
        df['signal_final'] = 0
        df.loc[df['return_5d'] > 0.05, 'signal_final'] = 1   # 5日涨幅超过5%买入
        df.loc[df['return_5d'] < -0.03, 'signal_final'] = -1  # 5日跌幅超过3%卖出
        
        # ============================================
        
        return df


class MomentumBreakthroughStrategy(BaseStrategy):
    """
    动量突破选股策略 v2
    
    选股条件（满足以下所有条件）:
    1. 昨日涨停 OR 今日涨幅>9.5% OR (今日跳空高开 AND 今日涨幅>5%) - 三选一
    2. 收盘价创20日新高 OR 创历史新高 - 二选一
    3. 股价 > 100元
    
    买入方式:
    - 当日收盘价买入（信号日收盘买入）
    - 或次日开盘价买入（可配置）
    
    卖出条件:
    - 触发止损（默认10%）
    - 无固定持有天数，一直持有直到止损
    """
    
    def __init__(self, stop_loss: float = -0.10, buy_next_day: bool = False, dedup_window: int = 10, min_amount: float = 1e9):
        """
        Args:
            stop_loss: 止损比例，默认-10%
            buy_next_day: 是否次日开盘买入，False=当日收盘买入
            dedup_window: 去重窗口（交易日），同一上涨段内只保留首次突破信号。0=关闭去重
            min_amount: 当日最低成交额（元），默认10亿
        """
        super().__init__("动量突破策略")
        self.set_params(stop_loss=stop_loss, buy_next_day=buy_next_day,
                        dedup_window=dedup_window, min_amount=min_amount)
    
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        
        # ========== 计算基础指标 ==========
        
        # 今日涨跌幅
        df['pct_change'] = df['close'].pct_change() * 100
        
        # 昨日涨跌幅（用于判断昨日涨停）
        df['pct_change_prev'] = df['pct_change'].shift(1)
        
        # 昨日涨停（涨幅>=9.9%，考虑四舍五入）
        df['prev_limit_up'] = df['pct_change_prev'] >= 9.9
        
        # 今日涨幅>9.5%
        df['today_high_gain'] = df['pct_change'] > 9.5
        
        # 今日跳空高开（今开 > 昨高）
        df['gap_up'] = df['open'] > df['high'].shift(1)
        
        # 今日涨幅>5%
        df['gain_above_5'] = df['pct_change'] > 5
        
        # 跳空高开且涨幅>5%
        df['gap_up_with_gain'] = df['gap_up'] & df['gain_above_5']
        
        # ========== 条件1：动量信号（三选一） ==========
        condition1 = df['prev_limit_up'] | df['today_high_gain'] | df['gap_up_with_gain']
        
        # ========== 条件2：创新高（二选一） ==========
        # 100日新高：当日收盘价突破前100日盘中最高价（high），不含当天
        df['high_100d'] = df['high'].shift(1).rolling(window=100, min_periods=20).max()
        df['new_100d_high'] = df['close'] > df['high_100d']
        
        # 历史新高：当日收盘价突破此前所有日期的盘中最高价
        df['all_time_high_prev'] = df['high'].shift(1).expanding().max()
        df['new_all_time_high'] = df['close'] > df['all_time_high_prev']
        
        condition2 = df['new_100d_high'] | df['new_all_time_high']
        
        # 突破位（作为非涨停日买入参考价）
        df['breakthrough_level'] = df['high_100d'].fillna(df['all_time_high_prev'])
        
        # 兼容旧字段（避免 batch_scan 取 conditions 时缺字段）
        df['new_20d_high'] = df['new_100d_high']
        
        # ========== 条件3：成交额 >= min_amount（默认 10 亿） ==========
        min_amount = self.params.get('min_amount', 1e9)
        if 'amount' in df.columns:
            condition3 = df['amount'] >= min_amount
        else:
            # 兼容：若无 amount 字段，用 close * volume 近似
            condition3 = (df['close'] * df['volume']) >= min_amount
        
        # ========== 综合选股信号 ==========
        # 同时满足三个条件，标记为候选买入日
        df['breakthrough_signal'] = condition1 & condition2 & condition3
        
        # ========== 去重过滤：前 N 日已出过信号则不再重复 ==========
        # 目的：仅保留"首次突破"，过滤掉连续上涨段内的重复新高信号
        dedup_window = self.params.get('dedup_window', 10)
        if dedup_window and dedup_window > 0:
            signal_int = df['breakthrough_signal'].astype(int)
            # shift(1) 使当前天不计入统计，rolling 统计前 N 天内的信号数
            prev_signals = signal_int.shift(1).rolling(window=dedup_window, min_periods=1).sum().fillna(0)
            df['breakthrough_signal'] = df['breakthrough_signal'] & (prev_signals == 0)
        
        # ========== 买入信号生成 ==========
        buy_next_day = self.params.get('buy_next_day', False)
        
        df['signal_final'] = 0
        df['buy_price'] = np.nan
        df['signal_type'] = ''
        
        # 一字涨停：开高低收均相等，且涨幅>=9.9%
        price_eq = (df['open'] == df['high']) & (df['high'] == df['low']) & (df['low'] == df['close'])
        is_one_word_limit = (df['pct_change'] >= 9.9) & price_eq
        
        # 跳空突破：开盘高于昨日最高价 且 当日最低价高于突破位（未回踩）
        gap_open = df['open'] > df['high'].shift(1)
        is_gap_breakthrough = gap_open & (df['low'] > df['breakthrough_level'])
        
        final_mask = df['breakthrough_signal'] == True
        
        if buy_next_day:
            # 次日开盘价买入
            df['next_open'] = df['open'].shift(-1)
            df.loc[final_mask, 'signal_final'] = 1
            df.loc[final_mask, 'buy_price'] = df['next_open']
            df.loc[final_mask, 'signal_type'] = 'next_open'
        else:
            df.loc[final_mask, 'signal_final'] = 1
            
            # 优先级：一字涨停 > 跳空突破 > 普通突破
            mask_one_word = final_mask & is_one_word_limit
            mask_gap = final_mask & ~is_one_word_limit & is_gap_breakthrough
            mask_break = final_mask & ~is_one_word_limit & ~is_gap_breakthrough
            
            df.loc[mask_one_word, 'buy_price'] = df.loc[mask_one_word, 'close']
            df.loc[mask_one_word, 'signal_type'] = 'one_word'
            
            df.loc[mask_gap, 'buy_price'] = df.loc[mask_gap, 'low']
            df.loc[mask_gap, 'signal_type'] = 'gap'
            
            df.loc[mask_break, 'buy_price'] = df.loc[mask_break, 'breakthrough_level']
            df.loc[mask_break, 'signal_type'] = 'breakthrough'
        
        return df


class BacktestEngineV2:
    """
    回测引擎 v2 - 支持止损持有的策略
    """
    
    def __init__(self, initial_capital: float = 100000, commission: float = 0.0003):
        self.initial_capital = initial_capital
        self.commission = commission
        self.results = None
    
    def run(self, data: pd.DataFrame, strategy) -> dict:
        """运行回测"""
        signals = strategy.generate_signals(data)
        
        stop_loss = strategy.params.get('stop_loss', -0.10)
        buy_next_day = strategy.params.get('buy_next_day', False)
        
        cash = self.initial_capital
        position = 0
        buy_price = 0
        portfolio_value = []
        trades = []
        
        for i in range(len(signals)):
            date = signals.index[i]
            close = signals['close'].iloc[i]
            open_price = signals['open'].iloc[i]
            signal = int(signals['signal_final'].iloc[i]) if pd.notna(signals['signal_final'].iloc[i]) else 0
            
            # 如果次日买入模式，检查昨天的信号
            if buy_next_day and position == 0:
                if i > 0:
                    yesterday_signal = signals['signal_final'].iloc[i-1]
                    if yesterday_signal == 1 and position == 0:
                        # 次日开盘买入
                        shares = int(cash * 0.95 / open_price / 100) * 100
                        if shares > 0:
                            cost = shares * open_price * (1 + self.commission)
                            if cost <= cash:
                                position = shares
                                buy_price = open_price
                                cash -= cost
                                trades.append({
                                    'date': date,
                                    'type': 'BUY',
                                    'price': open_price,
                                    'shares': shares,
                                    'capital': cash + position * close
                                })
            
            # 当日收盘买入模式
            elif not buy_next_day and signal == 1 and position == 0:
                shares = int(cash * 0.95 / close / 100) * 100
                if shares > 0:
                    cost = shares * close * (1 + self.commission)
                    if cost <= cash:
                        position = shares
                        buy_price = close
                        cash -= cost
                        trades.append({
                            'date': date,
                            'type': 'BUY',
                            'price': close,
                            'shares': shares,
                            'capital': cash + position * close
                        })
            
            # 止损检查
            if position > 0:
                pnl_pct = (close - buy_price) / buy_price
                
                if pnl_pct <= stop_loss:
                    # 触发止损
                    revenue = position * close * (1 - self.commission)
                    cash += revenue
                    trades.append({
                        'date': date,
                        'type': 'SELL (止损)',
                        'price': close,
                        'shares': position,
                        'capital': cash,
                        'pnl_pct': pnl_pct * 100
                    })
                    position = 0
                    buy_price = 0
            
            # 记录账户价值
            portfolio_value.append({
                'date': date,
                'cash': cash,
                'position': position,
                'position_value': position * close,
                'total': cash + position * close,
                'buy_price': buy_price if position > 0 else 0,
                'pnl_pct': (close - buy_price) / buy_price if position > 0 and buy_price > 0 else 0
            })
        
        # 整理结果
        results_df = pd.DataFrame(portfolio_value)
        results_df = results_df.set_index('date')
        
        # 如果最后还持仓，按收盘价清仓计算
        final_close = signals['close'].iloc[-1]
        if position > 0:
            revenue = position * final_close * (1 - self.commission)
            cash += revenue
            trades.append({
                'date': signals.index[-1],
                'type': 'SELL (回测结束清仓)',
                'price': final_close,
                'shares': position,
                'capital': cash,
                'pnl_pct': (final_close - buy_price) / buy_price * 100
            })
            position = 0
            # 更新最后一天的账户价值
            results_df.iloc[-1, results_df.columns.get_loc('total')] = cash
            results_df.iloc[-1, results_df.columns.get_loc('cash')] = cash
            results_df.iloc[-1, results_df.columns.get_loc('position')] = 0
            results_df.iloc[-1, results_df.columns.get_loc('position_value')] = 0
        
        self.results = {
            'portfolio': results_df,
            'trades': trades,
            'signals': signals,
            'strategy_name': strategy.name,
            'stop_loss': stop_loss
        }
        
        return self.results
    
    def calculate_metrics(self) -> dict:
        """计算绩效指标"""
        if self.results is None:
            return {}
        
        portfolio = self.results['portfolio']
        
        portfolio['returns'] = portfolio['total'].pct_change()
        
        total_return = (portfolio['total'].iloc[-1] - self.initial_capital) / self.initial_capital
        
        days = (portfolio.index[-1] - portfolio.index[0]).days
        annual_return = (1 + total_return) ** (365 / days) - 1 if days > 0 else 0
        
        cummax = portfolio['total'].cummax()
        drawdown = (portfolio['total'] - cummax) / cummax
        max_drawdown = drawdown.min()
        
        risk_free_rate = 0.03 / 252
        excess_returns = portfolio['returns'] - risk_free_rate
        sharpe_ratio = np.sqrt(252) * excess_returns.mean() / excess_returns.std() if excess_returns.std() > 0 else 0
        
        trades = self.results['trades']
        buy_trades = [t for t in trades if 'BUY' in t['type']]
        sell_trades = [t for t in trades if 'SELL' in t['type']]
        
        win_trades = 0
        total_profit = 0
        total_loss = 0
        max_holding_days = 0
        
        for i, sell in enumerate(sell_trades):
            buy = buy_trades[i]
            profit = (sell['price'] - buy['price']) * sell['shares']
            holding_days = (sell['date'] - buy['date']).days
            max_holding_days = max(max_holding_days, holding_days)
            
            if profit > 0:
                win_trades += 1
                total_profit += profit
            else:
                total_loss += abs(profit)
        
        win_rate = win_trades / len(sell_trades) if sell_trades else 0
        profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')
        avg_holding_days = np.mean([(s['date'] - b['date']).days for s, b in zip(sell_trades, buy_trades)]) if sell_trades else 0
        
        return {
            '总收益率': f"{total_return * 100:.2f}%",
            '年化收益率': f"{annual_return * 100:.2f}%",
            '最大回撤': f"{max_drawdown * 100:.2f}%",
            '夏普比率': f"{sharpe_ratio:.2f}",
            '总交易次数': len(trades),
            '买入次数': len(buy_trades),
            '止损次数': len(sell_trades),
            '胜率': f"{win_rate * 100:.2f}%",
            '盈亏比': f"{profit_factor:.2f}",
            '平均持仓天数': f"{avg_holding_days:.1f}天",
            '最长持仓天数': f"{max_holding_days}天",
            '止损比例': f"{self.results['stop_loss'] * 100:.0f}%",
            '最终资金': f"¥{portfolio['total'].iloc[-1]:,.2f}"
        }
    
    def plot_results(self, save_path: str = None, stock_name: str = None):
        """绘制回测结果（优化版，避免字体遮挡）"""
        if self.results is None:
            return
        
        portfolio = self.results['portfolio']
        signals = self.results['signals']
        trades = self.results['trades']
        
        # 懒加载 matplotlib（仅在画图时需要，避免无 GUI 环境强依赖）
        import matplotlib.pyplot as plt
        
        # 增大图像尺寸，增加边距
        fig, axes = plt.subplots(3, 1, figsize=(16, 14))
        
        plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'STHeiti']
        plt.rcParams['axes.unicode_minus'] = False
        plt.rcParams['figure.constrained_layout.use'] = True
        
        # 子图1：价格和交易点
        ax1 = axes[0]
        ax1.plot(signals.index, signals['close'], label='收盘价', color='#1a1a2e', linewidth=1.5, alpha=0.8)
        
        buy_trades = [t for t in trades if 'BUY' in t['type']]
        sell_trades = [t for t in trades if 'SELL' in t['type']]
        
        if buy_trades:
            ax1.scatter([t['date'] for t in buy_trades], [t['price'] for t in buy_trades],
                       marker='^', color='#ef4444', s=120, label='买入', zorder=5, edgecolors='white', linewidths=1)
        if sell_trades:
            ax1.scatter([t['date'] for t in sell_trades], [t['price'] for t in sell_trades],
                       marker='v', color='#10b981', s=120, label='卖出', zorder=5, edgecolors='white', linewidths=1)
        
        # 标题使用股票名称
        title_text = f'{stock_name}' if stock_name else self.results["strategy_name"]
        ax1.set_title(title_text, fontsize=16, fontweight='bold', pad=15, loc='left')
        
        # 图例放在右侧
        ax1.legend(loc='upper right', framealpha=0.9, fontsize=10)
        ax1.grid(True, alpha=0.3, linestyle='--')
        ax1.set_ylabel('价格 (元)', fontsize=11)
        
        # 在右上角显示关键信息（不遮挡）
        if buy_trades:
            buy_price = buy_trades[0]['price']
            ax1.text(0.98, 0.02, f'买入价: {buy_price:.2f}', transform=ax1.transAxes,
                    fontsize=10, ha='right', va='bottom',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='#fef3c7', edgecolor='#f59e0b', alpha=0.9))
        
        # 子图2：账户价值曲线
        ax2 = axes[1]
        ax2.plot(portfolio.index, portfolio['total'], label='账户价值', color='#3b82f6', linewidth=2)
        ax2.axhline(y=self.initial_capital, color='#9ca3af', linestyle='--', label=f'初始资金: ¥{self.initial_capital:,.0f}', linewidth=1)
        ax2.fill_between(portfolio.index, self.initial_capital, portfolio['total'],
                         where=portfolio['total'] >= self.initial_capital, color='#10b981', alpha=0.2)
        ax2.fill_between(portfolio.index, self.initial_capital, portfolio['total'],
                         where=portfolio['total'] < self.initial_capital, color='#ef4444', alpha=0.2)
        ax2.set_title('账户价值曲线', fontsize=14, fontweight='bold', pad=10, loc='left')
        ax2.legend(loc='upper right', framealpha=0.9, fontsize=10)
        ax2.grid(True, alpha=0.3, linestyle='--')
        ax2.set_ylabel('账户价值 (元)', fontsize=11)
        
        # 显示最终收益
        final_value = portfolio['total'].iloc[-1]
        profit = (final_value - self.initial_capital) / self.initial_capital * 100
        color = '#10b981' if profit >= 0 else '#ef4444'
        ax2.text(0.98, 0.02, f'收益率: {profit:+.2f}%', transform=ax2.transAxes,
                fontsize=12, ha='right', va='bottom', fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor=color, alpha=0.9),
                color=color)
        
        # 子图3：持仓盈亏
        ax3 = axes[2]
        pnl_series = portfolio['pnl_pct'] * 100
        ax3.fill_between(portfolio.index, pnl_series, 0,
                         where=pnl_series >= 0, color='#10b981', alpha=0.4, label='浮盈')
        ax3.fill_between(portfolio.index, pnl_series, 0,
                         where=pnl_series < 0, color='#ef4444', alpha=0.4, label='浮亏')
        ax3.axhline(y=self.results['stop_loss'] * 100, color='#f59e0b', linestyle='--',
                   label=f'止损线 ({self.results["stop_loss"]*100:.0f}%)', linewidth=1.5)
        ax3.axhline(y=0, color='#6b7280', linestyle='-', linewidth=0.5)
        ax3.set_title('持仓盈亏', fontsize=14, fontweight='bold', pad=10, loc='left')
        ax3.set_ylabel('盈亏 (%)', fontsize=11)
        ax3.set_xlabel('日期', fontsize=11)
        ax3.legend(loc='upper right', framealpha=0.9, fontsize=10)
        ax3.grid(True, alpha=0.3, linestyle='--')
        
        # 调整布局，增加间距
        plt.tight_layout(pad=2.0, h_pad=2.0)
        
        if save_path:
            plt.savefig(save_path, dpi=120, bbox_inches='tight', facecolor='white', edgecolor='none')
        
        plt.close()  # 关闭图形避免内存泄漏
    
    def print_summary(self):
        """打印回测摘要"""
        metrics = self.calculate_metrics()
        
        print("\n" + "="*60)
        print(f"  回测结果摘要 - {self.results['strategy_name']}")
        print("="*60)
        for key, value in metrics.items():
            print(f"  {key:12s}: {value}")
        print("="*60 + "\n")
        
        # 打印交易详情
        trades = self.results['trades']
        if trades:
            print("\n交易明细:")
            print("-" * 80)
            for t in trades:
                pnl_str = f", 盈亏: {t['pnl_pct']:.2f}%" if 'pnl_pct' in t else ""
                print(f"  {t['date'].date()} | {t['type']:10s} | 价格: {t['price']:.2f} | 数量: {t['shares']}{pnl_str}")
            print("-" * 80)
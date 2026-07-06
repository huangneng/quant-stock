# -*- coding: utf-8 -*-
"""
动量突破策略回测 - Web报告生成器
生成Bash风格的K线图报告
"""
import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime

# 添加路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant_backtest.data import get_stock_data, get_stock_list
from quant_backtest.strategy import MomentumBreakthroughStrategy, BacktestEngineV2
from quant_backtest.report_bash import generate_report

# 初始资金
INITIAL_CAPITAL = 1000000

# K线图生成
try:
    import mplfinance as mpf
    import matplotlib.pyplot as plt
    HAS_MPLFINANCE = True
except ImportError:
    HAS_MPLFINANCE = False
    print("提示: 安装 mplfinance 可生成K线图: pip install mplfinance")


def plot_kline(data, trades, save_path, stock_name):
    """生成K线图"""
    if not HAS_MPLFINANCE:
        return plot_simple_chart(data, trades, save_path, stock_name)
    
    df = data.copy()
    df = df.rename(columns={
        'open': 'Open', 'high': 'High', 
        'low': 'Low', 'close': 'Close', 'volume': 'Volume'
    })
    
    # 添加均线
    df['MA5'] = df['Close'].rolling(5).mean()
    df['MA20'] = df['Close'].rolling(20).mean()
    
    # 买卖点标记
    markers = []
    for t in trades:
        if 'BUY' in t['type']:
            markers.append(df.index.get_loc(t['date']) if t['date'] in df.index else -1)
    
    mc = mpf.make_marketcolors(
        up='#ef5350', down='#26a69a',
        edge='inherit', wick='inherit',
        volume={'up': '#ef5350', 'down': '#26a69a'}
    )
    style = mpf.make_mpf_style(
        marketcolors=mc,
        gridstyle=':', gridcolor='#3b4261',
        facecolor='#1a1b26', edgecolor='#3b4261',
        figcolor='#1a1b26', rc={'font.size': 10}
    )
    
    addplot = [
        mpf.make_addplot(df['MA5'], color='#7aa2f7', width=1, linestyle='-'),
        mpf.make_addplot(df['MA20'], color='#e0af68', width=1, linestyle='-'),
    ]
    
    fig, axes = mpf.plot(
        df, type='candle', style=style,
        title=f'{stock_name}',
        ylabel='价格', ylabel_lower='成交量',
        volume=True, addplot=addplot,
        figsize=(14, 10), returnfig=True,
        tight_layout=True
    )
    
    ax = axes[0]
    buy_trades = [t for t in trades if 'BUY' in t['type']]
    sell_trades = [t for t in trades if 'SELL' in t['type']]
    
    if buy_trades:
        ax.scatter([t['date'] for t in buy_trades], [t['price'] for t in buy_trades],
                   marker='^', color='#e0af68', s=200, zorder=5, edgecolors='white', linewidths=2)
    if sell_trades:
        ax.scatter([t['date'] for t in sell_trades], [t['price'] for t in sell_trades],
                   marker='v', color='#f7768e', s=200, zorder=5, edgecolors='white', linewidths=2)
    
    fig.savefig(save_path, dpi=120, bbox_inches='tight', facecolor='#1a1b26')
    plt.close()
    return save_path


def plot_simple_chart(data, trades, save_path, stock_name):
    """简单折线图（备用）"""
    import matplotlib.pyplot as plt
    
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei']
    plt.rcParams['axes.unicode_minus'] = False
    
    fig, ax = plt.subplots(figsize=(14, 8), facecolor='#1a1b26')
    ax.set_facecolor('#1a1b26')
    
    ax.plot(data.index, data['close'], color='#c0caf5', linewidth=1.5, label='收盘价')
    ax.plot(data.index, data['close'].rolling(20).mean(), color='#e0af68', linewidth=1, label='MA20')
    
    buy_trades = [t for t in trades if 'BUY' in t['type']]
    sell_trades = [t for t in trades if 'SELL' in t['type']]
    
    if buy_trades:
        ax.scatter([t['date'] for t in buy_trades], [t['price'] for t in buy_trades],
                   marker='^', color='#e0af68', s=150, label='买入', zorder=5)
    if sell_trades:
        ax.scatter([t['date'] for t in sell_trades], [t['price'] for t in sell_trades],
                   marker='v', color='#f7768e', s=150, label='卖出', zorder=5)
    
    ax.set_title(stock_name, color='#c0caf5', fontsize=16, fontweight='bold')
    ax.legend(loc='upper right', facecolor='#24283b', edgecolor='#3b4261', labelcolor='#c0caf5')
    ax.tick_params(colors='#565f89')
    ax.grid(True, alpha=0.3, color='#3b4261')
    
    for spine in ax.spines.values():
        spine.set_color('#3b4261')
    
    fig.savefig(save_path, dpi=120, bbox_inches='tight', facecolor='#1a1b26')
    plt.close()
    return save_path


def scan_stocks(start_date, end_date, min_price=100):
    """扫描符合条件的股票"""
    print(f"正在扫描股票池...")
    stock_list = get_stock_list()
    print(f"共 {len(stock_list)} 只股票")
    
    # 为了正确计算20日新高，需要更多历史数据
    # 将开始日期提前30天
    from datetime import datetime, timedelta
    start_dt = datetime.strptime(start_date, '%Y%m%d')
    extended_start = (start_dt - timedelta(days=45)).strftime('%Y%m%d')
    
    results = []
    for i, (code, name) in enumerate(stock_list[:2000]):  # 扫描前2000只
        if (i + 1) % 200 == 0:
            print(f"已扫描 {i+1}/{min(2000, len(stock_list))} 只...")
        
        # 测试模式：找到2个以上股票就停止
        if len(results) >= 2:
            print(f"已找到 {len(results)} 只符合条件的股票，停止扫描")
            break
        
        try:
            # 使用扩展的日期范围获取数据
            data = get_stock_data(code, extended_start, end_date)
            if data.empty or len(data) < 20:
                continue
            
            # 检查股价>100（使用最新价格）
            if data['close'].iloc[-1] < min_price:
                continue
            
            strategy = MomentumBreakthroughStrategy()
            signals = strategy.generate_signals(data)
            
            # 只统计目标日期范围内的信号
            target_start = pd.to_datetime(start_date)
            target_signals = signals[signals.index >= target_start]
            
            if int(target_signals['signal_final'].sum()) > 0:
                print(f"  发现信号: {name} ({code})")
                results.append((code, name, data, signals))
        except Exception as e:
            continue
    
    return results


def run_backtest(start_date, end_date, output_dir="report_output"):
    """运行回测并生成报告"""
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(f"{output_dir}/charts", exist_ok=True)
    
    # 扫描股票
    stocks = scan_stocks(start_date, end_date)
    print(f"\n共发现 {len(stocks)} 只符合条件的股票")
    
    if not stocks:
        print("未找到符合条件的股票")
        return
    
    report_results = []
    
    for code, name, data, signals in stocks:
        print(f"\n回测: {name} ({code})")
        
        # 回测
        strategy = MomentumBreakthroughStrategy()
        engine = BacktestEngineV2(initial_capital=INITIAL_CAPITAL)
        engine.run(data, strategy)
        metrics = engine.calculate_metrics()
        trades = engine.results['trades']
        
        # 生成图表
        chart_path = f"{output_dir}/charts/{code.replace('.', '')}.png"
        plot_kline(data, trades, chart_path, name)
        
        # 收集信号详情
        signal_details = []
        for idx, row in signals[signals['signal_final'] == 1].iterrows():
            signal_details.append({
                'date': idx.strftime('%Y-%m-%d'),
                'price': row['close'],
                'pct': row.get('pct_change', 0),
                'limit_up': row.get('limit_up', False),
                'high_gain': row.get('high_gain', False),
                'new_high': row.get('new_high', False)
            })
        
        report_results.append({
            'code': code,
            'name': name,
            'period_return': (data['close'].iloc[-1] / data['close'].iloc[0] - 1) * 100,
            'strategy_return': metrics.get('total_return', 0) * 100,
            'max_drawdown': metrics.get('max_drawdown', 0) * 100,
            'win_rate': metrics.get('win_rate', 0) * 100,
            'trades': len([t for t in trades if 'SELL' in t['type']]),
            'signal_count': len(signal_details),
            'signals': signal_details,
            'chart_path': chart_path
        })
    
    # 按策略收益排序
    report_results.sort(key=lambda x: x['strategy_return'], reverse=True)
    
    # 生成报告
    index_file = generate_report(report_results, output_dir)
    print(f"\n报告已生成: {index_file}")
    return index_file


if __name__ == "__main__":
    # 回测期间: 2026年5月1日-8日
    run_backtest("20260420", "20260510")

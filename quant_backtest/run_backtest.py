# -*- coding: utf-8 -*-
"""
动量突破策略回测 - 生成Bash风格Web报告
"""
import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# 添加模块路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant_backtest.data import get_stock_data, get_stock_list
from quant_backtest.strategy import MomentumBreakthroughStrategy, BacktestEngineV2
from quant_backtest.report_bash import generate_report

# K线图绘制
try:
    import mplfinance as mpf
    import matplotlib.pyplot as plt
    HAS_MPLFINANCE = True
except ImportError:
    HAS_MPLFINANCE = False
    print("提示: 安装 mplfinance 可生成K线图: pip install mplfinance")


def scan_breakthrough_stocks(start_date: str, end_date: str, min_price: float = 100.0) -> list:
    """
    扫描满足突破条件的股票
    
    Args:
        start_date: 开始日期 '20260101'
        end_date: 结束日期 '20261231'
        min_price: 最低股价筛选
    """
    print(f"\n正在扫描股票池...")
    
    # 获取股票列表
    stock_list = get_stock_list()
    print(f"股票池数量: {len(stock_list)}")
    
    # 需要更多历史数据来判断20日新高
    scan_start = (datetime.strptime(start_date, '%Y%m%d') - timedelta(days=60)).strftime('%Y%m%d')
    
    results = []
    for i, stock in enumerate(stock_list):
        code = stock['code']
        name = stock.get('name', code)
        
        if i % 100 == 0:
            print(f"扫描进度: {i}/{len(stock_list)} - 已发现 {len(results)} 只")
        
        try:
            df = get_stock_data(code, scan_start, end_date)
            if df.empty or len(df) < 30:
                continue
            
            # 筛选日期范围
            df_range = df[df.index >= datetime.strptime(start_date, '%Y%m%d')]
            if df_range.empty:
                continue
            
            # 检查是否有突破信号
            for date, row in df_range.iterrows():
                close = row['close']
                
                # 条件3: 股价 > 100元
                if close <= min_price:
                    continue
                
                # 检查条件1和条件2
                signal = check_breakthrough_signal(df, date)
                
                if signal:
                    results.append({
                        'code': code,
                        'name': name,
                        'signal_date': date.strftime('%Y-%m-%d'),
                        'signal_price': close,
                        'signal_type': signal['type']
                    })
                    break  # 找到第一个信号就记录
                    
        except Exception as e:
            continue
    
    print(f"\n扫描完成，发现 {len(results)} 只符合条件的股票")
    return results


def check_breakthrough_signal(df: pd.DataFrame, date) -> dict:
    """检查是否有突破信号"""
    
    # 获取当天数据
    if date not in df.index:
        return None
    
    today = df.loc[date]
    today_close = today['close']
    today_open = today['open']
    today_pct = today.get('pct_change', (today_close - df.loc[:date].iloc[-2]['close']) / df.loc[:date].iloc[-2]['close'] * 100 if len(df.loc[:date]) > 1 else 0)
    
    # 获取昨日数据
    prev_dates = df.index[df.index < date]
    if len(prev_dates) == 0:
        return None
    yesterday = df.loc[prev_dates[-1]]
    yesterday_close = yesterday['close']
    
    # 条件1: 昨日涨停 或 今日涨幅>9.5% 或 (跳空高开且涨幅>5%)
    yesterday_pct = yesterday.get('pct_change', 0)
    
    limit_up = yesterday_pct >= 9.9  # 昨日涨停
    high_gain = today_pct >= 9.5     # 今日涨幅>9.5%
    gap_up = today_open > yesterday_close and today_pct >= 5  # 跳空高开且涨幅>5%
    
    if not (limit_up or high_gain or gap_up):
        return None
    
    # 条件2: 20日新高 或 历史新高
    prev_20_days = df.loc[:prev_dates[-1]].tail(20)
    high_20 = prev_20_days['high'].max() if len(prev_20_days) > 0 else 0
    
    all_time_high = df.loc[:prev_dates[-1]]['high'].max() if len(prev_dates) > 1 else 0
    
    new_20_high = today_close >= high_20
    new_all_time_high = today_close >= all_time_high
    
    if not (new_20_high or new_all_time_high):
        return None
    
    # 记录触发类型
    signal_types = []
    if limit_up:
        signal_types.append("涨停")
    if high_gain:
        signal_types.append("涨幅>9.5%")
    if gap_up:
        signal_types.append("跳空高开")
    if new_20_high:
        signal_types.append("20日新高")
    if new_all_time_high:
        signal_types.append("历史新高")
    
    return {
        'type': ', '.join(signal_types),
        'limit_up': limit_up,
        'high_gain': high_gain,
        'gap_up': gap_up,
        'new_20_high': new_20_high,
        'new_all_time_high': new_all_time_high
    }


def run_backtest(stock_code: str, stock_name: str, signal_date: str, 
                 start_date: str, end_date: str, initial_capital: float = 1000000):
    """对单只股票运行回测"""
    
    # 获取数据
    df = get_stock_data(stock_code, start_date, end_date)
    if df.empty:
        return None
    
    # 创建策略实例
    strategy = MomentumBreakthroughStrategy(
        name=f"动量突破-{stock_name}",
        stop_loss=0.10  # 10%止损
    )
    
    # 创建回测引擎
    engine = BacktestEngineV2(
        strategy=strategy,
        initial_capital=initial_capital
    )
    
    # 运行回测
    try:
        results = engine.run(df)
        
        # 计算额外指标
        metrics = engine.calculate_metrics()
        
        # 获取买入信号详情
        signals = []
        for trade in results['trades']:
            if 'BUY' in trade['type']:
                signal = check_breakthrough_signal(df, trade['date'])
                signals.append({
                    'date': trade['date'].strftime('%Y-%m-%d'),
                    'price': trade['price'],
                    'pct': df.loc[trade['date']].get('pct_change', 0),
                    'limit_up': signal.get('limit_up', False) if signal else False,
                    'high_gain': signal.get('high_gain', False) if signal else False,
                    'new_high': signal.get('new_20_high', False) or signal.get('new_all_time_high', False) if signal else False
                })
        
        # 生成K线图
        chart_path = None
        if HAS_MPLFINANCE:
            chart_path = generate_kline_chart(df, results, stock_name, stock_code)
        else:
            chart_path = engine.plot_results(save_path=f"report_output/chart_{stock_code.replace('.', '')}.png", 
                                              stock_name=stock_name)
        
        return {
            'code': stock_code,
            'name': stock_name,
            'signal_date': signal_date,
            'period_return': metrics.get('period_return', 0),
            'strategy_return': metrics.get('strategy_return', 0),
            'max_drawdown': metrics.get('max_drawdown', 0) * 100,
            'win_rate': metrics.get('win_rate', 0),
            'trades': len([t for t in results['trades'] if 'SELL' in t['type']]),
            'signal_count': len(signals),
            'signals': signals,
            'chart_path': chart_path
        }
        
    except Exception as e:
        print(f"回测失败 {stock_name}: {e}")
        return None


def generate_kline_chart(df, results, stock_name: str, stock_code: str) -> str:
    """生成K线图"""
    
    # 准备数据
    ohlc = df[['open', 'high', 'low', 'close', 'volume']].copy()
    ohlc.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
    
    # 添加均线
    ohlc['MA5'] = ohlc['Close'].rolling(5).mean()
    ohlc['MA10'] = ohlc['Close'].rolling(10).mean()
    ohlc['MA20'] = ohlc['Close'].rolling(20).mean()
    
    # 买卖点标记
    trades = results['trades']
    buy_signals = []
    sell_signals = []
    
    for trade in trades:
        if 'BUY' in trade['type']:
            buy_signals.append(trade['date'])
        elif 'SELL' in trade['type']:
            sell_signals.append(trade['date'])
    
    # 自定义样式 - Tokyo Night风格
    mc = mpf.make_marketcolors(
        up='#9ece6a', down='#f7768e',
        edge='inherit', Wick='inherit',
        volume={'up': '#9ece6a', 'down': '#f7768e'}
    )
    
    s = mpf.make_mpf_style(
        marketcolors=mc,
        gridstyle=':', gridcolor='#3b4261',
        facecolor='#1a1b26', edgecolor='#3b4261',
        figcolor='#1a1b26', rc={
            'font.family': ['Arial Unicode MS', 'SimHei', 'sans-serif'],
            'axes.labelcolor': '#c0caf5',
            'xtick.color': '#c0caf5',
            'ytick.color': '#c0caf5',
            'axes.titlecolor': '#c0caf5'
        }
    )
    
    # 创建附加图层
    apds = [
        mpf.make_addplot(ohlc['MA5'], color='#7aa2f7', width=1, alpha=0.8),
        mpf.make_addplot(ohlc['MA10'], color='#e0af68', width=1, alpha=0.8),
        mpf.make_addplot(ohlc['MA20'], color='#bb9af7', width=1, alpha=0.8),
    ]
    
    # 绘图
    fig, axes = mpf.plot(
        ohlc,
        type='candle',
        style=s,
        title=f'{stock_name} ({stock_code})',
        ylabel='价格',
        ylabel_lower='成交量',
        volume=True,
        figsize=(14, 8),
        addplot=apds,
        returnfig=True
    )
    
    # 添加买卖点标记
    ax = axes[0]
    for buy_date in buy_signals:
        if buy_date in ohlc.index:
            ax.scatter([buy_date], [ohlc.loc[buy_date, 'Low'] * 0.99],
                      marker='^', color='#9ece6a', s=200, zorder=5, 
                      edgecolors='white', linewidths=1.5)
    
    for sell_date in sell_signals:
        if sell_date in ohlc.index:
            ax.scatter([sell_date], [ohlc.loc[sell_date, 'High'] * 1.01],
                      marker='v', color='#f7768e', s=200, zorder=5,
                      edgecolors='white', linewidths=1.5)
    
    # 保存
    output_dir = "report_output"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    chart_path = f"{output_dir}/chart_{stock_code.replace('.', '')}.png"
    fig.savefig(chart_path, dpi=120, bbox_inches='tight', facecolor='#1a1b26')
    plt.close(fig)
    
    return chart_path


def main():
    """主函数"""
    
    # 参数设置
    START_DATE = '20260401'  # 回测开始日期
    END_DATE = '20260508'    # 回测结束日期
    INITIAL_CAPITAL = 1000000  # 初始资金100万
    MIN_PRICE = 100.0        # 股价筛选条件
    
    print("="*60)
    print("  动量突破策略回测系统")
    print("="*60)
    print(f"  回测区间: {START_DATE} - {END_DATE}")
    print(f"  初始资金: ¥{INITIAL_CAPITAL:,.0f}")
    print(f"  止损比例: 10%")
    print(f"  股价筛选: > ¥{MIN_PRICE}")
    print("="*60)
    
    # 扫描股票
    stocks = scan_breakthrough_stocks(START_DATE, END_DATE, MIN_PRICE)
    
    if not stocks:
        print("\n未发现符合条件的股票")
        return
    
    print(f"\n发现 {len(stocks)} 只符合条件的股票:")
    for s in stocks:
        print(f"  - {s['name']} ({s['code']}) 信号日期: {s['signal_date']}")
    
    # 运行回测
    print("\n" + "="*60)
    print("  开始回测...")
    print("="*60)
    
    backtest_start = (datetime.strptime(START_DATE, '%Y%m%d') - timedelta(days=30)).strftime('%Y%m%d')
    
    all_results = []
    for stock in stocks:
        print(f"\n回测: {stock['name']} ({stock['code']})")
        result = run_backtest(
            stock['code'],
            stock['name'],
            stock['signal_date'],
            backtest_start,
            END_DATE,
            INITIAL_CAPITAL
        )
        if result:
            all_results.append(result)
            print(f"  策略收益: {result['strategy_return']:+.2f}%")
            print(f"  最大回撤: {result['max_drawdown']:.2f}%")
    
    # 生成报告
    if all_results:
        print("\n" + "="*60)
        print("  生成Web报告...")
        print("="*60)
        
        index_file = generate_report(all_results, "report_output")
        
        print(f"\n报告已生成!")
        print(f"请打开浏览器访问: file://{os.path.abspath(index_file)}")
    else:
        print("\n回测无有效结果")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
动量突破策略回测 - Web报告生成器
初始资金100万，K线图可视化，Bash风格UI
"""
import os
import sys
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

# 添加模块路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from quant_backtest.data import get_stock_data, get_stock_list
from quant_backtest.strategy import MomentumBreakthroughStrategy, BacktestEngineV2
from quant_backtest.report_bash import generate_report

# 尝试导入mplfinance用于K线图
try:
    import mplfinance as mpf
    HAS_MPLFINANCE = True
except ImportError:
    HAS_MPLFINANCE = False
    print("提示: 安装mplfinance可启用K线图: pip install mplfinance")


def plot_kline(data, signals, trades, save_path, stock_name):
    """生成K线图"""
    if not HAS_MPLFINANCE:
        return plot_fallback(data, signals, trades, save_path, stock_name)
    
    # 准备K线数据
    df = data.copy()
    df = df.rename(columns={
        'open': 'Open', 'high': 'High', 
        'low': 'Low', 'close': 'Close', 'volume': 'Volume'
    })
    
    # 确保有必要的列
    required = ['Open', 'High', 'Low', 'Close', 'Volume']
    for col in required:
        if col not in df.columns:
            return plot_fallback(data, signals, trades, save_path, stock_name)
    
    df = df[required].dropna()
    
    # 创建买卖点标记
    buy_signals = signals[signals['signal_final'] == 1].index
    sell_signals = [t['date'] for t in trades if 'SELL' in t['type']]
    
    # K线图样式 - Tokyo Night风格
    mc = mpf.make_marketcolors(
        up='#9ece6a', down='#f7768e',
        edge='#c0caf5', wick='#565f89',
        volume='#7aa2f7'
    )
    s = mpf.make_mpf_style(
        marketcolors=mc,
        gridstyle=':', gridcolor='#3b4261',
        facecolor='#1a1b26', edgecolor='#3b4261',
        figcolor='#1a1b26', rc={
            'font.sans-serif': ['Arial Unicode MS', 'SimHei'],
            'axes.unicode_minus': False
        }
    )
    
    # 添加买卖点标记
    markers = []
    for idx in buy_signals:
        if idx in df.index:
            markers.append(mpff.make_addplot(
                [df.loc[idx, 'Close']] if idx in df.index else [None],
                type='scatter', markersize=100, marker='^', color='#e0af68'
            ))
    
    # 生成K线图
    fig, axes = mpf.plot(
        df, type='candle', style=s,
        title=f'{stock_name} K线图',
        ylabel='价格', ylabel_lower='成交量',
        volume=True, figsize=(14, 8),
        returnfig=True, tight_layout=True
    )
    
    # 添加买卖点
    ax = axes[0]
    for idx in buy_signals:
        if idx in df.index:
            ax.scatter([idx], [df.loc[idx, 'Close']], 
                      marker='^', color='#e0af68', s=150, zorder=5, edgecolors='white')
    for idx in sell_signals:
        if idx in df.index:
            ax.scatter([idx], [df.loc[idx, 'Close']], 
                      marker='v', color='#bb9af7', s=150, zorder=5, edgecolors='white')
    
    plt.savefig(save_path, dpi=120, bbox_inches='tight', facecolor='#1a1b26')
    plt.close()


def plot_fallback(data, signals, trades, save_path, stock_name):
    """备选图表（无K线时使用）"""
    fig, axes = plt.subplots(2, 1, figsize=(14, 8))
    
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei']
    plt.rcParams['axes.unicode_minus'] = False
    plt.rcParams['figure.facecolor'] = '#1a1b26'
    
    # 价格走势
    ax1 = axes[0]
    ax1.set_facecolor('#1a1b26')
    ax1.plot(data.index, data['close'], color='#c0caf5', linewidth=1.5, label='收盘价')
    
    # 买卖点
    buy_signals = signals[signals['signal_final'] == 1]
    if not buy_signals.empty:
        ax1.scatter(buy_signals.index, buy_signals['close'], 
                   marker='^', color='#e0af68', s=150, label='买入', zorder=5)
    
    for t in trades:
        if 'SELL' in t['type']:
            ax1.scatter([t['date']], [t['price']], 
                       marker='v', color='#bb9af7', s=150, label='卖出', zorder=5)
    
    ax1.set_title(f'{stock_name}', fontsize=14, color='#c0caf5', loc='left')
    ax1.legend(loc='upper right', facecolor='#24283b', edgecolor='#3b4261')
    ax1.grid(True, alpha=0.3, color='#3b4261')
    ax1.tick_params(colors='#565f89')
    for spine in ax1.spines.values():
        spine.set_color('#3b4261')
    
    # 成交量
    ax2 = axes[1]
    ax2.set_facecolor('#1a1b26')
    ax2.bar(data.index, data['volume'], color='#7aa2f7', alpha=0.6)
    ax2.set_title('成交量', fontsize=12, color='#c0caf5', loc='left')
    ax2.grid(True, alpha=0.3, color='#3b4261')
    ax2.tick_params(colors='#565f89')
    for spine in ax2.spines.values():
        spine.set_color('#3b4261')
    
    plt.tight_layout()
    plt.savefig(save_path, dpi=120, bbox_inches='tight', facecolor='#1a1b26')
    plt.close()


def prefilter_by_amount(stock_list, end_date, min_amount=1e9):
    """第 1 阶段：按当日成交额预筛
    缓存：stock_data/cache/prefilter_amount_{end_date}.csv —— 同一天复用
    返回过滤后的 [(code, name), ...]
    """
    import baostock as bs
    from pathlib import Path

    cache_path = Path('stock_data/cache') / f'prefilter_amount_{end_date}.csv'
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    end_str = end_date  # 'YYYY-MM-DD'

    if cache_path.exists():
        cache_df = pd.read_csv(cache_path, dtype={'code': str, 'name': str, 'amount': float})
        kept = cache_df[cache_df['amount'] >= min_amount].sort_values('amount', ascending=False)
        print(f"[预筛] 命中缓存 {cache_path.name}，{len(cache_df)} 只 → 阈值 {min_amount/1e8:.0f} 亿过滤后 {len(kept)} 只")
        return list(zip(kept['code'].tolist(), kept['name'].tolist()))

    print(f"\n[预筛] 全市场 {len(stock_list)} 只 → 拉取 {end_str} 当日成交额（首次较慢，结果会缓存）")

    bs.login()
    rows = []
    try:
        for i, (code, name) in enumerate(stock_list):
            try:
                rs = bs.query_history_k_data_plus(
                    code, "date,amount",
                    start_date=end_str, end_date=end_str,
                    frequency="d", adjustflag="3"
                )
                drows = []
                while rs.next():
                    drows.append(rs.get_row_data())
                if not drows:
                    continue
                amount = float(drows[-1][1] or 0)
                rows.append({'code': code, 'name': name, 'amount': amount})
            except Exception:
                continue

            if (i + 1) % 500 == 0:
                print(f"  [预筛] 已查 {i+1}/{len(stock_list)}")
    finally:
        bs.logout()

    cache_df = pd.DataFrame(rows)
    cache_df.to_csv(cache_path, index=False)
    print(f"[预筛] 缓存写入 {cache_path}（{len(cache_df)} 行）")

    kept = cache_df[cache_df['amount'] >= min_amount].sort_values('amount', ascending=False)
    print(f"[预筛] 完成：阈值 {min_amount/1e8:.0f} 亿过滤后 {len(kept)} 只")
    return list(zip(kept['code'].tolist(), kept['name'].tolist()))


def scan_stocks(start_date, end_date, min_price=0):
    """扫描符合策略条件的股票（先按成交额预筛，再做策略判断）"""
    print(f"\n正在扫描全市场...")

    full_list = get_stock_list()
    print(f"共获取 {len(full_list)} 只股票")

    # 第 1 阶段：成交额预筛（≥30 亿）
    stock_list = prefilter_by_amount(full_list, end_date, min_amount=3e9)

    qualified = []

    # 扩展日期范围以获取足够的历史数据
    scan_start = pd.to_datetime(start_date) - pd.Timedelta(days=60)
    scan_start_str = scan_start.strftime('%Y%m%d')
    scan_end_str = end_date.replace('-', '')

    for i, (code, name) in enumerate(stock_list):
        try:
            data = get_stock_data(code, scan_start_str, scan_end_str)
            if data.empty or len(data) < 30:
                continue
            
            # 过滤到目标日期范围
            target_start = pd.to_datetime(start_date.replace('-', ''))
            target_end = pd.to_datetime(end_date.replace('-', ''))
            mask = (data.index >= target_start) & (data.index <= target_end)
            period_data = data[mask]
            
            if period_data.empty:
                continue
            
            # 检查条件
            for date, row in period_data.iterrows():
                close = row['close']
                if close < min_price:
                    continue
                
                # 获取前一日数据
                prev_idx = data.index.get_loc(date) - 1
                if prev_idx < 0:
                    continue
                prev_row = data.iloc[prev_idx]
                
                # 条件1: 动量信号
                limit_up = prev_row['pct_change'] >= 9.9 if 'pct_change' in prev_row else False
                high_gain = row['pct_change'] >= 9.5 if 'pct_change' in row else False
                gap_up = row['open'] > prev_row['close'] * 1.02 and row['pct_change'] >= 5
                cond1 = limit_up or high_gain or gap_up
                
                # 条件2: 新高
                lookback = data.iloc[:prev_idx+1]
                high_20 = lookback.tail(20)['high'].max() if len(lookback) >= 20 else lookback['high'].max()
                cond2 = close >= high_20
                
                if cond1 and cond2:
                    qualified.append({
                        'code': code,
                        'name': name,
                        'signal_date': date.strftime('%Y-%m-%d'),
                        'price': close,
                        'pct': row['pct_change']
                    })
                    break  # 每只股票只记录首次信号
            
        except Exception as e:
            continue
        
        if (i + 1) % 100 == 0:
            print(f"已扫描 {i+1} 只股票, 发现 {len(qualified)} 只符合条件")
    
    print(f"\n扫描完成: 共发现 {len(qualified)} 只股票符合条件")
    return qualified


def run_backtest():
    """运行回测并生成报告"""
    # 回测参数：默认 end_date = 今天（A 股最近交易日由 baostock 自然限制）
    # 若需固定日期回测，可通过环境变量 BACKTEST_END / BACKTEST_START 覆盖
    today = pd.Timestamp.today().strftime('%Y-%m-%d')
    end_date = os.environ.get('BACKTEST_END', today)
    # 默认看 end_date 前 30 个自然日的回测窗口
    default_start = (pd.to_datetime(end_date) - pd.Timedelta(days=30)).strftime('%Y-%m-%d')
    start_date = os.environ.get('BACKTEST_START', default_start)
    initial_capital = 1000000  # 100万
    print(f"[run_backtest] 回测窗口 {start_date} ~ {end_date}")
    
    # 扫描股票
    stocks = scan_stocks(start_date, end_date)
    
    if not stocks:
        print("未找到符合条件的股票")
        return
    
    # 准备输出目录
    output_dir = "report_output"
    chart_dir = f"{output_dir}/charts"
    os.makedirs(chart_dir, exist_ok=True)
    
    results = []
    
    # 数据获取日期范围（扩展以计算指标）
    data_start = (pd.to_datetime(start_date) - pd.Timedelta(days=60)).strftime('%Y%m%d')
    data_end = end_date.replace('-', '')
    
    for s in stocks:
        print(f"\n处理 {s['name']} ({s['code']})...")
        
        # 获取数据
        data = get_stock_data(s['code'], data_start, data_end)
        if data.empty:
            continue
        
        # 策略信号
        strategy = MomentumBreakthroughStrategy(
            stop_loss=-0.10,
            min_amount=1e9
        )
        signals = strategy.generate_signals(data)
        
        if signals.empty:
            continue
        
        # 回测
        backtest_start = start_date.replace('-', '')
        backtest_end = end_date.replace('-', '')
        
        engine = BacktestEngineV2(
            initial_capital=initial_capital,
            commission=0.0003
        )
        
        result = engine.run(data, strategy)
        
        if result is None:
            continue
        
        # 计算指标
        metrics = engine.calculate_metrics()
        
        # 生成K线图
        chart_path = f"{chart_dir}/{s['code'].replace('.', '')}_kline.png"
        trades = result['trades'] if 'trades' in result else []
        plot_kline(data, signals, trades, chart_path, s['name'])
        
        # 保存结果
        signal_list = []
        buy_signals = signals[signals['signal_final'] == 1]
        for idx, row in buy_signals.iterrows():
            signal_list.append({
                'date': idx.strftime('%Y-%m-%d'),
                'price': row['close'],
                'pct': row.get('pct_change', 0),
                'limit_up': True,
                'new_high': True
            })
        
        results.append({
            'code': s['code'],
            'name': s['name'],
            'period_return': metrics.get('total_return', 0),
            'strategy_return': metrics.get('total_return', 0),
            'max_drawdown': metrics.get('max_drawdown', 0) * 100,
            'win_rate': metrics.get('win_rate', 0),
            'trades': len(trades),
            'signal_count': len(signal_list),
            'signals': signal_list,
            'chart_path': chart_path
        })
    
    # 生成报告
    if results:
        index_file = generate_report(results, output_dir)
        print(f"\n报告已生成: {os.path.abspath(index_file)}")
        print("请在浏览器中打开查看")
    else:
        print("无有效回测结果")


if __name__ == "__main__":
    run_backtest()

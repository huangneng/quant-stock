# -*- coding: utf-8 -*-
"""
量化策略回测主程序
========================

使用方法:
1. 修改下方的配置参数（股票代码、日期范围）
2. 选择或自定义策略
3. 运行 python main.py

作者: Comate
"""

import pandas as pd
import numpy as np
from data import get_stock_data
from strategy import (
    DoubleMAStrategy, 
    RSIStrategy, 
    BollingerBandsStrategy,
    CustomStrategy,
    MomentumBreakthroughStrategy
)
from backtest import BacktestEngine
from strategy import BacktestEngineV2  # 新版回测引擎，支持止损持有


def create_mock_data(start_date: str = "20230101", end_date: str = "20241231", 
                      base_price: float = 100, volatility: float = 0.02,
                      seed: int = None, trend: str = "neutral") -> pd.DataFrame:
    """
    创建模拟数据（网络不可用时的备用方案）
    
    Args:
        start_date: 开始日期
        end_date: 结束日期  
        base_price: 基础价格
        volatility: 波动率
        seed: 随机种子
        trend: 趋势方向 ("up"上涨, "down"下跌, "neutral"震荡, "breakout"突破)
    """
    dates = pd.date_range(start_date, end_date, freq='B')
    n = len(dates)
    
    if seed is not None:
        np.random.seed(seed)
    
    price = base_price
    opens = []
    highs = []
    lows = []
    closes = []
    
    for i in range(n):
        # 根据趋势类型调整价格行为
        if trend == "up":
            daily_drift = 0.001  # 正向漂移
        elif trend == "down":
            daily_drift = -0.001
        elif trend == "breakout":
            # 突破模式：前段震荡，后段突破
            if i > n * 0.7:
                daily_drift = 0.005  # 后30%时间加速上涨
            else:
                daily_drift = 0
        else:
            daily_drift = 0
        
        # 开盘价
        open_price = price * (1 + np.random.randn() * 0.005)
        
        # 随机加入大涨行情（模拟涨停）
        if trend == "breakout" and i > n * 0.8 and np.random.random() < 0.15:
            change = np.random.uniform(0.095, 0.105)  # 9.5%-10.5%涨停
        elif np.random.random() < 0.02:  # 2%概率大跌
            change = np.random.uniform(-0.08, -0.03)
        else:
            change = daily_drift + np.random.randn() * volatility
        
        close_price = open_price * (1 + change)
        high_price = max(open_price, close_price) * (1 + abs(np.random.randn()) * 0.008)
        low_price = min(open_price, close_price) * (1 - abs(np.random.randn()) * 0.008)
        
        opens.append(open_price)
        closes.append(close_price)
        highs.append(high_price)
        lows.append(low_price)
        
        price = close_price
    
    return pd.DataFrame({
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': [1000000 + np.random.randint(-100000, 100000) for _ in range(n)]
    }, index=dates)


def main():
    # ============================================
    # 配置参数 - 根据需要修改
    # ============================================
    
    # 股票代码（A股，如 '000001' 平安银行, '600519' 贵州茅台）
    stock_code = "600519"  # 贵州茅台
    
    # 回测日期范围（假设今天是2026-05-01，取过去一年数据）
    start_date = "20250101"
    end_date = "20260430"  # 截止4月30日
    
    # 初始资金（建议>=20万以支持高价股）
    initial_capital = 200000  # 20万元
    
    # ============================================
    # 选择策略 - 取消注释你想使用的策略
    # ============================================
    
    # 策略1: 双均线策略
    # strategy = DoubleMAStrategy(short_window=5, long_window=20)
    
    # 策略2: RSI策略
    # strategy = RSIStrategy(period=14, oversold=30, overbought=70)
    
    # 策略3: 布林带策略
    # strategy = BollingerBandsStrategy(period=20, std_dev=2)
    
    # 策略4: 动量突破策略（你的选股策略）
    # stop_loss: 止损比例，默认-10%
    # buy_next_day: True=次日开盘买入, False=当日收盘买入
    strategy = MomentumBreakthroughStrategy(stop_loss=-0.10, buy_next_day=False)
    
    # 策略5: 自定义策略（在 strategy.py 中编辑）
    # strategy = CustomStrategy()
    
    # ============================================
    # 执行回测
    # ============================================
    
    print(f"\n正在获取股票数据: {stock_code}")
    print(f"回测区间: {start_date} - {end_date}")
    
    # 获取数据
    data = get_stock_data(stock_code, start_date, end_date)
    
    # 如果网络失败，使用模拟数据演示
    use_mock = False
    if data.empty:
        print("\n[提示] 网络数据获取失败，使用模拟数据演示回测流程...")
        data = create_mock_data(start_date, end_date)
        use_mock = True
    
    print(f"成功获取 {len(data)} 条交易数据")
    print(f"数据范围: {data.index[0].date()} 至 {data.index[-1].date()}")
    
    # 初始化回测引擎（使用新版引擎支持止损持有）
    engine = BacktestEngineV2(initial_capital=initial_capital)
    
    # 运行回测
    print(f"\n正在运行回测: {strategy.name}...")
    print(f"  止损比例: {strategy.params.get('stop_loss', -0.10) * 100:.0f}%")
    print(f"  买入方式: {'次日开盘买入' if strategy.params.get('buy_next_day') else '当日收盘买入'}")
    
    results = engine.run(data, strategy)
    
    # 打印结果摘要
    engine.print_summary()
    
    # 显示选股信号详情
    signals = results['signals']
    buy_signals = signals[signals['signal_final'] == 1]
    
    if len(buy_signals) > 0:
        print("\n买入信号详情:")
        print("-" * 80)
        for idx, row in buy_signals.iterrows():
            print(f"日期: {idx.date()}")
            print(f"  收盘价: {row['close']:.2f}")
            print(f"  涨跌幅: {row.get('pct_change', 0):.2f}%")
            print(f"  昨日涨停: {'是' if row.get('prev_limit_up', False) else '否'}")
            print(f"  创20日新高: {'是' if row.get('new_20d_high', False) else '否'}")
            print(f"  创历史新高: {'是' if row.get('new_all_time_high', False) else '否'}")
            print("-" * 80)
    
    # 绘制图表
    suffix = "_mock" if use_mock else ""
    engine.plot_results(save_path=f"backtest_result_{stock_code}{suffix}.png")


def run_stock_screener(start_date: str = "20260401", end_date: str = "20260508"):
    """
    选股器 - 批量筛选符合策略条件的股票
    
    Args:
        start_date: 数据开始日期
        end_date: 选股日期
    """
    print("\n" + "="*60)
    print(f"  动量突破选股器")
    print(f"  数据区间: {start_date[:4]}-{start_date[4:6]}-{start_date[6:8]} 至 {end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}")
    print("="*60)
    
    # 待筛选股票池（可自定义，扩展到更多股票）
    # (代码, 名称, 基础价格, 趋势模式)
    stock_pool = [
        ("600519", "贵州茅台", 1600, "breakout"),    # 突破模式
        ("000858", "五粮液", 140, "up"),            # 上涨模式
        ("000001", "平安银行", 12, "neutral"),      # 震荡模式
        ("601318", "中国平安", 45, "down"),         # 下跌模式
        ("600036", "招商银行", 35, "neutral"),
        ("601398", "工商银行", 5, "neutral"),
        ("601288", "农业银行", 4, "neutral"),
        ("600276", "恒瑞医药", 42, "breakout"),     # 突破模式
        ("000333", "美的集团", 65, "up"),
        ("600030", "中信证券", 22, "neutral"),
    ]
    
    strategy = MomentumBreakthroughStrategy()
    
    selected_stocks = []
    all_signals = []
    use_mock = False
    
    for stock_info in stock_pool:
        code, name, base_price, trend = stock_info[0], stock_info[1], stock_info[2], stock_info[3] if len(stock_info) > 3 else "neutral"
        print(f"\n正在分析: {code} {name}...")
        
        # 获取数据用于分析
        data = get_stock_data(code, start_date, end_date)
        
        if data.empty:
            # 网络失败，使用模拟数据
            print(f"  [使用模拟数据 - {trend}模式]")
            use_mock = True
            seed = int(code) % 1000  # 根据股票代码生成不同种子
            data = create_mock_data(start_date, end_date, base_price=base_price, seed=seed, trend=trend)
        
        signals = strategy.generate_signals(data)
        all_signals.append({'code': code, 'name': name, 'data': data, 'signals': signals})
        
        # 获取最近一个交易日的信号
        latest = signals.iloc[-1]
        
        # 检查是否满足条件
        condition1_met = (latest.get('prev_limit_up', False) or
                         latest.get('today_high_gain', False) or
                         latest.get('gap_up_with_gain', False))
        
        condition2_met = (latest.get('new_20d_high', False) or
                         latest.get('new_all_time_high', False))
        
        condition3_met = latest['close'] > 100
        
        if condition1_met and condition2_met and condition3_met:
            selected_stocks.append({
                'code': code,
                'name': name,
                'close': latest['close'],
                'pct_change': latest.get('pct_change', 0),
                'prev_limit_up': latest.get('prev_limit_up', False),
                'new_20d_high': latest.get('new_20d_high', False),
                'new_all_time_high': latest.get('new_all_time_high', False)
            })
            print(f"  [选中] 收盘价: {latest['close']:.2f}元, 涨跌幅: {latest.get('pct_change', 0):.2f}%")
        else:
            reasons = []
            if not condition1_met:
                reasons.append("动量信号不足")
            if not condition2_met:
                reasons.append("未创新高")
            if not condition3_met:
                reasons.append(f"股价{latest['close']:.2f}<100元")
            print(f"  [未选中] 原因: {', '.join(reasons)}")
    
    if use_mock:
        print("\n  [提示] 以上使用模拟数据演示，实际请等待网络恢复后获取真实数据")
    
    print("\n" + "="*60)
    print("  选股结果汇总")
    print("="*60)
    
    if selected_stocks:
        for stock in selected_stocks:
            signals = []
            if stock['prev_limit_up']:
                signals.append("昨日涨停")
            if stock['new_20d_high']:
                signals.append("创20日新高")
            if stock['new_all_time_high']:
                signals.append("创历史新高")
            print(f"  {stock['code']} {stock['name']}")
            print(f"    收盘价: {stock['close']:.2f}元 | 涨跌幅: {stock['pct_change']:.2f}%")
            print(f"    信号: {', '.join(signals)}")
    else:
        print("  今日无符合条件的股票")
    
    print("="*60 + "\n")
    
    return selected_stocks, all_signals


def run_batch_backtest(start_date: str = "20260401", end_date: str = "20260508"):
    """
    批量回测多只股票
    """
    print("\n" + "="*60)
    print(f"  批量回测")
    print(f"  数据区间: {start_date[:4]}-{start_date[4:6]}-{start_date[6:8]} 至 {end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}")
    print("="*60)
    
    # (代码, 名称, 基础价格, 趋势模式)
    stock_pool = [
        ("600519", "贵州茅台", 1600, "breakout"),
        ("000858", "五粮液", 140, "up"),
        ("000001", "平安银行", 12, "neutral"),
        ("601318", "中国平安", 45, "down"),
        ("600036", "招商银行", 35, "neutral"),
    ]
    
    strategy = MomentumBreakthroughStrategy(stop_loss=-0.10, buy_next_day=False)
    engine = BacktestEngineV2(initial_capital=200000)
    
    results_summary = []
    use_mock = False
    
    for stock_info in stock_pool:
        code, name, base_price = stock_info[0], stock_info[1], stock_info[2]
        trend = stock_info[3] if len(stock_info) > 3 else "neutral"
        
        print(f"\n回测: {code} {name}...")
        
        data = get_stock_data(code, start_date, end_date)
        
        if data.empty:
            print(f"  [使用模拟数据 - {trend}模式]")
            use_mock = True
            seed = int(code) % 1000
            data = create_mock_data(start_date, end_date, base_price=base_price, seed=seed, trend=trend)
        
        results = engine.run(data, strategy)
        metrics = engine.calculate_metrics()
        
        results_summary.append({
            'code': code,
            'name': name,
            'total_return': metrics.get('总收益率', '0%'),
            'max_drawdown': metrics.get('最大回撤', '0%'),
            'trades': metrics.get('总交易次数', 0),
            'final_capital': metrics.get('最终资金', '¥0'),
            'win_rate': metrics.get('胜率', '0%')
        })
        
        print(f"  总收益率: {metrics.get('总收益率', '0%')}")
        print(f"  最大回撤: {metrics.get('最大回撤', '0%')}")
        print(f"  交易次数: {metrics.get('总交易次数', 0)}")
    
    if use_mock:
        print("\n  [提示] 以上使用模拟数据演示，实际请等待网络恢复后获取真实数据")
    
    # 打印汇总表格
    print("\n" + "="*60)
    print("  回测结果汇总")
    print("="*60)
    print(f"  {'代码':<8s} {'名称':<10s} {'收益率':>10s} {'最大回撤':>10s} {'胜率':>8s}")
    print("  " + "-"*50)
    for r in results_summary:
        print(f"  {r['code']:<8s} {r['name']:<10s} {r['total_return']:>10s} {r['max_drawdown']:>10s} {r['win_rate']:>8s}")
    print("="*60 + "\n")
    
    return results_summary


if __name__ == "__main__":
    import sys
    
    # 5月1日-5月8日选股回测
    START_DATE = "20260401"  # 需要之前的数据计算20日新高
    END_DATE = "20260508"    # 选股截止日期
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        if cmd == "screen":
            # 运行选股器: python main.py screen
            run_stock_screener(START_DATE, END_DATE)
        
        elif cmd == "batch":
            # 批量回测: python main.py batch
            run_batch_backtest(START_DATE, END_DATE)
        
        elif cmd == "all":
            # 选股+回测: python main.py all
            run_stock_screener(START_DATE, END_DATE)
            run_batch_backtest(START_DATE, END_DATE)
        
        else:
            print("用法:")
            print("  python main.py        # 单股回测")
            print("  python main.py screen # 运行选股器")
            print("  python main.py batch  # 批量回测")
            print("  python main.py all    # 选股+批量回测")
    else:
        # 运行单股回测: python main.py
        main()
# -*- coding: utf-8 -*-
"""
演示脚本 - 模拟2026-05-01选股和回测

由于网络不稳定，使用精心设计的模拟数据演示完整的选股和回测流程
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from strategy import MomentumBreakthroughStrategy, BacktestEngineV2


def create_breakthrough_scenario(start_date: str = "20260101", end_date: str = "20260430"):
    """
    创建包含突破信号的模拟数据
    模拟一只股票在4月下旬出现突破行情
    """
    dates = pd.date_range(start_date, end_date, freq='B')
    n = len(dates)
    
    np.random.seed(42)
    
    base_price = 120  # 基础价格 > 100
    price = base_price
    opens, highs, lows, closes = [], [], [], []
    
    # 计算突破日的索引位置
    breakthrough_idx = int(n * 0.75)  # 75%位置出现突破
    
    for i in range(n):
        # 前75%时间震荡
        if i < breakthrough_idx:
            change = np.random.randn() * 0.012
            open_change = np.random.randn() * 0.003
        elif i == breakthrough_idx:
            # 突破日：涨停
            change = 0.10
            open_change = 0.01
        elif i == breakthrough_idx + 1:
            # 次日：继续上涨创新高
            change = 0.08
            open_change = 0.03
        else:
            # 之后继续上涨或震荡
            change = np.random.uniform(-0.01, 0.02)
            open_change = np.random.randn() * 0.005
        
        open_price = price * (1 + open_change)
        close_price = open_price * (1 + change)
        high_price = max(open_price, close_price) * (1 + np.random.rand() * 0.008)
        low_price = min(open_price, close_price) * (1 - np.random.rand() * 0.008)
        
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
        'volume': [500000 + np.random.randint(-50000, 50000) for _ in range(n)]
    }, index=dates)


def main():
    print("="*70)
    print("  动量突破策略 - 选股与回测演示")
    print("  假设日期: 2026年5月1日")
    print("="*70)
    
    # ========== 模拟选股场景 ==========
    print("\n" + "="*70)
    print("  一、选股结果")
    print("="*70)
    
    # 创建一只模拟突破股票
    stock_data = create_breakthrough_scenario("20260101", "20260430")
    
    strategy = MomentumBreakthroughStrategy(stop_loss=-0.10)
    signals = strategy.generate_signals(stock_data)
    
    # 获取最近的信号
    latest = signals.iloc[-1]
    
    # 找到突破日
    breakthrough_signals = signals[signals['signal_final'] == 1]
    
    print(f"\n  模拟股票 DEMO001 (演示股票)")
    print(f"  回测期间共 {len(signals)} 个交易日")
    
    # 显示突破日详情
    if len(breakthrough_signals) > 0:
        print(f"\n  发现 {len(breakthrough_signals)} 个买入信号！")
        print("\n  买入信号详情:")
        print("  " + "-"*60)
        for idx, row in breakthrough_signals.iterrows():
            print(f"  日期: {idx.date()}")
            print(f"    收盘价: {row['close']:.2f}元")
            print(f"    涨跌幅: {row.get('pct_change', 0):.2f}%")
            print(f"    昨日涨停: {'是' if row.get('prev_limit_up', False) else '否'}")
            print(f"    今日涨幅>9.5%: {'是' if row.get('today_high_gain', False) else '否'}")
            print(f"    创20日新高: {'是' if row.get('new_20d_high', False) else '否'}")
            print(f"    创历史新高: {'是' if row.get('new_all_time_high', False) else '否'}")
            print("  " + "-"*60)
    else:
        # 查看最近几天的信号详情，调试用
        print("\n  最近5个交易日数据:")
        recent = signals.tail(5)[['close', 'pct_change', 'prev_limit_up', 'today_high_gain', 
                                   'new_20d_high', 'new_all_time_high', 'signal_final']]
        for idx, row in recent.iterrows():
            print(f"  {idx.date()}: 收盘{row['close']:.2f}, 涨幅{row.get('pct_change', 0):.2f}%, 信号={row['signal_final']}")
    
    # ========== 回测 ==========
    print("\n" + "="*70)
    print("  二、策略回测")
    print("="*70)
    
    print(f"\n  回测区间: 2026-01-01 至 2026-04-30")
    print(f"  初始资金: 200,000元")
    print(f"  止损比例: -10%")
    print(f"  买入方式: 当日收盘买入")
    
    engine = BacktestEngineV2(initial_capital=200000)
    results = engine.run(stock_data, strategy)
    
    # 打印详细结果
    engine.print_summary()
    
    # 打印交易明细
    trades = results['trades']
    if trades:
        print("\n  交易明细:")
        print("  " + "-"*60)
        for t in trades:
            pnl_str = f", 盈亏: {t['pnl_pct']:.2f}%" if 'pnl_pct' in t else ""
            print(f"  {t['date'].date()} | {t['type']:15s} | 价格: {t['price']:.2f} | 数量: {t['shares']}{pnl_str}")
        print("  " + "-"*60)
    
    # 绘制图表
    print("\n  正在生成回测图表...")
    engine.plot_results(save_path="demo_backtest_result.png")
    
    print("\n" + "="*70)
    print("  演示完成")
    print("="*70)
    
    # 策略说明
    print("""
  策略说明:
  ─────────────────────────────────────────────────────────────────────
  【选股条件】三个条件同时满足:
    1. 昨日涨停 OR 今日涨幅>9.5% OR (跳空高开 且 涨幅>5%)
    2. 收盘价创20日新高 OR 创历史新高
    3. 股价 > 100元
  
  【买入方式】
    • 当日收盘价买入（可配置为次日开盘买入）
  
  【卖出条件】
    • 触发止损（默认-10%）
    • 无固定持有天数，一直持有直到止损
  
  【使用真实数据】
    网络恢复后运行: python main.py all
  ─────────────────────────────────────────────────────────────────────
    """)


if __name__ == "__main__":
    main()
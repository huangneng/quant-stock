# -*- coding: utf-8 -*-
"""
5月1日-5月8日 选股与回测演示

模拟这段时间内策略的表现
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from strategy import MomentumBreakthroughStrategy, BacktestEngineV2


def create_may_scenario(code: str, base_price: float, scenario: str = "breakout"):
    """
    创建模拟数据，展示完整的策略周期
    时间范围：2026-01-01 到 2026-05-08
    """
    dates = pd.date_range("20260101", "20260508", freq='B')
    n = len(dates)
    
    seed = int(code) % 1000
    np.random.seed(seed)
    
    price = base_price
    opens, highs, lows, closes = [], [], [], []
    
    # 找到5月初的位置
    may_indices = [i for i, d in enumerate(dates) if d.month == 5]
    may_first_idx = may_indices[0] if may_indices else n - 5
    
    for i in range(n):
        if scenario == "breakout":
            # 突破场景：5月初出现涨停突破
            if i == may_first_idx:  # 5月第一个交易日涨停
                change = 0.10
                open_change = 0.02
            elif i == may_first_idx + 1:  # 次日继续涨
                change = 0.06
                open_change = 0.02
            elif i == may_first_idx + 2:  # 第三天
                change = 0.03
                open_change = 0.01
            elif i > may_first_idx + 2:
                # 之后继续上涨或小幅震荡
                change = np.random.uniform(-0.01, 0.02)
                open_change = np.random.randn() * 0.003
            else:
                # 5月之前：震荡
                change = np.random.randn() * 0.012
                open_change = np.random.randn() * 0.003
        elif scenario == "pullback":
            # 回调场景
            if i == may_first_idx:
                change = -0.03
                open_change = -0.01
            else:
                change = np.random.randn() * 0.015
                open_change = np.random.randn() * 0.003
        else:
            change = np.random.randn() * 0.015
            open_change = np.random.randn() * 0.003
        
        open_price = price * (1 + open_change)
        close_price = open_price * (1 + change)
        high_price = max(open_price, close_price) * (1 + abs(np.random.randn()) * 0.005)
        low_price = min(open_price, close_price) * (1 - abs(np.random.randn()) * 0.005)
        
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
        'volume': [500000] * n
    }, index=dates)


def main():
    print("="*70)
    print("  动量突破策略 - 5月1日至5月8日 选股与回测")
    print("="*70)
    
    print("""
  【重要说明】
  ─────────────────────────────────────────────────────────────────
  由于网络不稳定无法获取真实A股数据，以下使用模拟数据演示框架功能。
  
  模拟数据是人为设置的突破场景，不代表真实市场情况！
  真实选股需要网络恢复后运行: python main.py all
  ─────────────────────────────────────────────────────────────────
    """)
    
    # 模拟股票池
    stock_pool = [
        ("600519", "贵州茅台", 1800, "breakout"),   # 突破
        ("000858", "五粮液", 130, "neutral"),       # 震荡
        ("600276", "恒瑞医药", 48, "breakout"),     # 突破但股价不足100
        ("000333", "美的集团", 72, "pullback"),     # 回调
        ("601318", "中国平安", 50, "neutral"),      # 震荡
    ]
    
    strategy = MomentumBreakthroughStrategy(stop_loss=-0.10, buy_next_day=False)
    
    print("\n" + "="*70)
    print("  一、选股结果（2026-05-08 截止）")
    print("="*70)
    
    selected_stocks = []
    all_results = []
    
    for code, name, base_price, scenario in stock_pool:
        data = create_may_scenario(code, base_price, scenario)
        signals = strategy.generate_signals(data)
        
        # 只看5月1日-5月8日的信号
        may_signals = signals.loc["2026-05-01":"2026-05-08"]
        
        # 检查是否有买入信号
        buy_in_may = may_signals[may_signals['signal_final'] == 1]
        
        if len(buy_in_may) > 0:
            selected_stocks.append({
                'code': code,
                'name': name,
                'signals': buy_in_may,
                'data': data,
                'base_price': base_price
            })
            print(f"\n  [选中] {code} {name}")
            for idx, row in buy_in_may.iterrows():
                print(f"    {idx.date()}: 收盘价 {row['close']:.2f}元, 涨幅 {row.get('pct_change', 0):.2f}%")
        else:
            # 检查最后一天是否满足条件
            latest = may_signals.iloc[-1]
            reasons = []
            condition1 = latest.get('prev_limit_up', False) or latest.get('today_high_gain', False) or latest.get('gap_up_with_gain', False)
            condition2 = latest.get('new_20d_high', False) or latest.get('new_all_time_high', False)
            condition3 = latest['close'] > 100
            
            if not condition1:
                reasons.append("动量信号不足")
            if not condition2:
                reasons.append("未创新高")
            if not condition3:
                reasons.append(f"股价{latest['close']:.2f}<100")
            
            print(f"\n  [未选中] {code} {name} - {', '.join(reasons)}")
    
    # 选股汇总
    print("\n" + "-"*70)
    print("  选股汇总:")
    print("-"*70)
    if selected_stocks:
        for s in selected_stocks:
            print(f"  {s['code']} {s['name']}")
    else:
        print("  5月1日-8日期间无符合条件的股票")
    
    # 回测
    print("\n" + "="*70)
    print("  二、策略回测（2026-01-01 至 2026-05-08）")
    print("="*70)
    
    results_summary = []
    
    for code, name, base_price, scenario in stock_pool:
        data = create_may_scenario(code, base_price, scenario)
        
        # 根据股价调整初始资金，确保能买入
        initial_capital = max(200000, base_price * 200)
        
        engine = BacktestEngineV2(initial_capital=initial_capital)
        results = engine.run(data, strategy)
        metrics = engine.calculate_metrics()
        
        results_summary.append({
            'code': code,
            'name': name,
            'total_return': metrics.get('总收益率', '0%'),
            'max_drawdown': metrics.get('最大回撤', '0%'),
            'trades': metrics.get('总交易次数', 0),
            'win_rate': metrics.get('胜率', '0%'),
            'final_capital': metrics.get('最终资金', '¥0')
        })
        
        print(f"\n  {code} {name}:")
        print(f"    总收益率: {metrics.get('总收益率', '0%')}")
        print(f"    最大回撤: {metrics.get('最大回撤', '0%')}")
        print(f"    交易次数: {metrics.get('总交易次数', 0)}")
    
    # 汇总表格
    print("\n" + "="*70)
    print("  回测结果汇总")
    print("="*70)
    print(f"  {'代码':<8s} {'名称':<10s} {'收益率':>10s} {'最大回撤':>10s} {'胜率':>8s}")
    print("  " + "-"*50)
    for r in results_summary:
        print(f"  {r['code']:<8s} {r['name']:<10s} {r['total_return']:>10s} {r['max_drawdown']:>10s} {r['win_rate']:>8s}")
    print("="*70)
    
    # 对选中股票详细回测
    if selected_stocks:
        print("\n" + "="*70)
        print("  三、选中股票详细回测")
        print("="*70)
        
        for s in selected_stocks:
            code, name = s['code'], s['name']
            data = s['data']
            base_price = s['base_price']
            
            # 根据股价调整初始资金
            initial_capital = max(500000, base_price * 300)
            
            engine = BacktestEngineV2(initial_capital=initial_capital)
            results = engine.run(data, strategy)
            
            print(f"\n  {code} {name}:")
            engine.print_summary()
            
            # 绘图 - 传入股票名称
            engine.plot_results(save_path=f"backtest_may_{code}.png", stock_name=f"{code} {name}")
    
    print("\n" + "="*70)
    print("  策略评估总结")
    print("="*70)
    print("""
  【选股条件】
    1. 昨日涨停 OR 今日涨幅>9.5% OR (跳空高开 且 涨幅>5%)
    2. 收盘价创20日新高 OR 创历史新高
    3. 股价 > 100元

  【买卖规则】
    • 买入: 当日收盘价买入
    • 卖出: 触发10%止损

  【注意事项】
    • 以上使用模拟数据演示
    • 真实数据请运行: python main.py all
    • 策略需要实时监控，在信号出现时及时买入
    """)


if __name__ == "__main__":
    main()
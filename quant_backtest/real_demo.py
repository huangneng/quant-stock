# -*- coding: utf-8 -*-
"""
5月1日-5月8日 选股演示（真实模拟）

使用随机模拟数据，不人为设置突破，让策略自然判断
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from strategy import MomentumBreakthroughStrategy, BacktestEngineV2


def create_realistic_data(code: str, base_price: float, days: int = 90):
    """
    创建真实的随机模拟数据
    不人为设置突破，让价格自然波动
    """
    np.random.seed(int(code) % 10000)  # 不同股票不同种子
    
    dates = pd.date_range(end="2026-05-08", periods=days, freq='B')
    
    price = base_price
    opens, highs, lows, closes = [], [], [], []
    
    for i in range(days):
        # 真实的日内波动
        gap = np.random.randn() * 0.01  # 开盘跳空
        intraday = np.random.randn() * 0.02  # 日内波动
        
        open_price = price * (1 + gap)
        close_price = open_price * (1 + intraday)
        
        # 真实的高低点
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
        'volume': [500000 + np.random.randint(-50000, 50000) for _ in range(days)]
    }, index=dates)


def main():
    print("="*70)
    print("  动量突破策略 - 5月选股演示（真实随机模拟）")
    print("="*70)
    
    print("""
  【重要说明】
  ─────────────────────────────────────────────────────────────────
  以下使用随机模拟数据演示选股逻辑，不人为设置突破。
  
  选股条件：
  1. 昨日涨停(涨幅≥9.9%) OR 今日涨幅>9.5% OR (跳空高开且涨幅>5%)
  2. 收盘价创20日新高 OR 创历史新高  
  3. 股价 > 100元
  
  买入：当日收盘价买入
  卖出：触发10%止损
  ─────────────────────────────────────────────────────────────────
    """)
    
    # 股票池
    stock_pool = [
        ("600519", "贵州茅台", 1800),
        ("000858", "五粮液", 140),
        ("000001", "平安银行", 12),
        ("601318", "中国平安", 48),
        ("600036", "招商银行", 35),
        ("600276", "恒瑞医药", 45),
        ("000333", "美的集团", 68),
        ("600030", "中信证券", 25),
        ("601012", "隆基绿能", 22),
        ("002594", "比亚迪", 260),
    ]
    
    strategy = MomentumBreakthroughStrategy(stop_loss=-0.10)
    
    print("="*70)
    print("  选股结果")
    print("="*70)
    
    selected = []
    
    for code, name, base_price in stock_pool:
        data = create_realistic_data(code, base_price)
        signals = strategy.generate_signals(data)
        
        # 检查5月1日-8日的信号
        may_signals = signals.loc["2026-05-01":"2026-05-08"] if len(signals.loc["2026-05-01":"2026-05-08"]) > 0 else signals.tail(5)
        
        latest = may_signals.iloc[-1]
        
        # 检查三个条件
        condition1 = latest.get('prev_limit_up', False) or latest.get('today_high_gain', False) or latest.get('gap_up_with_gain', False)
        condition2 = latest.get('new_20d_high', False) or latest.get('new_all_time_high', False)
        condition3 = latest['close'] > 100
        
        # 统计买入信号
        buy_count = (may_signals['signal_final'] == 1).sum()
        
        if condition1 and condition2 and condition3:
            selected.append((code, name, data, signals, base_price))
            print(f"\n  ✓ [选中] {code} {name}")
            print(f"      收盘价: {latest['close']:.2f}元")
            print(f"      涨跌幅: {latest.get('pct_change', 0):.2f}%")
            print(f"      昨日涨停: {'是' if latest.get('prev_limit_up') else '否'}")
            print(f"      今日涨幅>9.5%: {'是' if latest.get('today_high_gain') else '否'}")
            print(f"      创20日新高: {'是' if latest.get('new_20d_high') else '否'}")
            print(f"      创历史新高: {'是' if latest.get('new_all_time_high') else '否'}")
        else:
            reasons = []
            if not condition1:
                reasons.append("无动量信号")
            if not condition2:
                reasons.append("未创新高")
            if not condition3:
                reasons.append(f"股价{latest['close']:.0f}<100")
            print(f"\n  ✗ {code} {name} - {', '.join(reasons)}")
    
    print("\n" + "="*70)
    print(f"  选股汇总: 共选中 {len(selected)} 只股票")
    print("="*70)
    
    if selected:
        for code, name, _, _, _ in selected:
            print(f"  • {code} {name}")
    
    # 对选中股票回测
    if selected:
        print("\n" + "="*70)
        print("  选中股票回测")
        print("="*70)
        
        for code, name, data, signals, base_price in selected:
            initial_capital = max(500000, base_price * 300)
            
            engine = BacktestEngineV2(initial_capital=initial_capital)
            results = engine.run(data, strategy)
            
            print(f"\n  {code} {name}:")
            metrics = engine.calculate_metrics()
            print(f"    总收益率: {metrics.get('总收益率', '0%')}")
            print(f"    最大回撤: {metrics.get('最大回撤', '0%')}")
            print(f"    交易次数: {metrics.get('总交易次数', 0)}")
            
            # 绘图
            engine.plot_results(save_path=f"backtest_selected_{code}.png", stock_name=f"{code} {name}")
    else:
        print("\n  在5月1日-8日期间，没有股票满足选股条件。")
        print("  这在真实市场中是正常现象——策略条件较严格，只有少数股票能命中。")
    
    print("\n" + "="*70)
    print("  策略说明")
    print("="*70)
    print("""
  本策略是趋势跟踪策略，只在出现强势突破信号时才买入。
  
  优点：
    • 捕捉强势突破行情
    • 严格止损控制风险
  
  缺点：
    • 选股条件严格，可能错过一些机会
    • 震荡市中可能长期空仓
  
  真实使用：
    • 网络恢复后运行: python main.py all
    • 定期运行选股器监控市场
    • 建议结合基本面分析
    """)


if __name__ == "__main__":
    main()
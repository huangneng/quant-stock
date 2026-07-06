# -*- coding: utf-8 -*-
"""
动量突破策略 - 正确工作流程

工作流程:
1. 扫描市场 → 寻找符合选股条件的股票
2. 对符合条件的股票 → 执行交易策略回测
3. 评估策略效果

选股条件:
- 条件1: 昨日涨停 OR 今日涨幅>9.5% OR (跳空高开且涨幅>5%)
- 条件2: 创20日新高 OR 创历史新高
- 条件3: 股价 > 100元

交易策略:
- 买入: 当日收盘价买入
- 卖出: 触发10%止损
"""

import akshare as ak
import pandas as pd
import time
from strategy import MomentumBreakthroughStrategy, BacktestEngineV2


def get_stock_data(code, start_date, end_date, retries=3):
    """获取股票数据（带重试）"""
    for _ in range(retries):
        try:
            df = ak.stock_zh_a_hist(
                symbol=code, 
                period="daily", 
                start_date=start_date, 
                end_date=end_date, 
                adjust="qfq"
            )
            if not df.empty:
                df = df.rename(columns={
                    '日期': 'date', '开盘': 'open', '收盘': 'close',
                    '最高': 'high', '最低': 'low', '成交量': 'volume'
                })
                df['date'] = pd.to_datetime(df['date'])
                df = df.set_index('date')
                return df
        except:
            time.sleep(2)
    return None


def run_strategy(start_date="20260401", end_date="20260511"):
    """
    执行完整的选股和回测流程
    """
    print("="*70)
    print("  动量突破策略 - 选股与回测")
    print(f"  时间区间: {start_date} 至 {end_date}")
    print("="*70)
    
    # 股票池 - 高价股（股价可能>100）
    stock_pool = [
        # 白酒
        ('600519', '贵州茅台'), ('000858', '五粮液'), ('000568', '泸州老窖'),
        ('600809', '山西汾酒'), ('002304', '洋河股份'),
        # 新能源
        ('300750', '宁德时代'), ('002594', '比亚迪'),
        # 医药
        ('300760', '迈瑞医疗'), ('600276', '恒瑞医药'),
        # 其他
        ('600309', '万华化学'), ('000333', '美的集团'),
        ('002415', '海康威视'), ('300059', '东方财富'),
    ]
    
    # 步骤1: 扫描获取数据
    print(f"\n【步骤1】扫描 {len(stock_pool)} 只股票...")
    stock_data = {}
    
    for i, (code, name) in enumerate(stock_pool):
        print(f"[{i+1}/{len(stock_pool)}] {code} {name}...", end=" ", flush=True)
        df = get_stock_data(code, start_date, end_date)
        if df is not None:
            stock_data[code] = {'name': name, 'data': df}
            print(f"✓ 收盘{df['close'].iloc[-1]:.2f}元")
        else:
            print("× 获取失败")
        time.sleep(1)
    
    print(f"\n成功获取 {len(stock_data)} 只股票数据")
    
    if len(stock_data) == 0:
        print("无法获取数据，请检查网络")
        return
    
    # 步骤2: 选股
    print("\n" + "="*70)
    print("【步骤2】选股 - 寻找符合条件的股票")
    print("="*70)
    print("选股条件:")
    print("  1. 昨日涨停 OR 今日涨幅>9.5% OR (跳空高开且涨幅>5%)")
    print("  2. 创20日新高 OR 创历史新高")
    print("  3. 股价 > 100元")
    print("-"*70)
    
    strategy = MomentumBreakthroughStrategy(stop_loss=-0.10)
    SELECTED = []
    
    for code, info in stock_data.items():
        df = info['data']
        signals = strategy.generate_signals(df)
        latest = signals.iloc[-1]
        
        # 检查三个条件
        c1 = (latest.get('prev_limit_up', False) or 
              latest.get('today_high_gain', False) or 
              latest.get('gap_up_with_gain', False))
        c2 = (latest.get('new_20d_high', False) or 
              latest.get('new_all_time_high', False))
        c3 = latest['close'] > 100
        
        reasons = []
        if not c1: reasons.append("无动量信号")
        if not c2: reasons.append("未创新高")
        if not c3: reasons.append(f"股价{latest['close']:.0f}<100")
        
        status = "✓ 选中" if (c1 and c2 and c3) else "× 未选中"
        print(f"\n{code} {info['name']}: 收盘{latest['close']:.2f}元")
        print(f"  {status}: {', '.join(reasons) if reasons else '全部满足'}")
        
        if c1 and c2 and c3:
            SELECTED.append({
                'code': code, 
                'name': info['name'], 
                'data': df, 
                'signals': signals
            })
    
    print("-"*70)
    print(f"\n选股结果: 共选中 {len(SELECTED)} 只股票")
    
    # 步骤3: 回测选中股票
    if SELECTED:
        print("\n" + "="*70)
        print("【步骤3】对选中股票执行交易策略回测")
        print("="*70)
        
        for s in SELECTED:
            print(f"\n{'='*60}")
            print(f"  {s['code']} {s['name']}")
            print(f"{'='*60}")
            
            # 显示买入信号
            buys = s['signals'][s['signals']['signal_final'] == 1]
            print(f"\n买入信号: {len(buys)}个")
            for idx, row in buys.iterrows():
                print(f"  {idx.date()}: {row['close']:.2f}元, 涨幅{row.get('pct_change', 0):.2f}%")
            
            # 执行回测
            initial = max(300000, int(s['data']['close'].iloc[-1] * 250))
            engine = BacktestEngineV2(initial_capital=initial)
            engine.run(s['data'], strategy)
            engine.print_summary()
            engine.plot_results(
                save_path=f"strategy_result_{s['code']}.png",
                stock_name=f"{s['code']} {s['name']}"
            )
    else:
        print("\n" + "="*70)
        print("  策略评估")
        print("="*70)
        print("未选中任何股票，策略保持空仓。")
        print("这是正确的策略行为——只在强势突破时入场。")
    
    # 显示所有股票期间表现
    print("\n" + "="*70)
    print("  所有扫描股票期间表现")
    print("="*70)
    print(f"{'代码':<10s} {'名称':<10s} {'收盘价':>10s} {'期间涨跌':>10s} {'是否选中':>10s}")
    print("-"*60)
    
    for code, info in stock_data.items():
        df = info['data']
        change = (df['close'].iloc[-1] / df['close'].iloc[0] - 1) * 100
        selected = '是' if any(s['code']==code for s in SELECTED) else '否'
        print(f"{code:<10s} {info['name']:<10s} {df['close'].iloc[-1]:>10.2f} {change:>10.2f}% {selected:>10s}")
    
    print("="*70)


if __name__ == "__main__":
    import sys
    
    start_date = sys.argv[1] if len(sys.argv) > 1 else "20260401"
    end_date = sys.argv[2] if len(sys.argv) > 2 else "20260511"
    
    run_strategy(start_date, end_date)
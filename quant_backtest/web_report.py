# -*- coding: utf-8 -*-
"""
动量突破策略 - Web报告生成器

生成HTML格式的选股与回测报告
"""

import pandas as pd
import os
from datetime import datetime
from strategy import MomentumBreakthroughStrategy, BacktestEngineV2
from report import generate_html_report
from data_hub import api as hub


def get_stock_data(code, start_date, end_date):
    """获取股票数据 (统一走 data_hub)"""
    df = hub.get_kline(code, start_date, end_date)
    if df is None or df.empty:
        return None
    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.rename(columns={'pctChg': 'pct_change'})
    df = df.set_index('date')
    return df


def run_and_generate_report(start_date="2026-04-01", end_date="2026-05-11"):
    """
    执行选股、回测并生成Web报告
    """
    print("="*70)
    print("  动量突破策略 - Web报告生成")
    print(f"  时间区间: {start_date} 至 {end_date}")
    print("="*70)
    
    # 股票池
    stock_pool = [
        # 科技股
        ('sh.603083', '剑桥科技'), ('sh.688981', '中芯国际'), ('sz.300033', '同花顺'),
        ('sz.002230', '科大讯飞'), ('sz.002415', '海康威视'), ('sz.300750', '宁德时代'),
        # 白酒
        ('sh.600519', '贵州茅台'), ('sz.000858', '五粮液'), ('sz.000568', '泸州老窖'),
        ('sh.600809', '山西汾酒'),
        # 医药
        ('sz.300760', '迈瑞医疗'), ('sh.603259', '药明康德'), ('sh.600276', '恒瑞医药'),
        # 其他
        ('sz.002594', '比亚迪'), ('sh.600309', '万华化学'), ('sz.000333', '美的集团'),
        ('sh.601318', '中国平安'), ('sh.600036', '招商银行'),
    ]
    
    strategy = MomentumBreakthroughStrategy(stop_loss=-0.10)
    results = []
    charts_dir = "charts"
    
    # 创建图表目录
    if not os.path.exists(charts_dir):
        os.makedirs(charts_dir)
    
    print(f"\n【步骤1】扫描 {len(stock_pool)} 只股票...")
    print("-"*70)
    
    for i, (code, name) in enumerate(stock_pool):
        print(f"[{i+1}/{len(stock_pool)}] {code} {name}...", end=" ", flush=True)
        
        df = get_stock_data(code, start_date, end_date)
        
        if df is None:
            print("无数据")
            continue
        
        # 运行策略
        signals = strategy.generate_signals(df)
        buys = signals[signals['signal_final'] == 1]
        
        if len(buys) == 0:
            print("× 无信号")
            continue
        
        latest = signals.iloc[-1]
        
        # 检查股价>100
        if latest['close'] <= 100:
            print(f"× 有信号但股价{latest['close']:.0f}<100")
            continue
        
        # 符合条件！
        print(f"✓ 选中! {len(buys)}个信号")
        
        # 回测
        initial = 300000
        engine = BacktestEngineV2(initial_capital=initial)
        engine.run(df, strategy)
        metrics = engine.calculate_metrics()
        
        # 生成图表
        chart_path = f"{charts_dir}/{code.replace('.', '_')}.png"
        engine.plot_results(save_path=chart_path, stock_name=f"{code} {name}")
        
        # 计算期间涨跌幅
        period_return = (df['close'].iloc[-1] / df['close'].iloc[0] - 1) * 100
        
        # 提取策略收益率数值
        strategy_return = float(metrics.get('总收益率', '0%').replace('%', ''))
        max_dd = float(metrics.get('最大回撤', '0%').replace('%', ''))
        win_rate = float(metrics.get('胜率', '0%').replace('%', ''))
        trades = int(metrics.get('总交易次数', 0))
        
        # 提取买入信号详情
        signal_details = []
        for idx, row in buys.iterrows():
            signal_details.append({
                'date': idx.strftime('%Y-%m-%d'),
                'price': row['close'],
                'pct': row.get('pct_change', 0),
                'limit_up': row.get('prev_limit_up', False) or row.get('today_high_gain', False),
                'high_gain': row.get('today_high_gain', False),
                'new_high': row.get('new_20d_high', False) or row.get('new_all_time_high', False)
            })
        
        results.append({
            'code': code,
            'name': name,
            'period_return': period_return,
            'strategy_return': strategy_return,
            'max_drawdown': max_dd,
            'win_rate': win_rate,
            'trades': trades,
            'signal_count': len(buys),
            'signals': signal_details,
            'chart_path': chart_path,
            'profit': strategy_return
        })
    
    print("-"*70)
    print(f"\n【步骤2】选股结果: 共选中 {len(results)} 只股票")
    
    # 生成HTML报告
    print("\n【步骤3】生成HTML报告...")
    
    report_file = f"strategy_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    generate_html_report(results, title="动量突破策略回测报告", output_file=report_file)
    
    # 打开报告
    print(f"\n{'='*70}")
    print("  报告生成完成!")
    print("="*70)
    print(f"\n  HTML报告: {report_file}")
    print(f"  图表目录: {charts_dir}/")
    print(f"\n  在浏览器中打开 {report_file} 查看完整报告")
    
    # 自动打开浏览器
    try:
        import webbrowser
        webbrowser.open(f"file://{os.path.abspath(report_file)}")
    except:
        pass
    
    return results


if __name__ == "__main__":
    import sys
    
    start = sys.argv[1] if len(sys.argv) > 1 else "2026-04-01"
    end = sys.argv[2] if len(sys.argv) > 2 else "2026-05-11"
    
    run_and_generate_report(start, end)
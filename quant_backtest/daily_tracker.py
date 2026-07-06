# -*- coding: utf-8 -*-
"""
日常选股跟踪系统
- 每天分析并记录选股结果
- 跟踪入选股票的表现
- 生成总览和详情报告
"""
import os
import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant_backtest.data import get_stock_data, get_stock_list
from quant_backtest.strategy import MomentumBreakthroughStrategy

# 初始资金
INITIAL_CAPITAL = 1000000

# 数据存储目录
DATA_DIR = "stock_data"
os.makedirs(DATA_DIR, exist_ok=True)

# 选股记录文件
SELECTIONS_FILE = os.path.join(DATA_DIR, "selections.json")


def load_selections():
    """加载历史选股记录"""
    if os.path.exists(SELECTIONS_FILE):
        with open(SELECTIONS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_selections(selections):
    """保存选股记录"""
    with open(SELECTIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(selections, f, ensure_ascii=False, indent=2)


def scan_market(scan_date, min_price=100):
    """
    扫描市场，返回当天符合条件的股票
    
    Args:
        scan_date: 扫描日期，格式 '20260501'
        min_price: 最低股价筛选
    """
    print(f"正在扫描 {scan_date} 的市场...")
    
    # 获取股票列表
    stock_list = get_stock_list()
    print(f"共 {len(stock_list)} 只股票待扫描")
    
    # 需要更多历史数据来计算指标
    scan_dt = datetime.strptime(scan_date, '%Y%m%d')
    start_date = (scan_dt - timedelta(days=60)).strftime('%Y%m%d')
    
    # 格式化日期用于筛选信号
    scan_pd_date = pd.to_datetime(scan_date)
    
    results = []
    for i, (code, name) in enumerate(stock_list[:1500]):
        try:
            data = get_stock_data(code, start_date, scan_date)
            if data.empty or len(data) < 30:
                continue
            
            # 检查最新股价
            if data['close'].iloc[-1] < min_price:
                continue
            
            # 生成信号
            strategy = MomentumBreakthroughStrategy()
            signals = strategy.generate_signals(data)
            
            # 只取扫描当天的信号
            if scan_date in [d.strftime('%Y%m%d') for d in signals.index]:
                day_signals = signals[signals.index.strftime('%Y%m%d') == scan_date]
                if int(day_signals['signal_final'].sum()) > 0:
                    row = day_signals.iloc[0]
                    results.append({
                        'code': code,
                        'name': name,
                        'price': float(row['close']),
                        'pct_change': float(row.get('pct_change', 0)),
                        'amount': float(row['amount']) if pd.notna(row.get('amount')) else 0.0,
                        'conditions': {
                            'prev_limit_up': bool(row.get('prev_limit_up', False)),
                            'today_high_gain': bool(row.get('today_high_gain', False)),
                            'gap_up_with_gain': bool(row.get('gap_up_with_gain', False)),
                            'new_20d_high': bool(row.get('new_20d_high', False)),
                            'new_all_time_high': bool(row.get('new_all_time_high', False))
                        }
                    })
                    print(f"  发现: {name} ({code}) 价格: {row['close']:.2f}")
        except Exception as e:
            continue
    
    return results


def run_daily_selection(scan_date):
    """执行每日选股并更新记录"""
    selections = load_selections()
    
    # 扫描当天市场
    today_picks = scan_market(scan_date)
    
    # 记录当天选股
    selections[scan_date] = {
        'scan_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'stocks': today_picks
    }
    
    save_selections(selections)
    print(f"\n{scan_date} 选股完成，共 {len(today_picks)} 只股票")
    
    return today_picks


def get_stock_selection_history(code):
    """获取某只股票的入选历史"""
    selections = load_selections()
    dates = []
    for date, data in sorted(selections.items()):
        for stock in data.get('stocks', []):
            if stock['code'] == code:
                dates.append({
                    'date': date,
                    'price': stock['price'],
                    'pct_change': stock['pct_change']
                })
    return dates


def get_multi_day_picks():
    """获取多日入选的股票"""
    selections = load_selections()
    stock_dates = defaultdict(list)
    
    for date, data in sorted(selections.items()):
        for stock in data.get('stocks', []):
            stock_dates[stock['code']].append({
                'date': date,
                'name': stock['name'],
                'price': stock['price']
            })
    
    # 筛选出入选次数>=2的股票
    multi_day = {k: v for k, v in stock_dates.items() if len(v) >= 2}
    return multi_day


def calculate_performance(code, start_date, end_date):
    """计算股票从入选日到当前的表现"""
    data = get_stock_data(code, start_date, end_date)
    if data.empty:
        return None
    
    start_price = data['close'].iloc[0]
    end_price = data['close'].iloc[-1]
    pnl_pct = (end_price - start_price) / start_price * 100
    
    # 计算期间最高价和最大回撤
    high_price = data['high'].max()
    max_drawdown = (data['close'].cummax() - data['close']).max() / data['close'].cummax().max() * 100
    
    return {
        'start_price': start_price,
        'end_price': end_price,
        'high_price': high_price,
        'pnl_pct': pnl_pct,
        'max_drawdown': max_drawdown,
        'data': data
    }


if __name__ == "__main__":
    # 测试：执行5月1日到5月8日的选股
    test_dates = ['20260506', '20260507', '20260508']
    
    for date in test_dates:
        print(f"\n{'='*50}")
        run_daily_selection(date)
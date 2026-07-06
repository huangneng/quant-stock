# -*- coding: utf-8 -*-
"""
日常选股报告生成器 - Bash风格
- 总览页：按日期展示选股结果，多日入选高亮
- 详情页：展示从入选到当前的盈亏
"""
import os
import base64
from datetime import datetime

try:
    import mplfinance as mpf
    import matplotlib.pyplot as plt
    HAS_MPLFINANCE = True
except ImportError:
    HAS_MPLFINANCE = False


def generate_kline_chart(data, buy_date, buy_price, save_path, stock_name):
    """生成K线图，标记买入点"""
    df = data.copy()
    df = df.rename(columns={
        'open': 'Open', 'high': 'High', 
        'low': 'Low', 'close': 'Close', 'volume': 'Volume'
    })
    
    # 均线
    df['MA5'] = df['Close'].rolling(5).mean()
    df['MA20'] = df['Close'].rolling(20).mean()
    
    # Tokyo Night 配色
    mc = mpf.make_marketcolors(
        up='#ef5350', down='#26a69a',
        edge='inherit', wick='inherit',
        volume={'up': '#ef5350', 'down': '#26a69a'}
    )
    style = mpf.make_mpf_style(
        marketcolors=mc,
        gridstyle=':', gridcolor='#3b4261',
        facecolor='#1a1b26', edgecolor='#3b4261',
        figcolor='#1a1b26', rc={'font.size': 9}
    )
    
    addplot = [
        mpf.make_addplot(df['MA5'], color='#7aa2f7', width=1),
        mpf.make_addplot(df['MA20'], color='#e0af68', width=1),
    ]
    
    fig, axes = mpf.plot(
        df, type='candle', style=style,
        title=f'{stock_name}',
        ylabel='价格', ylabel_lower='成交量',
        volume=True, addplot=addplot,
        figsize=(12, 8), returnfig=True
    )
    
    # 标记买入点
    ax = axes[0]
    if buy_date in df.index:
        ax.scatter([buy_date], [buy_price], marker='^', color='#e0af68', 
                   s=200, zorder=5, edgecolors='white', linewidths=2)
        ax.annotate(f'买入 ¥{buy_price:.2f}', (buy_date, buy_price),
                   textcoords="offset points", xytext=(10, 10),
                   fontsize=10, color='#e0af68')
    
    fig.savefig(save_path, dpi=100, bbox_inches='tight', facecolor='#1a1b26')
    plt.close()


def generate_simple_chart(data, buy_date, buy_price, save_path, stock_name):
    """生成简单折线图"""
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei']
    plt.rcParams['axes.unicode_minus'] = False
    
    fig, ax = plt.subplots(figsize=(12, 6), facecolor='#1a1b26')
    ax.set_facecolor('#1a1b26')
    
    ax.plot(data.index, data['close'], color='#c0caf5', linewidth=1.5)
    ax.axhline(y=buy_price, color='#e0af68', linestyle='--', linewidth=1, label=f'买入价 ¥{buy_price:.2f}')
    
    if buy_date in data.index:
        ax.scatter([buy_date], [buy_price], marker='^', color='#e0af68', s=150, zorder=5)
    
    ax.set_title(stock_name, color='#c0caf5', fontsize=14, fontweight='bold')
    ax.legend(loc='upper right', facecolor='#24283b', labelcolor='#c0caf5')
    ax.tick_params(colors='#565f89')
    ax.grid(True, alpha=0.3, color='#3b4261')
    
    for spine in ax.spines.values():
        spine.set_color('#3b4261')
    
    fig.savefig(save_path, dpi=100, bbox_inches='tight', facecolor='#1a1b26')
    plt.close()


def generate_index_page(selections, output_dir):
    """生成总览页"""
    
    # 统计多日入选股票
    stock_count = {}
    stock_first_date = {}
    for date in sorted(selections.keys()):
        for stock in selections[date].get('stocks', []):
            code = stock['code']
            stock_count[code] = stock_count.get(code, 0) + 1
            if code not in stock_first_date:
                stock_first_date[code] = date
    
    multi_day_stocks = {k: v for k, v in stock_count.items() if v >= 2}
    
    # 按日期生成表格
    date_sections = ""
    for date in sorted(selections.keys(), reverse=True):
        data = selections[date]
        stocks = data.get('stocks', [])
        
        if not stocks:
            continue
        
        stock_rows = ""
        for s in stocks:
            code = s['code']
            is_multi = code in multi_day_stocks
            detail_link = f"detail_{code.replace('.', '')}.html"
            
            # 触发条件
            conditions = []
            if s.get('conditions', {}).get('prev_limit_up'):
                conditions.append("昨日涨停")
            if s.get('conditions', {}).get('today_high_gain'):
                conditions.append("涨幅>9.5%")
            if s.get('conditions', {}).get('gap_up_with_gain'):
                conditions.append("跳空高开+涨幅>5%")
            if s.get('conditions', {}).get('new_20d_high'):
                conditions.append("20日新高")
            if s.get('conditions', {}).get('new_all_time_high'):
                conditions.append("历史新高")
            cond_str = ", ".join(conditions) if conditions else "-"
            
            row_class = "stock-row multi-day" if is_multi else "stock-row"
            badge = f'<span class="badge">{multi_day_stocks[code]}日入选</span>' if is_multi else ''
            
            stock_rows += f"""
            <a href="{detail_link}" class="{row_class}">
                <div class="stock-main">
                    <span class="stock-code">{s['code']}</span>
                    <span class="stock-name">{s['name']}</span>
                    {badge}
                </div>
                <div class="stock-price">¥{s['price']:.2f}</div>
                <div class="stock-pct {'positive' if s['pct_change'] > 0 else 'negative'}">{s['pct_change']:+.2f}%</div>
                <div class="stock-cond">{cond_str}</div>
            </a>
            """
        
        date_sections += f"""
        <div class="date-section">
            <div class="date-header">
                <span class="date-label">{date[:4]}-{date[4:6]}-{date[6:8]}</span>
                <span class="date-count">选中 {len(stocks)} 只</span>
            </div>
            <div class="stock-list">
                {stock_rows}
            </div>
        </div>
        """
    
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>动量突破选股系统</title>
    <style>
        :root {{
            --bg-primary: #1a1b26;
            --bg-secondary: #24283b;
            --bg-tertiary: #292e42;
            --text-primary: #c0caf5;
            --text-secondary: #a9b1d6;
            --text-muted: #565f89;
            --green: #9ece6a;
            --red: #f7768e;
            --yellow: #e0af68;
            --blue: #7aa2f7;
            --purple: #bb9af7;
            --border: #3b4261;
        }}
        
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            font-size: 13px;
        }}
        
        .container {{ max-width: 1000px; margin: 0 auto; padding: 20px; }}
        
        .header {{
            border-bottom: 1px solid var(--border);
            padding-bottom: 20px;
            margin-bottom: 30px;
        }}
        
        .header h1 {{
            font-size: 20px;
            font-weight: 600;
            color: var(--text-primary);
            margin-bottom: 8px;
        }}
        
        .header h1::before {{ content: '$ '; color: var(--green); }}
        
        .header .meta {{
            color: var(--text-muted);
            font-size: 12px;
        }}
        
        .summary {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
            margin-bottom: 30px;
        }}
        
        .summary-card {{
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 15px;
        }}
        
        .summary-card .label {{
            color: var(--text-muted);
            font-size: 11px;
            margin-bottom: 5px;
            text-transform: uppercase;
        }}
        
        .summary-card .value {{
            font-size: 24px;
            font-weight: 600;
        }}
        
        .summary-card .value.highlight {{ color: var(--yellow); }}
        
        .date-section {{
            margin-bottom: 25px;
        }}
        
        .date-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 15px;
            background: var(--bg-secondary);
            border-left: 3px solid var(--blue);
            margin-bottom: 10px;
        }}
        
        .date-label {{
            font-weight: 600;
            color: var(--blue);
        }}
        
        .date-count {{
            color: var(--text-muted);
            font-size: 12px;
        }}
        
        .stock-list {{
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}
        
        .stock-row {{
            display: grid;
            grid-template-columns: 2fr 1fr 1fr 2fr;
            align-items: center;
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 12px 15px;
            text-decoration: none;
            color: var(--text-primary);
            transition: all 0.2s;
        }}
        
        .stock-row:hover {{
            background: var(--bg-tertiary);
            border-color: var(--blue);
        }}
        
        .stock-row.multi-day {{
            border-color: var(--yellow);
            background: linear-gradient(90deg, rgba(224, 175, 104, 0.1), transparent);
        }}
        
        .stock-main {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        
        .stock-code {{
            color: var(--blue);
            font-weight: 600;
        }}
        
        .stock-name {{
            color: var(--text-secondary);
        }}
        
        .badge {{
            background: var(--yellow);
            color: var(--bg-primary);
            font-size: 10px;
            padding: 2px 6px;
            border-radius: 3px;
            font-weight: 600;
        }}
        
        .stock-price {{
            color: var(--text-primary);
            font-weight: 500;
        }}
        
        .stock-pct {{
            font-weight: 600;
        }}
        
        .stock-pct.positive {{ color: var(--green); }}
        .stock-pct.negative {{ color: var(--red); }}
        
        .stock-cond {{
            color: var(--text-muted);
            font-size: 11px;
            text-align: right;
        }}
        
        .legend {{
            display: flex;
            gap: 20px;
            margin-bottom: 20px;
            padding: 10px 15px;
            background: var(--bg-secondary);
            border-radius: 6px;
            font-size: 12px;
            color: var(--text-muted);
        }}
        
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        
        .legend-dot {{
            width: 10px;
            height: 10px;
            border-radius: 2px;
        }}
        
        .legend-dot.highlight {{
            background: var(--yellow);
        }}
        
        .footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid var(--border);
            color: var(--text-muted);
            font-size: 11px;
            text-align: center;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>./momentum_breakthrough --daily-scan</h1>
            <div class="meta">初始资金: ¥1,000,000 | 止损: 10% | 策略: 动量突破</div>
        </div>
        
        <div class="summary">
            <div class="summary-card">
                <div class="label">扫描天数</div>
                <div class="value">{len(selections)}</div>
            </div>
            <div class="summary-card">
                <div class="label">累计选股</div>
                <div class="value">{sum(len(s.get('stocks', [])) for s in selections.values())}</div>
            </div>
            <div class="summary-card">
                <div class="label">多日入选</div>
                <div class="value highlight">{len(multi_day_stocks)}</div>
            </div>
            <div class="summary-card">
                <div class="label">更新时间</div>
                <div class="value" style="font-size: 14px;">{datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
            </div>
        </div>
        
        <div class="legend">
            <div class="legend-item">
                <div class="legend-dot highlight"></div>
                <span>多日入选股票（重点关注）</span>
            </div>
        </div>
        
        {date_sections}
        
        <div class="footer">
            动量突破选股系统 | 数据源: baostock | 点击股票查看详情
        </div>
    </div>
</body>
</html>
"""


def generate_detail_page(stock_code, stock_name, history, perf_data, chart_path, output_dir):
    """生成详情页"""
    
    # 入选历史表格
    history_rows = ""
    for h in history:
        history_rows += f"""
        <tr>
            <td>{h['date'][:4]}-{h['date'][4:6]}-{h['date'][6:8]}</td>
            <td>¥{h['price']:.2f}</td>
            <td class="{'positive' if h['pct_change'] > 0 else 'negative'}">{h['pct_change']:+.2f}%</td>
        </tr>
        """
    
    # 图表
    chart_html = ""
    if chart_path and os.path.exists(chart_path):
        with open(chart_path, 'rb') as f:
            img_data = base64.b64encode(f.read()).decode()
        chart_html = f'<img src="data:image/png;base64,{img_data}" style="max-width:100%;border-radius:6px;">'
    
    # 盈亏指标
    pnl_class = "positive" if perf_data and perf_data['pnl_pct'] > 0 else "negative"
    pnl_value = f"{perf_data['pnl_pct']:+.2f}%" if perf_data else "-"
    max_dd = f"{perf_data['max_drawdown']:.2f}%" if perf_data else "-"
    
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{stock_name} - 选股详情</title>
    <style>
        :root {{
            --bg-primary: #1a1b26;
            --bg-secondary: #24283b;
            --bg-tertiary: #292e42;
            --text-primary: #c0caf5;
            --text-secondary: #a9b1d6;
            --text-muted: #565f89;
            --green: #9ece6a;
            --red: #f7768e;
            --yellow: #e0af68;
            --blue: #7aa2f7;
            --border: #3b4261;
        }}
        
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            font-size: 13px;
            padding: 20px;
        }}
        
        .container {{ max-width: 1000px; margin: 0 auto; }}
        
        .nav {{ margin-bottom: 20px; }}
        .nav a {{ color: var(--blue); text-decoration: none; }}
        .nav a:hover {{ text-decoration: underline; }}
        
        .header {{
            border-bottom: 1px solid var(--border);
            padding-bottom: 20px;
            margin-bottom: 25px;
        }}
        
        .header h1 {{ font-size: 22px; font-weight: 600; }}
        .header h1 .code {{ color: var(--blue); font-weight: normal; }}
        
        .metrics {{
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 12px;
            margin-bottom: 25px;
        }}
        
        .metric-card {{
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 15px;
        }}
        
        .metric-card .label {{
            color: var(--text-muted);
            font-size: 10px;
            text-transform: uppercase;
            margin-bottom: 5px;
        }}
        
        .metric-card .value {{
            font-size: 18px;
            font-weight: 600;
        }}
        
        .metric-card .value.positive {{ color: var(--green); }}
        .metric-card .value.negative {{ color: var(--red); }}
        
        .section {{ margin-bottom: 25px; }}
        
        .section-title {{
            color: var(--yellow);
            font-size: 13px;
            margin-bottom: 12px;
            padding-left: 10px;
            border-left: 3px solid var(--yellow);
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 6px;
            overflow: hidden;
        }}
        
        th, td {{
            padding: 10px 15px;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }}
        
        th {{
            background: var(--bg-tertiary);
            color: var(--text-muted);
            font-size: 11px;
            text-transform: uppercase;
        }}
        
        tr:last-child td {{ border-bottom: none; }}
        tr:hover td {{ background: var(--bg-tertiary); }}
        
        .positive {{ color: var(--green); }}
        .negative {{ color: var(--red); }}
        
        .chart-container {{
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 15px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="nav">
            <a href="index.html">← 返回总览</a>
        </div>
        
        <div class="header">
            <h1>{stock_name} <span class="code">{stock_code}</span></h1>
        </div>
        
        <div class="metrics">
            <div class="metric-card">
                <div class="label">入选次数</div>
                <div class="value">{len(history)}</div>
            </div>
            <div class="metric-card">
                <div class="label">首次入选价</div>
                <div class="value">¥{history[0]['price']:.2f}</div>
            </div>
            <div class="metric-card">
                <div class="label">期间收益</div>
                <div class="value {pnl_class}">{pnl_value}</div>
            </div>
            <div class="metric-card">
                <div class="label">最大回撤</div>
                <div class="value negative">{max_dd}</div>
            </div>
            <div class="metric-card">
                <div class="label">持有天数</div>
                <div class="value">{len(perf_data['data']) if perf_data else '-'}</div>
            </div>
        </div>
        
        <div class="section">
            <div class="section-title">// 入选历史</div>
            <table>
                <thead>
                    <tr>
                        <th>入选日期</th>
                        <th>入选价格</th>
                        <th>当日涨跌</th>
                    </tr>
                </thead>
                <tbody>
                    {history_rows}
                </tbody>
            </table>
        </div>
        
        <div class="section">
            <div class="section-title">// K线走势（从首次入选至今）</div>
            <div class="chart-container">
                {chart_html}
            </div>
        </div>
    </div>
</body>
</html>
"""


def generate_full_report(selections, output_dir="report_output"):
    """生成完整报告系统"""
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(f"{output_dir}/charts", exist_ok=True)
    
    # 生成总览页
    index_html = generate_index_page(selections, output_dir)
    with open(f"{output_dir}/index.html", 'w', encoding='utf-8') as f:
        f.write(index_html)
    
    # 统计所有入选股票
    all_stocks = {}
    for date, data in selections.items():
        for stock in data.get('stocks', []):
            code = stock['code']
            if code not in all_stocks:
                all_stocks[code] = {
                    'name': stock['name'],
                    'history': []
                }
            all_stocks[code]['history'].append({
                'date': date,
                'price': stock['price'],
                'pct_change': stock['pct_change']
            })
    
    # 为每只股票生成详情页
    from quant_backtest.daily_tracker import calculate_performance, get_stock_data
    
    for code, info in all_stocks.items():
        history = info['history']
        first_date = history[0]['date']
        last_date = max(h['date'] for h in history)
        
        # 获取最新数据（到今天）
        today = datetime.now().strftime('%Y%m%d')
        
        # 计算表现
        perf = calculate_performance(code, first_date, today)
        
        # 生成图表
        chart_path = f"{output_dir}/charts/{code.replace('.', '')}.png"
        if perf and not perf['data'].empty:
            data = perf['data']
            buy_date = pd.to_datetime(first_date)
            buy_price = history[0]['price']
            
            if HAS_MPLFINANCE:
                generate_kline_chart(data, buy_date, buy_price, chart_path, info['name'])
            else:
                generate_simple_chart(data, buy_date, buy_price, chart_path, info['name'])
        
        # 生成详情页
        detail_html = generate_detail_page(
            code, info['name'], history, perf, chart_path, output_dir
        )
        with open(f"{output_dir}/detail_{code.replace('.', '')}.html", 'w', encoding='utf-8') as f:
            f.write(detail_html)
    
    print(f"报告已生成: {output_dir}/index.html")
    return f"{output_dir}/index.html"

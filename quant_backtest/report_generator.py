# -*- coding: utf-8 -*-
"""
Web报告生成器 - 生成HTML格式的选股与回测报告
"""
import os
from datetime import datetime


def generate_html_report(selected_stocks, results_summary, start_date, end_date, output_path="report.html"):
    """
    生成HTML格式的策略报告
    
    Args:
        selected_stocks: 选中股票列表 [{'code', 'name', 'signals', 'buys', 'metrics'}, ...]
        results_summary: 结果汇总
        start_date: 开始日期
        end_date: 结束日期
        output_path: 输出文件路径
    """
    
    html_template = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>动量突破策略 - 选股与回测报告</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e4e4e4;
            min-height: 100vh;
            padding: 20px;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        
        .header {{
            text-align: center;
            padding: 40px 20px;
            background: linear-gradient(135deg, #0f3460 0%, #16213e 100%);
            border-radius: 16px;
            margin-bottom: 30px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.3);
        }}
        
        .header h1 {{
            font-size: 2.5em;
            color: #00d9ff;
            margin-bottom: 10px;
            text-shadow: 0 0 20px rgba(0,217,255,0.5);
        }}
        
        .header .subtitle {{
            color: #888;
            font-size: 1.1em;
        }}
        
        .date-range {{
            background: #0f3460;
            display: inline-block;
            padding: 8px 20px;
            border-radius: 20px;
            margin-top: 15px;
            color: #00d9ff;
        }}
        
        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        
        .card {{
            background: linear-gradient(135deg, #1e3a5f 0%, #0f3460 100%);
            border-radius: 12px;
            padding: 25px;
            text-align: center;
            box-shadow: 0 5px 20px rgba(0,0,0,0.2);
            transition: transform 0.3s;
        }}
        
        .card:hover {{
            transform: translateY(-5px);
        }}
        
        .card .value {{
            font-size: 2em;
            font-weight: bold;
            color: #00d9ff;
            margin-bottom: 5px;
        }}
        
        .card .label {{
            color: #888;
            font-size: 0.9em;
        }}
        
        .card.profit .value {{
            color: #00ff88;
        }}
        
        .card.loss .value {{
            color: #ff6b6b;
        }}
        
        .strategy-info {{
            background: linear-gradient(135deg, #1e3a5f 0%, #0f3460 100%);
            border-radius: 12px;
            padding: 25px;
            margin-bottom: 30px;
        }}
        
        .strategy-info h2 {{
            color: #00d9ff;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 1px solid #333;
        }}
        
        .condition-list {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 15px;
        }}
        
        .condition {{
            background: rgba(0,0,0,0.2);
            padding: 15px;
            border-radius: 8px;
            border-left: 3px solid #00d9ff;
        }}
        
        .condition-title {{
            color: #00d9ff;
            font-weight: bold;
            margin-bottom: 8px;
        }}
        
        .condition-content {{
            color: #ccc;
            font-size: 0.95em;
            line-height: 1.6;
        }}
        
        .stock-section {{
            margin-bottom: 30px;
        }}
        
        .stock-card {{
            background: linear-gradient(135deg, #1e3a5f 0%, #0f3460 100%);
            border-radius: 16px;
            overflow: hidden;
            margin-bottom: 25px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.3);
        }}
        
        .stock-header {{
            background: linear-gradient(90deg, #0f3460 0%, #1a3a5f 100%);
            padding: 20px 25px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #333;
        }}
        
        .stock-name {{
            font-size: 1.5em;
            font-weight: bold;
        }}
        
        .stock-code {{
            color: #888;
            margin-left: 10px;
        }}
        
        .stock-return {{
            font-size: 1.8em;
            font-weight: bold;
        }}
        
        .stock-return.positive {{
            color: #00ff88;
        }}
        
        .stock-return.negative {{
            color: #ff6b6b;
        }}
        
        .stock-content {{
            padding: 25px;
        }}
        
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 25px;
        }}
        
        .metric {{
            background: rgba(0,0,0,0.2);
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }}
        
        .metric-value {{
            font-size: 1.3em;
            font-weight: bold;
            color: #00d9ff;
        }}
        
        .metric-label {{
            color: #888;
            font-size: 0.85em;
            margin-top: 5px;
        }}
        
        .signals-table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 20px;
        }}
        
        .signals-table th,
        .signals-table td {{
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #333;
        }}
        
        .signals-table th {{
            background: rgba(0,0,0,0.3);
            color: #00d9ff;
            font-weight: 500;
        }}
        
        .signals-table tr:hover {{
            background: rgba(0,217,255,0.1);
        }}
        
        .buy-signal {{
            color: #00ff88;
        }}
        
        .chart-container {{
            background: #0a1628;
            border-radius: 8px;
            padding: 15px;
            text-align: center;
        }}
        
        .chart-container img {{
            max-width: 100%;
            border-radius: 8px;
        }}
        
        .no-signals {{
            background: rgba(255,107,107,0.1);
            border: 1px solid #ff6b6b;
            color: #ff6b6b;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
        }}
        
        .summary-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }}
        
        .summary-table th,
        .summary-table td {{
            padding: 15px;
            text-align: left;
            border-bottom: 1px solid #333;
        }}
        
        .summary-table th {{
            background: #0f3460;
            color: #00d9ff;
        }}
        
        .positive-return {{
            color: #00ff88;
        }}
        
        .negative-return {{
            color: #ff6b6b;
        }}
        
        .footer {{
            text-align: center;
            padding: 30px;
            color: #666;
            margin-top: 40px;
        }}
        
        .footer a {{
            color: #00d9ff;
            text-decoration: none;
        }}
        
        @media (max-width: 768px) {{
            .header h1 {{
                font-size: 1.8em;
            }}
            
            .stock-header {{
                flex-direction: column;
                gap: 15px;
                text-align: center;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>动量突破策略报告</h1>
            <p class="subtitle">选股条件：涨停/大涨突破 + 创新高 + 股价>100元</p>
            <div class="date-range">
                回测区间：{start_date} 至 {end_date}
            </div>
        </div>
        
        <div class="summary-cards">
            <div class="card">
                <div class="value">{len(selected_stocks)}</div>
                <div class="label">选中股票</div>
            </div>
            <div class="card">
                <div class="value">{sum(1 for s in selected_stocks if s.get('is_profit', False))}</div>
                <div class="label">盈利股票</div>
            </div>
            <div class="card">
                <div class="value">{calculate_total_return(selected_stocks)}</div>
                <div class="label">平均收益</div>
            </div>
            <div class="card">
                <div class="value">{sum(s.get('buy_signals', 0) for s in selected_stocks)}</div>
                <div class="label">总买入信号</div>
            </div>
        </div>
        
        <div class="strategy-info">
            <h2>策略说明</h2>
            <div class="condition-list">
                <div class="condition">
                    <div class="condition-title">条件1：动量信号</div>
                    <div class="condition-content">
                        昨日涨停（涨幅≥9.9%）<br>
                        或 今日涨幅>9.5%<br>
                        或 跳空高开且涨幅>5%
                    </div>
                </div>
                <div class="condition">
                    <div class="condition-title">条件2：创新高</div>
                    <div class="condition-content">
                        收盘价创20日新高<br>
                        或 创历史新高
                    </div>
                </div>
                <div class="condition">
                    <div class="condition-title">条件3：股价筛选</div>
                    <div class="condition-content">
                        股价 > 100元
                    </div>
                </div>
                <div class="condition">
                    <div class="condition-title">交易规则</div>
                    <div class="condition-content">
                        买入：当日收盘价买入<br>
                        卖出：触发10%止损
                    </div>
                </div>
            </div>
        </div>
        
        <div class="stock-section">
            <h2 style="color: #00d9ff; margin-bottom: 20px;">选中股票详情</h2>
            {generate_stock_cards(selected_stocks)}
        </div>
        
        <div class="strategy-info">
            <h2>汇总表格</h2>
            <table class="summary-table">
                <thead>
                    <tr>
                        <th>代码</th>
                        <th>名称</th>
                        <th>期间涨幅</th>
                        <th>策略收益</th>
                        <th>最大回撤</th>
                        <th>买入信号</th>
                    </tr>
                </thead>
                <tbody>
                    {generate_summary_rows(selected_stocks)}
                </tbody>
            </table>
        </div>
        
        <div class="footer">
            <p>报告生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
            <p>数据来源：baostock | 策略：动量突破</p>
        </div>
    </div>
</body>
</html>'''
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_template)
    
    print(f"HTML报告已生成: {output_path}")
    return output_path


def calculate_total_return(stocks):
    """计算平均收益"""
    if not stocks:
        return "0%"
    
    returns = []
    for s in stocks:
        ret = s.get('strategy_return', '0%')
        try:
            ret_val = float(ret.replace('%', '').replace('+', ''))
            returns.append(ret_val)
        except:
            pass
    
    if returns:
        avg = sum(returns) / len(returns)
        return f"{avg:+.2f}%"
    return "0%"


def generate_stock_cards(stocks):
    """生成股票卡片HTML"""
    if not stocks:
        return '<div class="no-signals">未找到符合条件的股票</div>'
    
    cards = []
    for s in stocks:
        is_profit = s.get('is_profit', False)
        return_class = 'positive' if is_profit else 'negative'
        return_sign = '+' if is_profit else ''
        
        card = f'''
        <div class="stock-card">
            <div class="stock-header">
                <div>
                    <span class="stock-name">{s.get('name', '')}</span>
                    <span class="stock-code">{s.get('code', '')}</span>
                </div>
                <div class="stock-return {return_class}">
                    {return_sign}{s.get('strategy_return', '0%')}
                </div>
            </div>
            <div class="stock-content">
                <div class="metrics-grid">
                    <div class="metric">
                        <div class="metric-value">{s.get('period_return', '0%')}</div>
                        <div class="metric-label">期间涨幅</div>
                    </div>
                    <div class="metric">
                        <div class="metric-value">{s.get('max_drawdown', '0%')}</div>
                        <div class="metric-label">最大回撤</div>
                    </div>
                    <div class="metric">
                        <div class="metric-value">{s.get('win_rate', '0%')}</div>
                        <div class="metric-label">胜率</div>
                    </div>
                    <div class="metric">
                        <div class="metric-value">{s.get('buy_signals', 0)}</div>
                        <div class="metric-label">买入信号</div>
                    </div>
                    <div class="metric">
                        <div class="metric-value">{s.get('holding_days', '0天')}</div>
                        <div class="metric-label">持仓天数</div>
                    </div>
                    <div class="metric">
                        <div class="metric-value">{s.get('final_capital', '¥0')}</div>
                        <div class="metric-label">最终资金</div>
                    </div>
                </div>
                
                {generate_signals_table(s.get('signals_list', []))}
                
                {generate_chart_section(s.get('chart_path', ''))}
            </div>
        </div>
        '''
        cards.append(card)
    
    return '\n'.join(cards)


def generate_signals_table(signals):
    """生成买入信号表格"""
    if not signals:
        return '<div class="no-signals">无买入信号详情</div>'
    
    rows = []
    for sig in signals:
        rows.append(f'''
        <tr>
            <td>{sig.get('date', '-')}</td>
            <td>{sig.get('close', '-')}</td>
            <td class="buy-signal">{sig.get('pct_change', '-')}</td>
            <td>{sig.get('reason', '-')}</td>
        </tr>
        ''')
    
    return f'''
    <h3 style="color: #00d9ff; margin: 20px 0 15px 0;">买入信号详情</h3>
    <table class="signals-table">
        <thead>
            <tr>
                <th>日期</th>
                <th>收盘价(元)</th>
                <th>涨跌幅</th>
                <th>触发条件</th>
            </tr>
        </thead>
        <tbody>
            {''.join(rows)}
        </tbody>
    </table>
    '''


def generate_chart_section(chart_path):
    """生成图表区域"""
    if not chart_path or not os.path.exists(chart_path):
        return ''
    
    return f'''
    <div class="chart-container">
        <img src="{chart_path}" alt="回测图表">
    </div>
    '''


def generate_summary_rows(stocks):
    """生成汇总表格行"""
    if not stocks:
        return '<tr><td colspan="6" style="text-align:center;">未找到符合条件的股票</td></tr>'
    
    rows = []
    for s in stocks:
        is_profit = s.get('is_profit', False)
        return_class = 'positive-return' if is_profit else 'negative-return'
        
        rows.append(f'''
        <tr>
            <td>{s.get('code', '-')}</td>
            <td>{s.get('name', '-')}</td>
            <td class="{return_class}">{s.get('period_return', '0%')}</td>
            <td class="{return_class}">{s.get('strategy_return', '0%')}</td>
            <td>{s.get('max_drawdown', '0%')}</td>
            <td>{s.get('buy_signals', 0)}</td>
        </tr>
        ''')
    
    return '\n'.join(rows)

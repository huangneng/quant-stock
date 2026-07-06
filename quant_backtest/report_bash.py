# -*- coding: utf-8 -*-
"""
Bash风格Web报告生成器 - 总览+详情页
"""
import os
import json
import base64
from datetime import datetime


def generate_report(results, output_dir="report_output"):
    """生成完整的报告系统"""
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # 生成详情页
    for r in results:
        detail_html = generate_detail_page(r)
        detail_file = f"{output_dir}/detail_{r['code'].replace('.', '')}.html"
        with open(detail_file, 'w', encoding='utf-8') as f:
            f.write(detail_html)
    
    # 生成总览页
    index_html = generate_index_page(results, output_dir)
    index_file = f"{output_dir}/index.html"
    with open(index_file, 'w', encoding='utf-8') as f:
        f.write(index_html)
    
    print(f"报告已生成: {index_file}")
    return index_file


def generate_index_page(results, output_dir):
    """生成总览页"""
    
    # 计算汇总数据
    total_profit = sum(r['strategy_return'] for r in results)
    avg_profit = total_profit / len(results) if results else 0
    win_count = sum(1 for r in results if r['strategy_return'] > 0)
    
    # 股票列表HTML
    stock_rows = ""
    for r in results:
        profit_class = "profit" if r['strategy_return'] > 0 else "loss"
        arrow = "↑" if r['strategy_return'] > 0 else "↓"
        detail_link = f"detail_{r['code'].replace('.', '')}.html"
        
        stock_rows += f"""
        <a href="{detail_link}" class="stock-card">
            <div class="stock-info">
                <span class="stock-code">{r['code']}</span>
                <span class="stock-name">{r['name']}</span>
            </div>
            <div class="stock-metrics">
                <span class="metric">期间: {r['period_return']:+.2f}%</span>
                <span class="metric">策略: {r['strategy_return']:+.2f}%</span>
                <span class="metric">回撤: {r['max_drawdown']:.2f}%</span>
            </div>
            <div class="stock-profit {profit_class}">
                {arrow} {abs(r['strategy_return']):.2f}%
            </div>
        </a>
        """
    
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>策略回测报告</title>
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
            font-family: 'JetBrains Mono', 'Fira Code', 'SF Mono', Consolas, monospace;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            padding: 20px;
            font-size: 14px;
        }}
        
        .container {{ max-width: 1200px; margin: 0 auto; }}
        
        .header {{
            border-bottom: 1px solid var(--border);
            padding-bottom: 20px;
            margin-bottom: 30px;
        }}
        
        .header h1 {{
            font-size: 24px;
            font-weight: 600;
            margin-bottom: 8px;
            color: var(--text-primary);
        }}
        
        .header .meta {{
            color: var(--text-muted);
            font-size: 12px;
        }}
        
        .summary {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin-bottom: 30px;
        }}
        
        .summary-card {{
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 20px;
        }}
        
        .summary-card .label {{
            color: var(--text-muted);
            font-size: 12px;
            margin-bottom: 8px;
            text-transform: uppercase;
        }}
        
        .summary-card .value {{
            font-size: 28px;
            font-weight: 600;
        }}
        
        .summary-card .value.profit {{ color: var(--green); }}
        .summary-card .value.loss {{ color: var(--red); }}
        
        .section-title {{
            color: var(--yellow);
            font-size: 14px;
            margin-bottom: 15px;
            padding-left: 10px;
            border-left: 3px solid var(--yellow);
        }}
        
        .stock-card {{
            display: flex;
            align-items: center;
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 15px 20px;
            margin-bottom: 10px;
            text-decoration: none;
            color: var(--text-primary);
            transition: background 0.2s;
        }}
        
        .stock-card:hover {{
            background: var(--bg-tertiary);
            border-color: var(--blue);
        }}
        
        .stock-info {{
            flex: 1;
        }}
        
        .stock-code {{
            color: var(--blue);
            font-weight: 600;
        }}
        
        .stock-name {{
            color: var(--text-secondary);
            margin-left: 10px;
        }}
        
        .stock-metrics {{
            display: flex;
            gap: 20px;
            margin-right: 30px;
        }}
        
        .stock-metrics .metric {{
            color: var(--text-muted);
            font-size: 12px;
        }}
        
        .stock-profit {{
            font-size: 18px;
            font-weight: 600;
            min-width: 100px;
            text-align: right;
        }}
        
        .stock-profit.profit {{ color: var(--green); }}
        .stock-profit.loss {{ color: var(--red); }}
        
        .footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid var(--border);
            color: var(--text-muted);
            font-size: 12px;
            text-align: center;
        }}
        
        @media (max-width: 768px) {{
            .summary {{ grid-template-columns: repeat(2, 1fr); }}
            .stock-metrics {{ display: none; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>$ ./strategy_backtest --report</h1>
            <div class="meta">时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 初始资金: ¥1,000,000 | 止损: 10%</div>
        </div>
        
        <div class="summary">
            <div class="summary-card">
                <div class="label">选中股票</div>
                <div class="value">{len(results)}</div>
            </div>
            <div class="summary-card">
                <div class="label">盈利股票</div>
                <div class="value profit">{win_count}</div>
            </div>
            <div class="summary-card">
                <div class="label">总收益</div>
                <div class="value {'profit' if total_profit > 0 else 'loss'}">{total_profit:+.2f}%</div>
            </div>
            <div class="summary-card">
                <div class="label">平均收益</div>
                <div class="value {'profit' if avg_profit > 0 else 'loss'}">{avg_profit:+.2f}%</div>
            </div>
        </div>
        
        <div class="section-title">// 股票列表 (点击查看详情)</div>
        
        {stock_rows}
        
        <div class="footer">
            动量突破策略回测系统 | 数据源: baostock
        </div>
    </div>
</body>
</html>
"""


def generate_detail_page(r):
    """生成详情页"""
    
    # 买入信号表格
    signal_rows = ""
    for sig in r.get('signals', []):
        conditions = []
        if sig.get('limit_up'):
            conditions.append("涨停")
        if sig.get('high_gain'):
            conditions.append("涨幅>9.5%")
        if sig.get('new_high'):
            conditions.append("创新高")
        
        signal_rows += f"""
        <tr>
            <td>{sig.get('date', '')}</td>
            <td>¥{sig.get('price', 0):.2f}</td>
            <td>{sig.get('pct', 0):+.2f}%</td>
            <td>{', '.join(conditions) if conditions else '-'}</td>
        </tr>
        """
    
    # 图表嵌入
    chart_html = ""
    if r.get('chart_path') and os.path.exists(r.get('chart_path', '')):
        with open(r['chart_path'], 'rb') as f:
            img_data = base64.b64encode(f.read()).decode()
        chart_html = f'<img src="data:image/png;base64,{img_data}" style="max-width:100%;border-radius:6px;">'
    
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{r['name']} - 回测详情</title>
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
            font-family: 'JetBrains Mono', 'Fira Code', 'SF Mono', Consolas, monospace;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            padding: 20px;
            font-size: 14px;
        }}
        
        .container {{ max-width: 1200px; margin: 0 auto; }}
        
        .nav {{
            margin-bottom: 20px;
        }}
        
        .nav a {{
            color: var(--blue);
            text-decoration: none;
        }}
        
        .nav a:hover {{ text-decoration: underline; }}
        
        .header {{
            border-bottom: 1px solid var(--border);
            padding-bottom: 20px;
            margin-bottom: 30px;
        }}
        
        .header h1 {{
            font-size: 24px;
            font-weight: 600;
            margin-bottom: 8px;
        }}
        
        .header .code {{
            color: var(--blue);
            font-weight: normal;
        }}
        
        .metrics {{
            display: grid;
            grid-template-columns: repeat(6, 1fr);
            gap: 15px;
            margin-bottom: 30px;
        }}
        
        .metric-card {{
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 15px;
        }}
        
        .metric-card .label {{
            color: var(--text-muted);
            font-size: 11px;
            margin-bottom: 5px;
            text-transform: uppercase;
        }}
        
        .metric-card .value {{
            font-size: 20px;
            font-weight: 600;
        }}
        
        .metric-card .value.profit {{ color: var(--green); }}
        .metric-card .value.loss {{ color: var(--red); }}
        
        .section {{
            margin-bottom: 30px;
        }}
        
        .section-title {{
            color: var(--yellow);
            font-size: 14px;
            margin-bottom: 15px;
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
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }}
        
        th {{
            background: var(--bg-tertiary);
            color: var(--text-muted);
            font-weight: 600;
            font-size: 12px;
            text-transform: uppercase;
        }}
        
        tr:last-child td {{ border-bottom: none; }}
        
        tr:hover td {{ background: var(--bg-tertiary); }}
        
        .chart-container {{
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 20px;
        }}
        
        @media (max-width: 768px) {{
            .metrics {{ grid-template-columns: repeat(3, 1fr); }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="nav">
            <a href="index.html">← 返回总览</a>
        </div>
        
        <div class="header">
            <h1>{r['name']} <span class="code">{r['code']}</span></h1>
        </div>
        
        <div class="metrics">
            <div class="metric-card">
                <div class="label">期间涨跌</div>
                <div class="value {'profit' if r['period_return'] > 0 else 'loss'}">{r['period_return']:+.2f}%</div>
            </div>
            <div class="metric-card">
                <div class="label">策略收益</div>
                <div class="value {'profit' if r['strategy_return'] > 0 else 'loss'}">{r['strategy_return']:+.2f}%</div>
            </div>
            <div class="metric-card">
                <div class="label">最大回撤</div>
                <div class="value loss">{r['max_drawdown']:.2f}%</div>
            </div>
            <div class="metric-card">
                <div class="label">胜率</div>
                <div class="value">{r['win_rate']:.1f}%</div>
            </div>
            <div class="metric-card">
                <div class="label">交易次数</div>
                <div class="value">{r['trades']}</div>
            </div>
            <div class="metric-card">
                <div class="label">买入信号</div>
                <div class="value">{r['signal_count']}</div>
            </div>
        </div>
        
        <div class="section">
            <div class="section-title">// 买入信号</div>
            <table>
                <thead>
                    <tr>
                        <th>日期</th>
                        <th>价格</th>
                        <th>涨跌幅</th>
                        <th>触发条件</th>
                    </tr>
                </thead>
                <tbody>
                    {signal_rows}
                </tbody>
            </table>
        </div>
        
        <div class="section">
            <div class="section-title">// 回测图表</div>
            <div class="chart-container">
                {chart_html}
            </div>
        </div>
    </div>
</body>
</html>
"""

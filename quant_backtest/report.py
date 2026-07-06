# -*- coding: utf-8 -*-
"""
HTML报告生成器 - 将回测结果输出为Web页面
"""
import os
import base64
from datetime import datetime


def generate_html_report(results, title="动量突破策略回测报告", output_file="report.html"):
    """
    生成HTML报告
    
    Args:
        results: 回测结果列表，每个元素包含 code, name, signals, trades, metrics, chart_path
        title: 报告标题
        output_file: 输出文件名
    """
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        
        .header {{
            background: white;
            border-radius: 16px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
        }}
        
        .header h1 {{
            color: #1a1a2e;
            font-size: 28px;
            margin-bottom: 10px;
        }}
        
        .header .meta {{
            color: #666;
            font-size: 14px;
        }}
        
        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }}
        
        .card {{
            background: white;
            border-radius: 16px;
            padding: 25px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
        }}
        
        .card h3 {{
            color: #666;
            font-size: 14px;
            margin-bottom: 10px;
            text-transform: uppercase;
        }}
        
        .card .value {{
            font-size: 32px;
            font-weight: bold;
            color: #1a1a2e;
        }}
        
        .card .value.positive {{
            color: #10b981;
        }}
        
        .card .value.negative {{
            color: #ef4444;
        }}
        
        .stock-section {{
            background: white;
            border-radius: 16px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
        }}
        
        .stock-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 2px solid #f0f0f0;
        }}
        
        .stock-header h2 {{
            color: #1a1a2e;
            font-size: 24px;
        }}
        
        .stock-header .code {{
            background: #667eea;
            color: white;
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 14px;
        }}
        
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 25px;
        }}
        
        .metric {{
            background: #f8fafc;
            padding: 15px;
            border-radius: 10px;
        }}
        
        .metric-label {{
            color: #666;
            font-size: 12px;
            margin-bottom: 5px;
        }}
        
        .metric-value {{
            font-size: 20px;
            font-weight: bold;
            color: #1a1a2e;
        }}
        
        .metric-value.positive {{
            color: #10b981;
        }}
        
        .metric-value.negative {{
            color: #ef4444;
        }}
        
        .signals-table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 25px;
        }}
        
        .signals-table th,
        .signals-table td {{
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #f0f0f0;
        }}
        
        .signals-table th {{
            background: #f8fafc;
            color: #666;
            font-weight: 600;
            font-size: 13px;
            text-transform: uppercase;
        }}
        
        .signals-table td {{
            color: #1a1a2e;
        }}
        
        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 500;
        }}
        
        .badge.buy {{
            background: #dcfce7;
            color: #166534;
        }}
        
        .badge.sell {{
            background: #fee2e2;
            color: #991b1b;
        }}
        
        .badge.limit-up {{
            background: #fef3c7;
            color: #92400e;
        }}
        
        .chart-container {{
            background: #f8fafc;
            border-radius: 12px;
            padding: 20px;
            text-align: center;
        }}
        
        .chart-container img {{
            max-width: 100%;
            height: auto;
            border-radius: 8px;
        }}
        
        .footer {{
            text-align: center;
            padding: 20px;
            color: rgba(255,255,255,0.8);
            font-size: 14px;
        }}
        
        @media (max-width: 768px) {{
            .summary-cards {{
                grid-template-columns: repeat(2, 1fr);
            }}
            
            .metrics-grid {{
                grid-template-columns: repeat(2, 1fr);
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 {title}</h1>
            <div class="meta">
                生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} | 
                选股策略: 动量突破 | 
                止损比例: 10%
            </div>
        </div>
        
        <div class="summary-cards">
            <div class="card">
                <h3>选中股票</h3>
                <div class="value">{len(results)}</div>
            </div>
            <div class="card">
                <h3>盈利股票</h3>
                <div class="value positive">{sum(1 for r in results if r.get('profit', 0) > 0)}</div>
            </div>
            <div class="card">
                <h3>最大收益</h3>
                <div class="value positive">{max([r.get('strategy_return', 0) for r in results] + [0]):.1f}%</div>
            </div>
            <div class="card">
                <h3>平均收益</h3>
                <div class="value">{sum([r.get('strategy_return', 0) for r in results]) / len(results) if results else 0:.1f}%</div>
            </div>
        </div>
"""

    # 添加每只股票的详情
    for r in results:
        profit = r.get('strategy_return', 0)
        profit_class = 'positive' if profit > 0 else 'negative' if profit < 0 else ''
        
        html += f"""
        <div class="stock-section">
            <div class="stock-header">
                <h2>{r.get('name', '未知')}</h2>
                <span class="code">{r.get('code', '')}</span>
            </div>
            
            <div class="metrics-grid">
                <div class="metric">
                    <div class="metric-label">期间涨跌</div>
                    <div class="metric-value {profit_class}">{r.get('period_return', 0):+.2f}%</div>
                </div>
                <div class="metric">
                    <div class="metric-label">策略收益</div>
                    <div class="metric-value {profit_class}">{r.get('strategy_return', 0):+.2f}%</div>
                </div>
                <div class="metric">
                    <div class="metric-label">最大回撤</div>
                    <div class="metric-value negative">{r.get('max_drawdown', 0):.2f}%</div>
                </div>
                <div class="metric">
                    <div class="metric-label">交易次数</div>
                    <div class="metric-value">{r.get('trades', 0)}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">胜率</div>
                    <div class="metric-value">{r.get('win_rate', 0):.1f}%</div>
                </div>
                <div class="metric">
                    <div class="metric-label">买入信号</div>
                    <div class="metric-value">{r.get('signal_count', 0)}个</div>
                </div>
            </div>
            
            <h3 style="margin-bottom: 15px; color: #1a1a2e;">买入信号详情</h3>
            <table class="signals-table">
                <thead>
                    <tr>
                        <th>日期</th>
                        <th>价格</th>
                        <th>涨跌幅</th>
                        <th>触发条件</th>
                    </tr>
                </thead>
                <tbody>
"""
        
        for sig in r.get('signals', []):
            conditions = []
            if sig.get('limit_up'):
                conditions.append('<span class="badge limit-up">涨停</span>')
            if sig.get('high_gain'):
                conditions.append('<span class="badge limit-up">大涨>9.5%</span>')
            if sig.get('new_high'):
                conditions.append('<span class="badge buy">创新高</span>')
            
            html += f"""
                    <tr>
                        <td>{sig.get('date', '')}</td>
                        <td>{sig.get('price', 0):.2f}元</td>
                        <td>{sig.get('pct', 0):+.2f}%</td>
                        <td>{' '.join(conditions) if conditions else '-'}</td>
                    </tr>
"""
        
        html += """
                </tbody>
            </table>
"""
        
        # 添加图表
        if r.get('chart_path') and os.path.exists(r.get('chart_path', '')):
            with open(r['chart_path'], 'rb') as f:
                img_data = base64.b64encode(f.read()).decode()
            html += f"""
            <div class="chart-container">
                <img src="data:image/png;base64,{img_data}" alt="{r.get('name', '')} 回测图表">
            </div>
"""
        
        html += """
        </div>
"""

    html += """
        <div class="footer">
            动量突破策略回测报告 | 自动生成
        </div>
    </div>
</body>
</html>
"""
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"报告已生成: {output_file}")
    return output_file

# -*- coding: utf-8 -*-
"""
HTML报告生成器 - 将回测结果输出为Web页面
"""
import os
from datetime import datetime

def generate_html_report(results, start_date, end_date, output_path="report.html"):
    """
    生成HTML报告
    
    Args:
        results: 回测结果列表
        start_date: 开始日期
        end_date: 结束日期
        output_path: 输出文件路径
    """
    
    html_template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>动量突破策略 - 回测报告</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            color: #e0e0e0;
            padding: 20px;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        
        .header {
            text-align: center;
            padding: 40px 20px;
            background: rgba(255,255,255,0.05);
            border-radius: 20px;
            margin-bottom: 30px;
        }
        
        .header h1 {
            font-size: 2.5em;
            background: linear-gradient(90deg, #00d9ff, #00ff88);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 15px;
        }
        
        .header .subtitle {
            color: #888;
            font-size: 1.1em;
        }
        
        .header .date-range {
            margin-top: 10px;
            padding: 8px 20px;
            background: rgba(0,217,255,0.1);
            border-radius: 20px;
            display: inline-block;
        }
        
        .summary-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .card {
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
            padding: 25px;
            text-align: center;
            border: 1px solid rgba(255,255,255,0.1);
            transition: transform 0.3s, box-shadow 0.3s;
        }
        
        .card:hover {
            transform: translateY(-5px);
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        }
        
        .card .value {
            font-size: 2.2em;
            font-weight: bold;
            margin: 10px 0;
        }
        
        .card .label {
            color: #888;
            font-size: 0.9em;
        }
        
        .card.profit .value {
            color: #00ff88;
        }
        
        .card.loss .value {
            color: #ff6b6b;
        }
        
        .card.neutral .value {
            color: #00d9ff;
        }
        
        .strategy-info {
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
            padding: 30px;
            margin-bottom: 30px;
        }
        
        .strategy-info h2 {
            color: #00d9ff;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        
        .strategy-conditions {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
        }
        
        .condition {
            background: rgba(0,0,0,0.2);
            padding: 20px;
            border-radius: 10px;
            border-left: 3px solid #00d9ff;
        }
        
        .condition h3 {
            color: #00d9ff;
            margin-bottom: 10px;
            font-size: 1em;
        }
        
        .condition ul {
            list-style: none;
            padding-left: 10px;
        }
        
        .condition li {
            padding: 5px 0;
            color: #ccc;
        }
        
        .condition li::before {
            content: "• ";
            color: #00ff88;
        }
        
        .results-table {
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
            padding: 30px;
            margin-bottom: 30px;
            overflow-x: auto;
        }
        
        .results-table h2 {
            color: #00d9ff;
            margin-bottom: 20px;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.95em;
        }
        
        th, td {
            padding: 15px 12px;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        
        th {
            background: rgba(0,217,255,0.1);
            color: #00d9ff;
            font-weight: 600;
            white-space: nowrap;
        }
        
        tr:hover {
            background: rgba(255,255,255,0.05);
        }
        
        .profit-value {
            color: #00ff88;
            font-weight: bold;
        }
        
        .loss-value {
            color: #ff6b6b;
            font-weight: bold;
        }
        
        .stock-detail {
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
            padding: 30px;
            margin-bottom: 30px;
        }
        
        .stock-detail h2 {
            color: #00d9ff;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .stock-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            flex-wrap: wrap;
            gap: 15px;
        }
        
        .stock-name {
            font-size: 1.5em;
            color: #fff;
        }
        
        .stock-code {
            color: #888;
            font-size: 0.9em;
        }
        
        .stock-metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        
        .metric {
            background: rgba(0,0,0,0.2);
            padding: 15px;
            border-radius: 10px;
            text-align: center;
        }
        
        .metric .value {
            font-size: 1.3em;
            font-weight: bold;
            margin-bottom: 5px;
        }
        
        .metric .label {
            color: #888;
            font-size: 0.85em;
        }
        
        .signals-list {
            background: rgba(0,0,0,0.2);
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
        }
        
        .signals-list h3 {
            color: #00d9ff;
            margin-bottom: 15px;
        }
        
        .signal-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 15px;
            background: rgba(255,255,255,0.03);
            border-radius: 8px;
            margin-bottom: 8px;
            flex-wrap: wrap;
            gap: 10px;
        }
        
        .signal-date {
            color: #888;
        }
        
        .signal-price {
            color: #00ff88;
            font-weight: bold;
        }
        
        .signal-change {
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.85em;
        }
        
        .signal-change.positive {
            background: rgba(0,255,136,0.2);
            color: #00ff88;
        }
        
        .signal-change.negative {
            background: rgba(255,107,107,0.2);
            color: #ff6b6b;
        }
        
        .chart-container {
            background: rgba(0,0,0,0.2);
            border-radius: 10px;
            padding: 20px;
            text-align: center;
        }
        
        .chart-container img {
            max-width: 100%;
            border-radius: 10px;
        }
        
        .chart-placeholder {
            padding: 60px;
            color: #666;
            font-style: italic;
        }
        
        .footer {
            text-align: center;
            padding: 30px;
            color: #666;
            font-size: 0.9em;
        }
        
        .footer a {
            color: #00d9ff;
            text-decoration: none;
        }
        
        @media (max-width: 768px) {
            .header h1 {
                font-size: 1.8em;
            }
            
            .card .value {
                font-size: 1.8em;
            }
            
            th, td {
                padding: 10px 8px;
                font-size: 0.85em;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>动量突破策略回测报告</h1>
            <p class="subtitle">Momentum Breakthrough Strategy Backtest Report</p>
            <p class="date-range">回测区间: {start_date} 至 {end_date}</p>
        </div>
        
        <div class="summary-cards">
            {summary_cards}
        </div>
        
        <div class="strategy-info">
            <h2>策略说明</h2>
            <div class="strategy-conditions">
                <div class="condition">
                    <h3>选股条件</h3>
                    <ul>
                        <li>昨日涨停 (涨幅≥9.9%)</li>
                        <li>或今日涨幅 > 9.5%</li>
                        <li>或跳空高开且涨幅 > 5%</li>
                    </ul>
                </div>
                <div class="condition">
                    <h3>创新高条件</h3>
                    <ul>
                        <li>收盘价创20日新高</li>
                        <li>或收盘价创历史新高</li>
                    </ul>
                </div>
                <div class="condition">
                    <h3>价格条件</h3>
                    <ul>
                        <li>股价 > 100元</li>
                    </ul>
                </div>
                <div class="condition">
                    <h3>交易规则</h3>
                    <ul>
                        <li>买入: 当日收盘价买入</li>
                        <li>卖出: 触发10%止损</li>
                    </ul>
                </div>
            </div>
        </div>
        
        <div class="results-table">
            <h2>选股结果汇总</h2>
            {results_table}
        </div>
        
        {stock_details}
        
        <div class="footer">
            <p>报告生成时间: {generated_time}</p>
            <p>数据来源: baostock | 策略: 动量突破策略</p>
        </div>
    </div>
</body>
</html>
"""
    
    # 计算汇总数据
    total_stocks = len(results)
    profit_stocks = len([r for r in results if r.get('strategy_return_num', 0) > 0])
    total_return = sum([r.get('strategy_return_num', 0) for r in results]) / max(total_stocks, 1)
    
    # 生成汇总卡片
    summary_cards = f"""
        <div class="card neutral">
            <div class="label">选中股票</div>
            <div class="value">{total_stocks}</div>
        </div>
        <div class="card profit">
            <div class="label">盈利股票</div>
            <div class="value">{profit_stocks}</div>
        </div>
        <div class="card {'profit' if total_return > 0 else 'loss'}">
            <div class="label">平均收益</div>
            <div class="value">{total_return:+.2f}%</div>
        </div>
        <div class="card neutral">
            <div class="label">胜率</div>
            <div class="value">{profit_stocks/total_stocks*100 if total_stocks > 0 else 0:.1f}%</div>
        </div>
    """
    
    # 生成结果表格
    table_rows = ""
    for r in results:
        ret_class = 'profit-value' if r.get('strategy_return_num', 0) > 0 else 'loss-value'
        period_class = 'profit-value' if r.get('period_return', 0) > 0 else 'loss-value'
        
        table_rows += f"""
            <tr>
                <td>{r.get('code', '')}</td>
                <td>{r.get('name', '')}</td>
                <td class="{period_class}">{r.get('period_return', 0):+.2f}%</td>
                <td class="{ret_class}">{r.get('strategy_return', '0%')}</td>
                <td>{r.get('max_drawdown', '0%')}</td>
                <td>{r.get('trades', 0)}</td>
                <td>{r.get('win_rate', '0%')}</td>
            </tr>
        """
    
    results_table = f"""
        <table>
            <thead>
                <tr>
                    <th>股票代码</th>
                    <th>股票名称</th>
                    <th>期间涨幅</th>
                    <th>策略收益</th>
                    <th>最大回撤</th>
                    <th>交易次数</th>
                    <th>胜率</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
    """
    
    # 生成股票详情
    stock_details = ""
    for r in results:
        # 买入信号列表
        signals_html = ""
        for sig in r.get('signals', []):
            change_class = 'positive' if sig.get('change', 0) >= 0 else 'negative'
            signals_html += f"""
                <div class="signal-item">
                    <span class="signal-date">{sig.get('date', '')}</span>
                    <span class="signal-price">¥{sig.get('price', 0):.2f}</span>
                    <span class="signal-change {change_class}">{sig.get('change', 0):+.2f}%</span>
                </div>
            """
        
        # 图表
        chart_path = r.get('chart_path', '')
        if chart_path and os.path.exists(chart_path):
            chart_html = f'<img src="{chart_path}" alt="{r.get("name", "")} 回测图表">'
        else:
            chart_html = '<p class="chart-placeholder">图表文件未生成</p>'
        
        ret_class = 'profit' if r.get('strategy_return_num', 0) > 0 else 'loss'
        
        stock_details += f"""
        <div class="stock-detail">
            <h2>
                <span>{r.get('name', '')}</span>
                <span class="stock-code">{r.get('code', '')}</span>
            </h2>
            
            <div class="stock-metrics">
                <div class="metric">
                    <div class="value profit-value">{r.get('period_return', 0):+.2f}%</div>
                    <div class="label">期间涨幅</div>
                </div>
                <div class="metric">
                    <div class="value {ret_class}">{r.get('strategy_return', '0%')}</div>
                    <div class="label">策略收益</div>
                </div>
                <div class="metric">
                    <div class="value">{r.get('max_drawdown', '0%')}</div>
                    <div class="label">最大回撤</div>
                </div>
                <div class="metric">
                    <div class="value">{r.get('final_capital', '¥0')}</div>
                    <div class="label">最终资金</div>
                </div>
            </div>
            
            <div class="signals-list">
                <h3>买入信号 ({len(r.get('signals', []))}个)</h3>
                {signals_html}
            </div>
            
            <div class="chart-container">
                <h3>回测图表</h3>
                {chart_html}
            </div>
        </div>
        """
    
    # 填充模板
    html_content = html_template.format(
        start_date=start_date,
        end_date=end_date,
        summary_cards=summary_cards,
        results_table=results_table,
        stock_details=stock_details,
        generated_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    
    # 写入文件
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"HTML报告已生成: {output_path}")
    return output_path

# -*- coding: utf-8 -*-
"""
动量突破策略 - 程序员风格Web报告生成器

特点：
- Bash配色风格 (深色背景 + 绿色文字)
- 总览页 + 详情页结构
- K线图展示
- 简洁无干扰
"""

import os
import base64
from datetime import datetime


def generate_kline_html(open_data, high_data, low_data, close_data, dates, trades, container_id, height=400):
    """
    生成K线图的HTML/JS代码 (使用echarts)
    """
    # 准备数据
    kline_data = []
    for i in range(len(dates)):
        kline_data.append([
            open_data[i],
            close_data[i],
            low_data[i],
            high_data[i]
        ])
    
    # 准备买卖点标记
    markers = []
    for t in trades:
        if 'BUY' in t['type']:
            markers.append({
                'name': '买入',
                'coord': [t['date'].strftime('%Y-%m-%d'), t['price']],
                'value': f"买入 {t['price']:.2f}",
                'itemStyle': {'color': '#22c55e'}
            })
        else:
            markers.append({
                'name': '卖出', 
                'coord': [t['date'].strftime('%Y-%m-%d'), t['price']],
                'value': f"卖出 {t['price']:.2f}",
                'itemStyle': {'color': '#ef4444'}
            })
    
    dates_str = [d.strftime('%Y-%m-%d') for d in dates]
    
    html = f"""
    <div id="{container_id}" style="width: 100%; height: {height}px;"></div>
    <script>
        var chart_{container_id} = echarts.init(document.getElementById('{container_id}'));
        var option = {{
            backgroundColor: 'transparent',
            animation: false,
            tooltip: {{
                trigger: 'axis',
                axisPointer: {{ type: 'cross' }},
                backgroundColor: '#1e1e1e',
                borderColor: '#303030',
                textStyle: {{ color: '#d4d4d4' }},
                formatter: function(params) {{
                    var kline = params[0];
                    return kline.name + '<br/>' +
                        '开: ' + kline.data[1].toFixed(2) + '<br/>' +
                        '收: ' + kline.data[2].toFixed(2) + '<br/>' +
                        '低: ' + kline.data[3].toFixed(2) + '<br/>' +
                        '高: ' + kline.data[4].toFixed(2);
                }}
            }},
            axisPointer: {{
                link: [{{xAxisIndex: 'all'}}]
            }},
            grid: [
                {{ left: '8%', right: '3%', top: '5%', height: '60%' }},
                {{ left: '8%', right: '3%', top: '75%', height: '15%' }}
            ],
            xAxis: [
                {{
                    type: 'category',
                    data: {dates_str},
                    boundaryGap: false,
                    axisLine: {{ lineStyle: {{ color: '#303030' }} }},
                    axisLabel: {{ color: '#6b7280', fontSize: 10 }},
                    splitLine: {{ show: false }}
                }},
                {{
                    type: 'category',
                    gridIndex: 1,
                    data: {dates_str},
                    boundaryGap: false,
                    axisLine: {{ lineStyle: {{ color: '#303030' }} }},
                    axisLabel: {{ show: false }},
                    splitLine: {{ show: false }}
                }}
            ],
            yAxis: [
                {{
                    scale: true,
                    axisLine: {{ lineStyle: {{ color: '#303030' }} }},
                    axisLabel: {{ color: '#6b7280', fontSize: 10 }},
                    splitLine: {{ lineStyle: {{ color: '#262626' }} }}
                }},
                {{
                    scale: true,
                    gridIndex: 1,
                    splitNumber: 2,
                    axisLine: {{ lineStyle: {{ color: '#303030' }} }},
                    axisLabel: {{ show: false }},
                    splitLine: {{ show: false }}
                }}
            ],
            dataZoom: [
                {{
                    type: 'inside',
                    xAxisIndex: [0, 1],
                    start: 0,
                    end: 100
                }}
            ],
            series: [
                {{
                    name: 'K线',
                    type: 'candlestick',
                    data: {kline_data},
                    itemStyle: {{
                        color: '#22c55e',
                        color0: '#ef4444',
                        borderColor: '#22c55e',
                        borderColor0: '#ef4444'
                    }},
                    markPoint: {{
                        symbol: 'pin',
                        symbolSize: 40,
                        data: {markers}
                    }}
                }}
            ]
        }};
        chart_{container_id}.setOption(option);
    </script>
    """
    return html


def generate_index_page(results, output_file="index.html"):
    """
    生成总览页
    """
    # 计算汇总数据
    total_selected = len(results)
    total_profit = sum(r['strategy_return'] for r in results)
    avg_profit = total_profit / total_selected if total_selected > 0 else 0
    win_count = sum(1 for r in results if r['strategy_return'] > 0)
    win_rate = win_count / total_selected * 100 if total_selected > 0 else 0
    max_return = max((r['strategy_return'] for r in results), default=0)
    max_drawdown = min((r['max_drawdown'] for r in results), default=0)
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>动量突破策略 - 总览</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Code', monospace;
            background: #0d1117;
            color: #c9d1d9;
            min-height: 100vh;
            padding: 24px;
            font-size: 14px;
            line-height: 1.6;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        
        /* 终端风格的头部 */
        .terminal-header {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 16px 20px;
            margin-bottom: 20px;
        }}
        
        .terminal-header .prompt {{
            color: #58a6ff;
        }}
        
        .terminal-header .command {{
            color: #7ee787;
        }}
        
        .terminal-header .time {{
            color: #6e7681;
            float: right;
        }}
        
        /* 统计卡片 */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        
        .stat-card {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 16px;
        }}
        
        .stat-card .label {{
            color: #6e7681;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        .stat-card .value {{
            font-size: 24px;
            font-weight: 600;
            margin-top: 4px;
        }}
        
        .stat-card .value.green {{ color: #7ee787; }}
        .stat-card .value.red {{ color: #f85149; }}
        .stat-card .value.blue {{ color: #58a6ff; }}
        .stat-card .value.yellow {{ color: #d29922; }}
        
        /* 股票列表 */
        .stock-list {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            overflow: hidden;
        }}
        
        .stock-list-header {{
            background: #21262d;
            padding: 12px 16px;
            border-bottom: 1px solid #30363d;
            font-weight: 600;
        }}
        
        .stock-item {{
            display: grid;
            grid-template-columns: 100px 120px 1fr 100px 100px 80px;
            align-items: center;
            padding: 14px 16px;
            border-bottom: 1px solid #21262d;
            cursor: pointer;
            transition: background 0.15s;
            text-decoration: none;
            color: inherit;
        }}
        
        .stock-item:hover {{
            background: #21262d;
        }}
        
        .stock-item:last-child {{
            border-bottom: none;
        }}
        
        .stock-code {{
            color: #58a6ff;
            font-weight: 500;
        }}
        
        .stock-name {{
            color: #c9d1d9;
        }}
        
        .stock-signals {{
            color: #6e7681;
            font-size: 12px;
        }}
        
        .stock-return {{
            font-weight: 600;
        }}
        
        .stock-return.green {{ color: #7ee787; }}
        .stock-return.red {{ color: #f85149; }}
        
        .view-btn {{
            color: #6e7681;
            text-align: right;
        }}
        
        .view-btn:after {{
            content: ' →';
            color: #30363d;
        }}
        
        /* 表格头 */
        .list-header {{
            display: grid;
            grid-template-columns: 100px 120px 1fr 100px 100px 80px;
            padding: 10px 16px;
            background: #0d1117;
            color: #6e7681;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        /* 底部 */
        .footer {{
            text-align: center;
            padding: 30px;
            color: #484f58;
            font-size: 12px;
        }}
        
        /* 响应式 */
        @media (max-width: 768px) {{
            .stats-grid {{
                grid-template-columns: repeat(2, 1fr);
            }}
            .stock-item, .list-header {{
                grid-template-columns: 80px 1fr 80px;
            }}
            .stock-signals, .stock-drawdown {{
                display: none;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- 终端风格头部 -->
        <div class="terminal-header">
            <span class="prompt">$</span>
            <span class="command"> momentum_strategy --scan --backtest --capital=1000000</span>
            <span class="time">{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</span>
        </div>
        
        <!-- 统计卡片 -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="label">选中股票</div>
                <div class="value blue">{total_selected}</div>
            </div>
            <div class="stat-card">
                <div class="label">盈利股票</div>
                <div class="value green">{win_count} ({win_rate:.0f}%)</div>
            </div>
            <div class="stat-card">
                <div class="label">平均收益</div>
                <div class="value {'green' if avg_profit > 0 else 'red'}">{avg_profit:+.2f}%</div>
            </div>
            <div class="stat-card">
                <div class="label">最大收益</div>
                <div class="value green">{max_return:+.2f}%</div>
            </div>
            <div class="stat-card">
                <div class="label">最大回撤</div>
                <div class="value red">{max_drawdown:.2f}%</div>
            </div>
            <div class="stat-card">
                <div class="label">初始资金</div>
                <div class="value yellow">¥100万</div>
            </div>
        </div>
        
        <!-- 股票列表 -->
        <div class="stock-list">
            <div class="stock-list-header">选股结果</div>
            <div class="list-header">
                <span>代码</span>
                <span>名称</span>
                <span>买入信号</span>
                <span>收益率</span>
                <span>最大回撤</span>
                <span style="text-align:right">详情</span>
            </div>
"""
    
    for r in results:
        return_color = 'green' if r['strategy_return'] > 0 else 'red'
        signals_str = ', '.join([s['date'][-5:] for s in r['signals'][:3]])  # 只显示前3个
        if len(r['signals']) > 3:
            signals_str += f' +{len(r["signals"])-3}'
        
        html += f"""
            <a href="detail_{r['code'].replace('.', '')}.html" class="stock-item">
                <span class="stock-code">{r['code']}</span>
                <span class="stock-name">{r['name']}</span>
                <span class="stock-signals">{signals_str}</span>
                <span class="stock-return {return_color}">{r['strategy_return']:+.2f}%</span>
                <span class="stock-drawdown">{r['max_drawdown']:.2f}%</span>
                <span class="view-btn">查看</span>
            </a>
"""
    
    html += """
        </div>
        
        <div class="footer">
            动量突破策略 | 条件: 涨停/大涨>9.5% + 创新高 + 股价>100 | 止损: 10%
        </div>
    </div>
</body>
</html>
"""
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)
    
    return output_file


def generate_detail_page(result, output_file):
    """
    生成详情页
    """
    code = result['code']
    name = result['name']
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{name} ({code}) - 详情</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Code', monospace;
            background: #0d1117;
            color: #c9d1d9;
            min-height: 100vh;
            padding: 24px;
            font-size: 14px;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        
        /* 导航 */
        .nav {{
            margin-bottom: 20px;
        }}
        
        .nav a {{
            color: #58a6ff;
            text-decoration: none;
        }}
        
        .nav a:hover {{
            text-decoration: underline;
        }}
        
        /* 终端头部 */
        .terminal-header {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 16px 20px;
            margin-bottom: 20px;
        }}
        
        .stock-title {{
            font-size: 20px;
            font-weight: 600;
            margin-bottom: 4px;
        }}
        
        .stock-code {{
            color: #58a6ff;
        }}
        
        .stock-period {{
            color: #6e7681;
            font-size: 12px;
        }}
        
        /* 指标网格 */
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 12px;
            margin-bottom: 24px;
        }}
        
        .metric {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 12px;
        }}
        
        .metric-label {{
            color: #6e7681;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        .metric-value {{
            font-size: 18px;
            font-weight: 600;
            margin-top: 2px;
        }}
        
        .metric-value.green {{ color: #7ee787; }}
        .metric-value.red {{ color: #f85149; }}
        .metric-value.blue {{ color: #58a6ff; }}
        
        /* 图表区域 */
        .chart-section {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 20px;
            margin-bottom: 24px;
        }}
        
        .chart-title {{
            color: #6e7681;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 16px;
        }}
        
        .chart-container {{
            width: 100%;
            height: 450px;
        }}
        
        /* 信号表格 */
        .signals-section {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            overflow: hidden;
        }}
        
        .signals-header {{
            background: #21262d;
            padding: 12px 16px;
            border-bottom: 1px solid #30363d;
            font-weight: 600;
        }}
        
        .signal-row {{
            display: grid;
            grid-template-columns: 100px 100px 100px 1fr;
            padding: 12px 16px;
            border-bottom: 1px solid #21262d;
            align-items: center;
        }}
        
        .signal-row:last-child {{
            border-bottom: none;
        }}
        
        .signal-date {{
            color: #58a6ff;
        }}
        
        .signal-price {{
            color: #c9d1d9;
        }}
        
        .signal-pct {{
            font-weight: 500;
        }}
        
        .signal-pct.green {{ color: #7ee787; }}
        .signal-pct.red {{ color: #f85149; }}
        
        .signal-tags {{
            text-align: right;
        }}
        
        .tag {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 3px;
            font-size: 11px;
            margin-left: 4px;
        }}
        
        .tag.limit-up {{
            background: #f8514920;
            color: #f85149;
            border: 1px solid #f8514940;
        }}
        
        .tag.high-gain {{
            background: #d2992220;
            color: #d29922;
            border: 1px solid #d2992240;
        }}
        
        .tag.new-high {{
            background: #7ee78720;
            color: #7ee787;
            border: 1px solid #7ee78740;
        }}
        
        .table-header {{
            display: grid;
            grid-template-columns: 100px 100px 100px 1fr;
            padding: 10px 16px;
            background: #0d1117;
            color: #6e7681;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- 导航 -->
        <div class="nav">
            <a href="index.html">← 返回总览</a>
        </div>
        
        <!-- 头部 -->
        <div class="terminal-header">
            <div class="stock-title">
                <span class="stock-code">{code}</span> {name}
            </div>
            <div class="stock-period">回测区间: 2026-04-01 至 2026-05-11 | 初始资金: ¥1,000,000</div>
        </div>
        
        <!-- 指标 -->
        <div class="metrics-grid">
            <div class="metric">
                <div class="metric-label">期间涨跌</div>
                <div class="metric-value {'green' if result['period_return'] > 0 else 'red'}">{result['period_return']:+.2f}%</div>
            </div>
            <div class="metric">
                <div class="metric-label">策略收益</div>
                <div class="metric-value {'green' if result['strategy_return'] > 0 else 'red'}">{result['strategy_return']:+.2f}%</div>
            </div>
            <div class="metric">
                <div class="metric-label">最大回撤</div>
                <div class="metric-value red">{result['max_drawdown']:.2f}%</div>
            </div>
            <div class="metric">
                <div class="metric-label">胜率</div>
                <div class="metric-value blue">{result['win_rate']:.0f}%</div>
            </div>
            <div class="metric">
                <div class="metric-label">交易次数</div>
                <div class="metric-value">{result['trades']}次</div>
            </div>
            <div class="metric">
                <div class="metric-label">买入信号</div>
                <div class="metric-value blue">{result['signal_count']}个</div>
            </div>
        </div>
        
        <!-- K线图 -->
        <div class="chart-section">
            <div class="chart-title">K线图与交易信号</div>
            <div id="kline" class="chart-container"></div>
        </div>
        
        <!-- 买入信号表格 -->
        <div class="signals-section">
            <div class="signals-header">买入信号详情</div>
            <div class="table-header">
                <span>日期</span>
                <span>价格</span>
                <span>涨跌幅</span>
                <span style="text-align:right">触发条件</span>
            </div>
"""
    
    for sig in result['signals']:
        tags = []
        pct_class = 'green' if sig['pct'] > 0 else 'red'
        
        if sig.get('limit_up'):
            tags.append('<span class="tag limit-up">涨停</span>')
        if sig.get('high_gain') and not sig.get('limit_up'):
            tags.append('<span class="tag high-gain">大涨>9.5%</span>')
        if sig.get('new_high'):
            tags.append('<span class="tag new-high">创新高</span>')
        
        html += f"""
            <div class="signal-row">
                <span class="signal-date">{sig['date']}</span>
                <span class="signal-price">{sig['price']:.2f}</span>
                <span class="signal-pct {pct_class}">{sig['pct']:+.2f}%</span>
                <div class="signal-tags">{(' '.join(tags)) if tags else '-'}</div>
            </div>
"""
    
    html += """
        </div>
    </div>
"""
    
    # K线图数据
    if result.get('chart_data'):
        cd = result['chart_data']
        html += f"""
    <script>
        var chart = echarts.init(document.getElementById('kline'));
        var option = {{
            backgroundColor: 'transparent',
            animation: false,
            tooltip: {{
                trigger: 'axis',
                axisPointer: {{ type: 'cross' }},
                backgroundColor: '#1e1e1e',
                borderColor: '#303030',
                textStyle: {{ color: '#d4d4d4' }},
                formatter: function(params) {{
                    if (params[0]) {{
                        var kline = params[0];
                        return kline.name + '<br/>' +
                            '开: ' + kline.data[1].toFixed(2) + '<br/>' +
                            '收: ' + kline.data[2].toFixed(2) + '<br/>' +
                            '低: ' + kline.data[3].toFixed(2) + '<br/>' +
                            '高: ' + kline.data[4].toFixed(2);
                    }}
                    return '';
                }}
            }},
            grid: {{ left: '8%', right: '3%', top: '8%', bottom: '12%' }},
            xAxis: {{
                type: 'category',
                data: {cd['dates']},
                axisLine: {{ lineStyle: {{ color: '#303030' }} }},
                axisLabel: {{ color: '#6b7280', fontSize: 10 }},
                splitLine: {{ show: false }}
            }},
            yAxis: {{
                scale: true,
                axisLine: {{ lineStyle: {{ color: '#303030' }} }},
                axisLabel: {{ color: '#6b7280', fontSize: 10 }},
                splitLine: {{ lineStyle: {{ color: '#262626' }} }}
            }},
            dataZoom: [
                {{ type: 'inside', start: 0, end: 100 }}
            ],
            series: [{{
                name: 'K线',
                type: 'candlestick',
                data: {cd['kline']},
                itemStyle: {{
                    color: '#22c55e',
                    color0: '#ef4444',
                    borderColor: '#22c55e',
                    borderColor0: '#ef4444'
                }},
                markPoint: {{
                    symbol: 'pin',
                    symbolSize: 40,
                    label: {{ color: '#fff', fontSize: 10 }},
                    data: {cd['markers']}
                }}
            }}]
        }};
        chart.setOption(option);
        window.addEventListener('resize', function() {{ chart.resize(); }});
    </script>
"""
    
    html += """
</body>
</html>
"""
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)
    
    return output_file
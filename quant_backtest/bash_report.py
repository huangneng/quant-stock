# -*- coding: utf-8 -*-
"""
程序员风格HTML报告生成器 - Bash配色主题
支持总览页+详情页，使用K线图
"""
import os
import base64
import json
from datetime import datetime


def generate_bash_style_report(results, output_dir="report_output"):
    """
    生成程序员风格的HTML报告
    
    Args:
        results: 回测结果列表
        output_dir: 输出目录
    """
    
    # 创建输出目录
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # ========== 生成总览页 ==========
    index_html = generate_index_page(results)
    with open(f"{output_dir}/index.html", 'w', encoding='utf-8') as f:
        f.write(index_html)
    
    # ========== 生成各股票详情页 ==========
    for r in results:
        detail_html = generate_detail_page(r)
        filename = f"{output_dir}/{r['code'].replace('.', '_')}.html"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(detail_html)
    
    # 复制图表到输出目录
    for r in results:
        if r.get('chart_path') and os.path.exists(r['chart_path']):
            import shutil
            dest = f"{output_dir}/{os.path.basename(r['chart_path'])}"
            shutil.copy(r['chart_path'], dest)
    
    print(f"报告已生成: {output_dir}/index.html")
    return f"{output_dir}/index.html"


def generate_index_page(results):
    """生成总览页"""
    
    # 计算汇总数据
    total_profit = sum(r['strategy_return'] for r in results)
    avg_profit = total_profit / len(results) if results else 0
    win_count = sum(1 for r in results if r['strategy_return'] > 0)
    win_rate = win_count / len(results) * 100 if results else 0
    
    # 生成股票列表
    stock_rows = ""
    for r in results:
        profit_class = "profit" if r['strategy_return'] >= 0 else "loss"
        arrow = "↑" if r['strategy_return'] >= 0 else "↓"
        
        stock_rows += f"""
    <tr class="stock-row" onclick="location.href='{r['code'].replace('.', '_')}.html'">
      <td class="code">{r['code'].split('.')[1]}</td>
      <td class="name">{r['name']}</td>
      <td class="number">{r['period_return']:+.2f}%</td>
      <td class="number {profit_class}">{arrow} {abs(r['strategy_return']):.2f}%</td>
      <td class="number">{r['max_drawdown']:.2f}%</td>
      <td class="number">{r['signal_count']}</td>
      <td class="arrow">→</td>
    </tr>"""
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>动量突破策略 - 总览</title>
  <style>
    * {{
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }}
    
    body {{
      font-family: 'SF Mono', 'Monaco', 'Menlo', 'Consolas', monospace;
      background: #1a1b26;
      color: #a9b1d6;
      min-height: 100vh;
      padding: 20px;
      font-size: 14px;
      line-height: 1.6;
    }}
    
    .container {{
      max-width: 1200px;
      margin: 0 auto;
    }}
    
    /* 终端风格头部 */
    .terminal-header {{
      background: #24283b;
      border-radius: 8px 8px 0 0;
      padding: 12px 16px;
      border: 1px solid #414868;
      border-bottom: none;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    
    .terminal-dots {{
      display: flex;
      gap: 6px;
    }}
    
    .terminal-dots span {{
      width: 12px;
      height: 12px;
      border-radius: 50%;
    }}
    
    .dot-red {{ background: #f7768e; }}
    .dot-yellow {{ background: #e0af68; }}
    .dot-green {{ background: #9ece6a; }}
    
    .terminal-title {{
      flex: 1;
      text-align: center;
      color: #565f89;
      font-size: 13px;
    }}
    
    .terminal-body {{
      background: #16161e;
      border: 1px solid #414868;
      border-radius: 0 0 8px 8px;
      padding: 20px;
      margin-bottom: 20px;
    }}
    
    /* 命令提示符风格 */
    .prompt {{
      color: #9ece6a;
      font-weight: bold;
    }}
    
    .command {{
      color: #7aa2f7;
    }}
    
    .output {{
      color: #a9b1d6;
      margin-left: 20px;
    }}
    
    /* 统计卡片 */
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 16px;
      margin-bottom: 24px;
    }}
    
    .stat-card {{
      background: #24283b;
      border: 1px solid #414868;
      border-radius: 6px;
      padding: 16px;
    }}
    
    .stat-label {{
      color: #565f89;
      font-size: 12px;
      text-transform: uppercase;
      margin-bottom: 8px;
    }}
    
    .stat-value {{
      font-size: 24px;
      font-weight: bold;
      color: #c0caf5;
    }}
    
    .stat-value.profit {{ color: #9ece6a; }}
    .stat-value.loss {{ color: #f7768e; }}
    
    /* 表格 */
    .table-container {{
      background: #16161e;
      border: 1px solid #414868;
      border-radius: 6px;
      overflow: hidden;
    }}
    
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    
    th {{
      background: #24283b;
      color: #565f89;
      font-size: 12px;
      text-transform: uppercase;
      text-align: left;
      padding: 12px 16px;
      border-bottom: 1px solid #414868;
    }}
    
    td {{
      padding: 14px 16px;
      border-bottom: 1px solid #24283b;
    }}
    
    .stock-row {{
      cursor: pointer;
      transition: background 0.15s;
    }}
    
    .stock-row:hover {{
      background: #24283b;
    }}
    
    .code {{
      color: #7aa2f7;
      font-weight: 500;
    }}
    
    .name {{
      color: #c0caf5;
    }}
    
    .number {{
      font-family: 'SF Mono', Monaco, monospace;
    }}
    
    .profit {{ color: #9ece6a; }}
    .loss {{ color: #f7768e; }}
    
    .arrow {{
      color: #565f89;
      text-align: right;
    }}
    
    /* 信息区 */
    .info-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 0;
      border-top: 1px solid #414868;
      margin-top: 20px;
    }}
    
    .info-item {{
      display: flex;
      align-items: center;
      gap: 8px;
      color: #565f89;
      font-size: 12px;
    }}
    
    .tag {{
      background: #34548a;
      color: #7aa2f7;
      padding: 2px 8px;
      border-radius: 3px;
      font-size: 11px;
    }}
    
    /* 响应式 */
    @media (max-width: 768px) {{
      .stats-grid {{
        grid-template-columns: repeat(2, 1fr);
      }}
    }}
  </style>
</head>
<body>
  <div class="container">
    
    <!-- 终端风格头部 -->
    <div class="terminal-header">
      <div class="terminal-dots">
        <span class="dot-red"></span>
        <span class="dot-yellow"></span>
        <span class="dot-green"></span>
      </div>
      <div class="terminal-title">momentum-breakthrough-strategy — zsh</div>
    </div>
    
    <div class="terminal-body">
      <p><span class="prompt">❯</span> <span class="command">./run_strategy.py</span> --start 2026-04-01 --end 2026-05-11</p>
      <p class="output" style="margin-top: 12px;">扫描完成，共发现 <span class="profit">{len(results)}</span> 只符合条件的股票</p>
    </div>
    
    <!-- 统计概览 -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">选中股票</div>
        <div class="stat-value">{len(results)}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">盈利股票</div>
        <div class="stat-value profit">{win_count}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">胜率</div>
        <div class="stat-value">{win_rate:.1f}%</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">平均收益</div>
        <div class="stat-value {'profit' if avg_profit >= 0 else 'loss'}">{avg_profit:+.2f}%</div>
      </div>
    </div>
    
    <!-- 股票列表 -->
    <div class="table-container">
      <table>
        <thead>
          <tr>
            <th>代码</th>
            <th>名称</th>
            <th>期间涨跌</th>
            <th>策略收益</th>
            <th>最大回撤</th>
            <th>信号数</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {stock_rows}
        </tbody>
      </table>
    </div>
    
    <!-- 底部信息 -->
    <div class="info-bar">
      <div class="info-item">
        <span class="tag">初始资金</span>
        <span>¥1,000,000</span>
      </div>
      <div class="info-item">
        <span class="tag">止损</span>
        <span>-10%</span>
      </div>
      <div class="info-item">
        <span class="tag">策略</span>
        <span>动量突破</span>
      </div>
      <div class="info-item">
        {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
      </div>
    </div>
    
  </div>
</body>
</html>"""
    
    return html


def generate_detail_page(r):
    """生成详情页"""
    
    profit_class = "profit" if r['strategy_return'] >= 0 else "loss"
    arrow = "↑" if r['strategy_return'] >= 0 else "↓"
    
    # 买入信号表格
    signal_rows = ""
    for sig in r.get('signals', []):
        conditions = []
        if sig.get('limit_up'):
            conditions.append('<span class="tag tag-yellow">涨停</span>')
        if sig.get('high_gain'):
            conditions.append('<span class="tag tag-yellow">大涨</span>')
        if sig.get('new_high'):
            conditions.append('<span class="tag tag-green">创新高</span>')
        
        signal_rows += f"""
        <tr>
          <td class="number">{sig['date']}</td>
          <td class="number">¥{sig['price']:.2f}</td>
          <td class="number {'profit' if sig['pct'] >= 0 else 'loss'}">{sig['pct']:+.2f}%</td>
          <td>{' '.join(conditions) if conditions else '-'}</td>
        </tr>"""
    
    # 图表路径
    chart_filename = os.path.basename(r['chart_path']) if r.get('chart_path') else ""
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{r['name']} - 详情</title>
  <style>
    * {{
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }}
    
    body {{
      font-family: 'SF Mono', 'Monaco', 'Menlo', 'Consolas', monospace;
      background: #1a1b26;
      color: #a9b1d6;
      min-height: 100vh;
      padding: 20px;
      font-size: 14px;
    }}
    
    .container {{
      max-width: 1200px;
      margin: 0 auto;
    }}
    
    /* 导航 */
    .nav {{
      display: flex;
      align-items: center;
      gap: 16px;
      margin-bottom: 20px;
      padding: 12px 16px;
      background: #24283b;
      border-radius: 6px;
      border: 1px solid #414868;
    }}
    
    .nav a {{
      color: #565f89;
      text-decoration: none;
      font-size: 13px;
      transition: color 0.15s;
    }}
    
    .nav a:hover {{
      color: #7aa2f7;
    }}
    
    .nav-sep {{
      color: #414868;
    }}
    
    .nav-current {{
      color: #c0caf5;
      font-weight: 500;
    }}
    
    /* 终端头部 */
    .terminal-header {{
      background: #24283b;
      border-radius: 8px 8px 0 0;
      padding: 12px 16px;
      border: 1px solid #414868;
      border-bottom: none;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    
    .terminal-dots {{
      display: flex;
      gap: 6px;
    }}
    
    .terminal-dots span {{
      width: 12px;
      height: 12px;
      border-radius: 50%;
    }}
    
    .dot-red {{ background: #f7768e; }}
    .dot-yellow {{ background: #e0af68; }}
    .dot-green {{ background: #9ece6a; }}
    
    .terminal-title {{
      flex: 1;
      text-align: center;
      color: #565f89;
      font-size: 13px;
    }}
    
    .terminal-body {{
      background: #16161e;
      border: 1px solid #414868;
      border-radius: 0 0 8px 8px;
      padding: 20px;
      margin-bottom: 20px;
    }}
    
    .prompt {{
      color: #9ece6a;
      font-weight: bold;
    }}
    
    .command {{
      color: #7aa2f7;
    }}
    
    /* 头部信息 */
    .stock-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 24px;
    }}
    
    .stock-info h1 {{
      font-size: 28px;
      color: #c0caf5;
      margin-bottom: 8px;
    }}
    
    .stock-code {{
      color: #7aa2f7;
      font-size: 14px;
    }}
    
    .main-profit {{
      text-align: right;
    }}
    
    .main-profit .label {{
      color: #565f89;
      font-size: 12px;
      text-transform: uppercase;
    }}
    
    .main-profit .value {{
      font-size: 36px;
      font-weight: bold;
    }}
    
    .profit {{ color: #9ece6a; }}
    .loss {{ color: #f7768e; }}
    
    /* 指标网格 */
    .metrics-grid {{
      display: grid;
      grid-template-columns: repeat(6, 1fr);
      gap: 12px;
      margin-bottom: 24px;
    }}
    
    .metric {{
      background: #24283b;
      border: 1px solid #414868;
      border-radius: 6px;
      padding: 14px;
      text-align: center;
    }}
    
    .metric-label {{
      color: #565f89;
      font-size: 11px;
      text-transform: uppercase;
      margin-bottom: 6px;
    }}
    
    .metric-value {{
      font-size: 18px;
      font-weight: 500;
      color: #c0caf5;
    }}
    
    /* 两列布局 */
    .two-col {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
      margin-bottom: 20px;
    }}
    
    /* 表格 */
    .section-title {{
      color: #565f89;
      font-size: 12px;
      text-transform: uppercase;
      margin-bottom: 12px;
      padding-left: 8px;
      border-left: 2px solid #7aa2f7;
    }}
    
    .table-container {{
      background: #16161e;
      border: 1px solid #414868;
      border-radius: 6px;
      overflow: hidden;
    }}
    
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    
    th {{
      background: #24283b;
      color: #565f89;
      font-size: 11px;
      text-transform: uppercase;
      text-align: left;
      padding: 10px 14px;
      border-bottom: 1px solid #414868;
    }}
    
    td {{
      padding: 12px 14px;
      border-bottom: 1px solid #24283b;
    }}
    
    tr:last-child td {{
      border-bottom: none;
    }}
    
    .number {{
      font-family: 'SF Mono', Monaco, monospace;
    }}
    
    .tag {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 3px;
      font-size: 11px;
      margin-right: 4px;
    }}
    
    .tag-yellow {{
      background: #3d4759;
      color: #e0af68;
    }}
    
    .tag-green {{
      background: #2a4038;
      color: #9ece6a;
    }}
    
    /* 图表 */
    .chart-container {{
      background: #16161e;
      border: 1px solid #414868;
      border-radius: 6px;
      padding: 16px;
      text-align: center;
    }}
    
    .chart-container img {{
      max-width: 100%;
      height: auto;
      border-radius: 4px;
    }}
    
    /* K线图容器 */
    #kline-chart {{
      height: 400px;
      background: #16161e;
      border-radius: 6px;
    }}
    
    /* 响应式 */
    @media (max-width: 768px) {{
      .two-col {{
        grid-template-columns: 1fr;
      }}
      .metrics-grid {{
        grid-template-columns: repeat(3, 1fr);
      }}
    }}
  </style>
</head>
<body>
  <div class="container">
    
    <!-- 导航 -->
    <div class="nav">
      <a href="index.html">← 返回总览</a>
      <span class="nav-sep">|</span>
      <span class="nav-current">{r['name']}</span>
    </div>
    
    <!-- 终端风格头部 -->
    <div class="terminal-header">
      <div class="terminal-dots">
        <span class="dot-red"></span>
        <span class="dot-yellow"></span>
        <span class="dot-green"></span>
      </div>
      <div class="terminal-title">{r['code']} {r['name']} — 回测详情</div>
    </div>
    
    <div class="terminal-body">
      
      <!-- 股票头部 -->
      <div class="stock-header">
        <div class="stock-info">
          <h1>{r['name']}</h1>
          <div class="stock-code">{r['code']}</div>
        </div>
        <div class="main-profit">
          <div class="label">策略收益</div>
          <div class="value {profit_class}">{arrow} {abs(r['strategy_return']):.2f}%</div>
        </div>
      </div>
      
      <!-- 指标 -->
      <div class="metrics-grid">
        <div class="metric">
          <div class="metric-label">期间涨跌</div>
          <div class="metric-value {'profit' if r['period_return'] >= 0 else 'loss'}">{r['period_return']:+.2f}%</div>
        </div>
        <div class="metric">
          <div class="metric-label">最大回撤</div>
          <div class="metric-value loss">{r['max_drawdown']:.2f}%</div>
        </div>
        <div class="metric">
          <div class="metric-label">胜率</div>
          <div class="metric-value">{r['win_rate']:.1f}%</div>
        </div>
        <div class="metric">
          <div class="metric-label">交易次数</div>
          <div class="metric-value">{r['trades']}</div>
        </div>
        <div class="metric">
          <div class="metric-label">买入信号</div>
          <div class="metric-value">{r['signal_count']}</div>
        </div>
        <div class="metric">
          <div class="metric-label">初始资金</div>
          <div class="metric-value">¥100万</div>
        </div>
      </div>
      
      <!-- K线图 -->
      <div class="section-title">K线图</div>
      <div class="chart-container">
        <div id="kline-chart"></div>
      </div>
      
      <!-- 买入信号 -->
      <div class="section-title" style="margin-top: 24px;">买入信号</div>
      <div class="table-container">
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
      
    </div>
    
  </div>
  
  <!-- ECharts K线图 -->
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
  <script>
    // K线图数据（从后端注入）
    var klineData = {json.dumps(r.get('kline_data', []))};
    var buySignals = {json.dumps(r.get('signals', []))};
    
    if (klineData.length > 0) {{
      var chart = echarts.init(document.getElementById('kline-chart'));
      
      var option = {{
        backgroundColor: '#16161e',
        tooltip: {{
          trigger: 'axis',
          backgroundColor: '#24283b',
          borderColor: '#414868',
          textStyle: {{ color: '#a9b1d6' }},
          axisPointer: {{ type: 'cross' }}
        }},
        legend: {{
          data: ['K线', '买入'],
          textStyle: {{ color: '#565f89' }},
          top: 10
        }},
        grid: {{
          left: '10%',
          right: '10%',
          top: '15%',
          bottom: '10%'
        }},
        xAxis: {{
          type: 'category',
          data: klineData.map(d => d[0]),
          axisLine: {{ lineStyle: {{ color: '#414868' }} }},
          axisLabel: {{ color: '#565f89' }}
        }},
        yAxis: {{
          type: 'value',
          scale: true,
          axisLine: {{ lineStyle: {{ color: '#414868' }} }},
          axisLabel: {{ color: '#565f89' }},
          splitLine: {{ lineStyle: {{ color: '#24283b' }} }}
        }},
        dataZoom: [
          {{ type: 'inside', start: 50, end: 100 }},
          {{ type: 'slider', start: 50, end: 100, textStyle: {{ color: '#565f89' }} }}
        ],
        series: [
          {{
            name: 'K线',
            type: 'candlestick',
            data: klineData.map(d => [d[1], d[2], d[3], d[4]]),
            itemStyle: {{
              color: '#9ece6a',
              color0: '#f7768e',
              borderColor: '#9ece6a',
              borderColor0: '#f7768e'
            }}
          }},
          {{
            name: '买入',
            type: 'scatter',
            data: buySignals.map(s => {{
              var idx = klineData.findIndex(d => d[0] === s.date);
              return [idx, s.price];
            }}),
            symbol: 'triangle',
            symbolSize: 15,
            itemStyle: {{ color: '#e0af68' }}
          }}
        ]
      }};
      
      chart.setOption(option);
    }}
  </script>
</body>
</html>"""
    
    return html


if __name__ == "__main__":
    print("报告生成器模块")

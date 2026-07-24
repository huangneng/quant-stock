# -*- coding: utf-8 -*-
"""
选股跟踪系统报告生成器
- 总览页：按日期显示选股，多日入选高亮
- 详情页：从入选日到当前的盈亏
"""
import os
import json
import base64
import pandas as pd
from datetime import datetime
from urllib.parse import quote

try:
    import mplfinance as mpf
    import matplotlib.pyplot as plt
    HAS_MPLFINANCE = True
except ImportError:
    HAS_MPLFINANCE = False

from quant_backtest.daily_tracker import (
    load_selections, get_multi_day_picks
)

try:
    from stock_research.recommender import score as rec_score
    HAS_RECOMMENDER = True
except Exception:
    HAS_RECOMMENDER = False

DATA_DIR = "stock_data"
OUTPUT_DIR = "tracker_report"


def _compute_rec_features(code, entry_date):
    """计算 recommender 所需的 9 个入选当日特征。失败返回 None。"""
    try:
        import numpy as np
        from data_hub import api as hub
        entry_dt = pd.to_datetime(entry_date)
        start = (entry_dt - pd.Timedelta(days=200)).strftime('%Y-%m-%d')
        end = (entry_dt + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        df = hub.get_kline(code, start, end)
        if df is None or df.empty:
            return None
        df = df.sort_values('date').reset_index(drop=True)
        df['date'] = pd.to_datetime(df['date'])
        today_rows = df[df['date'] == entry_dt]
        pre = df[df['date'] < entry_dt].tail(60)
        if today_rows.empty or len(pre) < 20:
            return None
        today = today_rows.iloc[0]
        o, h, l, c = float(today['open']), float(today['high']), float(today['low']), float(today['close'])
        if o <= 0:
            return None
        feat = {}
        feat['body_pct'] = (c - o) / o
        feat['upper_shadow_pct'] = (h - max(o, c)) / o
        amt = float(today['amount'])
        pre20_amt = float(pre['amount'].tail(20).mean())
        feat['amount_ratio_20d'] = amt / pre20_amt if pre20_amt > 0 else float('nan')
        ma20 = float(pre['close'].tail(20).mean())
        feat['ma20_deviation'] = (c - ma20) / ma20 if ma20 > 0 else float('nan')
        feat['is_60d_high'] = int(c >= float(pre['high'].tail(min(60, len(pre))).max()))
        feat['is_120d_high'] = int(c >= float(pre['high'].max()))
        pre3 = pre.tail(3)
        if len(pre3) >= 2:
            feat['pre3_red_count'] = int((pre3['close'] > pre3['open']).sum())
            feat['pre3_amplitude_avg'] = float(((pre3['high'] - pre3['low']) / pre3['open']).mean())
            vols = pre3['volume'].values.astype(float)
            if vols.mean() > 0:
                slope = np.polyfit(np.arange(len(vols)), vols, 1)[0]
                feat['pre3_volume_slope'] = float(slope / vols.mean())
            else:
                feat['pre3_volume_slope'] = float('nan')
        return feat
    except Exception:
        return None


def _calc_position_action(df_buy, is_stopped: bool):
    """根据 entry 起 OHLC 计算持仓动作。

    df_buy: 已按日期升序、首行为 entry 日的 DataFrame（含 open/high/low/close）。
    is_stopped: 是否已触发 stopout。
    return: (action_text, action_class)
    """
    try:
        if df_buy is None or df_buy.empty:
            return ('-', 'act-none')
        if is_stopped:
            return ('已清仓', 'act-clear')
        n = len(df_buy)
        if n <= 1:
            return ('建仓', 'act-open')
        close_t = float(df_buy.iloc[0]['close'])
        if close_t <= 0:
            return ('-', 'act-none')
        post = df_buy.iloc[1:1 + 3]  # T+1..T+3，可能不足 3 条
        post_n = len(post)
        if post_n == 0:
            return ('建仓', 'act-open')
        close_last = float(post['close'].iloc[-1])
        high_max = float(post['high'].max())
        low_min = float(post['low'].min())
        open_arr = post['open'].astype(float).values
        close_arr = post['close'].astype(float).values
        red_count = int((close_arr > open_arr).sum())
        ret = close_last / close_t - 1.0
        runup = high_max / close_t - 1.0
        drop = low_min / close_t - 1.0  # 负值
        if ret <= -0.05 or drop <= -0.07:
            return ('清仓', 'act-clear')
        if ret <= -0.02 and drop <= -0.03:
            return ('减仓', 'act-reduce')
        if ret >= 0.06 and red_count >= 2 and runup >= 0.06:
            return ('加仓', 'act-add')
        return ('持有', 'act-hold')
    except Exception:
        return ('-', 'act-none')


def _star_html(star: int) -> str:
    if not star or star <= 0:
        return '<span class="rec-na">-</span>'
    klass = {5: 'rec-5', 4: 'rec-4', 3: 'rec-3', 2: 'rec-2', 1: 'rec-1'}.get(star, 'rec-na')
    return '<span class="' + klass + '">' + ('★' * star) + '</span>'


def _safe_float(value):
    try:
        if value is None:
            return None
        v = float(value)
        if v != v:
            return None
        return v
    except Exception:
        return None


def _fmt_pct(value):
    v = _safe_float(value)
    if v is None:
        return '-'
    return '{:+.2f}%'.format(v * 100)




def _rocket_html(record: dict) -> str:
    if not record.get('sector_resonance'):
        return ''
    name = record.get('sector_resonance_name') or '板块'
    date = record.get('sector_resonance_date') or '-'
    pct = _fmt_pct(record.get('sector_resonance_breakout_pct'))
    title = '板块共振：' + str(name) + ' ' + str(date) + ' 突破 ' + pct
    return '<span class="rocket-mark" title="' + title + '">🚀</span>'


def _limit_dot_html(record: dict) -> str:
    """涨停突破首次标记：黄色小圆点，仅在 cycle 首日且涨幅 >= 9.5% 时显示。"""
    # 仅 cycle 第一天显示
    if record.get('cycle_entry_date') != record.get('date'):
        return ''
    pct = record.get('pct', 0) or 0
    # 科创板/创业板20%，主板10%，统一用 >= 9.5 覆盖
    if abs(pct) < 9.5:
        return ''
    return '<span class="limit-dot" title="涨停突破首次入选">●</span>'


def _fizzle_warning_html(record: dict) -> str:
    """熄火预警：连续强势>=2天的 cycle 已结束（掉出/出局），
    在 cycle 最后命中行打橙红警示。与 🔥(活跃多日热门) 互斥。"""
    if record.get('cycle_active'):
        return ''  # 仍活跃 → 由 🔥 处理
    if record.get('cycle_hits', 0) < 2:
        return ''  # 未达连续强势>=2天
    # 只在 cycle 最后一个命中行显示
    if record.get('cycle_last_hit') != record.get('date'):
        return ''
    n = record.get('cycle_hits', 0)
    title = '熄火预警：连续强势 ' + str(n) + ' 天后已结束，注意回调风险'
    return '<span class="fizzle-mark" title="' + title + '">⚠</span>'


def plot_kline(data, buy_date, buy_price, save_path, stock_name):
    """生成K线图，标注买入点"""
    import matplotlib.pyplot as plt
    
    if data.empty or len(data) < 2:
        # 数据不足，生成简单提示图
        fig, ax = plt.subplots(figsize=(14, 8), facecolor='#1a1b26')
        ax.set_facecolor('#1a1b26')
        ax.text(0.5, 0.5, '数据不足', ha='center', va='center', color='#c0caf5', fontsize=20)
        ax.set_title(stock_name, color='#c0caf5', fontsize=16)
        fig.savefig(save_path, dpi=120, bbox_inches='tight', facecolor='#1a1b26')
        plt.close()
        return
    
    df = data.copy()
    df = df.rename(columns={
        'open': 'Open', 'high': 'High', 
        'low': 'Low', 'close': 'Close', 'volume': 'Volume'
    })
    
    # 使用简单折线图，避免mplfinance的兼容性问题
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), 
                                    gridspec_kw={'height_ratios': [3, 1]},
                                    facecolor='#1a1b26')
    ax1.set_facecolor('#1a1b26')
    ax2.set_facecolor('#1a1b26')
    
    # 价格图
    ax1.plot(df.index, df['Close'], color='#c0caf5', linewidth=1.5, label='收盘价')
    if len(df) >= 20:
        ax1.plot(df.index, df['Close'].rolling(20).mean(), color='#e0af68', linewidth=1, label='MA20')
    if len(df) >= 5:
        ax1.plot(df.index, df['Close'].rolling(5).mean(), color='#7aa2f7', linewidth=1, label='MA5')
    
    # 标记买入点
    try:
        buy_dt = pd.to_datetime(buy_date)
        if buy_dt in df.index:
            ax1.scatter([buy_dt], [buy_price], marker='^', color='#e0af68', s=200, 
                       label='买入', zorder=5, edgecolors='white', linewidths=2)
    except:
        pass
    
    ax1.set_title(stock_name, color='#c0caf5', fontsize=16, fontweight='bold')
    ax1.legend(loc='upper right', facecolor='#24283b', edgecolor='#3b4261', labelcolor='#c0caf5')
    ax1.tick_params(colors='#565f89')
    ax1.grid(True, alpha=0.3, color='#3b4261')
    ax1.set_ylabel('价格', color='#c0caf5')
    for spine in ax1.spines.values():
        spine.set_color('#3b4261')
    
    # 成交量图
    colors = ['#ef5350' if df['Close'].iloc[i] >= df['Open'].iloc[i] else '#26a69a' 
              for i in range(len(df))]
    ax2.bar(df.index, df['Volume'], color=colors, alpha=0.7)
    ax2.set_ylabel('成交量', color='#c0caf5')
    ax2.tick_params(colors='#565f89')
    ax2.grid(True, alpha=0.3, color='#3b4261')
    for spine in ax2.spines.values():
        spine.set_color('#3b4261')
    
    plt.tight_layout()
    fig.savefig(save_path, dpi=120, bbox_inches='tight', facecolor='#1a1b26')
    plt.close()


def generate_detail_page(code, name, first_date, output_dir):
    """生成详情页 - 使用ECharts绘制K线图"""
    from data_hub import api as hub
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 获取从入选日前150天到今天的数据（多取30天保险，确保有120个交易日）
    first_dt = pd.to_datetime(first_date)
    start_dt = first_dt - pd.Timedelta(days=150)
    start_date = start_dt.strftime('%Y-%m-%d')
    
    from datetime import time as dt_time
    _detail_post_close = pd.Timestamp.now().time() >= dt_time(15, 0)
    df = hub.get_kline(code, start_date, today, require_today=not _detail_post_close)
    if df is None or df.empty:
        return None
    # 重建为 index='date' 格式，兼容下游逻辑
    data = df.copy()
    data['date'] = pd.to_datetime(data['date'])
    data = data.set_index('date')
    
    # 买入价使用入选日当天的收盘价
    buy_date_str = first_dt.strftime('%Y-%m-%d')
    date_str_list = [d.strftime('%Y-%m-%d') for d in data.index]
    if buy_date_str in date_str_list:
        buy_price = data.loc[data.index.strftime('%Y-%m-%d') == buy_date_str, 'close'].iloc[0]
    else:
        buy_price = data['close'].iloc[0]
    
    end_price = data['close'].iloc[-1]
    pnl_pct = (end_price - buy_price) / buy_price * 100
    
    # 计算最大回撤（从入选日开始）
    data_from_buy = data[data.index >= first_dt]
    if not data_from_buy.empty:
        max_drawdown = (data_from_buy['close'].cummax() - data_from_buy['close']).max() / data_from_buy['close'].cummax().max() * 100
    else:
        max_drawdown = 0
    
    # 准备K线数据 [日期, 开盘, 收盘, 最低, 最高]
    kline_data = []
    dates = []
    for idx, row in data.iterrows():
        date_str = idx.strftime('%Y-%m-%d')
        dates.append(date_str)
        kline_data.append([
            round(row['open'], 2),
            round(row['close'], 2),
            round(row['low'], 2),
            round(row['high'], 2)
        ])
    
    # 准备标记点数据
    markers = []
    
    # 买入点标记 (B)
    if buy_date_str in dates:
        idx = dates.index(buy_date_str)
        markers.append({
            'coord': [buy_date_str, data['high'].iloc[idx]],
            'value': 'B',
            'itemStyle': {'color': '#e0af68'}
        })
    
    # 计算止损价 (买入价的90%)
    stop_loss_price = buy_price * 0.9
    
    # 检查是否触发止损
    sell_triggered = False
    sell_date = None
    for idx, row in data.iterrows():
        if row['low'] <= stop_loss_price and pd.to_datetime(first_date) < idx:
            sell_triggered = True
            sell_date = idx.strftime('%Y-%m-%d')
            sell_price = stop_loss_price
            break
    
    # 如果没有触发止损，按最后一天的收盘价算
    if not sell_triggered:
        sell_date = dates[-1]
        sell_price = data['close'].iloc[-1]
    
    # 卖出点标记 (S)
    if sell_date in dates:
        idx = dates.index(sell_date)
        markers.append({
            'coord': [sell_date, data['high'].iloc[idx]],
            'value': 'S',
            'itemStyle': {'color': '#f7768e'}
        })
    
    # 转换为JSON
    kline_json = json.dumps(kline_data)
    dates_json = json.dumps(dates)
    markers_json = json.dumps(markers)
    
    pnl_class = "profit" if pnl_pct >= 0 else "loss"
    pnl_color = "#9ece6a" if pnl_pct >= 0 else "#f7768e"
    
    # 使用普通字符串拼接，避免JavaScript中的{}与Python f-string冲突
    html_head = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{name} - 策略跟踪</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
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
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            padding: 20px;
            font-size: 14px;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .nav {{ margin-bottom: 20px; }}
        .nav a {{ color: var(--blue); text-decoration: none; }}
        .nav a:hover {{ text-decoration: underline; }}
        .header {{ border-bottom: 1px solid var(--border); padding-bottom: 20px; margin-bottom: 30px; }}
        .header h1 {{ font-size: 24px; font-weight: 600; margin-bottom: 8px; }}
        .header .code {{ color: var(--blue); font-weight: normal; }}
        .header .meta {{ color: var(--text-muted); font-size: 12px; margin-top: 5px; }}
        .metrics {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 15px; margin-bottom: 30px; }}
        .metric-card {{
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 15px;
        }}
        .metric-card .label {{ color: var(--text-muted); font-size: 11px; margin-bottom: 5px; text-transform: uppercase; }}
        .metric-card .value {{ font-size: 20px; font-weight: 600; }}
        .metric-card .value.profit {{ color: var(--green); }}
        .metric-card .value.loss {{ color: var(--red); }}
        .section {{ margin-bottom: 30px; }}
        .section-title {{
            color: var(--yellow);
            font-size: 14px;
            margin-bottom: 15px;
            padding-left: 10px;
            border-left: 3px solid var(--yellow);
        }}
        #kline-chart {{
            width: 100%;
            height: 650px;
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 6px;
        }}
        .marker-legend {{
            display: flex;
            gap: 20px;
            margin-bottom: 15px;
            font-size: 12px;
        }}
        .marker-item {{
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .marker-dot {{
            width: 18px;
            height: 18px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 10px;
            font-weight: bold;
            color: #1a1b26;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="nav"><a href="index.html">← 返回总览</a></div>
        <div class="header">
            <h1>{name} <span class="code">{code}</span></h1>
            <div class="meta">入选日期: {first_date} | 初始资金: ¥1,000,000 | 止损: 10%</div>
        </div>
        <div class="metrics">
            <div class="metric-card">
                <div class="label">买入价格</div>
                <div class="value">¥{buy_price:.2f}</div>
            </div>
            <div class="metric-card">
                <div class="label">当前价格</div>
                <div class="value">¥{end_price:.2f}</div>
            </div>
            <div class="metric-card">
                <div class="label">浮动盈亏</div>
                <div class="value {pnl_class}">{pnl_pct:+.2f}%</div>
            </div>
            <div class="metric-card">
                <div class="label">最大回撤</div>
                <div class="value loss">{max_drawdown:.2f}%</div>
            </div>
            <div class="metric-card">
                <div class="label">止损价格</div>
                <div class="value">¥{stop_loss_price:.2f}</div>
            </div>
        </div>
        <div class="section">
            <div class="section-title">// K线走势</div>
            <div class="marker-legend">
                <div class="marker-item">
                    <div class="marker-dot" style="background: #e0af68;">B</div>
                    <span style="color: #e0af68;">买入点</span>
                </div>
                <div class="marker-item">
                    <div class="marker-dot" style="background: #f7768e;">S</div>
                    <span style="color: #f7768e;">卖出点/当前</span>
                </div>
            </div>
            <div id="kline-chart"></div>
        </div>
    </div>
    <script>
        const dates = {{dates_json}};
        const klineData = {{kline_json}};
        const markers = {{markers_json}};
"""
    
    # JavaScript部分使用普通字符串，避免花括号冲突
    html_js = """
        const chart = echarts.init(document.getElementById('kline-chart'), 'dark');
        
        // 计算默认显示范围（最近120个交易日）
        const totalDays = dates.length;
        const defaultStart = totalDays > 120 ? Math.round((totalDays - 120) / totalDays * 100) : 0;
        
        // 标记点配置
        const markPoints = markers.map(m => ({{
            coord: m.coord,
            value: m.value,
            symbol: 'circle',
            symbolSize: 22,
            itemStyle: {{
                color: m.itemStyle.color,
                borderWidth: 2,
                borderColor: '#1a1b26'
            }},
            label: {{
                show: true,
                formatter: m.value,
                color: '#1a1b26',
                fontSize: 10,
                fontWeight: 'bold'
            }}
        }}));
        
        const option = {{
            backgroundColor: '#24283b',
            animation: false,
            tooltip: {{
                trigger: 'axis',
                axisPointer: {{ type: 'cross' }},
                backgroundColor: 'rgba(36, 40, 59, 0.95)',
                borderColor: '#3b4261',
                textStyle: {{ color: '#c0caf5', fontFamily: 'JetBrains Mono' }},
                formatter: function(params) {{
                    let dd = params[0];
                    let change = (dd.data[2] - dd.data[1]).toFixed(2);
                    let changePct = ((dd.data[2] - dd.data[1]) / dd.data[1] * 100).toFixed(2);
                    let changeColor = change >= 0 ? '#ef5350' : '#26a69a';
                    return '<div style="font-weight:bold;margin-bottom:5px;font-size:13px;">' + dd.name + '</div>' +
                           '<div style="display:flex;justify-content:space-between;gap:15px;"><span>开盘</span><span style="color:#c0caf5;">¥' + dd.data[1] + '</span></div>' +
                           '<div style="display:flex;justify-content:space-between;gap:15px;"><span>收盘</span><span style="color:' + changeColor + ';">¥' + dd.data[2] + '</span></div>' +
                           '<div style="display:flex;justify-content:space-between;gap:15px;"><span>最高</span><span style="color:#ef5350;">¥' + dd.data[4] + '</span></div>' +
                           '<div style="display:flex;justify-content:space-between;gap:15px;"><span>最低</span><span style="color:#26a69a;">¥' + dd.data[3] + '</span></div>' +
                           '<div style="border-top:1px solid #3b4261;margin:5px 0;padding-top:3px;display:flex;justify-content:space-between;">' +
                           '<span>涨跌</span><span style="color:' + changeColor + ';">' + (change>=0?'+':'') + change + ' (' + changePct + '%)</span></div>';
                }}
            }},
            grid: {{
                left: '3%',
                right: '3%',
                top: '3%',
                height: '90%'
            }},
            xAxis: {{
                type: 'category',
                data: dates,
                scale: true,
                boundaryGap: false,
                axisLine: {{ lineStyle: {{ color: '#3b4261' }} }},
                axisLabel: {{ color: '#565f89', fontSize: 10 }},
                splitLine: {{ show: false }}
            }},
            yAxis: {{
                scale: true,
                position: 'right',
                axisLine: {{ lineStyle: {{ color: '#3b4261' }} }},
                axisLabel: {{ color: '#565f89', fontSize: 10, formatter: '¥{{value}}' }},
                splitLine: {{ lineStyle: {{ color: '#292e42', type: 'dashed' }} }}
            }},
            dataZoom: [
                {{
                    type: 'inside',
                    start: defaultStart,
                    end: 100
                }},
                {{
                    type: 'slider',
                    start: defaultStart,
                    end: 100,
                    height: 20,
                    bottom: 5,
                    borderColor: '#3b4261',
                    fillerColor: 'rgba(122, 162, 247, 0.2)',
                    handleStyle: {{ color: '#7aa2f7' }},
                    textStyle: {{ color: '#565f89' }}
                }}
            ],
            series: [{{
                name: 'K线',
                type: 'candlestick',
                data: klineData,
                itemStyle: {{
                    color: '#ef5350',
                    color0: '#26a69a',
                    borderColor: '#ef5350',
                    borderColor0: '#26a69a'
                }},
                markPoint: {{
                    data: markPoints,
                    animation: false
                }}
            }}]
        }};
        
        chart.setOption(option);
        window.addEventListener('resize', () => chart.resize());

    <!-- 公众号二维码弹窗 -->
    <div id="qr-modal" style="display:-webkit-flex;display:flex;position:fixed;top:0;left:0;right:0;bottom:0;z-index:9999;background:rgba(0,0,0,0.75);-webkit-align-items:center;align-items:center;-webkit-justify-content:center;justify-content:center;">
        <div style="background:#1e2030;border:1px solid #3b4261;border-radius:12px;padding:32px 28px;text-align:center;max-width:320px;width:88%;box-shadow:0 8px 40px rgba(0,0,0,0.6);">
            <div style="font-size:16px;color:#e0af68;font-weight:600;margin-bottom:8px;">为防止失联，请关注！</div>
            <div style="font-size:12px;color:#a9b1d6;margin-bottom:16px;">扫码关注公众号，获取最新选股推送</div>
            <img src="data:image/jpeg;base64,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" alt="公众号二维码" style="width:200px;height:200px;border-radius:8px;display:block;margin:0 auto 20px;" />
            <button onclick="closeQrModal()" style="background:#7aa2f7;color:#1a1b26;border:none;border-radius:6px;padding:10px 32px;font-size:14px;cursor:pointer;font-weight:600;-webkit-appearance:none;">我已关注，关闭</button>
        </div>
    </div>
    <script>
        (function(){{
            try {{
                var key = 'qr_modal_closed';
                var last = localStorage.getItem(key);
                if (last && Date.now() - parseInt(last) < 7*24*3600*1000) {{
                    document.getElementById('qr-modal').style.display = 'none';
                }}
            }} catch(e) {{}}
        }})();
        function closeQrModal(){{
            try {{ localStorage.setItem('qr_modal_closed', String(Date.now())); }} catch(e) {{}}
            document.getElementById('qr-modal').style.display = 'none';
        }}
    </script>
    </script>
</body>
</html>"""
    
    html = html_head + html_js
    
    return html


def _calc_stopout_from_df(df, buy_price):
    """
    移动止损语义：
      初始 stop = buy_price * 0.9
      每创新高 peak 时 stop 上移到 peak * 0.9（只升不降）
      close <= stop 即触发出局，exit_price = 当日 close
      peak 使用持仓以来最高价 high，而不是最高收盘价
      止盈 ⇔ exit_price > buy_price，否则 止损

      注意：建仓日（T+0）不参与 peak 追踪。
        入选日盘中 high 常已远高于 buy_price（buy_price = 收盘价），
        若立即用 T+0 high 上移 stop，会导致 T+1 稍跌就被打穿，
        与真正的 trailing stop 意图不符。因此从 T+1 起才追踪 peak。
    返回 (stopout_date, stopout_type, exit_price, peak, stop_level)
    其中 stop_level 为最终的（动态）止损价：
      - 已出局：触发时的 stop
      - 仍持有：当前的移动止损价
    """
    if df is None or df.empty:
        return None, None, None, buy_price, buy_price * 0.9

    df = df.sort_values('date').reset_index(drop=True)
    peak = buy_price
    stop_level = buy_price * 0.9
    stopout_date = None
    stopout_type = None
    exit_price = None

    for i, row in df.iterrows():
        high = float(row['high'])
        close = float(row['close'])
        # T+0（建仓日，i==0）不追 peak，只判断当日是否已跌破初始止损
        if i > 0 and high > peak:
            peak = high
            new_stop = peak * 0.9
            if new_stop > stop_level:
                stop_level = new_stop
        if close <= stop_level:
            exit_price = close
            stopout_type = '止盈' if exit_price > buy_price else '止损'
            stopout_date = pd.to_datetime(row['date']).strftime('%m-%d')
            break

    return stopout_date, stopout_type, exit_price, peak, stop_level

NEAR_BREAKOUT_MIN_AMOUNT = 1.5e9


def _get_local_kline_with_today(code: str, start: str, end: str) -> pd.DataFrame:
    """仅读 KlineDB，并用 Sina 拼接当天行；避免 tracker 生成时触发 baostock。"""
    try:
        from data_hub.store.kline_db import KlineDB
        from data_hub import api as hub
        from data_hub.sources.base import UNIFIED_COLS
        db = KlineDB()
        df = db.query_kline(code, start, end)
        if df is None:
            df = pd.DataFrame(columns=UNIFIED_COLS)
        today_iso = pd.Timestamp.now().strftime('%Y-%m-%d')
        if end >= today_iso and (df.empty or today_iso not in set(df['date'].tolist())):
            snap = hub.get_market_snapshot([code])
            row = snap.get(code)
            if row:
                new_row = {k: row.get(k) for k in UNIFIED_COLS}
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        if not df.empty:
            df = df.sort_values('date').reset_index(drop=True)
            for c in ['open', 'high', 'low', 'close', 'volume', 'amount', 'turn', 'pctChg']:
                df[c] = pd.to_numeric(df[c], errors='coerce')
        return df
    except Exception:
        return pd.DataFrame()


def _limit_up_ratio(code: str, name: str = '') -> float:
    """粗略估算涨停幅度，用于待突破池模拟。"""
    name_upper = (name or '').upper()
    if 'ST' in name_upper or name_upper.startswith('*ST'):
        return 0.05
    if code.startswith('sz.30') or code.startswith('sh.688') or code.startswith('bj.'):
        return 0.20
    return 0.10


def _is_one_limit_away(code: str, name: str, hist: pd.DataFrame, today: str) -> bool:
    """当前未新高，但模拟一个涨停后可突破新高。"""
    if hist is None or hist.empty:
        return False
    today_rows = hist[hist['date'] == today]
    if today_rows.empty:
        return False
    pre = hist[hist['date'] < today]
    if len(pre) < 100:
        return False
    today_row = today_rows.iloc[0]
    close = float(today_row['close'])
    pre100_high = float(pre.tail(100)['high'].max())
    all_time_high = float(pre['high'].max())
    current_cond2 = (close > pre100_high) or (close >= all_time_high)
    if current_cond2:
        return False
    limit_close = close * (1.0 + _limit_up_ratio(code, name))
    would_new_100d_high = limit_close > pre100_high
    would_new_all_time_high = limit_close >= all_time_high
    return would_new_100d_high or would_new_all_time_high


def _build_near_breakout_pool(today_iso: str, selected_codes: set, limit: int = 30) -> list:
    """构建待突破股票池。仅用于 index 展示，不写入 selections/CSV。"""
    try:
        from daily_select import get_stock_list, _is_real_stock, detect_today_signal
        from data_hub import api as hub
        from stock_research.feature_extractor import extract_features
        from stock_research.recommender import score as recommender_score
    except Exception:
        return []

    try:
        candidates = [(c, n) for c, n in get_stock_list() if _is_real_stock(c)]
    except Exception:
        return []

    rows = []
    start_date = (datetime.strptime(today_iso, '%Y-%m-%d') - pd.Timedelta(days=220)).strftime('%Y-%m-%d')
    for code, name in candidates:
        if code in selected_codes:
            continue
        try:
            hist = _get_local_kline_with_today(code, start_date, today_iso)
            if hist is None or hist.empty:
                continue
            today_rows = hist[hist['date'] == today_iso]
            if today_rows.empty:
                continue
            today_row = today_rows.iloc[0]
            amount = float(today_row['amount']) if pd.notna(today_row['amount']) else 0.0
            if amount < NEAR_BREAKOUT_MIN_AMOUNT:
                continue
            if detect_today_signal(code, hist, today_iso) is not None:
                continue
            if not _is_one_limit_away(code, name, hist, today_iso):
                continue
            sample = {
                'code': code,
                'entry_date': today_iso,
                'signal_type': 'watch',
                'is_limit_up': False,
                'hist': hist,
            }
            feat = extract_features(sample)
            if feat is None:
                star = 0
                score = 0.0
            else:
                sc = recommender_score(feat)
                star = int(sc.get('star', 0))
                score = float(sc.get('score', 0.0))
            rows.append({
                'date': today_iso.replace('-', ''),
                'code': code,
                'name': name,
                'price': float(today_row['close']),
                'pct': float(today_row['pctChg']) if pd.notna(today_row['pctChg']) else 0.0,
                'amount': float(today_row['amount']) if pd.notna(today_row['amount']) else 0.0,
                'rec_star': star,
                'score': score,
            })
        except Exception:
            continue
    rows.sort(key=lambda r: (r['rec_star'], r['score'], r['amount']), reverse=True)
    return rows[:limit]


def _render_near_breakout_rows(rows: list) -> str:
    if not rows:
        return '<div class="watch-empty">暂无待突破股票</div>'
    out = []
    for idx, record in enumerate(rows, start=1):
        code = record['code']
        detail_link = 'https://www.iwencai.com/unifiedwap/result?w=' + quote(record['name']) + '&querytype=stock'
        amount_yi = record.get('amount', 0) / 1e8
        if amount_yi >= 50:
            amount_class = 'amount-high'
        elif amount_yi >= 30:
            amount_class = 'amount-mid'
        else:
            amount_class = 'amount-low'
        pct_class = 'profit' if record.get('pct', 0) >= 0 else 'loss'
        date_class = 'date-group-' + str(idx % 2)
        amount_cell = '<span class="col-amount ' + amount_class + '">' + '{:.1f}亿'.format(amount_yi) + '</span>'
        out.append(
            '\n            <a href="' + detail_link + '" target="_blank" rel="noopener"'
            ' class="stock-row watch-row ' + date_class + '">'
            '\n                <span class="col-date">' + str(record['date']) + '</span>'
            '\n                <span class="col-name">' + record['name'] + '</span>'
            '\n                <span class="col-code">' + code + '</span>'
            '\n                <span data-label="成交额" class="col-amount-cell">' + amount_cell + '</span>'
            '\n                <span data-label="当日涨幅" class="col-pct ' + pct_class + '">' + '{:+.2f}%'.format(record.get('pct', 0)) + '</span>'
            '\n                <span data-label="信号强度" class="col-rec-cell">' + _star_html(record.get('rec_star', 0)) + '</span>'
            '\n                <span data-label="买入价" class="col-price"></span>'
            '\n                <span data-label="持仓动作" class="col-action"></span>'
            '\n                <span data-label="浮动盈亏" class="col-pnl"></span>'
            '\n                <span data-label="止损/止盈" class="col-stop"></span>'
            '\n            </a>'
        )
    return ''.join(out)


def generate_index_page(output_dir):
    """生成总览页 - 合并为单一表格，日期作为列"""
    from data_hub import api as hub
    selections = load_selections()
    multi_day_picks = get_multi_day_picks()
    
    if selections:
        today = sorted(selections.keys())[-1]
        today_iso = f'{today[:4]}-{today[4:6]}-{today[6:8]}'
    else:
        today = datetime.now().strftime('%Y%m%d')
        today_iso = datetime.now().strftime('%Y-%m-%d')

    # ============ 周期探测（per code）+ 周期级状态计算 ============
    # 每个 (date, stock) 仍独立成行渲染，但持仓数据（buy_price/pnl/止损/动作）
    # 沿用所属 cycle 的首日状态，避免"同周期内的后续命中又显示建仓"的误解。
    code_dates = {}  # code → [(date_str, stock_dict), ...] 升序
    for date in sorted(selections.keys()):
        for stock in selections[date].get('stocks', []):
            code_dates.setdefault(stock['code'], []).append((date, stock))

    # 盘后（>=15:00）今日数据已由 sync_today 写入 KlineDB，不强制在线拉取今日行
    from datetime import time as dt_time
    _post_close = pd.Timestamp.now().time() >= dt_time(15, 0)


    # cycle dict: {code, entry_date, entry_stock, stop_dt(Timestamp|None), stop_str,
    #              stop_type, exit_price, current_price, pnl_pct, stop_level,
    #              base_action_text, base_action_class, df, hits: [date_str,...], active}
    cycle_map = {}
    cycles_all = []
    today_dt = pd.to_datetime(today)
    for code, hits in code_dates.items():
        cur_cycle = None
        for d_str, stock in hits:
            d_dt = pd.to_datetime(d_str)
            in_prev = (
                cur_cycle is not None
                and cur_cycle.get('base_action_class') != 'act-clear'
                and (cur_cycle['stop_dt'] is None or d_dt <= cur_cycle['stop_dt'])
            )
            if in_prev:
                cur_cycle['hits'].append(d_str)
                cycle_map[(code, d_str)] = cur_cycle
                continue
            # 新 cycle：拉一次数据，算 stopout / action
            buy_price_c = stock.get('buy_price', stock.get('price'))
            cyc_df = None
            stop_dt_c = None
            stop_str_c = None
            stop_type_c = None
            exit_price_c = None
            current_price_c = None
            pnl_pct_c = None
            stop_level_c = buy_price_c * 0.9
            base_action_text = '-'
            base_action_class = 'act-none'
            try:
                df = hub.get_kline(code, d_str, today, require_today=not _post_close)
                if df is not None and not df.empty:
                    df = df.sort_values('date').reset_index(drop=True)
                    df_buy = df[pd.to_datetime(df['date']) >= d_dt].reset_index(drop=True)
                    if not df_buy.empty:
                        cyc_df = df_buy
                        current_price_c = float(df_buy['close'].iloc[-1])
                        sd, st, ep, _peak, sl = _calc_stopout_from_df(df_buy, buy_price_c)
                        stop_type_c = st
                        exit_price_c = ep
                        stop_level_c = sl
                        if sd is not None:
                            year = int(d_str[:4])
                            try:
                                stop_dt_c = pd.to_datetime(f'{year}-{sd}')
                                if stop_dt_c < d_dt:
                                    stop_dt_c = pd.to_datetime(f'{year + 1}-{sd}')
                                stop_str_c = stop_dt_c.strftime('%Y%m%d')
                            except Exception:
                                stop_dt_c = None
                        if exit_price_c is not None:
                            current_price_c = exit_price_c
                            pnl_pct_c = (exit_price_c - buy_price_c) / buy_price_c * 100
                        else:
                            pnl_pct_c = (current_price_c - buy_price_c) / buy_price_c * 100
                        base_action_text, base_action_class = _calc_position_action(
                            df_buy, is_stopped=stop_dt_c is not None
                        )
            except Exception:
                pass
            cur_cycle = {
                'code': code,
                'entry_date': d_str,
                'entry_stock': stock,
                'buy_price': buy_price_c,
                'df': cyc_df,
                'stop_dt': stop_dt_c,
                'stop_str': stop_str_c,
                'stop_type': stop_type_c,
                'exit_price': exit_price_c,
                'current_price': current_price_c,
                'pnl_pct': pnl_pct_c,
                'stop_level': stop_level_c,
                'base_action_text': base_action_text,
                'base_action_class': base_action_class,
                'hits': [d_str],
            }
            # active = cycle 没出局，或 stop_dt 在未来（不会发生但保险）
            cur_cycle['active'] = stop_dt_c is None or stop_dt_c > today_dt
            cycles_all.append(cur_cycle)
            cycle_map[(code, d_str)] = cur_cycle

    def _cycle_offset(cyc, d_str):
        """返回 d_str 在 cycle 内的交易日偏移（0 = entry day）"""
        df = cyc.get('df')
        d_dt = pd.to_datetime(d_str)
        if df is not None and not df.empty:
            dates_idx = pd.to_datetime(df['date']).reset_index(drop=True)
            entry_dt = pd.to_datetime(cyc['entry_date'])
            try:
                entry_pos = int(dates_idx[dates_idx == entry_dt].index[0])
                hit_pos = int(dates_idx[dates_idx == d_dt].index[0])
                return max(0, hit_pos - entry_pos)
            except Exception:
                pass
        # fallback：自然日差
        return max(0, (d_dt - pd.to_datetime(cyc['entry_date'])).days)

    def _strip_init_prefix(s):
        if not s:
            return s
        for p in ('（初步）', '(初步)'):
            if s.startswith(p):
                return s[len(p):]
        return s

    all_records = []
    flat_hits = []
    for date in selections.keys():
        for stock in selections[date].get('stocks', []):
            flat_hits.append((date, stock))
    for date, stock in sorted(flat_hits, key=lambda x: x[0], reverse=True):
            code = stock['code']
            cyc = cycle_map.get((code, date))
            signal_type = stock.get('signal_type') or ('one_word' if stock.get('is_limit_up') else 'breakthrough')

            # 推荐指数：优先使用 selections.json 自带 star
            rec_star = 0
            stored_star = stock.get('star')
            if stored_star is not None:
                try:
                    rec_star = int(stored_star)
                except Exception:
                    rec_star = 0
            elif HAS_RECOMMENDER:
                feats = _compute_rec_features(stock['code'], date)
                if feats:
                    try:
                        rec_star = rec_score(feats)['star']
                    except Exception:
                        rec_star = 0

            # 默认值兜底（cyc 为 None 不应出现，但保险）
            if cyc is None:
                all_records.append({
                    'date': date, 'code': code, 'name': stock['name'],
                    'price': stock['price'],
                    'buy_price': stock.get('buy_price', stock['price']),
                    'signal_type': signal_type,
                    'pct': stock['pct_change'],
                    'current_price': None, 'pnl_pct': None,
                    'stopout_date': None, 'stopout_type': None, 'exit_price': None,
                    'stop_level': stock.get('buy_price', stock['price']) * 0.9,
                    'is_stopped': False, 'amount': stock.get('amount'),
                    'rec_star': rec_star,
                    'sector_resonance': stock.get('sector_resonance'),
                    'sector_resonance_type': stock.get('sector_resonance_type'),
                    'sector_resonance_name': stock.get('sector_resonance_name'),
                    'sector_resonance_date': stock.get('sector_resonance_date'),
                    'sector_resonance_breakout_pct': stock.get('sector_resonance_breakout_pct'),
                    'action_text': '-', 'action_class': 'act-none',
                    'cycle_entry_date': date, 'cycle_active': True,
                    'cycle_hits': 1, 'cycle_offset': 0,
                    'cycle_last_hit': date,
                })
                continue

            n_offset = _cycle_offset(cyc, date)
            # 动作文案：cycle 首日恒为"建仓（T+0）"；其他行用 cycle base 动作 + T+N
            if date == cyc['entry_date']:
                action_text = f'建仓（T+{n_offset}）'
                action_class = 'act-open'
            else:
                base = _strip_init_prefix(cyc['base_action_text'])
                if cyc['stop_dt'] is not None:
                    # 该行夹在 entry 与 stopout 之间，base 可能是 act-clear；保留
                    base = base or '清仓'
                if not base or base == '-':
                    base = '持有'
                action_text = f'{base}（T+{n_offset}）'
                action_class = cyc['base_action_class'] or 'act-hold'

            # cycle 已出局：止损触发 或 满仓清仓 均归入已出局区
            cyc_stopped = cyc['stop_dt'] is not None
            cyc_cleared = cyc.get('base_action_class') == 'act-clear'
            if cyc_stopped:
                stopout_date_disp = cyc['stop_dt'].strftime('%m-%d')
                stopout_type_disp = cyc['stop_type']
            elif cyc_cleared:
                stopout_date_disp = '清仓'
                stopout_type_disp = 'clear'
            else:
                stopout_date_disp = None
                stopout_type_disp = None
            is_stopped_row = cyc_stopped or cyc_cleared

            all_records.append({
                'date': date,
                'code': code,
                'name': stock['name'],
                'price': stock['price'],
                'buy_price': cyc['buy_price'],
                'signal_type': signal_type,
                'pct': stock['pct_change'],
                'current_price': cyc['current_price'],
                'pnl_pct': cyc['pnl_pct'],
                'stopout_date': stopout_date_disp,
                'stopout_type': stopout_type_disp,
                'exit_price': cyc['exit_price'] if cyc_stopped else None,
                'stop_level': cyc['stop_level'],
                'is_stopped': is_stopped_row,
                'amount': stock.get('amount'),
                'rec_star': rec_star,
                'sector_resonance': stock.get('sector_resonance'),
                'sector_resonance_type': stock.get('sector_resonance_type'),
                'sector_resonance_name': stock.get('sector_resonance_name'),
                'sector_resonance_date': stock.get('sector_resonance_date'),
                'sector_resonance_breakout_pct': stock.get('sector_resonance_breakout_pct'),
                'action_text': action_text,
                'action_class': action_class,
                'cycle_entry_date': cyc['entry_date'],
                'cycle_active': cyc['active'],
                'cycle_hits': len(cyc['hits']),
                'cycle_offset': n_offset,
                'cycle_last_hit': cyc['hits'][-1] if cyc.get('hits') else date,
            })
    
    # 生成活跃持仓行 + 已出局行
    active_list = []
    stopped_list = []
    prev_date = None
    date_index = 0
    for record in all_records:
        code = record['code']
        # 高亮规则：仅 cycle 处于活跃状态 + cycle 内多日命中
        is_multi_day = bool(record.get('cycle_active')) and record.get('cycle_hits', 0) >= 2
        # 已出局：硬止损触发 OR 持仓动作判定为「清仓」
        action_class = record.get('action_class', '')
        action_text = record.get('action_text', '')
        is_stopped = record.get('is_stopped', False) or action_class == 'act-clear'
        
        is_new_date = record['date'] != prev_date
        if is_new_date:
            date_index += 1
            prev_date = record['date']
        
        date_class = "date-group-" + str(date_index % 2)
        row_class = date_class
        if is_multi_day:
            row_class += " multi-day"
        date_border = "date-border" if is_new_date and date_index > 1 else ""
        
        # 「再相逢」列已移除：每日命中独立成行，多日命中通过 col-name 高亮表达
        pct_class = "profit" if record['pct'] >= 0 else "loss"
        pnl_class = "profit" if record['pnl_pct'] is not None and record['pnl_pct'] >= 0 else "loss"
        
        current_price_str = "¥" + "{:.2f}".format(record['current_price']) if record['current_price'] else "-"
        pnl_str = "{:+.2f}%".format(record['pnl_pct']) if record['pnl_pct'] is not None else "-"
        stop_price_str = "¥" + "{:.2f}".format(record['stop_level']) if record.get('stop_level') is not None else "-"
        # 已出局：显示出局成交价（exit_price）；未出局：显示当前移动止损价
        if is_stopped and record.get('exit_price') is not None:
            stop_price_str = "¥" + "{:.2f}".format(record['exit_price'])
        
        tag_map = {
            'one_word': ('一字涨停', 'tag-oneword'),
            'gap': ('跳空突破', 'tag-gap'),
            'breakthrough': ('突破', 'tag-break'),
        }
        buy_tag, buy_tag_class = tag_map.get(record['signal_type'], ('突破', 'tag-break'))
        
        detail_link = "https://www.iwencai.com/unifiedwap/result?w=" + quote(record['name']) + "&querytype=stock"
        pnl_data = record['pnl_pct'] if record['pnl_pct'] is not None else -9999
        
        # 成交额三档着色（亿元）
        amount_val = record.get('amount')
        if amount_val and amount_val > 0:
            amount_yi = amount_val / 1e8
            if amount_yi >= 50:
                amount_class = 'amount-high'
            elif amount_yi >= 30:
                amount_class = 'amount-mid'
            else:
                amount_class = 'amount-low'
            amount_cell = '<span class="col-amount ' + amount_class + '">' + "{:.1f}亿".format(amount_yi) + '</span>'
        else:
            amount_cell = '<span class="col-amount">-</span>'
        
        if is_stopped:
            # 两类：硬止损（有 stopout_date / stopout_type）/ post3 动作判定清仓（仅 action 文案）
            if record.get('stopout_date') and record.get('stopout_type'):
                stop_tag_class = 'profit-tag' if record['stopout_type'] == '止盈' else 'stop-tag'
                stop_inline = (
                    '<br><span class="' + stop_tag_class + ' stop-tag-inline">'
                    + str(record['stopout_date']) + ' ' + str(record['stopout_type']) + '</span>'
                )
            else:
                stop_inline = (
                    '<br><span class="stop-tag stop-tag-inline">' + action_text + '</span>'
                )
            date_with_tag = str(record['date']) + stop_inline
            row_html = (
                '\n            <a href="' + detail_link + '" target="_blank" rel="noopener"'
                ' class="stock-row ' + row_class + ' ' + date_border + ' stopped">'
                '\n                <span class="col-date">' + date_with_tag + '</span>'
                '\n                <span class="col-name">' + record['name'] + _limit_dot_html(record) + _fizzle_warning_html(record) + _rocket_html(record) + ('<span class="hot-mark">🔥</span>' if is_multi_day else '') + '</span>'
                '\n                <span class="col-code">' + code + '</span>'
                '\n                <span data-label="成交额" class="col-amount-cell">' + amount_cell + '</span>'
                '\n                <span data-label="当日涨幅" class="col-pct ' + pct_class + '">' + "{:+.2f}%".format(record['pct']) + '</span>'
                '\n                <span data-label="信号强度" class="col-rec-cell">' + _star_html(record.get('rec_star', 0)) + '</span>'
                '\n                <span data-label="买入价" class="col-price">¥' + "{:.2f}".format(record['buy_price'])
                + ' <span class="buy-tag ' + buy_tag_class + '">' + buy_tag + '</span></span>'
                '\n                <span data-label="持仓动作" class="col-action ' + record['action_class'] + '">' + record['action_text'] + '</span>'
                '\n                <span data-label="浮动盈亏" class="col-pnl ' + pnl_class + '">' + pnl_str + '</span>'
                '\n                <span data-label="止损/止盈" class="col-stop">' + stop_price_str + '</span>'
                '\n            </a>')
            stopped_list.append(row_html)
        else:
            row_html = (
                '\n            <a href="' + detail_link + '" target="_blank" rel="noopener"'
                ' class="stock-row ' + row_class + ' ' + date_border + '"'
                ' data-pnl="' + str(pnl_data) + '" data-date="' + str(record['date']) + '">'
                '\n                <span class="col-date">' + str(record['date']) + '</span>'
                '\n                <span class="col-name">' + record['name'] + _limit_dot_html(record) + _fizzle_warning_html(record) + _rocket_html(record) + ('<span class="hot-mark">🔥</span>' if is_multi_day else '') + '</span>'
                '\n                <span class="col-code">' + code + '</span>'
                '\n                <span data-label="成交额" class="col-amount-cell">' + amount_cell + '</span>'
                '\n                <span data-label="当日涨幅" class="col-pct ' + pct_class + '">' + "{:+.2f}%".format(record['pct']) + '</span>'
                '\n                <span data-label="信号强度" class="col-rec-cell">' + _star_html(record.get('rec_star', 0)) + '</span>'
                '\n                <span data-label="买入价" class="col-price">¥' + "{:.2f}".format(record['buy_price'])
                + ' <span class="buy-tag ' + buy_tag_class + '">' + buy_tag + '</span></span>'
                '\n                <span data-label="持仓动作" class="col-action ' + record['action_class'] + '">' + record['action_text'] + '</span>'
                '\n                <span data-label="浮动盈亏" class="col-pnl ' + pnl_class + '">' + pnl_str + '</span>'
                '\n                <span data-label="止损/止盈" class="col-stop">' + stop_price_str + '</span>'
                '\n            </a>')
            active_list.append(row_html)
    
    active_rows = ''.join(active_list)
    stopped_rows = ''.join(stopped_list)
    stopped_count = len(stopped_list)

    selected_codes_today = set()
    today_payload = selections.get(today, {})
    if isinstance(today_payload, dict):
        for stock in today_payload.get('stocks', []):
            if isinstance(stock, dict) and stock.get('code'):
                selected_codes_today.add(stock['code'])
    # 已选出（含历史活跃持仓）也要从突破池中排除
    active_codes = {cyc['code'] for cyc in cycles_all if cyc.get('active', False)}
    excluded_codes = selected_codes_today | active_codes
    watch_rows_data = _build_near_breakout_pool(today_iso, excluded_codes, limit=30)
    watch_rows = _render_near_breakout_rows(watch_rows_data)
    watch_count = len(watch_rows_data)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>选股策略跟踪系统</title>
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
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
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
            font-size: 20px;
            font-weight: 600;
            margin-bottom: 8px;
            color: var(--green);
        }}
        .header .meta {{
            color: var(--text-muted);
            font-size: 12px;
        }}
        .stock-table {{ 
            border: 1px solid var(--border); 
            border-radius: 6px; 
            overflow: hidden;
        }}
        .stock-header {{
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 18px;
            background: var(--bg-tertiary);
            border-bottom: 1px solid var(--border);
            color: var(--text-muted);
            font-size: 12px;
            text-transform: uppercase;
        }}
        .stock-row {{
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px 18px;
            border-bottom: 1px solid var(--border);
            text-decoration: none;
            color: var(--text-primary);
            transition: background 0.2s;
        }}
        .stock-row:last-child {{ border-bottom: none; }}
        .stock-row:hover {{ background: var(--bg-tertiary); }}
        .stock-row.date-group-0 {{ background: var(--bg-secondary); }}
        .stock-row.date-group-1 {{ background: var(--bg-primary); }}
        .stock-row:hover {{ background: var(--bg-tertiary); }}
        .stock-row.multi-day {{ background: rgba(224, 175, 104, 0.06); }}
        .stock-row.date-border {{ border-top: 2px dashed #7aa2f7; }}
        .col-date {{ flex: 1.1; color: var(--yellow); font-weight: 500; }}
        .col-name {{ flex: 1.6; position: relative; padding-right: 18px; }}
        .col-name .hot-mark {{ position: absolute; right: 2px; top: -4px; margin-left: 0; font-size: 11px; line-height: 1; filter: drop-shadow(0 0 3px rgba(255, 120, 0, 0.5)); }}
        .col-name .rocket-mark {{ position: absolute; right: 2px; top: 10px; margin-left: 0; font-size: 12px; line-height: 1; filter: drop-shadow(0 0 4px rgba(122, 162, 247, 0.6)); }}
        .col-name .limit-dot {{ position: absolute; right: 28px; top: 2px; margin-left: 0; font-size: 11px; line-height: 1; color: #e0af68; filter: drop-shadow(0 0 3px rgba(224, 175, 104, 0.7)); }}
        .col-name .fizzle-mark {{ position: absolute; right: 2px; top: -4px; margin-left: 0; font-size: 11px; line-height: 1; color: #f7768e; filter: drop-shadow(0 0 3px rgba(247, 118, 142, 0.6)); }}
        .col-code {{ flex: 1.1; color: var(--blue); }}
        .col-amount {{ flex: 1.0; text-align: right; font-weight: 500; }}
        .col-amount-cell {{ flex: 1.0; text-align: right; font-weight: 500; }}
        .amount-low {{ color: var(--blue); }}
        .amount-mid {{ color: var(--yellow); }}
        .amount-high {{ color: var(--green); }}
        .col-rec {{ flex: 0.8; text-align: center; font-size: 13px; letter-spacing: 1px; }}
        .col-rec-cell {{ flex: 0.8; text-align: center; font-size: 13px; letter-spacing: 1px; }}
        .rec-5 {{ color: #ffd966; text-shadow: 0 0 6px rgba(255, 215, 102, 0.4); }}
        .rec-4 {{ color: var(--green); }}
        .rec-3 {{ color: var(--blue); }}
        .rec-2 {{ color: var(--text-muted); }}
        .rec-1 {{ color: #3b4261; }}
        .rec-na {{ color: var(--text-muted); }}
        .col-price {{ flex: 1.5; }}
        .col-stop {{ flex: 1.1; color: var(--yellow); text-align: right; }}
        .col-current {{ flex: 1; text-align: right; }}
        .col-pnl {{ flex: 1.1; text-align: right; font-weight: 600; }}
        .col-pct {{ flex: 0.9; text-align: right; }}
        .col-action {{ flex: 0.9; text-align: center; font-weight: 500; font-size: 12px; }}
        .act-open   {{ color: var(--blue); }}
        .act-add    {{ color: var(--green); }}
        .act-hold   {{ color: var(--text-secondary); }}
        .act-reduce {{ color: var(--yellow); }}
        .act-clear  {{ color: var(--red); }}
        .act-none   {{ color: var(--text-muted); }}
        .profit {{ color: var(--green); }}
        .loss {{ color: var(--red); }}
        .buy-tag {{
            display: inline-block;
            font-size: 10px;
            padding: 1px 6px;
            margin-left: 4px;
            border-radius: 3px;
            font-weight: 500;
        }}
        .tag-limit {{
            color: var(--red);
            background: rgba(247, 118, 142, 0.15);
            border: 1px solid rgba(247, 118, 142, 0.4);
        }}
        .tag-oneword {{
            color: var(--red);
            background: rgba(247, 118, 142, 0.2);
            border: 1px solid var(--red);
            font-weight: 600;
        }}
        .tag-gap {{
            color: var(--yellow);
            background: rgba(224, 175, 104, 0.18);
            border: 1px solid var(--yellow);
            font-weight: 600;
        }}
        .tag-break {{
            color: var(--blue);
            background: rgba(122, 162, 247, 0.15);
            border: 1px solid rgba(122, 162, 247, 0.4);
        }}
                .sort-btn {{
            background: none;
            border: 1px solid var(--border);
            color: var(--text-muted);
            font-family: inherit;
            font-size: 11px;
            padding: 3px 8px;
            margin-left: 6px;
            border-radius: 3px;
            cursor: pointer;
            transition: all 0.15s;
        }}
        .sort-btn:hover {{
            color: var(--yellow);
            border-color: var(--yellow);
        }}
        .sort-btn.active {{
            color: var(--yellow);
            border-color: var(--yellow);
            background: rgba(224, 175, 104, 0.1);
        }}
        .stock-row.stopped {{
            opacity: 0.55;
            color: var(--text-secondary);
        }}
        .stopped-section, .watch-section {{
            margin-top: 20px;
            border: 1px solid var(--border);
            border-radius: 6px;
            overflow: hidden;
        }}
        .watch-header {{
            color: var(--yellow);
            cursor: default;
        }}
        .watch-row {{
            background: rgba(122, 162, 247, 0.03);
        }}
        .watch-empty {{
            padding: 14px 15px;
            color: var(--text-muted);
            font-size: 12px;
            background: var(--bg-secondary);
        }}
        .section-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 10px 15px;
            background: var(--bg-tertiary);
            cursor: pointer;
            color: var(--text-secondary);
            font-size: 12px;
        }}
        .section-header:hover {{ background: var(--bg-secondary); }}
        #stopped-rows.collapsed {{ display: none; }}
        .stop-tag, .profit-tag {{
            font-size: 10px;
            padding: 1px 5px;
            border-radius: 3px;
            margin-left: 4px;
        }}
        .stop-tag-inline {{
            display: inline-block;
            margin-left: 0;
            margin-top: 2px;
            font-size: 10px;
            font-weight: 600;
        }}
        .stop-tag {{
            background: rgba(247, 118, 142, 0.2);
            border: 1px solid var(--red);
            color: var(--red);
        }}
        .profit-tag {{
            background: rgba(158, 206, 106, 0.2);
            border: 1px solid var(--green);
            color: var(--green);
        }}
        .footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid var(--border);
            color: var(--text-muted);
            font-size: 12px;
            text-align: center;
        }}

        /* ============ 移动端适配（≤ 720px）============ */
        @media (max-width: 720px) {{
            body {{ padding: 8px; font-size: 12px; }}
            .container {{ max-width: 100%; }}
            .header h1 {{ font-size: 16px; }}
            .header .meta {{ font-size: 11px; line-height: 1.5; }}

            /* 表头在移动端隐藏，由行的 data-label 替代 */
            .stock-header {{ display: none; }}
            .stock-table, .stopped-section, .watch-section {{ border-radius: 4px; }}

            /* 行改为竖向堆叠 */
            .stock-row {{
                flex-wrap: wrap;
                gap: 4px 8px;
                padding: 10px 12px;
                align-items: baseline;
            }}

            /* 日期独占一行 */
            .col-date {{ flex: 1 1 100%; font-size: 12px; color: var(--yellow); font-weight: 500; }}

            /* 名称行：独占一行，加大 */
            .col-name {{ flex: 1 1 100%; order: 0; font-size: 15px; font-weight: 600; margin-bottom: 2px; }}
            .col-code {{ display: inline; margin-left: 6px; font-size: 11px; color: var(--text-muted); font-weight: 400; }}

            /* 其它字段：用 data-label 前缀 + 网格化 */
            .col-amount-cell, .col-pct, .col-rec-cell, .col-price, .col-action, .col-pnl, .col-stop {{
                flex: 1 1 30%;
                font-size: 11px;
                text-align: left !important;
            }}
            .col-amount-cell::before, .col-pct::before, .col-rec-cell::before::before, .col-price::before, .col-action::before, .col-pnl::before, .col-stop::before {{
                content: attr(data-label);
                display: block;
                font-size: 10px;
                color: var(--text-muted);
                margin-bottom: 2px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }}
            .col-rec-cell::before::before {{ text-align: left; }}
            .col-rec-cell,            .col-amount-cell {{ display: block; }}

            .profit, .loss {{ font-weight: 500; }}
            .buy-tag {{ font-size: 9px; padding: 0 4px; margin-left: 2px; }}
            .stop-tag-inline {{ font-size: 10px; padding: 0 4px; }}

            /* 折叠区头部：紧凑 */
            .section-header {{ padding: 10px 12px; font-size: 12px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="meta">策略跟踪：突破时买入，回撤10%止损或者创新高后高点回撤10%止盈。不构成投资建议，投资有风险，自己理性把握。 | 更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
            <div style="color:#ff4444;font-weight:700;font-size:14px;text-align:left;padding:6px 0;letter-spacing:0.5px;">注意关注数据更新日期，最近突破股票很少，建议不要做，市场风险巨大。</div>
        </div>
        <div class="stock-table">
            <div class="stock-header">
                <span class="col-date">选股日期</span>
                <span class="col-name">股票名称</span>
                <span class="col-code">代码</span>
                <span class="col-amount">成交额</span>
                <span class="col-pct">当日涨幅</span>
                <span class="col-rec">信号强度</span>
                <span class="col-price">买入价</span>
                <span class="col-action">持仓动作</span>
                <span class="col-pnl">浮动盈亏 <button class="sort-btn" id="sort-pnl" onclick="toggleSort(event)">↕</button></span>
                <span class="col-stop">止损/止盈价</span>
            </div>
            <div id="rows-container">
            {active_rows}
            </div>
        </div>
        <div class="stopped-section">
            <div class="section-header" onclick="toggleStopped()">
                <span id="stopped-label">已出局 ({stopped_count} 只)</span>
                <span id="stopped-toggle">▶</span>
            </div>
            <div id="stopped-rows" class="collapsed">
            {stopped_rows}
            </div>
        </div>
        <div class="watch-section">
            <div class="section-header watch-header">
                <span>待突破股票池 ({watch_count} 只)</span>
            </div>
            <div class="stock-header">
                <span class="col-date">选股日期</span>
                <span class="col-name">股票名称</span>
                <span class="col-code">代码</span>
                <span class="col-amount">成交额</span>
                <span class="col-pct">当日涨幅</span>
                <span class="col-rec">信号强度</span>
                <span class="col-price">买入价</span>
                <span class="col-action">持仓动作</span>
                <span class="col-pnl">浮动盈亏</span>
                <span class="col-stop">止损/止盈价</span>
            </div>
            <div id="watch-rows">
            {watch_rows}
            </div>
        </div>
        <div class="footer">选股策略跟踪系统 | 数据源: data_hub (Sina/Baostock/Akshare)</div>
    </div>
    <script>
        const container = document.getElementById('rows-container');
        const originalRows = Array.from(container.querySelectorAll('.stock-row'));
        let sortState = 0;
        
        function toggleSort(e) {{
            e.preventDefault();
            e.stopPropagation();
            const btn = document.getElementById('sort-pnl');
            sortState = (sortState + 1) % 3;
            
            let rows;
            if (sortState === 0) {{
                rows = [...originalRows];
                btn.textContent = '↕';
                btn.classList.remove('active');
            }} else if (sortState === 1) {{
                rows = [...originalRows].sort((a, b) => 
                    parseFloat(b.dataset.pnl) - parseFloat(a.dataset.pnl));
                btn.textContent = '↓';
                btn.classList.add('active');
                rows.forEach(r => r.classList.remove('date-border'));
            }} else {{
                rows = [...originalRows].sort((a, b) => 
                    parseFloat(a.dataset.pnl) - parseFloat(b.dataset.pnl));
                btn.textContent = '↑';
                btn.classList.add('active');
                rows.forEach(r => r.classList.remove('date-border'));
            }}
            
            if (sortState === 0) {{
                originalRows.forEach(r => {{
                    if (r.dataset.originalBorder === 'true') {{
                        r.classList.add('date-border');
                    }}
                }});
            }}
            
            container.innerHTML = '';
            rows.forEach(r => container.appendChild(r));
        }}
        
        originalRows.forEach(r => {{
            r.dataset.originalBorder = r.classList.contains('date-border') ? 'true' : 'false';
        }});
        
        function toggleStopped() {{
            const el = document.getElementById('stopped-rows');
            const arrow = document.getElementById('stopped-toggle');
            el.classList.toggle('collapsed');
            arrow.textContent = el.classList.contains('collapsed') ? '▶' : '▼';
        }}
    </script>

    <!-- 公众号二维码弹窗 -->
    <div id="qr-modal" style="display:-webkit-flex;display:flex;position:fixed;top:0;left:0;right:0;bottom:0;z-index:9999;background:rgba(0,0,0,0.75);-webkit-align-items:center;align-items:center;-webkit-justify-content:center;justify-content:center;">
        <div style="background:#1e2030;border:1px solid #3b4261;border-radius:12px;padding:32px 28px;text-align:center;max-width:320px;width:88%;box-shadow:0 8px 40px rgba(0,0,0,0.6);">
            <div style="font-size:16px;color:#e0af68;font-weight:600;margin-bottom:8px;">为防止失联，请关注！</div>
            <div style="font-size:12px;color:#a9b1d6;margin-bottom:16px;">扫码关注公众号，获取最新选股推送</div>
            <img src="data:image/jpeg;base64,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" alt="公众号二维码" style="width:200px;height:200px;border-radius:8px;display:block;margin:0 auto 20px;" />
            <button onclick="closeQrModal()" style="background:#7aa2f7;color:#1a1b26;border:none;border-radius:6px;padding:10px 32px;font-size:14px;cursor:pointer;font-weight:600;-webkit-appearance:none;">我已关注，关闭</button>
        </div>
    </div>
    <script>
        (function(){{
            try {{
                var key = 'qr_modal_closed';
                var last = localStorage.getItem(key);
                if (last && Date.now() - parseInt(last) < 7*24*3600*1000) {{
                    document.getElementById('qr-modal').style.display = 'none';
                }}
            }} catch(e) {{}}
        }})();
        function closeQrModal(){{
            try {{ localStorage.setItem('qr_modal_closed', String(Date.now())); }} catch(e) {{}}
            document.getElementById('qr-modal').style.display = 'none';
        }}
    </script>
</body>
</html>"""


def generate_full_report(output_dir="tracker_report"):
    """生成完整报告（仅生成总览，详情页改用 iwencai 外链）"""
    from data_hub.completeness import check_completeness
    # 数据完整性检查
    try:
        selections = load_selections()
        all_codes = set()
        for date_key, payload in selections.items():
            items = payload.get('stocks', []) if isinstance(payload, dict) else (payload or [])
            for it in items:
                if isinstance(it, dict) and it.get('code'):
                    all_codes.add(it['code'])
        if all_codes:
            report = check_completeness(list(all_codes), datetime.now().strftime('%Y-%m-%d'))
            if report.get('missing_pct', 0) > 10:
                print(f"[tracker] KlineDB 缺失 {len(report.get('missing_codes',[]))} 只股票数据，报告可能不完整")
    except Exception:
        pass
    os.makedirs(output_dir, exist_ok=True)
    
    # 清理旧的本地详情页文件（改为外链后不再需要）
    try:
        for fn in os.listdir(output_dir):
            if fn.startswith("detail_") and fn.endswith(".html"):
                os.remove(os.path.join(output_dir, fn))
    except FileNotFoundError:
        pass
    
    # 生成总览页
    index_html = generate_index_page(output_dir)
    index_file = f"{output_dir}/index.html"
    with open(index_file, 'w', encoding='utf-8') as f:
        f.write(index_html)
    
    print(f"报告已生成: {index_file}")
    return index_file


if __name__ == "__main__":
    generate_full_report()

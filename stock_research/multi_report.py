"""多维回测 HTML 报告 (Tokyo Night)"""
from __future__ import annotations
from datetime import datetime
import pandas as pd

from .config import OUTPUT_DIR
from .holding_period import HORIZONS

CSS = """
:root {
  --bg-primary: #1a1b26; --bg-secondary: #24283b; --bg-tertiary: #292e42;
  --text-primary: #c0caf5; --text-secondary: #a9b1d6; --text-muted: #565f89;
  --green: #9ece6a; --red: #f7768e; --yellow: #e0af68; --blue: #7aa2f7;
  --purple: #bb9af7; --border: #3b4261;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'JetBrains Mono','Fira Code',monospace; background:var(--bg-primary);
  color:var(--text-primary); padding:24px; font-size:13px; }
.container { max-width:1280px; margin:0 auto; }
h1 { color:var(--green); font-size:22px; margin-bottom:8px; }
.meta { color:var(--text-muted); font-size:12px; margin-bottom:24px; }
.section { margin-bottom:30px; }
.section-title { color:var(--yellow); font-size:14px; margin-bottom:12px;
  padding-left:10px; border-left:3px solid var(--yellow); }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; }
.card { background:var(--bg-secondary); border:1px solid var(--border); border-radius:6px; padding:12px; }
.card .label { color:var(--text-muted); font-size:11px; text-transform:uppercase; }
.card .value { font-size:18px; font-weight:600; margin-top:4px; }
.card .value.profit { color:var(--green); }
.card .value.loss { color:var(--red); }
table { width:100%; border-collapse:collapse; background:var(--bg-secondary); border:1px solid var(--border); border-radius:6px; overflow:hidden; font-size:12px; }
th, td { padding:8px 10px; text-align:right; border-bottom:1px solid var(--border); }
th { background:var(--bg-tertiary); color:var(--text-muted); text-transform:uppercase; font-size:10px; font-weight:500; }
th:first-child, td:first-child { text-align:left; color:var(--blue); }
tr:last-child td { border-bottom:none; }
td.pos { color:var(--green); }
td.neg { color:var(--red); }
td.weak { color:var(--text-muted); }
.findings { background:var(--bg-secondary); border:1px solid var(--border); border-radius:6px; padding:14px; }
.findings ol { margin-left:20px; line-height:1.8; }
.findings li { color:var(--text-secondary); }
.heatmap td { font-weight:600; }
details { margin-bottom:10px; }
summary { cursor:pointer; color:var(--blue); padding:6px 0; }
.flag { color:var(--text-muted); font-size:10px; padding-left:4px; }
"""


def _color_class(v):
    if v is None or pd.isna(v):
        return 'weak'
    return 'pos' if v > 0 else ('neg' if v < 0 else 'weak')


def _fmt_pct(v):
    if v is None or pd.isna(v):
        return '-'
    return f'{v * 100:+.1f}%'


def _fmt_num(v, digits=2):
    if v is None or pd.isna(v):
        return '-'
    return f'{v:.{digits}f}'


def _slice_table_html(df: pd.DataFrame, dim: str) -> str:
    if df is None or df.empty:
        return f'<p class="weak">无数据</p>'
    rows = []
    cols = ['bucket', 'n'] + [f'ret_{h}_mean' for h in HORIZONS] + ['win_30', 'max_dd_30_mean', 'breakdown_ratio']
    head = '<tr>' + ''.join(f'<th>{c}</th>' for c in cols) + '</tr>'
    for _, r in df.iterrows():
        cells = [f'<td>{r["bucket"]}</td>', f'<td>{int(r["n"])}</td>']
        for h in HORIZONS:
            v = r.get(f'ret_{h}_mean')
            cells.append(f'<td class="{_color_class(v)}">{_fmt_pct(v)}</td>')
        win = r.get('win_30')
        cells.append(f'<td>{_fmt_pct(win) if win is not None and not pd.isna(win) else "-"}</td>')
        dd = r.get('max_dd_30_mean')
        cells.append(f'<td class="{_color_class(dd)}">{_fmt_pct(dd)}</td>')
        bd = r.get('breakdown_ratio')
        cells.append(f'<td>{_fmt_pct(bd) if bd is not None and not pd.isna(bd) else "-"}</td>')
        flag = ''
        if r.get('flag') == 'n_too_small':
            flag = '<span class="flag">⚠样本少</span>'
        rows.append('<tr>' + ''.join(cells) + '</tr>')
        if flag:
            rows[-1] = rows[-1].replace('<td>' + str(r['bucket']) + '</td>',
                                        f'<td>{r["bucket"]}{flag}</td>')
    return f'<table>{head}{"".join(rows)}</table>'


def _heatmap_html(mean_pv: pd.DataFrame, n_pv: pd.DataFrame, title: str) -> str:
    if mean_pv is None or mean_pv.empty:
        return ''
    cols = list(mean_pv.columns)
    head = '<tr><th>{}</th>'.format(mean_pv.index.name or 'row') + ''.join(f'<th>{c}</th>' for c in cols) + '</tr>'
    rows = []
    for idx, row in mean_pv.iterrows():
        cells = [f'<td>{idx}</td>']
        for c in cols:
            v = row[c]
            n = n_pv.loc[idx, c] if (idx in n_pv.index and c in n_pv.columns) else None
            n_str = f' (n={int(n)})' if n and not pd.isna(n) else ''
            cells.append(f'<td class="{_color_class(v)}">{_fmt_pct(v)}{n_str}</td>')
        rows.append('<tr>' + ''.join(cells) + '</tr>')
    return f'<div class="section"><div class="section-title">// {title}</div><table class="heatmap">{head}{"".join(rows)}</table></div>'


def _findings_html(findings: list[str]) -> str:
    if not findings:
        return '<p class="weak">暂无显著发现</p>'
    items = ''.join(f'<li>{f}</li>' for f in findings)
    return f'<div class="findings"><ol>{items}</ol></div>'


def _summary_cards(risk_df: pd.DataFrame) -> str:
    if risk_df is None or risk_df.empty:
        return ''
    d = dict(zip(risk_df['metric'], risk_df['value']))
    pick = [
        ('总样本', d.get('n_total'), 'int'),
        ('30日已结算', d.get('n_30d_resolved'), 'int'),
        ('30日胜率', d.get('win_rate_30'), 'pct'),
        ('30日均值', d.get('ret_30_mean'), 'pct'),
        ('Sharpe (近似)', d.get('sharpe_approx'), 'num'),
        ('盈亏比', d.get('profit_loss_ratio'), 'num'),
        ('Breakdown 比例', d.get('breakdown_ratio_30'), 'pct'),
        ('α(vs HS300)', d.get('alpha_30_mean'), 'pct'),
        ('α 胜率', d.get('alpha_30_win_rate'), 'pct'),
        ('止损命中率', d.get('stop_hit_rate'), 'pct'),
    ]
    cards = []
    for label, val, kind in pick:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            disp, klass = '-', 'weak'
        elif kind == 'pct':
            disp = _fmt_pct(val)
            klass = _color_class(val)
        elif kind == 'int':
            disp = str(int(val))
            klass = ''
        else:
            disp = _fmt_num(val)
            klass = ''
        cards.append(f'<div class="card"><div class="label">{label}</div>'
                     f'<div class="value {klass}">{disp}</div></div>')
    return '<div class="cards">' + ''.join(cards) + '</div>'


def _cohort_table(cohort_df: pd.DataFrame) -> str:
    if cohort_df is None or cohort_df.empty:
        return '<p class="weak">无数据</p>'
    head = '<tr><th>月份</th><th>样本</th><th>ret_30 mean</th><th>胜率</th><th>max_dd</th><th>状态</th></tr>'
    rows = []
    for _, r in cohort_df.iterrows():
        flag = '<span class="flag">⚠失效</span>' if r.get('underperform') == 1 else ''
        rows.append('<tr>'
                    f'<td>{r["month"]}{flag}</td>'
                    f'<td>{int(r["n"])}</td>'
                    f'<td class="{_color_class(r["ret_30_mean"])}">{_fmt_pct(r["ret_30_mean"])}</td>'
                    f'<td>{_fmt_pct(r["win_rate_30"])}</td>'
                    f'<td class="{_color_class(r.get("max_dd_30_mean"))}">{_fmt_pct(r.get("max_dd_30_mean"))}</td>'
                    f'<td>{"-" if pd.isna(r.get("underperform")) else ("⚠" if r.get("underperform") == 1 else "✓")}</td>'
                    '</tr>')
    return f'<table>{head}{"".join(rows)}</table>'


def render(slices: dict, crosses: dict, risk_df: pd.DataFrame,
           cohort_df: pd.DataFrame, findings: list[str]) -> str:
    summary = _summary_cards(risk_df)
    findings_block = _findings_html(findings)
    slice_blocks = []
    for dim, s in slices.items():
        slice_blocks.append(
            f'<details open><summary>{dim} ({len(s)} 桶)</summary>{_slice_table_html(s, dim)}</details>'
        )
    cross_blocks = []
    for k, payload in crosses.items():
        cross_blocks.append(_heatmap_html(payload['mean'], payload['n'], k.replace('__', ' × ') + ' (ret_30)'))
    cohort_block = _cohort_table(cohort_df)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>多维度回测报告</title><style>{CSS}</style></head>
<body><div class="container">
<h1>多维度历史回测报告</h1>
<div class="meta">生成时间 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · 策略: 突破/涨停 + 10% 移动止损</div>

<div class="section"><div class="section-title">// 整体摘要</div>{summary}</div>
<div class="section"><div class="section-title">// 关键发现 Top 5</div>{findings_block}</div>
<div class="section"><div class="section-title">// 单维度切片</div>{''.join(slice_blocks)}</div>
{''.join(cross_blocks)}
<div class="section"><div class="section-title">// Cohort 月度表现</div>{cohort_block}</div>

</div></body></html>"""
    out = OUTPUT_DIR / 'multi_backtest_report.html'
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'[multi_report] -> {out}')
    return str(out)

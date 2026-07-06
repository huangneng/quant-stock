"""HTML 报告生成（Tokyo Night 风格）

包含：
- 样本量与标签分布
- Top 因子箱线图（matplotlib base64 内联）
- 各标签下 Top 因子的中位数表
- 决策树规则
- 时间切分验证结果
- 典型样本 Case
"""
from __future__ import annotations
import base64
import io
from datetime import datetime

import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from .config import OUTPUT_DIR, SPLIT_DATE


PALETTE = {
    'bg': '#1a1b26', 'card': '#24283b', 'text': '#c0caf5', 'muted': '#565f89',
    'blue': '#7aa2f7', 'green': '#9ece6a', 'red': '#f7768e', 'yellow': '#e0af68',
    'purple': '#bb9af7',
}
LABEL_COLOR = {
    'strong': PALETTE['green'],
    'breakdown': PALETTE['red'],
    'oscillate': PALETTE['yellow'],
    'weak': PALETTE['muted'],
}


def _fig_to_base64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=110, bbox_inches='tight', facecolor=PALETTE['bg'])
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _set_dark(ax):
    ax.set_facecolor(PALETTE['card'])
    for spine in ax.spines.values():
        spine.set_color(PALETTE['muted'])
    ax.tick_params(colors=PALETTE['text'])
    ax.xaxis.label.set_color(PALETTE['text'])
    ax.yaxis.label.set_color(PALETTE['text'])
    ax.title.set_color(PALETTE['blue'])
    ax.grid(True, color=PALETTE['muted'], alpha=0.2)


def chart_label_dist(df: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(6, 4), facecolor=PALETTE['bg'])
    counts = df['label'].value_counts()
    colors = [LABEL_COLOR.get(l, PALETTE['blue']) for l in counts.index]
    bars = ax.bar(counts.index, counts.values, color=colors, edgecolor=PALETTE['bg'])
    for b, v in zip(bars, counts.values):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.3, str(v),
                ha='center', color=PALETTE['text'], fontsize=11)
    ax.set_title('label distribution')
    _set_dark(ax)
    return _fig_to_base64(fig)


def chart_top_features(df: pd.DataFrame, ranking: pd.DataFrame, top_k: int = 6) -> str:
    cols = ranking.head(top_k)['feature'].tolist()
    if not cols:
        return ''
    fig, axes = plt.subplots(2, 3, figsize=(13, 7), facecolor=PALETTE['bg'])
    axes = axes.flatten()
    label_order = ['strong', 'oscillate', 'weak', 'breakdown']
    label_order = [l for l in label_order if l in df['label'].unique()]

    for i, col in enumerate(cols):
        if i >= len(axes):
            break
        ax = axes[i]
        data = [df[df['label'] == l][col].dropna().values for l in label_order]
        bp = ax.boxplot(data, labels=label_order, patch_artist=True,
                         medianprops={'color': PALETTE['yellow'], 'linewidth': 2})
        for patch, l in zip(bp['boxes'], label_order):
            patch.set_facecolor(LABEL_COLOR.get(l, PALETTE['blue']))
            patch.set_alpha(0.55)
            patch.set_edgecolor(PALETTE['text'])
        for whisker in bp['whiskers'] + bp['caps']:
            whisker.set_color(PALETTE['text'])
        ax.set_title(col)
        _set_dark(ax)
    for j in range(len(cols), len(axes)):
        axes[j].axis('off')
        axes[j].set_facecolor(PALETTE['bg'])
    fig.tight_layout()
    return _fig_to_base64(fig)


def render_html(merged: pd.DataFrame, ranking: pd.DataFrame, tree_rules: str,
                split_info: dict) -> str:
    label_chart = chart_label_dist(merged)
    feature_chart = chart_top_features(merged, ranking)

    # Top 因子表
    top_rows = ''
    for _, r in ranking.head(10).iterrows():
        top_rows += (
            f"<tr><td>{r['feature']}</td>"
            f"<td>{r['p']:.3e}</td>"
            f"<td>{r.get('med_strong', float('nan')):.4g}</td>"
            f"<td>{r.get('med_oscillate', float('nan')):.4g}</td>"
            f"<td>{r.get('med_weak', float('nan')):.4g}</td>"
            f"<td>{r.get('med_breakdown', float('nan')):.4g}</td></tr>"
        )

    # Case 列表（每类抽 5 条，按入选日倒序）
    case_html = ''
    for label in ['strong', 'breakdown', 'oscillate', 'weak']:
        sub = merged[merged['label'] == label].sort_values('entry_date', ascending=False).head(5)
        if sub.empty:
            continue
        rows = ''
        for _, r in sub.iterrows():
            rows += (f"<tr><td>{r['entry_date']}</td>"
                     f"<td>{r['code']}</td>"
                     f"<td>{r.get('signal_type', '')}</td>"
                     f"<td>{r.get('amount_today_yi', float('nan')):.2f}</td>"
                     f"<td>{r.get('amount_ratio_20d', float('nan')):.2f}</td>"
                     f"<td>{r.get('turnover_today', float('nan')):.2f}</td></tr>")
        color = LABEL_COLOR.get(label, PALETTE['blue'])
        case_html += (
            f'<h3 style="color:{color}">{label} · 最近 {len(sub)} 例</h3>'
            f'<table><thead><tr><th>入选日</th><th>代码</th><th>信号</th>'
            f'<th>当日成交额(亿)</th><th>量比20d</th><th>换手率</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>'
        )

    split_block = ''
    if split_info.get('train_acc') is not None:
        split_block = (
            f'<p>切分日期: <code>{SPLIT_DATE}</code> ｜ '
            f'训练集: {split_info["train_n"]} / 测试集: {split_info["test_n"]} ｜ '
            f'训练准确率: <b>{split_info["train_acc"]:.3f}</b> ｜ '
            f'测试准确率: <b>{split_info["test_acc"]:.3f}</b></p>'
        )
    else:
        split_block = '<p class="muted">样本量不足以做时间切分</p>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>选股后走势归因报告</title>
<style>
body {{ background:{PALETTE['bg']}; color:{PALETTE['text']};
       font-family:-apple-system,"PingFang SC",Helvetica,sans-serif;
       padding:24px; max-width:1200px; margin:0 auto; }}
h1, h2, h3 {{ color:{PALETTE['blue']}; }}
.muted {{ color:{PALETTE['muted']}; }}
.card {{ background:{PALETTE['card']}; padding:18px 22px; border-radius:8px;
        margin-bottom:20px; }}
table {{ border-collapse:collapse; width:100%; margin-top:8px; font-size:13px; }}
th, td {{ padding:8px 10px; border-bottom:1px solid {PALETTE['muted']};
         text-align:left; }}
th {{ color:{PALETTE['blue']}; background:{PALETTE['bg']}; }}
pre {{ background:{PALETTE['bg']}; padding:12px; border-radius:6px;
      color:{PALETTE['green']}; overflow:auto; font-size:12px;
      border:1px solid {PALETTE['muted']}; }}
img {{ max-width:100%; border-radius:6px; }}
code {{ background:{PALETTE['bg']}; padding:2px 6px; border-radius:3px;
       color:{PALETTE['yellow']}; }}
.small {{ font-size:12px; color:{PALETTE['muted']}; }}
</style></head>
<body>
<h1>选股后走势归因报告</h1>
<p class="small">生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ·
样本数: {len(merged)}</p>

<div class="card">
  <h2>1. 标签分布</h2>
  <img src="data:image/png;base64,{label_chart}">
</div>

<div class="card">
  <h2>2. Top 因子箱线图</h2>
  <img src="data:image/png;base64,{feature_chart}">
</div>

<div class="card">
  <h2>3. 因子区分度排名（Kruskal-Wallis）</h2>
  <table><thead><tr><th>因子</th><th>p 值</th><th>strong</th>
  <th>oscillate</th><th>weak</th><th>breakdown</th></tr></thead>
  <tbody>{top_rows}</tbody></table>
  <p class="small">中位数列；p 越小区分度越高</p>
</div>

<div class="card">
  <h2>4. 决策树规则</h2>
  <pre>{tree_rules}</pre>
</div>

<div class="card">
  <h2>5. 时间切分验证</h2>
  {split_block}
</div>

<div class="card">
  <h2>6. 典型样本（每类最近 5 例）</h2>
  {case_html}
</div>
</body></html>"""


def build_report(merged: pd.DataFrame, ranking: pd.DataFrame,
                 tree_rules: str, split_info: dict) -> str:
    html = render_html(merged, ranking, tree_rules, split_info)
    out = OUTPUT_DIR / 'report.html'
    out.write_text(html, encoding='utf-8')
    print(f'[report_builder] -> {out}')
    return str(out)


if __name__ == '__main__':
    merged = pd.read_parquet(OUTPUT_DIR / 'merged.parquet')
    ranking = pd.read_csv(OUTPUT_DIR / 'feature_ranking.csv')
    rules = (OUTPUT_DIR / 'tree_rules.txt').read_text(encoding='utf-8')
    build_report(merged, ranking, rules, {'train_acc': None, 'test_acc': None,
                                          'train_n': 0, 'test_n': 0})

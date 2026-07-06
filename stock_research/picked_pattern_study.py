"""已选股技术形态归因研究

只在 selections.json 已经命中策略的样本里，对比：
  - 启动前 3 日（pre3_*）
  - 启动当日（量价、上影线、K 线、相对位置）
  - 启动后 3 日（post3_*）
在 30 个交易日后的真实走势分类（continuation / oscillation / breakdown）下的特征差异。

输出：
  output/picked_pattern_features.parquet
  tracker_report/pattern_study.html
  控制台 top-findings
"""
from __future__ import annotations
import argparse
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .config import SELECTIONS_FILE, OUTPUT_DIR, PROJECT_ROOT
from .data_loader import fetch_ohlcv
from .feature_extractor import extract_features


REPORT_PATH = PROJECT_ROOT / 'tracker_report' / 'pattern_study.html'
FEATURES_PATH = OUTPUT_DIR / 'picked_pattern_features.parquet'

# 标签阈值（post 窗口为 POST_WINDOW 个交易日）
POST_WINDOW = 10
CONT_RUNUP = 0.06       # +6% 以上
CONT_MAX_DD = 0.04      # 期间最大回撤 < 4%
BD_DROP = 0.05          # -5% 以上跌幅
OSC_ABS_RET = 0.03
OSC_RANGE = 0.05


def _flatten_selections(path: Path) -> list[dict]:
    """把 {date_key: {stocks: [...]}} 拍平成 [(code, entry, signal_type, is_limit_up), ...]"""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    out = []
    for date_key, day in data.items():
        # date_key 形如 "20260415"
        if len(date_key) != 8 or not date_key.isdigit():
            continue
        entry = f'{date_key[:4]}-{date_key[4:6]}-{date_key[6:]}'
        for s in day.get('stocks', []):
            out.append({
                'code': s['code'],
                'entry_date': entry,
                'signal_type': s.get('signal_type'),
                'is_limit_up': bool(s.get('is_limit_up', False)),
                'name': s.get('name', ''),
                'buy_price': s.get('buy_price'),
            })
    return out


def label_outcome(hist: pd.DataFrame, entry: str, end_iso: str) -> dict:
    """根据 entry 之后最多 POST_WINDOW 个交易日的走势打标。

    返回 dict: outcome / ret_post / mdd_post / runup_post / post_n
    outcome ∈ {continuation, oscillation, breakdown, neutral, unknown}
    """
    today_rows = hist[hist['date'] == entry]
    if today_rows.empty:
        return {'outcome': 'unknown', 'ret_post': np.nan, 'mdd_post': np.nan,
                'runup_post': np.nan, 'post_n': 0}
    close_t = float(today_rows.iloc[0]['close'])
    if close_t <= 0:
        return {'outcome': 'unknown', 'ret_post': np.nan, 'mdd_post': np.nan,
                'runup_post': np.nan, 'post_n': 0}

    post = hist[(hist['date'] > entry) & (hist['date'] <= end_iso)].head(POST_WINDOW)
    n = len(post)
    if n == 0:
        return {'outcome': 'unknown', 'ret_post': np.nan, 'mdd_post': np.nan,
                'runup_post': np.nan, 'post_n': 0}

    max_close = float(post['close'].max())
    min_close = float(post['close'].min())
    runup = max_close / close_t - 1.0
    mdd = min_close / close_t - 1.0  # 负值
    ret_final = float(post['close'].iloc[-1]) / close_t - 1.0

    # n 不够 POST_WINDOW 的样本，事件还没走完，标记 unknown 不进入对比
    if n < POST_WINDOW:
        return {'outcome': 'unknown', 'ret_post': ret_final, 'mdd_post': mdd,
                'runup_post': runup, 'post_n': n}

    if runup >= CONT_RUNUP and mdd >= -CONT_MAX_DD:
        outcome = 'continuation'
    elif mdd <= -BD_DROP:
        outcome = 'breakdown'
    elif abs(ret_final) < OSC_ABS_RET and (runup - mdd) < OSC_RANGE:
        outcome = 'oscillation'
    else:
        outcome = 'neutral'

    return {'outcome': outcome, 'ret_post': ret_final, 'mdd_post': mdd,
            'runup_post': runup, 'post_n': n}


def collect_features(end_iso: str) -> pd.DataFrame:
    picks = _flatten_selections(SELECTIONS_FILE)
    print(f'[study] selections: {len(picks)} picks across '
          f'{len(set(p["entry_date"] for p in picks))} days')

    rows = []
    skipped = 0
    for i, p in enumerate(picks):
        entry = p['entry_date']
        # 拉 [entry-150d, entry+50d] 的自然日窗口（超出今天的部分 fetch_ohlcv 自然返回少行）
        start_dt = (datetime.strptime(entry, '%Y-%m-%d') - timedelta(days=150)).strftime('%Y-%m-%d')
        end_dt = (datetime.strptime(entry, '%Y-%m-%d') + timedelta(days=50)).strftime('%Y-%m-%d')
        end_dt = min(end_dt, end_iso)
        try:
            hist = fetch_ohlcv(p['code'], start_dt, end_dt)
        except Exception as e:
            print(f'[skip] {p["code"]} @ {entry} fetch error: {e}')
            skipped += 1
            continue
        if hist is None or hist.empty:
            print(f'[skip] {p["code"]} @ {entry} empty hist')
            skipped += 1
            continue

        feat = extract_features({
            'code': p['code'],
            'entry_date': entry,
            'signal_type': p['signal_type'],
            'is_limit_up': p['is_limit_up'],
            'hist': hist,
        })
        if feat is None:
            print(f'[skip] {p["code"]} @ {entry} extract_features=None')
            skipped += 1
            continue

        outcome = label_outcome(hist, entry, end_iso)
        feat.update(outcome)
        feat['name'] = p['name']
        feat['buy_price'] = p['buy_price']
        rows.append(feat)

    df = pd.DataFrame(rows)
    print(f'[study] collected {len(df)} feature rows, skipped {skipped}')
    df.to_parquet(FEATURES_PATH, index=False)
    print(f'[study] saved -> {FEATURES_PATH}')
    return df


def compare_by_outcome(df: pd.DataFrame) -> pd.DataFrame:
    """对每个数值特征做 continuation vs breakdown t-test，按效应量排序。"""
    from scipy import stats

    # 排除非数值与不应入对比的列
    blacklist = {
        'code', 'entry_date', 'signal_type', 'name', 'buy_price', 'outcome',
        'ret_post', 'mdd_post', 'runup_post', 'post_n',
    }
    num_cols = [c for c in df.columns
                if c not in blacklist and pd.api.types.is_numeric_dtype(df[c])]

    cont = df[df['outcome'] == 'continuation']
    osc = df[df['outcome'] == 'oscillation']
    bd = df[df['outcome'] == 'breakdown']
    n_cont, n_osc, n_bd = len(cont), len(osc), len(bd)
    print(f'[study] outcome distribution: cont={n_cont} osc={n_osc} bd={n_bd} '
          f'neutral={(df["outcome"]=="neutral").sum()} unknown={(df["outcome"]=="unknown").sum()}')

    rows = []
    for col in num_cols:
        c_vals = cont[col].dropna().values
        b_vals = bd[col].dropna().values
        o_vals = osc[col].dropna().values
        if len(c_vals) < 2 or len(b_vals) < 2:
            continue
        c_mean, c_std = float(np.mean(c_vals)), float(np.std(c_vals, ddof=1))
        b_mean, b_std = float(np.mean(b_vals)), float(np.std(b_vals, ddof=1))
        o_mean = float(np.mean(o_vals)) if len(o_vals) > 0 else float('nan')
        # Welch t-test
        try:
            t_stat, p_val = stats.ttest_ind(c_vals, b_vals, equal_var=False, nan_policy='omit')
        except Exception:
            t_stat, p_val = float('nan'), float('nan')
        # 标准化差异（Cohen's d）
        pooled = math.sqrt((c_std**2 + b_std**2) / 2) if (c_std and b_std) else 0.0
        effect = (c_mean - b_mean) / pooled if pooled > 1e-12 else 0.0
        sig = ''
        if not np.isnan(p_val):
            if p_val < 0.001:
                sig = '***'
            elif p_val < 0.01:
                sig = '**'
            elif p_val < 0.05:
                sig = '*'
        rows.append({
            'feature': col,
            'cont_mean': c_mean, 'osc_mean': o_mean, 'bd_mean': b_mean,
            'cont_n': len(c_vals), 'osc_n': len(o_vals), 'bd_n': len(b_vals),
            'diff_cont_bd': c_mean - b_mean,
            'effect_size': effect,
            't_stat': float(t_stat) if not np.isnan(t_stat) else float('nan'),
            'p_value': float(p_val) if not np.isnan(p_val) else float('nan'),
            'sig': sig,
        })
    cmp_df = pd.DataFrame(rows)
    if cmp_df.empty:
        return cmp_df
    cmp_df = cmp_df.reindex(cmp_df['effect_size'].abs().sort_values(ascending=False).index)
    return cmp_df.reset_index(drop=True)


def _ab_to_em(code: str) -> str:
    """sz.002361 -> 002361.SZ for 股市通 链接"""
    if '.' not in code:
        return code
    pre, num = code.split('.', 1)
    return f'{num}.{pre.upper()}'


def render_html(df: pd.DataFrame, cmp_df: pd.DataFrame, end_iso: str) -> str:
    n_cont = (df['outcome'] == 'continuation').sum()
    n_osc = (df['outcome'] == 'oscillation').sum()
    n_bd = (df['outcome'] == 'breakdown').sum()
    n_neu = (df['outcome'] == 'neutral').sum()
    n_unk = (df['outcome'] == 'unknown').sum()
    total = len(df)

    valid = df[df['outcome'].isin(['continuation', 'oscillation', 'breakdown', 'neutral'])]
    avg_ret = valid['ret_post'].mean() if len(valid) else float('nan')

    # 对比表 HTML（取前 20）
    top = cmp_df.head(20)
    cmp_rows_html = []
    for _, r in top.iterrows():
        cmp_rows_html.append(
            f'<tr><td>{r["feature"]}</td>'
            f'<td>{r["cont_mean"]:.4f} (n={int(r["cont_n"])})</td>'
            f'<td>{r["osc_mean"]:.4f} (n={int(r["osc_n"])})</td>'
            f'<td>{r["bd_mean"]:.4f} (n={int(r["bd_n"])})</td>'
            f'<td>{r["diff_cont_bd"]:+.4f}</td>'
            f'<td>{r["effect_size"]:+.3f}</td>'
            f'<td>{r["p_value"]:.4f} <span class="sig">{r["sig"]}</span></td></tr>'
        )
    cmp_table = '\n'.join(cmp_rows_html)

    # 样本明细 HTML
    detail_cols = ['code', 'name', 'entry_date', 'signal_type', 'outcome',
                   'ret_post', 'mdd_post', 'runup_post',
                   'upper_shadow_pct', 'body_pct', 'amount_ratio_20d',
                   'pre3_volume_slope', 'post3_break_high']
    detail_cols = [c for c in detail_cols if c in df.columns]
    detail_rows_html = []
    for _, r in df.sort_values(['entry_date', 'code']).iterrows():
        cells = []
        for c in detail_cols:
            v = r.get(c)
            if c == 'code':
                em = _ab_to_em(str(v))
                cells.append(f'<td><a href="https://gushitong.baidu.com/stock/ab-{em.split(".")[0]}" target="_blank">{v}</a></td>')
            elif c == 'outcome':
                cls = {'continuation': 'oc-cont', 'breakdown': 'oc-bd',
                       'oscillation': 'oc-osc', 'neutral': 'oc-neu',
                       'unknown': 'oc-unk'}.get(str(v), '')
                cells.append(f'<td class="{cls}">{v}</td>')
            elif isinstance(v, float):
                if math.isnan(v):
                    cells.append('<td>-</td>')
                else:
                    cells.append(f'<td>{v:.4f}</td>')
            else:
                cells.append(f'<td>{v}</td>')
        detail_rows_html.append('<tr>' + ''.join(cells) + '</tr>')
    detail_thead = ''.join(f'<th>{c}</th>' for c in detail_cols)
    detail_table = '\n'.join(detail_rows_html)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>已选股技术形态归因研究 · {end_iso}</title>
<style>
body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
        background: #f5f5f7; color: #1d1d1f; max-width: 1200px; margin: 24px auto; padding: 0 16px; }}
h1 {{ font-size: 22px; }}
h2 {{ font-size: 17px; border-left: 3px solid #0071e3; padding-left: 8px; margin-top: 28px; }}
.summary {{ background: #fff; border-radius: 12px; padding: 16px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
.summary-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-top: 8px; }}
.kpi {{ background: #fafafa; border-radius: 8px; padding: 10px; text-align: center; }}
.kpi .num {{ font-size: 22px; font-weight: 600; }}
.kpi .lbl {{ color: #6e6e73; font-size: 12px; }}
table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 12px; overflow: hidden;
         box-shadow: 0 1px 3px rgba(0,0,0,0.06); margin-top: 8px; font-size: 13px; }}
th {{ background: #f5f5f7; text-align: left; padding: 10px; font-weight: 500; color: #6e6e73; border-bottom: 1px solid #e5e5ea; }}
td {{ padding: 8px 10px; border-bottom: 1px solid #f0f0f2; }}
tr:hover {{ background: #fafafa; }}
.sig {{ color: #c41e3a; font-weight: 700; }}
.oc-cont {{ color: #2da44e; font-weight: 600; }}
.oc-bd {{ color: #c41e3a; font-weight: 600; }}
.oc-osc {{ color: #9a6700; }}
.oc-neu {{ color: #6e6e73; }}
.oc-unk {{ color: #b0b0b5; }}
.note {{ color: #6e6e73; font-size: 12px; margin-top: 6px; }}
a {{ color: #0071e3; text-decoration: none; }}
</style>
</head>
<body>
<h1>已选股技术形态归因研究 <span style="color:#6e6e73;font-size:14px;font-weight:400;">截至 {end_iso}</span></h1>
<div class="summary">
  <div class="note">对 selections.json 中 {total} 个 (code, entry_date) 样本，按事件后 30 个交易日真实走势分类，对比 pre3 / 当日 / post3 各类技术特征。</div>
  <div class="summary-grid">
    <div class="kpi"><div class="num oc-cont">{n_cont}</div><div class="lbl">持续新高</div></div>
    <div class="kpi"><div class="num oc-osc">{n_osc}</div><div class="lbl">震荡</div></div>
    <div class="kpi"><div class="num oc-bd">{n_bd}</div><div class="lbl">破位</div></div>
    <div class="kpi"><div class="num oc-neu">{n_neu}</div><div class="lbl">中性</div></div>
    <div class="kpi"><div class="num oc-unk">{n_unk}</div><div class="lbl">未走完</div></div>
  </div>
  <div class="note">post {POST_WINDOW} 日平均收益（已走完样本）：{avg_ret:+.2%}</div>
</div>

<h2>特征区分性对比（continuation vs breakdown，按 |效应量| 降序）</h2>
<table>
<thead><tr><th>特征</th><th>持续新高 均值</th><th>震荡 均值</th><th>破位 均值</th><th>cont-bd 差</th><th>效应量(d)</th><th>p 值</th></tr></thead>
<tbody>
{cmp_table}
</tbody>
</table>
<div class="note">显著性：*** p&lt;0.001 · ** p&lt;0.01 · * p&lt;0.05；效应量 = (cont_mean - bd_mean) / pooled_std。</div>

<h2>样本明细（{len(df)} 条）</h2>
<table>
<thead><tr>{detail_thead}</tr></thead>
<tbody>
{detail_table}
</tbody>
</table>

</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description='已选股技术形态归因研究')
    parser.add_argument('--end', default=None, help='截至日期 YYYY-MM-DD（默认今日）')
    args = parser.parse_args()
    end_iso = args.end or datetime.now().strftime('%Y-%m-%d')

    df = collect_features(end_iso)
    if df.empty:
        print('[study] no samples, abort')
        return

    cmp_df = compare_by_outcome(df)
    if not cmp_df.empty:
        print('\n[study] top 10 区分性最强的特征 (cont vs bd):')
        print(cmp_df.head(10)[['feature', 'cont_mean', 'bd_mean',
                                'effect_size', 'p_value', 'sig']].to_string(index=False))

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    html = render_html(df, cmp_df, end_iso)
    REPORT_PATH.write_text(html, encoding='utf-8')
    print(f'\n[study] report -> {REPORT_PATH}')


if __name__ == '__main__':
    main()

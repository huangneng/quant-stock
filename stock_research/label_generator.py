"""走势打标

读取 hist DataFrame + buy_price，输出 strong/breakdown/oscillate/weak/pending。
"""
from __future__ import annotations
import pandas as pd

from .config import POST_DAYS, LABEL_THRESHOLDS, OUTPUT_DIR


def label_trajectory(buy_price: float, post_df: pd.DataFrame) -> tuple[str, dict]:
    """
    post_df: 入选日**之后**的日线（不含入选日），按日期升序。

    返回 (label, metrics)
    """
    metrics = {
        'post_n': len(post_df),
        'ret_30': None,
        'min_low_pct': None,
        'max_high_pct': None,
        'max_dd': None,
    }
    if len(post_df) < 5:
        return 'pending', metrics

    # 截断到 30 日
    df = post_df.head(POST_DAYS).copy()
    metrics['post_n'] = len(df)

    last_close = float(df['close'].iloc[-1])
    min_low = float(df['low'].min())
    max_high = float(df['high'].max())

    metrics['ret_30'] = last_close / buy_price - 1
    metrics['min_low_pct'] = min_low / buy_price - 1
    metrics['max_high_pct'] = max_high / buy_price - 1

    # 期间最大回撤（基于 close 滚动峰值）
    cummax = df['close'].cummax()
    dd = (df['close'] / cummax - 1).min()
    metrics['max_dd'] = float(dd)

    th_break = LABEL_THRESHOLDS['breakdown']['stop_loss']
    if metrics['min_low_pct'] <= th_break:
        return 'breakdown', metrics

    s = LABEL_THRESHOLDS['strong']
    if abs(metrics['max_dd']) < s['max_dd_lt'] and metrics['ret_30'] > s['ret_30_gt']:
        return 'strong', metrics

    o = LABEL_THRESHOLDS['oscillate']
    lo, hi = o['max_dd_range']
    if abs(metrics['ret_30']) < o['abs_ret_lt'] and lo <= abs(metrics['max_dd']) <= hi:
        return 'oscillate', metrics

    return 'weak', metrics


def label_all(samples: list[dict]) -> pd.DataFrame:
    rows = []
    for s in samples:
        rec = {k: s[k] for k in ('entry_date_key', 'entry_date', 'code', 'name',
                                  'buy_price', 'signal_type', 'is_limit_up')}
        hist = s.get('hist')
        if hist is None or hist.empty:
            rec['label'] = 'missing'
            rows.append(rec)
            continue
        post = hist[hist['date'] > s['entry_date']]
        label, metrics = label_trajectory(s['buy_price'], post)
        rec['label'] = label
        rec.update(metrics)
        rows.append(rec)
    df = pd.DataFrame(rows)
    out = OUTPUT_DIR / 'labels.parquet'
    df.to_parquet(out)
    print(f'[label_generator] -> {out}')
    print(df['label'].value_counts())
    return df


if __name__ == '__main__':
    from .data_loader import load_all
    df = label_all(load_all())
    print(df.head())

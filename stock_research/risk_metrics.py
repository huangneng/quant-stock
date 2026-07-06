"""风险指标全景：胜率/盈亏比/Sharpe/最大回撤分布"""
from __future__ import annotations
import pandas as pd
import numpy as np

from .config import OUTPUT_DIR


def compute(df: pd.DataFrame) -> pd.DataFrame:
    """对 fullframe（含 ret_30, max_dd_30, days_to_peak, days_to_stop, excess_30）算汇总"""
    rets = df['ret_30'].dropna() if 'ret_30' in df else pd.Series(dtype=float)
    metrics = {}
    metrics['n_total'] = int(len(df))
    metrics['n_30d_resolved'] = int(len(rets))
    if len(rets) > 0:
        metrics['ret_30_mean'] = float(rets.mean())
        metrics['ret_30_median'] = float(rets.median())
        metrics['ret_30_std'] = float(rets.std())
        metrics['win_rate_30'] = float((rets > 0).mean())
        pos = rets[rets > 0]
        neg = rets[rets < 0]
        if len(neg) > 0 and abs(neg.mean()) > 1e-9:
            metrics['profit_loss_ratio'] = float(pos.mean() / abs(neg.mean())) if len(pos) > 0 else None
        else:
            metrics['profit_loss_ratio'] = None
        metrics['ret_30_max'] = float(rets.max())
        metrics['ret_30_min'] = float(rets.min())
        # Sharpe 近似（年化）
        if rets.std() > 1e-9:
            metrics['sharpe_approx'] = float(rets.mean() / rets.std() * np.sqrt(252 / 30))
        else:
            metrics['sharpe_approx'] = None
    if 'max_dd_30' in df.columns:
        dd = df['max_dd_30'].dropna()
        if len(dd) > 0:
            for q in (0.25, 0.50, 0.75, 0.95):
                metrics[f'max_dd_30_q{int(q * 100)}'] = float(dd.quantile(q))
            metrics['breakdown_ratio_30'] = float((dd <= -0.10).mean())
    if 'days_to_peak' in df.columns:
        v = df['days_to_peak'].dropna()
        if len(v) > 0:
            metrics['days_to_peak_median'] = float(v.median())
    if 'days_to_stop' in df.columns:
        v = df['days_to_stop'].dropna()
        triggered = v[v > 0]
        metrics['stop_hit_rate'] = float(len(triggered) / len(v)) if len(v) > 0 else None
        if len(triggered) > 0:
            metrics['days_to_stop_median'] = float(triggered.median())
    if 'excess_30' in df.columns:
        ex = df['excess_30'].dropna()
        if len(ex) > 0:
            metrics['alpha_30_mean'] = float(ex.mean())
            metrics['alpha_30_win_rate'] = float((ex > 0).mean())

    out = pd.DataFrame([{'metric': k, 'value': v} for k, v in metrics.items()])
    out.to_csv(OUTPUT_DIR / 'risk_metrics.csv', index=False)
    print('[risk_metrics] ->')
    for k, v in metrics.items():
        if v is None:
            continue
        if isinstance(v, float):
            print(f'  {k:30s} = {v:.4f}')
        else:
            print(f'  {k:30s} = {v}')
    return out


if __name__ == '__main__':
    df = pd.read_parquet(OUTPUT_DIR / 'fullframe.parquet')
    compute(df)

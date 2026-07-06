"""二维交叉切片"""
from __future__ import annotations
import pandas as pd

from .config import OUTPUT_DIR


def cross_by(dim_a: str, dim_b: str, df: pd.DataFrame, metric: str = 'ret_30') -> pd.DataFrame:
    if dim_a not in df.columns or dim_b not in df.columns or metric not in df.columns:
        return pd.DataFrame()
    sub = df.dropna(subset=[metric, dim_a, dim_b])
    if sub.empty:
        return pd.DataFrame()
    pivot_mean = sub.pivot_table(index=dim_a, columns=dim_b, values=metric,
                                 aggfunc='mean')
    pivot_n = sub.pivot_table(index=dim_a, columns=dim_b, values=metric,
                              aggfunc='count')
    return pivot_mean, pivot_n


PAIRS = [
    ('star', 'amount_tier'),
    ('star', 'signal_type'),
    ('upper_shadow_filter', 'sector'),
    ('body_pct_tier', 'pre3_red_tier'),
]


def run(df: pd.DataFrame, metric: str = 'ret_30') -> dict:
    results = {}
    for a, b in PAIRS:
        if a not in df.columns or b not in df.columns:
            continue
        res = cross_by(a, b, df, metric)
        if isinstance(res, pd.DataFrame) and res.empty:
            continue
        mean_pv, n_pv = res
        # 交错落盘：mean 与 n 各一个
        out_mean = OUTPUT_DIR / f'cross_{a}__{b}_{metric}_mean.csv'
        out_n = OUTPUT_DIR / f'cross_{a}__{b}_{metric}_n.csv'
        mean_pv.to_csv(out_mean)
        n_pv.to_csv(out_n)
        results[f'{a}__{b}'] = {'mean': mean_pv, 'n': n_pv}
        print(f'  cross [{a}×{b}] {metric} matrix shape={mean_pv.shape}')
    print(f'[cross_slice] -> {len(results)} pairs')
    return results


if __name__ == '__main__':
    df = pd.read_parquet(OUTPUT_DIR / 'fullframe.parquet')
    run(df)

"""单维度切片分析

输入：holdings + features + sector + star 合并后的全特征大表
对每个维度产出 n / ret_X / win_X / max_dd / breakdown_ratio 切片表
"""
from __future__ import annotations
import pandas as pd
import numpy as np

from .config import OUTPUT_DIR
from .holding_period import HORIZONS

MIN_BUCKET_N = 5  # 桶内样本数门槛


def amount_tier(amt) -> str:
    if amt is None or pd.isna(amt):
        return 'unknown'
    yi = float(amt) / 1e8
    if yi < 30:
        return '<30亿'
    if yi < 50:
        return '30-50亿'
    return '≥50亿'


def body_tier(body_pct) -> str:
    if body_pct is None or pd.isna(body_pct):
        return 'unknown'
    b = float(body_pct)
    if b < 0.03:
        return '小阳<3%'
    if b < 0.07:
        return '中阳3-7%'
    return '大阳≥7%'


def pre3_red_tier(rc) -> str:
    if rc is None or pd.isna(rc):
        return 'unknown'
    return f'{int(rc)}阳'


def upper_shadow_filter_tag(row) -> str:
    body = row.get('body_pct')
    upper = row.get('upper_shadow_pct')
    if body is None or pd.isna(body) or upper is None or pd.isna(upper):
        return 'unknown'
    if float(body) > 0 and float(upper) <= float(body) * 0.3:
        return 'filtered'
    return 'excluded'


def annotate(df: pd.DataFrame) -> pd.DataFrame:
    """为大表追加分桶列"""
    df = df.copy()
    df['amount_tier'] = df['amount'].map(amount_tier)
    df['body_pct_tier'] = df['body_pct'].map(body_tier) if 'body_pct' in df else 'unknown'
    df['pre3_red_tier'] = df['pre3_red_count'].map(pre3_red_tier) if 'pre3_red_count' in df else 'unknown'
    df['upper_shadow_filter'] = df.apply(upper_shadow_filter_tag, axis=1)
    return df


def _bucket_stats(group: pd.DataFrame) -> dict:
    out = {'n': len(group)}
    for h in HORIZONS:
        col = f'ret_{h}'
        if col in group.columns:
            v = group[col].dropna()
            if len(v) > 0:
                out[f'ret_{h}_mean'] = float(v.mean())
                out[f'win_{h}'] = float((v > 0).mean())
            else:
                out[f'ret_{h}_mean'] = None
                out[f'win_{h}'] = None
    if 'max_dd_30' in group.columns:
        v = group['max_dd_30'].dropna()
        out['max_dd_30_mean'] = float(v.mean()) if len(v) > 0 else None
    # breakdown_ratio：30日内出现 < -10%
    if 'max_dd_30' in group.columns:
        v = group['max_dd_30'].dropna()
        out['breakdown_ratio'] = float((v <= -0.10).mean()) if len(v) > 0 else None
    return out


def slice_by(dim: str, df: pd.DataFrame) -> pd.DataFrame:
    if dim not in df.columns:
        print(f'[slicer] dim {dim} missing')
        return pd.DataFrame()
    rows = []
    for val, g in df.groupby(dim, dropna=False):
        rec = {'bucket': val, **_bucket_stats(g)}
        if rec['n'] < MIN_BUCKET_N:
            rec['flag'] = 'n_too_small'
        rows.append(rec)
    out = pd.DataFrame(rows).sort_values('n', ascending=False).reset_index(drop=True)
    return out


DIMS = [
    'signal_type',
    'amount_tier',
    'sector',
    'is_60d_high',
    'is_120d_high',
    'body_pct_tier',
    'upper_shadow_filter',
    'pre3_red_tier',
    'star',
]


def run(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """跑所有 9 个维度，返回 dict[dim_name -> slice DataFrame]"""
    df = annotate(df)
    results = {}
    for dim in DIMS:
        if dim not in df.columns:
            print(f'[slicer] skip {dim} (missing)')
            continue
        s = slice_by(dim, df)
        out = OUTPUT_DIR / f'slice_{dim}.csv'
        s.to_csv(out, index=False)
        results[dim] = s
        # 终端打印每个切片最强/最弱
        valid = s[s['n'] >= MIN_BUCKET_N].dropna(subset=['ret_30_mean'])
        if len(valid) >= 2:
            best = valid.iloc[valid['ret_30_mean'].argmax()]
            worst = valid.iloc[valid['ret_30_mean'].argmin()]
            print(f'  [{dim}] 最强:{best["bucket"]}(n={int(best["n"])},ret30={best["ret_30_mean"]:.2%})  '
                  f'最弱:{worst["bucket"]}(n={int(worst["n"])},ret30={worst["ret_30_mean"]:.2%})')
    print(f'[slicer] -> {len(results)} dims into output/slice_*.csv')
    return results


if __name__ == '__main__':
    df = pd.read_parquet(OUTPUT_DIR / 'fullframe.parquet')
    run(df)

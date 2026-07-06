"""Cohort 月度时间分析"""
from __future__ import annotations
import pandas as pd

from .config import OUTPUT_DIR


def run(df: pd.DataFrame) -> pd.DataFrame:
    if 'entry_date' not in df.columns or 'ret_30' not in df.columns:
        return pd.DataFrame()
    sub = df.copy()
    sub['month'] = sub['entry_date'].astype(str).str.slice(0, 7)
    rows = []
    overall_win = (sub['ret_30'].dropna() > 0).mean() if sub['ret_30'].dropna().size > 0 else None
    for month, g in sub.groupby('month'):
        rets = g['ret_30'].dropna()
        if len(rets) == 0:
            continue
        rec = {
            'month': month,
            'n': len(g),
            'n_resolved': len(rets),
            'ret_30_mean': float(rets.mean()),
            'win_rate_30': float((rets > 0).mean()),
        }
        if 'max_dd_30' in g.columns:
            dd = g['max_dd_30'].dropna()
            rec['max_dd_30_mean'] = float(dd.mean()) if len(dd) > 0 else None
        # 是否失效月：胜率比整体低 > 20pp
        if overall_win is not None:
            rec['underperform'] = int(rec['win_rate_30'] < overall_win - 0.2)
        rows.append(rec)
    out = pd.DataFrame(rows).sort_values('month').reset_index(drop=True)
    out.to_csv(OUTPUT_DIR / 'cohort_monthly.csv', index=False)
    print(f'[cohort] -> cohort_monthly.csv')
    print(out.to_string(index=False))
    return out


if __name__ == '__main__':
    df = pd.read_parquet(OUTPUT_DIR / 'fullframe.parquet')
    run(df)

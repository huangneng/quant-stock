"""推荐指数事后回测：按 1-5 星分组复核标签分布与 30 日收益的单调性"""
from __future__ import annotations
import pandas as pd

from .config import OUTPUT_DIR
from .recommender import score


def _is_monotonic(series, decreasing=False) -> bool:
    """忽略 NaN，检查 1-N 是否（严格/宽松）单调"""
    vals = [v for v in series if v == v]
    if len(vals) < 3:
        return False
    diffs = [vals[i + 1] - vals[i] for i in range(len(vals) - 1)]
    if decreasing:
        return all(d <= 1e-9 for d in diffs)
    return all(d >= -1e-9 for d in diffs)


def run() -> pd.DataFrame:
    feats = pd.read_parquet(OUTPUT_DIR / 'features.parquet')
    labels = pd.read_parquet(OUTPUT_DIR / 'labels.parquet')

    rows = []
    for _, r in feats.iterrows():
        s = score(r.to_dict())
        rows.append({'code': r['code'], 'entry_date': r['entry_date'],
                     'score': s['score'], 'star': s['star']})
    rec = pd.DataFrame(rows)

    df = rec.merge(labels[['code', 'entry_date', 'label', 'ret_30']],
                   on=['code', 'entry_date'], how='inner')
    df = df[df['label'].isin(['strong', 'breakdown', 'oscillate', 'weak'])]

    if df.empty:
        print('[rec_backtest] no labeled samples, skip')
        return pd.DataFrame()

    g = df.groupby('star').agg(
        n=('code', 'size'),
        strong_ratio=('label', lambda s: (s == 'strong').mean()),
        breakdown_ratio=('label', lambda s: (s == 'breakdown').mean()),
        weak_ratio=('label', lambda s: (s == 'weak').mean()),
        ret_30_mean=('ret_30', 'mean'),
        ret_30_median=('ret_30', 'median'),
    ).round(4)

    out = OUTPUT_DIR / 'recommender_backtest.csv'
    g.to_csv(out)
    print(f'[rec_backtest] -> {out}, n={len(df)}')
    print(g.to_string())

    breakdown_mono = _is_monotonic(g['breakdown_ratio'].sort_index().values, decreasing=True)
    ret_mono = _is_monotonic(g['ret_30_mean'].sort_index().values, decreasing=False)
    print(f'\n[rec_backtest] 单调性复核（1→5 星）：')
    print(f'  breakdown_ratio 单调递减: {"✓" if breakdown_mono else "✗"}  '
          f'{[round(v, 3) for v in g["breakdown_ratio"].sort_index().values]}')
    print(f'  ret_30_mean    单调递增: {"✓" if ret_mono else "✗"}  '
          f'{[round(v, 3) for v in g["ret_30_mean"].sort_index().values]}')

    # 5 星样本数与可信度提示
    if 5 in g.index:
        n5 = int(g.loc[5, 'n'])
        if n5 < 5:
            print(f'  ⚠ 5 星样本仅 {n5} 个，统计上不显著；考虑收紧阈值')
    else:
        print(f'  ℹ 当前样本下无 5 星案例（阈值过严或样本不足）')

    return g


if __name__ == '__main__':
    run()

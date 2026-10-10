"""上影线过滤回测验证

规则：upper_shadow_pct <= body_pct * 0.3 且 body_pct > 0  → 合规组
其余 → 淘汰组

对比两组的 strong / breakdown 比例和 ret_30 收益。
"""
from __future__ import annotations
import pandas as pd

from .config import OUTPUT_DIR


def split_groups(df: pd.DataFrame, ratio: float = 0.3) -> tuple[pd.DataFrame, pd.DataFrame]:
    cond = (df['body_pct'] > 0) & (df['upper_shadow_pct'] <= df['body_pct'] * ratio)
    return df[cond].copy(), df[~cond].copy()


def group_stats(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return {'n': 0}
    counts = df['label'].value_counts()
    out = {
        'n': n,
        'strong_ratio': counts.get('strong', 0) / n,
        'breakdown_ratio': counts.get('breakdown', 0) / n,
        'oscillate_ratio': counts.get('oscillate', 0) / n,
        'weak_ratio': counts.get('weak', 0) / n,
    }
    if 'ret_30' in df.columns:
        out['ret_30_mean'] = float(df['ret_30'].mean())
        out['ret_30_median'] = float(df['ret_30'].median())
    return out


def validate(merged_with_ret: pd.DataFrame) -> pd.DataFrame:
    """merged 必须含 label / upper_shadow_pct / body_pct / ret_30 列"""
    a, b = split_groups(merged_with_ret)
    rows = [
        {'group': 'filtered (上影<=0.3*实体)', **group_stats(a)},
        {'group': 'excluded', **group_stats(b)},
        {'group': 'overall', **group_stats(merged_with_ret)},
    ]
    out = pd.DataFrame(rows)
    out.to_csv(OUTPUT_DIR / 'validation.csv', index=False)
    print('[validator] saved -> output/validation.csv')
    print(out.to_string(index=False))

    # 结论
    a_strong = rows[0].get('strong_ratio', 0) or 0
    b_strong = rows[1].get('strong_ratio', 0) or 0
    a_break = rows[0].get('breakdown_ratio', 0) or 0
    b_break = rows[1].get('breakdown_ratio', 0) or 0
    print(f'\n[validator] 结论：')
    print(f'  strong:    filtered {a_strong:.1%}  vs  excluded {b_strong:.1%}  '
          f'( delta {(a_strong - b_strong)*100:+.1f} pp )')
    print(f'  breakdown: filtered {a_break:.1%}  vs  excluded {b_break:.1%}  '
          f'( delta {(a_break - b_break)*100:+.1f} pp )')
    return out


def run():
    merged = pd.read_parquet(OUTPUT_DIR / 'merged.parquet')
    labels = pd.read_parquet(OUTPUT_DIR / 'labels.parquet')
    if 'ret_30' not in merged.columns and 'ret_30' in labels.columns:
        merged = merged.merge(
            labels[['code', 'entry_date', 'ret_30']],
            on=['code', 'entry_date'], how='left',
        )
    return validate(merged)


if __name__ == '__main__':
    run()

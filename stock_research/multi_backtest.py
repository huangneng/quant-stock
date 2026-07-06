"""多维度回测协调入口

串联：
  load_all → holding_period → sector → alpha
        → 合并 features + recommender 星级
        → slicer / cross_slice / risk_metrics / cohort / findings
        → multi_report.render
"""
from __future__ import annotations
import pandas as pd

from .config import OUTPUT_DIR
from . import holding_period, sector_map, alpha
from . import slicer, cross_slice, risk_metrics, cohort, findings, multi_report
from . import recommender


def _build_fullframe(samples: list[dict] | None = None) -> pd.DataFrame:
    """合并 holdings_matrix + features + sector + recommender star → 全量大表"""
    # 1. holdings_matrix
    hm_path = OUTPUT_DIR / 'holdings_matrix.parquet'
    if samples is not None:
        holdings = holding_period.build(samples)
    elif hm_path.exists():
        holdings = pd.read_parquet(hm_path)
    else:
        from .data_loader import load_all
        holdings = holding_period.build(load_all())

    # 2. sector
    holdings = sector_map.add_sector(holdings, code_col='code')

    # 3. alpha (excess_X 列)
    holdings = alpha.compute_alpha(holdings)
    # alpha.compute_alpha 已写 alpha_30.csv，并返回带 excess 列的 DataFrame

    # 4. 合并 features
    feats_path = OUTPUT_DIR / 'features.parquet'
    if feats_path.exists():
        feats = pd.read_parquet(feats_path)
        keep = [c for c in feats.columns if c not in holdings.columns or c in ('code', 'entry_date')]
        feats_sub = feats[keep] if 'code' in feats.columns and 'entry_date' in feats.columns else feats
        if 'code' in feats_sub.columns and 'entry_date' in feats_sub.columns:
            full = holdings.merge(feats_sub, on=['code', 'entry_date'], how='left')
        else:
            print('[multi_backtest] features.parquet 缺少 code/entry_date，跳过合并')
            full = holdings
    else:
        print('[multi_backtest] features.parquet 不存在，跳过合并')
        full = holdings

    # 5. 推荐指数 star
    if 'star' not in full.columns:
        try:
            scores_path = OUTPUT_DIR / 'recommend_scores.csv'
            if scores_path.exists():
                rec = pd.read_csv(scores_path)
                rec = rec[['code', 'entry_date', 'star']]
                full = full.merge(rec, on=['code', 'entry_date'], how='left')
            elif feats_path.exists():
                rec = recommender.batch_score(pd.read_parquet(feats_path))
                full = full.merge(rec[['code', 'entry_date', 'star']],
                                  on=['code', 'entry_date'], how='left')
        except Exception as e:
            print(f'[multi_backtest] star 合并失败: {e}')

    # 6. annotate（amount_tier / body_pct_tier / pre3_red_tier / upper_shadow_filter）
    full = slicer.annotate(full)

    # 7. 落盘
    out = OUTPUT_DIR / 'fullframe.parquet'
    full.to_parquet(out)
    print(f'[multi_backtest] fullframe -> {out} (rows={len(full)}, cols={full.shape[1]})')
    return full


def run(samples: list[dict] | None = None) -> str:
    print('==== [multi_backtest] start ====')
    full = _build_fullframe(samples)
    if full.empty:
        print('[multi_backtest] empty fullframe, abort')
        return ''

    print('---- slicer ----')
    slices = slicer.run(full)
    print('---- cross_slice ----')
    crosses = cross_slice.run(full)
    print('---- risk_metrics ----')
    risk_df = risk_metrics.compute(full)
    print('---- cohort ----')
    cohort_df = cohort.run(full)
    print('---- findings ----')
    fdg = findings.extract(slices)
    print('---- multi_report ----')
    path = multi_report.render(slices, crosses, risk_df, cohort_df, fdg)
    print('==== [multi_backtest] done ====')
    return path


if __name__ == '__main__':
    run()

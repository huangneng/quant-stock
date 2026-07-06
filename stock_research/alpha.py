"""超额收益 (α)：每只入选股相对沪深 300 同期收益的差。"""
from __future__ import annotations
import pandas as pd

from .config import OUTPUT_DIR
from .data_loader import fetch_hs300
from .holding_period import HORIZONS


def compute_alpha(holdings: pd.DataFrame) -> pd.DataFrame:
    hs = fetch_hs300()
    if hs is None or hs.empty:
        print('[alpha] HS300 unavailable, skip')
        return holdings.assign(**{f'excess_{h}': None for h in HORIZONS})
    hs = hs.sort_values('date').reset_index(drop=True)
    hs['date'] = pd.to_datetime(hs['date'])
    hs = hs.set_index('date')

    rows = []
    for _, r in holdings.iterrows():
        rec = dict(r)
        entry = pd.to_datetime(r['entry_date'])
        # entry 当日的 HS300 收盘 - 找离 entry 最近且 <= entry 的索引（停牌日跳过）
        upto = hs.loc[:entry]
        if upto.empty:
            for h in HORIZONS:
                rec[f'excess_{h}'] = None
            rows.append(rec)
            continue
        base_close = float(upto['close'].iloc[-1])
        future = hs.loc[entry:].iloc[1:]  # 入选日之后的指数
        for h in HORIZONS:
            stock_ret = r.get(f'ret_{h}')
            if stock_ret is None or pd.isna(stock_ret):
                rec[f'excess_{h}'] = None
                continue
            if len(future) < h:
                rec[f'excess_{h}'] = None
                continue
            hs_close = float(future['close'].iloc[h - 1])
            hs_ret = hs_close / base_close - 1
            rec[f'excess_{h}'] = float(stock_ret) - hs_ret
        rows.append(rec)
    out = pd.DataFrame(rows)
    out.to_csv(OUTPUT_DIR / 'alpha_30.csv', index=False)
    print(f'[alpha] -> alpha_30.csv ({len(out)} rows)')
    # 终端摘要
    for h in HORIZONS:
        col = f'excess_{h}'
        if col in out.columns:
            valid = out[col].dropna()
            if len(valid) > 0:
                print(f'  excess_{h}: n={len(valid)}, mean={valid.mean():.3f}, '
                      f'win_rate={(valid > 0).mean():.1%}')
    return out


if __name__ == '__main__':
    holdings = pd.read_parquet(OUTPUT_DIR / 'holdings_matrix.parquet')
    compute_alpha(holdings)

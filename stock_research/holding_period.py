"""多持有期收益矩阵

对每只入选样本，从 entry_date 之后 N 个交易日窗口算 ret/max_high/max_dd/win，
以及 days_to_peak、days_to_stop（10% 移动止损）。
"""
from __future__ import annotations
import pandas as pd
import numpy as np

from .config import OUTPUT_DIR

HORIZONS = (5, 10, 20, 30, 60)


def _safe(v):
    try:
        f = float(v)
        if pd.isna(f):
            return None
        return f
    except Exception:
        return None


def _trailing_stop_days(post: pd.DataFrame, buy_price: float, drawdown: float = 0.10) -> int:
    """模拟 10% 移动止损，返回触发天数（1-based）；未触发返回 -1。"""
    peak = float(buy_price)
    stop = peak * (1 - drawdown)
    for i, row in enumerate(post.itertuples(index=False), 1):
        close = float(row.close)
        if close > peak:
            peak = close
            new_stop = peak * (1 - drawdown)
            if new_stop > stop:
                stop = new_stop
        if close <= stop:
            return i
    return -1


def compute(sample: dict) -> dict | None:
    hist = sample.get('hist')
    if hist is None or hist.empty:
        return None
    entry = sample['entry_date']
    buy = float(sample['buy_price'])
    if buy <= 0:
        return None
    post = hist[hist['date'] > entry].sort_values('date').reset_index(drop=True)
    if post.empty:
        return None

    out = {
        'code': sample['code'],
        'entry_date': entry,
        'signal_type': sample.get('signal_type'),
        'is_limit_up': bool(sample.get('is_limit_up', False)),
        'buy_price': buy,
        'amount': sample.get('amount'),
        'post_n': int(len(post)),
    }
    # 多持有期
    for h in HORIZONS:
        win = post.head(h)
        if len(win) < h:
            out[f'ret_{h}'] = None
            out[f'max_high_{h}'] = None
            out[f'max_dd_{h}'] = None
            out[f'win_{h}'] = None
            continue
        last_close = float(win['close'].iloc[-1])
        ret = last_close / buy - 1
        max_high = float(win['high'].max()) / buy - 1
        cummax = win['close'].cummax()
        max_dd = float((win['close'] / cummax - 1).min())
        out[f'ret_{h}'] = ret
        out[f'max_high_{h}'] = max_high
        out[f'max_dd_{h}'] = max_dd
        out[f'win_{h}'] = int(ret > 0)
    # days_to_peak（最高 close 出现在第几日，post 内）
    if len(post) > 0:
        idx = int(post['close'].values.argmax()) + 1
        out['days_to_peak'] = idx
    else:
        out['days_to_peak'] = None
    # days_to_stop
    out['days_to_stop'] = _trailing_stop_days(post, buy)
    return out


def build(samples: list[dict]) -> pd.DataFrame:
    rows = []
    for s in samples:
        r = compute(s)
        if r is not None:
            rows.append(r)
    df = pd.DataFrame(rows)
    out = OUTPUT_DIR / 'holdings_matrix.parquet'
    df.to_parquet(out)
    print(f'[holding_period] -> {out} ({len(df)} rows, {df.shape[1]} cols)')
    return df


if __name__ == '__main__':
    from .data_loader import load_all
    df = build(load_all())
    print(df.describe(include='all').T.head(20))

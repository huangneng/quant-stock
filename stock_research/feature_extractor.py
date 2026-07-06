"""特征工程

对每个入选样本，基于 entry_date 之前 PRE_DAYS 个交易日 + entry_date 当天的数据，
抽取量价、涨停、形态、相对位置、流动性等特征，最终拼成宽表。
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from datetime import datetime

from .config import PRE_DAYS, OUTPUT_DIR


def _safe_div(a, b):
    try:
        return float(a) / float(b) if b not in (0, None) and not pd.isna(b) else np.nan
    except Exception:
        return np.nan


def extract_features(sample: dict) -> dict | None:
    hist = sample.get('hist')
    if hist is None or hist.empty:
        return None
    entry = sample['entry_date']
    pre = hist[hist['date'] < entry].tail(PRE_DAYS)
    today_rows = hist[hist['date'] == entry]
    if today_rows.empty or len(pre) < 20:
        return None
    today = today_rows.iloc[0]
    prev = pre.iloc[-1] if len(pre) > 0 else None

    feat = {
        'code': sample['code'],
        'entry_date': entry,
        'signal_type': sample.get('signal_type'),
        'is_limit_up': bool(sample.get('is_limit_up', False)),
    }

    # A. 量价
    amt = float(today['amount'])
    vol = float(today['volume'])
    pre20_amt = pre['amount'].tail(20).mean()
    pre20_vol = pre['volume'].tail(20).mean()
    feat['amount_ratio_20d'] = _safe_div(amt, pre20_amt)
    feat['volume_ratio_20d'] = _safe_div(vol, pre20_vol)
    feat['amount_today_yi'] = amt / 1e8  # 亿
    feat['amount_5d_avg_yi'] = pre['amount'].tail(5).mean() / 1e8
    feat['amount_5d_growth'] = _safe_div(amt, pre['amount'].tail(5).mean())

    # B. 涨停板
    is_lu = pre['pctChg'].fillna(0) >= 9.5
    feat['limit_up_count_60d'] = int(is_lu.sum())
    if is_lu.any():
        last_lu_idx = pre.index[is_lu][-1]
        # 距入选日 = pre 末尾索引 - last_lu_idx 行数差
        feat['days_since_last_limit_up'] = int(pre.index[-1] - last_lu_idx)
    else:
        feat['days_since_last_limit_up'] = -1

    # 一字板比例：涨停日且 high == low
    if is_lu.any():
        lu_rows = pre[is_lu]
        one_word = (lu_rows['high'] == lu_rows['low']).sum()
        feat['one_word_lu_ratio'] = _safe_div(one_word, len(lu_rows))
    else:
        feat['one_word_lu_ratio'] = 0.0

    # C. K 线形态（入选日）
    o, h, l, c = float(today['open']), float(today['high']), float(today['low']), float(today['close'])
    feat['body_pct'] = _safe_div(c - o, o)
    feat['upper_shadow_pct'] = _safe_div(h - max(o, c), o)
    feat['lower_shadow_pct'] = _safe_div(min(o, c) - l, o)
    feat['amplitude_pct'] = _safe_div(h - l, o)
    if prev is not None:
        prev_close = float(prev['close'])
        feat['gap_up_pct'] = _safe_div(o - prev_close, prev_close)
        feat['auction_gap_pct'] = feat['gap_up_pct']
    else:
        feat['gap_up_pct'] = np.nan
        feat['auction_gap_pct'] = np.nan

    try:
        pre100_high = float(pre.tail(100)['high'].max())
        all_time_high = float(pre['high'].max())
        breakout_ref = max(pre100_high, all_time_high)
        feat['auction_breakout_pct'] = _safe_div(o - breakout_ref, breakout_ref)
    except Exception:
        feat['auction_breakout_pct'] = np.nan

    # 真实 9:25 集合竞价成交额：由采集脚本通过 sample['auction_amount'] 注入。
    # 未注入时保持 np.nan 兜底，向后兼容。
    auction_amount = sample.get('auction_amount')
    if auction_amount is not None and auction_amount == auction_amount:
        feat['auction_amount'] = float(auction_amount)
        try:
            avg20 = float(pre.tail(20)['amount'].mean())
            feat['auction_amount_vs_20d'] = _safe_div(float(auction_amount), avg20)
        except Exception:
            feat['auction_amount_vs_20d'] = np.nan
        vr = sample.get('auction_volume_ratio')
        feat['auction_amount_ratio'] = float(vr) if (vr is not None and vr == vr) else np.nan
    else:
        feat['auction_amount'] = np.nan
        feat['auction_amount_ratio'] = np.nan
        feat['auction_amount_vs_20d'] = np.nan

    # ATR(14) / 价格
    pre14 = pre.tail(14).copy()
    if len(pre14) >= 5:
        prev_close = pre14['close'].shift(1)
        tr = pd.concat([
            pre14['high'] - pre14['low'],
            (pre14['high'] - prev_close).abs(),
            (pre14['low'] - prev_close).abs(),
        ], axis=1).max(axis=1)
        feat['atr14_pct'] = _safe_div(tr.mean(), c)
    else:
        feat['atr14_pct'] = np.nan

    # D. 相对位置
    feat['ma20_deviation'] = _safe_div(c - pre['close'].tail(20).mean(), pre['close'].tail(20).mean())
    if len(pre) >= 60:
        feat['ma60_deviation'] = _safe_div(c - pre['close'].tail(60).mean(), pre['close'].tail(60).mean())
    else:
        feat['ma60_deviation'] = np.nan
    feat['is_60d_high'] = int(c >= pre['high'].tail(min(60, len(pre))).max())
    feat['is_120d_high'] = int(c >= pre['high'].max())  # PRE_DAYS=60 时退化为 60d
    # 整理时长：连续多少日收盘价处于前一日 ±2% 之内
    consol = 0
    closes = pre['close'].tolist()
    for i in range(len(closes) - 1, 0, -1):
        if abs(closes[i] / closes[i - 1] - 1) <= 0.02:
            consol += 1
        else:
            break
    feat['consolidation_days'] = consol
    feat['ret_60d_pre'] = _safe_div(float(pre['close'].iloc[-1]) - float(pre['close'].iloc[0]),
                                     float(pre['close'].iloc[0]))

    # E. 流动性
    feat['turnover_today'] = float(today.get('turn') or 0)
    feat['turnover_5d_avg'] = float(pre['turn'].tail(5).mean()) if 'turn' in pre.columns else np.nan

    # F. 上市天数（粗略：现有数据起点到 entry）
    try:
        listed_days = (datetime.strptime(entry, '%Y-%m-%d')
                       - datetime.strptime(str(hist['date'].iloc[0]), '%Y-%m-%d')).days
    except Exception:
        listed_days = -1
    feat['listed_days_in_window'] = listed_days

    # G. 入选前 3 日窗口（pre3_*）
    pre3 = pre.tail(3)
    if len(pre3) >= 2:
        first_close = float(pre3['close'].iloc[0])
        last_close_pre = float(pre3['close'].iloc[-1])
        feat['pre3_close_return'] = _safe_div(last_close_pre - first_close, first_close)
        feat['pre3_max_high_dev'] = _safe_div(float(pre3['high'].max()) - o, o)
        feat['pre3_min_low_dev'] = _safe_div(float(pre3['low'].min()) - o, o)
        feat['pre3_red_count'] = int((pre3['close'] > pre3['open']).sum())
        # 量能斜率：3 日成交量做 1 阶线性拟合，标准化到日均量
        vols = pre3['volume'].values.astype(float)
        if len(vols) >= 2 and vols.mean() > 0:
            slope = np.polyfit(np.arange(len(vols)), vols, 1)[0]
            feat['pre3_volume_slope'] = float(slope / vols.mean())
        else:
            feat['pre3_volume_slope'] = np.nan
        feat['pre3_amplitude_avg'] = float(((pre3['high'] - pre3['low']) / pre3['open']).mean())
    else:
        for k in ('pre3_close_return', 'pre3_max_high_dev', 'pre3_min_low_dev',
                  'pre3_red_count', 'pre3_volume_slope', 'pre3_amplitude_avg'):
            feat[k] = np.nan

    # H. 入选后 3 日窗口（post3_*，事后特征，仅用于归因分析）
    post = hist[hist['date'] > entry].head(3)
    if len(post) >= 2:
        feat['post3_max_high_gain'] = _safe_div(float(post['high'].max()) - c, c)
        feat['post3_min_low_drop'] = _safe_div(float(post['low'].min()) - c, c)
        feat['post3_close_return'] = _safe_div(float(post['close'].iloc[-1]) - c, c)
        post_vol_avg = float(post['volume'].mean())
        feat['post3_volume_ratio'] = _safe_div(post_vol_avg, vol)
        feat['post3_red_count'] = int((post['close'] > post['open']).sum())
        prior_high = float(pre['high'].max()) if len(pre) > 0 else c
        feat['post3_break_high'] = int(float(post['high'].max()) > max(prior_high, h))
    else:
        for k in ('post3_max_high_gain', 'post3_min_low_drop', 'post3_close_return',
                  'post3_volume_ratio', 'post3_red_count', 'post3_break_high'):
            feat[k] = np.nan

    return feat


def extract_all(samples: list[dict]) -> pd.DataFrame:
    rows = []
    for s in samples:
        f = extract_features(s)
        if f is not None:
            rows.append(f)
    df = pd.DataFrame(rows)
    out = OUTPUT_DIR / 'features.parquet'
    df.to_parquet(out)
    print(f'[feature_extractor] -> {out} ({len(df)} rows, {df.shape[1]} cols)')
    return df


if __name__ == '__main__':
    from .data_loader import load_all
    df = extract_all(load_all())
    print(df.head())
    print(df.describe().T)

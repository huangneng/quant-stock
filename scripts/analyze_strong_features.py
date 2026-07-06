#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""强势股特征差异分析（信号强度进化的事实依据）。

口径（用户确认）：
- 样本 = 每个历史入选票（selections.json）
- 命中(win) = 入选后【次日】继续大涨：次日 pctChg >= 6%（或涨停 >=9.5%）
- 未命中(lose) = 次日 pctChg < 6%
分析：对比 win/lose 两组在现有各评分维度 + 若干候选新因子上的分布差异，
给出可用于重校权重 / 新增维度的证据。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stock_research import recommender as R
from stock_research.feature_extractor import extract_features

SELECTIONS = ROOT / 'stock_data' / 'selections.json'
DB = ROOT / 'stock_data' / 'kline.db'

WIN_STRONG = 6.0    # 次日大涨阈值(%)
WIN_LIMIT = 9.5     # 次日涨停阈值(%)


def _iso(k: str) -> str:
    return f'{k[:4]}-{k[4:6]}-{k[6:8]}'


def load_hist(conn, code: str) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close, volume, amount, turn, pctChg "
        "FROM kline WHERE code=? ORDER BY date", conn, params=(code,))
    return df


def main():
    raw = json.loads(SELECTIONS.read_text(encoding='utf-8'))
    conn = sqlite3.connect(DB)

    # 预载每个 code 的全量 hist（缓存）
    hist_cache: dict[str, pd.DataFrame] = {}

    rows = []
    for k, payload in raw.items():
        entry = _iso(k)
        stocks = payload.get('stocks', []) if isinstance(payload, dict) else payload
        for s in stocks:
            code = s.get('code')
            if not code:
                continue
            if code not in hist_cache:
                hist_cache[code] = load_hist(conn, code)
            hist = hist_cache[code]
            if hist.empty:
                continue
            # 次日行情
            after = hist[hist['date'] > entry]
            if after.empty:
                continue
            nxt = after.iloc[0]
            nxt_pct = nxt['pctChg']
            if nxt_pct is None or pd.isna(nxt_pct):
                continue
            nxt_pct = float(nxt_pct)

            sample = {
                'code': code, 'entry_date': entry, 'hist': hist,
                'signal_type': s.get('signal_type'),
                'is_limit_up': s.get('is_limit_up', False),
                'auction_amount': s.get('auction_amount'),
                'auction_volume_ratio': s.get('auction_volume_ratio'),
            }
            feat = extract_features(sample)
            if feat is None:
                continue
            # 现有评分维度
            sc = R.score(feat)
            row = {'code': code, 'entry': entry, 'next_pct': nxt_pct,
                   'win': int(nxt_pct >= WIN_STRONG),
                   'win_limit': int(nxt_pct >= WIN_LIMIT),
                   'score': sc['score'], 'star': sc['star']}
            for dk, dv in sc['dims'].items():
                row['dim_' + dk] = dv
            # 候选新因子（原始特征）
            for fk in ('amount_ratio_20d', 'volume_ratio_20d', 'limit_up_count_60d',
                       'days_since_last_limit_up', 'one_word_lu_ratio', 'body_pct',
                       'upper_shadow_pct', 'gap_up_pct', 'auction_breakout_pct',
                       'ma20_deviation', 'consolidation_days', 'ret_60d_pre',
                       'turnover_today', 'atr14_pct', 'amount_today_yi',
                       'auction_amount_vs_20d'):
                row['f_' + fk] = feat.get(fk, np.nan)
            rows.append(row)

    conn.close()
    df = pd.DataFrame(rows)
    n = len(df)
    if n == 0:
        print("无有效样本")
        return

    win = df[df['win'] == 1]
    lose = df[df['win'] == 0]
    print("=" * 64)
    print(f"强势股特征差异分析  样本={n}  "
          f"次日大涨(>= {WIN_STRONG}%)={len(win)} ({len(win)/n:.1%})  "
          f"次日涨停(>= {WIN_LIMIT}%)={df['win_limit'].sum()} ({df['win_limit'].mean():.1%})")
    print("=" * 64)

    # 现有 score/star 是否区分 win
    print("\n[现有信号强度区分度]")
    for st in sorted(df['star'].unique()):
        sub = df[df['star'] == st]
        print(f"  {st}★  样本 {len(sub):>4}  次日大涨率 {sub['win'].mean():.1%}  次日均涨 {sub['next_pct'].mean():+.2f}%")
    # 相关性：score vs next_pct
    corr = df['score'].corr(df['next_pct'])
    print(f"  score 与次日涨幅 相关系数: {corr:+.3f}")

    # 各维度 win/lose 均值差
    print("\n[评分维度 win vs lose 均值]  (差值大=区分力强)")
    dim_cols = [c for c in df.columns if c.startswith('dim_')]
    diffs = []
    for c in dim_cols:
        wv, lv = win[c].mean(), lose[c].mean()
        diffs.append((abs(wv - lv), c, wv, lv))
    for d, c, wv, lv in sorted(diffs, reverse=True):
        print(f"  {c[4:]:<16} win={wv:.3f}  lose={lv:.3f}  Δ={wv-lv:+.3f}")

    # 候选新因子
    print("\n[候选因子 win vs lose 均值 + 相关性]")
    fcols = [c for c in df.columns if c.startswith('f_')]
    frows = []
    for c in fcols:
        wv, lv = win[c].mean(), lose[c].mean()
        cc = df[c].corr(df['next_pct'])
        frows.append((abs(cc) if cc == cc else 0, c, wv, lv, cc))
    for a, c, wv, lv, cc in sorted(frows, reverse=True):
        print(f"  {c[2:]:<24} win={wv:>9.3f}  lose={lv:>9.3f}  corr(次日)={cc:+.3f}")

    print("\n" + "=" * 64)


if __name__ == '__main__':
    main()

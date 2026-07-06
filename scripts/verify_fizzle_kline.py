#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""二次验证（kline 全量形态口径）：连续强势后熄火 → 首日回调。

口径（用户确认）：
- 强势 = 当日 pctChg >= 9.5%（涨停/接近涨停）
- 连续强势 >=2 天 = 相邻交易日均强势
- 熄火 = 连续强势 >=2 天后，下一交易日"没大涨"（pct < 9.5%）
- 回调 = 熄火当日收跌 pct < 0
对照组 = 连续强势 >=2 天后，下一交易日仍强势(pct>=9.5%)，看该日涨跌。

数据源：stock_data/kline.db 全量（约 179 个交易日、1400+ 只）。
"""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / 'stock_data' / 'kline.db'

STRONG = 9.5   # 强势阈值(%)


def main():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT code, date, pctChg FROM kline WHERE pctChg IS NOT NULL", conn)
    conn.close()
    df['pctChg'] = pd.to_numeric(df['pctChg'], errors='coerce')
    df = df.dropna(subset=['pctChg'])

    all_dates = sorted(df['date'].unique())
    date_idx = {d: i for i, d in enumerate(all_dates)}

    # code -> {date: pct}
    by_code: dict[str, dict[str, float]] = defaultdict(dict)
    for code, date, pct in df.itertuples(index=False):
        by_code[code][date] = float(pct)

    fizzle_pull = 0
    fizzle_rets: list[float] = []
    cont_up = 0
    cont_rets: list[float] = []
    worst: list[tuple] = []   # (ret, code, fizzle_date)

    for code, dm in by_code.items():
        ds = sorted(dm.keys())
        for k in range(1, len(ds)):
            d0, d1 = ds[k - 1], ds[k]
            # 必须是相邻交易日
            if date_idx[d1] - date_idx[d0] != 1:
                continue
            if dm[d0] < STRONG or dm[d1] < STRONG:
                continue
            # 连续强势 >=2 天成立，看第3天(下一交易日)
            i1 = date_idx[d1]
            if i1 + 1 >= len(all_dates):
                continue
            d2 = all_dates[i1 + 1]
            pct2 = dm.get(d2)
            if pct2 is None:
                continue
            if pct2 >= STRONG:
                cont_up += 1 if pct2 > 0 else 0
                cont_rets.append(pct2)
            else:
                # 熄火
                fizzle_rets.append(pct2)
                if pct2 < 0:
                    fizzle_pull += 1
                worst.append((pct2, code, d2))

    def stat(rets):
        if not rets:
            return (0, 0.0, 0.0)
        s = pd.Series(rets)
        return (len(s), s.mean(), s.median())

    print("=" * 60)
    print(f"二次验证（kline 全量, 强势阈值 pct>={STRONG}%）")
    print(f"覆盖交易日: {len(all_dates)}  {all_dates[0]} ~ {all_dates[-1]}")
    print("=" * 60)

    n, mean, med = stat(fizzle_rets)
    print(f"\n【熄火组】连续强势>=2天后，第3天未延续(pct<{STRONG}%)：")
    print(f"  样本数：{n}")
    if n:
        print(f"  收跌(回调)概率：{fizzle_pull}/{n} = {fizzle_pull/n:.1%}")
        print(f"  平均涨跌：{mean:+.2f}%   中位数：{med:+.2f}%")

    n2, mean2, med2 = stat(cont_rets)
    print(f"\n【对照组】连续强势>=2天且第3天仍强势(pct>={STRONG}%)：")
    print(f"  样本数：{n2}")
    if n2:
        print(f"  当日收涨概率：{cont_up}/{n2} = {cont_up/n2:.1%}")
        print(f"  平均涨跌：{mean2:+.2f}%   中位数：{med2:+.2f}%")

    # 全市场基准：任意日的收跌概率
    dn = (df['pctChg'] < 0).sum()
    print(f"\n【全市场基准】任意个股任意日：收跌概率 {dn}/{len(df)} = {dn/len(df):.1%}"
          f"  平均 {df['pctChg'].mean():+.2f}%")

    worst.sort()
    print("\n熄火后跌幅最大 TOP10：")
    for ret, code, d in worst[:10]:
        print(f"  {code}  {d}  {ret:+.2f}%")

    print("\n" + "=" * 60)


if __name__ == '__main__':
    main()

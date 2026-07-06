#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证假设：连续入选 >=2 天后，第3天掉出池，则掉出后首日大概率回调。

口径（用户确认）：
- 强势 = 当天在 selections 池中出现
- 熄火 = 连续入选 >=2 天，随后首个交易日掉出池
- 回调 = 掉出后首个交易日收跌 pct < 0
对照组 = 连续入选 >=2 天，第3天仍在池中，比较其"第3天当日"涨跌。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SELECTIONS_FILE = ROOT / 'stock_data' / 'selections.json'
TRADE_CAL = ROOT / 'stock_data' / 'trade_calendar.json'
DB_PATH = ROOT / 'stock_data' / 'kline.db'


def _iso(k: str) -> str:
    return f'{k[:4]}-{k[4:6]}-{k[6:8]}'


def load_trade_dates() -> list[str]:
    data = json.loads(TRADE_CAL.read_text(encoding='utf-8'))
    if isinstance(data, dict):
        dates = data.get('dates') if isinstance(data.get('dates'), list) else list(data.keys())
    else:
        dates = data
    return sorted(d for d in dates if isinstance(d, str) and len(d) == 10)


def next_td(iso: str, tds: list[str]) -> str | None:
    for d in tds:
        if d > iso:
            return d
    return None


def load_selections() -> dict[str, set[str]]:
    """返回 {iso_date: set(codes)}。"""
    raw = json.loads(SELECTIONS_FILE.read_text(encoding='utf-8'))
    out: dict[str, set[str]] = {}
    for k, payload in raw.items():
        iso = _iso(k)
        stocks = payload.get('stocks', []) if isinstance(payload, dict) else payload
        codes = {s.get('code') for s in stocks if isinstance(s, dict) and s.get('code')}
        out[iso] = codes
    return out


def get_pct(conn, code: str, date: str) -> float | None:
    cur = conn.execute(
        "SELECT close, pctChg FROM kline WHERE code=? AND date=?", (code, date))
    row = cur.fetchone()
    if not row:
        return None
    close, pct = row
    if pct is not None:
        try:
            return float(pct)
        except (TypeError, ValueError):
            return None
    return None


def main():
    tds = load_trade_dates()
    sel = load_selections()
    sel_dates = sorted(sel.keys())
    conn = sqlite3.connect(DB_PATH)

    # 为每只股票统计连续入选序列
    # 收集：对每个"连续>=2天入选"的段，其后一交易日是否掉出，掉出首日涨跌
    from collections import defaultdict
    appear = defaultdict(set)  # code -> set of dates
    for d, codes in sel.items():
        for c in codes:
            appear[c].add(d)

    fizzle_pullback = 0   # 熄火后首日收跌
    fizzle_total = 0      # 熄火样本
    fizzle_rets = []      # 熄火首日收益

    cont_up = 0           # 第3天仍在池：当日收益
    cont_total = 0
    cont_rets = []

    for code, dates in appear.items():
        ds = sorted(dates)
        # 找连续入选段（相邻都是交易日连续）
        i = 0
        while i < len(ds):
            j = i
            while j + 1 < len(ds) and next_td(ds[j], tds) == ds[j + 1]:
                j += 1
            run = ds[i:j + 1]
            if len(run) >= 2:
                last = run[-1]
                nxt = next_td(last, tds)
                if nxt is not None:
                    in_pool_next = nxt in sel and code in sel[nxt]
                    if in_pool_next:
                        # 对照组：第3+天仍在池，看当日涨跌
                        pct = get_pct(conn, code, nxt)
                        if pct is not None:
                            cont_total += 1
                            cont_rets.append(pct)
                            if pct > 0:
                                cont_up += 1
                    else:
                        # 熄火：掉出池，看掉出首日涨跌
                        pct = get_pct(conn, code, nxt)
                        if pct is not None:
                            fizzle_total += 1
                            fizzle_rets.append(pct)
                            if pct < 0:
                                fizzle_pullback += 1
            i = j + 1

    conn.close()

    def stats(rets):
        if not rets:
            return (0, 0.0, 0.0)
        s = pd.Series(rets)
        return (len(s), s.mean(), s.median())

    print("=" * 56)
    print("假设验证：连续入选>=2天后第3天掉出池 → 掉出首日回调")
    print("=" * 56)
    n, mean, med = stats(fizzle_rets)
    print(f"\n【熄火组】连续>=2天入选后掉出池，掉出首日表现：")
    print(f"  样本数：{fizzle_total}")
    if fizzle_total:
        print(f"  收跌(回调)概率：{fizzle_pullback}/{fizzle_total} = {fizzle_pullback/fizzle_total:.1%}")
        print(f"  平均涨跌：{mean:+.2f}%   中位数：{med:+.2f}%")

    n, mean, med = stats(cont_rets)
    print(f"\n【对照组】连续>=2天入选且第3天仍在池，当日表现：")
    print(f"  样本数：{cont_total}")
    if cont_total:
        print(f"  收涨概率：{cont_up}/{cont_total} = {cont_up/cont_total:.1%}")
        print(f"  平均涨跌：{mean:+.2f}%   中位数：{med:+.2f}%")

    print("\n" + "=" * 56)


if __name__ == '__main__':
    main()

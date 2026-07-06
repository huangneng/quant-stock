#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描 selections 池里所有 cycle，列出"熄火"票：
连续入选 >=2 天后，cycle 结束（出局/掉出池）。复刻 tracker_report 的 cycle 探测口径。
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quant_backtest import tracker_report as tr
from data_hub import api as hub


def main():
    sel = tr.load_selections()
    today = sorted(sel.keys())[-1]
    today_dt = pd.to_datetime(today)

    code_dates = {}
    for date in sorted(sel.keys()):
        for stock in sel[date].get('stocks', []):
            code_dates.setdefault(stock['code'], []).append((date, stock))

    fizzles = []      # (entry, last_hit, code, name, hits_n, active)
    for code, hits in code_dates.items():
        cycles = []
        cur = None
        for d_str, stock in hits:
            d_dt = pd.to_datetime(d_str)
            in_prev = (cur is not None and not cur['cleared']
                       and (cur['stop_dt'] is None or d_dt <= cur['stop_dt']))
            if in_prev:
                cur['hits'].append(d_str)
                continue
            buy = stock.get('buy_price', stock.get('price'))
            stop_dt = None
            cleared = False
            try:
                df = hub.get_kline(code, d_str, today, require_today=True)
                if df is not None and not df.empty:
                    df = df.sort_values('date').reset_index(drop=True)
                    dfb = df[pd.to_datetime(df['date']) >= d_dt].reset_index(drop=True)
                    if not dfb.empty:
                        sd, st, ep, _pk, sl = tr._calc_stopout_from_df(dfb, buy)
                        if sd is not None:
                            yr = int(d_str[:4])
                            stop_dt = pd.to_datetime(f'{yr}-{sd}')
                            if stop_dt < d_dt:
                                stop_dt = pd.to_datetime(f'{yr + 1}-{sd}')
                        _bat, bac = tr._calc_position_action(dfb, is_stopped=stop_dt is not None)
                        cleared = (bac == 'act-clear')
            except Exception:
                pass
            cur = {'code': code, 'name': stock['name'], 'entry': d_str,
                   'stop_dt': stop_dt, 'cleared': cleared, 'hits': [d_str]}
            cur['active'] = stop_dt is None or stop_dt > today_dt
            cycles.append(cur)

        for c in cycles:
            n = len(c['hits'])
            if n >= 2 and not c['active']:
                fizzles.append((c['entry'], c['hits'][-1], code, c['name'], n))

    fizzles.sort(reverse=True)
    print(f"最新选股日: {today}")
    print(f"熄火票（连续入选>=2天后已出局/掉出）: {len(fizzles)} 个\n")
    for entry, last, code, name, n in fizzles:
        print(f"  {name:<8} {code}  入选 {entry}~{last}  连续{n}天  熄火日(最后命中行): {last}")


if __name__ == '__main__':
    main()

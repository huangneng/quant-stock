#!/usr/bin/env python3
"""回补历史日期的预筛成交额缓存（baostock 精确成交额）。

用法:
    python3 scripts/backfill_prefilter_cache.py 2026-08-25 2026-08-26 2026-08-27

daily_select 回补历史日期时会退到 baostock 逐只单日查询，N 个日期就是
N × 5207 次调用。这里每只票一次性拉整个日期区间（5207 次调用），
再按日期拆成 N 份缓存，缓存格式与 daily_select 自己写的完全一致。

写完缓存后按日期依次跑 `daily_select.py --date <日期>` 即可命中缓存、跳过扫描。

注意：baostock 不可用时（登录返回 10002007 网络接收错误）本脚本会整体失败，
不会写出任何缓存——宁可不写，也不能写出覆盖率不足的缓存让预筛静默漏选。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import baostock as bs

from daily_select import PREFILTER_CACHE_DIR, get_stock_list, _is_real_stock

MIN_COVERAGE = 0.95
RECONNECT_EVERY = 500


def main(dates):
    dates = sorted(dates)
    start, end = dates[0], dates[-1]
    stock_list = [(c, n) for c, n in get_stock_list() if _is_real_stock(c)]
    print(f'目标 {len(stock_list)} 只，区间 {start} ~ {end}', flush=True)

    lg = bs.login()
    if lg.error_code != '0':
        print(f'baostock 登录失败 error_code={lg.error_code} msg={lg.error_msg}，中止')
        return 1

    buckets = {d: [] for d in dates}
    missing = []
    t0 = time.time()
    try:
        for i, (code, name) in enumerate(stock_list):
            rows = None
            for retry in range(3):
                try:
                    rs = bs.query_history_k_data_plus(
                        code, 'date,amount', start_date=start, end_date=end,
                        frequency='d', adjustflag='3')
                    got = []
                    while rs.next():
                        got.append(rs.get_row_data())
                    rows = got
                    break
                except Exception as e:
                    if retry == 2:
                        print(f'  [{code}] 查询失败: {type(e).__name__}: {e}', flush=True)
                    else:
                        try:
                            bs.logout()
                        except Exception:
                            pass
                        bs.login()
            if not rows:
                missing.append(code)
            else:
                for d, amt in rows:
                    if d in buckets:
                        try:
                            buckets[d].append({'code': code, 'name': name,
                                               'amount': float(amt or 0)})
                        except (TypeError, ValueError):
                            pass
            if (i + 1) % RECONNECT_EVERY == 0:
                print(f'  进度 {i+1}/{len(stock_list)} elapsed={time.time()-t0:.0f}s '
                      f'missing={len(missing)} 各日行数={{{", ".join(f"{d}:{len(v)}" for d, v in buckets.items())}}}',
                      flush=True)
                try:
                    bs.logout()
                except Exception:
                    pass
                bs.login()
    finally:
        try:
            bs.logout()
        except Exception:
            pass

    print(flush=True)
    written = 0
    for d in dates:
        df = pd.DataFrame(buckets[d])
        cov = len(df) / max(1, len(stock_list))
        if df.empty or cov < MIN_COVERAGE:
            print(f'{d}: {len(df)} 行 覆盖率={cov:.1%} < {MIN_COVERAGE:.0%}，不写缓存', flush=True)
            continue
        path = PREFILTER_CACHE_DIR / f'prefilter_amount_{d}.csv'
        df.to_csv(path, index=False)
        written += 1
        print(f'{d}: {len(df)} 行 覆盖率={cov:.1%} 零成交额={int((df["amount"] <= 0).sum())} '
              f'≥25亿={int((df["amount"] >= 25e8).sum())} -> {path.name}', flush=True)

    print(f'\n未取到任何数据 {len(missing)} 只，写出缓存 {written}/{len(dates)} 份，'
          f'总耗时 {time.time()-t0:.0f}s', flush=True)
    return 0 if written == len(dates) else 1


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))

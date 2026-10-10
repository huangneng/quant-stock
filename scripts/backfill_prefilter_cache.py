#!/usr/bin/env python3
"""回补历史日期的预筛成交额缓存。

用法:
    python3 scripts/backfill_prefilter_cache.py 2026-08-25 2026-08-26 2026-08-27
    python3 scripts/backfill_prefilter_cache.py --source klinedb 2026-08-25

daily_select 回补历史日期时会退到 baostock 逐只单日查询，N 个日期就是
N × 5207 次调用。这里每只票一次性拉整个日期区间，再按日期拆成 N 份缓存，
缓存格式与 daily_select 自己写的完全一致（code,name,amount）。

写完缓存后按日期依次跑 `daily_select.py --date <日期>` 即可命中缓存、跳过扫描。

三条取数通路（`--source`）：

  baostock  精确成交额，逐票区间查询（~5200 次调用），默认通路。
  akshare   精确成交额，逐票区间查询，带重试与指数退避。东财时常间歇性
            RemoteDisconnected，连续失败达阈值即整体中止。
  klinedb   **近似**成交额，直接读本地 kline 表，零网络请求、秒级完成。
            腾讯日K 不返回成交额，库内 amount 是 均价×volume 估出来的。
            实测（2026-08-28，5192 只，对照新浪精确值）：P50 -0.157%、
            P99 +1.115%、|误差|>5% 占 0.00%；25 亿预筛与精确值比
            一致 143 / 漏选 3 / 误入 0，漏选的 3 只全卡在阈值边缘。
            精确源恢复后建议用 baostock/akshare 重跑对比。

无论走哪条通路，覆盖率不足 95% 就不写该日缓存——宁可不写，
也不能写出覆盖率不足的缓存让预筛静默漏选。
"""
import argparse
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from daily_select import PREFILTER_CACHE_DIR, get_stock_list, _is_real_stock
from data_hub.store.kline_db import DB_PATH

MIN_COVERAGE = 0.95
RECONNECT_EVERY = 500
AK_MAX_CONSECUTIVE_FAILS = 30
AK_BACKOFF_BASE_S = 1.0


def _bucket(buckets, date, code, name, amount):
    """把一行成交额投进对应日期的桶。非法值 / 非目标日期直接丢弃。"""
    if date not in buckets:
        return
    try:
        amt = float(amount or 0)
    except (TypeError, ValueError):
        return
    # amount <= 0 是停牌，写进缓存会被 daily_select 的
    # _prefilter_cache_has_bad_zero_amount 当成异常 0 值、整份缓存作废
    if amt <= 0:
        return
    buckets[date].append({'code': code, 'name': name, 'amount': amt})


def fetch_baostock(stock_list, dates):
    """逐票拉区间的 date,amount（精确）。"""
    import baostock as bs

    start, end = dates[0], dates[-1]
    lg = bs.login()
    if lg.error_code != '0':
        print(f'baostock 登录失败 error_code={lg.error_code} msg={lg.error_msg}，中止')
        return None, None

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
                    _bucket(buckets, d, code, name, amt)
            if (i + 1) % RECONNECT_EVERY == 0:
                _progress('baostock', i + 1, len(stock_list), t0, missing, buckets)
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
    return buckets, missing


def fetch_akshare(stock_list, dates):
    """逐票拉东财历史行情的成交额（精确）。

    直接调 ak.stock_zh_a_hist 而不复用 AkshareSource：后者把异常吞成 None，
    这里必须能区分「查无数据」和「网络失败」，否则退避与中止都无从判断。
    """
    import akshare as ak

    start, end = dates[0].replace('-', ''), dates[-1].replace('-', '')
    buckets = {d: [] for d in dates}
    missing = []
    consecutive_fails = 0
    t0 = time.time()
    for i, (code, name) in enumerate(stock_list):
        symbol = code.split('.')[1] if '.' in code else code
        df = None
        err = None
        for retry in range(3):
            try:
                df = ak.stock_zh_a_hist(symbol=symbol, period='daily',
                                        start_date=start, end_date=end, adjust='qfq')
                err = None
                break
            except Exception as e:
                err = e
                if retry < 2:
                    time.sleep(AK_BACKOFF_BASE_S * (2 ** retry))
        if err is not None:
            consecutive_fails += 1
            missing.append(code)
            if consecutive_fails >= AK_MAX_CONSECUTIVE_FAILS:
                # 连续这么多只全挂 = 东财整体不通，不是个股问题。
                # 继续跑只会攒出一份覆盖率不足的半份缓存，直接中止。
                print(f'  连续 {consecutive_fails} 只取数失败（最后一个 {code}: '
                      f'{type(err).__name__}: {err}），判定东财整体不可用，中止', flush=True)
                return None, None
            continue
        consecutive_fails = 0
        if df is None or df.empty or '日期' not in df.columns or '成交额' not in df.columns:
            missing.append(code)
        else:
            for _, row in df.iterrows():
                d = pd.Timestamp(row['日期']).strftime('%Y-%m-%d')
                _bucket(buckets, d, code, name, row['成交额'])
        if (i + 1) % RECONNECT_EVERY == 0:
            _progress('akshare', i + 1, len(stock_list), t0, missing, buckets)
    return buckets, missing


def fetch_klinedb(stock_list, dates):
    """从本地 kline 表读成交额（近似，零网络请求）。"""
    valid = {c: n for c, n in stock_list}
    buckets = {d: [] for d in dates}
    if not DB_PATH.exists():
        print(f'本地库不存在: {DB_PATH}，中止')
        return None, None
    conn = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)
    try:
        placeholders = ','.join('?' * len(dates))
        rows = conn.execute(
            f'SELECT code, date, amount FROM kline WHERE date IN ({placeholders})',
            dates).fetchall()
    finally:
        conn.close()
    seen = set()
    for code, date, amount in rows:
        if code not in valid:
            continue
        _bucket(buckets, date, code, valid[code], amount)
        seen.add(code)
    missing = [c for c in valid if c not in seen]
    print(f'  klinedb 命中 {len(rows)} 行 / {len(seen)} 只，'
          f'库内无数据 {len(missing)} 只', flush=True)
    return buckets, missing


FETCHERS = {'baostock': fetch_baostock, 'akshare': fetch_akshare, 'klinedb': fetch_klinedb}


def _progress(source, done, total, t0, missing, buckets):
    per_day = ', '.join(f'{d}:{len(v)}' for d, v in buckets.items())
    print(f'  [{source}] 进度 {done}/{total} elapsed={time.time()-t0:.0f}s '
          f'missing={len(missing)} 各日行数={{{per_day}}}', flush=True)


def write_caches(dates, buckets, total_codes, source):
    """覆盖率达标才写缓存。返回写出份数。"""
    written = 0
    for d in dates:
        df = pd.DataFrame(buckets[d])
        cov = len(df) / max(1, total_codes)
        if df.empty or cov < MIN_COVERAGE:
            print(f'{d}: {len(df)} 行 覆盖率={cov:.1%} < {MIN_COVERAGE:.0%}，不写缓存', flush=True)
            continue
        path = PREFILTER_CACHE_DIR / f'prefilter_amount_{d}.csv'
        df.to_csv(path, index=False)
        written += 1
        print(f'{d}: {len(df)} 行 覆盖率={cov:.1%} 零成交额={int((df["amount"] <= 0).sum())} '
              f'≥25亿={int((df["amount"] >= 25e8).sum())} [{source}] -> {path.name}', flush=True)
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description='回补历史日期的预筛成交额缓存')
    ap.add_argument('dates', nargs='+', help='交易日，如 2026-08-25 2026-08-26')
    ap.add_argument('--source', choices=sorted(FETCHERS), default='baostock',
                    help='取数通路：baostock/akshare 精确，klinedb 近似（零网络）')
    args = ap.parse_args(argv)

    dates = sorted(set(args.dates))
    stock_list = [(c, n) for c, n in get_stock_list() if _is_real_stock(c)]
    print(f'目标 {len(stock_list)} 只，区间 {dates[0]} ~ {dates[-1]}，'
          f'通路 {args.source}', flush=True)
    if args.source == 'klinedb':
        print('注意：klinedb 的成交额是 均价×volume 近似值，'
              '精确源恢复后建议重跑对比', flush=True)

    t0 = time.time()
    buckets, missing = FETCHERS[args.source](stock_list, dates)
    if buckets is None:
        print(f'\n取数中止，未写出任何缓存，耗时 {time.time()-t0:.0f}s', flush=True)
        return 1

    print(flush=True)
    written = write_caches(dates, buckets, len(stock_list), args.source)
    print(f'\n未取到任何数据 {len(missing)} 只，写出缓存 {written}/{len(dates)} 份，'
          f'总耗时 {time.time()-t0:.0f}s', flush=True)
    return 0 if written == len(dates) else 1


if __name__ == '__main__':
    sys.exit(main())

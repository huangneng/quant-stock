#!/usr/bin/env python3
"""把库内已有日 K 行的 amount / volume 回标为 baostock 的精确值。

用法:
    python3 scripts/backfill_amt_src.py                 # 全区间
    python3 scripts/backfill_amt_src.py --limit 50      # 只跑前 50 只
    python3 scripts/backfill_amt_src.py --dry-run       # 只统计不写库

为什么需要：腾讯日K 不返回成交额，`amount` 由 均价×volume 估出，volume 又是
按「手」上报后 ×100，所以取整到百股。`amt_src` 机制（见 kline_db.upsert_kline）
能防止近似值覆盖精确值，但只对已标 exact 的行生效——存量 34 万行里只有
1.5 万行（4.6%）标过，其余任何一天仍会被近似值改写。

关键点：baostock 的 query_history_k_data_plus 支持按代码一次拉整个日期区间，
所以全部 225 个交易日只需 5207 次调用（实测单只均 0.16s，约 14 分钟），
不是 225 × 5207 = 117 万次。

只更新库内已存在的行，不新增行——回标是修精度，不是补数据。
补数据走 fill_kline_from_snapshot.py（当日）或 sync_kline_db（历史）。
"""
import argparse
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_hub.store.kline_db import DB_PATH

RECONNECT_EVERY = 500
COMMIT_EVERY = 200


def db_range(con):
    return con.execute('SELECT MIN(date), MAX(date) FROM kline').fetchone()


def codes_in_db(con):
    return [r[0] for r in con.execute(
        'SELECT DISTINCT code FROM kline ORDER BY code')]


def fetch_range(bs, code, start, end):
    """拉整区间的 date,amount,volume。异常返回 None（与「查无数据」区分）。"""
    for retry in range(3):
        try:
            rs = bs.query_history_k_data_plus(
                code, 'date,amount,volume', start_date=start, end_date=end,
                frequency='d', adjustflag='3')
            out = {}
            while rs.next():
                d, amt, vol = rs.get_row_data()
                try:
                    amt_f, vol_f = float(amt or 0), float(vol or 0)
                except (TypeError, ValueError):
                    continue
                # amount<=0 是停牌，不能标成 exact
                if amt_f > 0:
                    out[d] = (amt_f, vol_f)
            return out
        except Exception as e:
            if retry == 2:
                print(f'  [{code}] 查询失败: {type(e).__name__}: {e}', flush=True)
                return None
            try:
                bs.logout()
            except Exception:
                pass
            bs.login()
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description='回标 amount/volume 为 baostock 精确值')
    ap.add_argument('--start', default=None)
    ap.add_argument('--end', default=None)
    ap.add_argument('--limit', type=int, default=0, help='只处理前 N 只，用于试跑')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)

    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.execute('PRAGMA journal_mode=WAL')
    lo, hi = db_range(con)
    start = args.start or lo
    end = args.end or hi
    codes = codes_in_db(con)
    if args.limit:
        codes = codes[:args.limit]
    print(f'库内 {len(codes)} 只，区间 {start} ~ {end}'
          + ('（--dry-run）' if args.dry_run else ''), flush=True)

    import baostock as bs
    lg = bs.login()
    if lg.error_code != '0':
        print(f'baostock 登录失败 error_code={lg.error_code} msg={lg.error_msg}，中止不写库')
        con.close()
        return 1

    cur = con.cursor()
    updated = amt_changed = vol_changed = skipped_halt = 0
    no_data = []
    amt_errs = []
    t0 = time.time()
    try:
        for i, code in enumerate(codes):
            got = fetch_range(bs, code, start, end)
            if got is None or not got:
                no_data.append(code)
            else:
                have = cur.execute(
                    'SELECT date, amount, volume FROM kline '
                    'WHERE code=? AND date>=? AND date<=?', (code, start, end)
                ).fetchall()
                for d, old_amt, old_vol in have:
                    ref = got.get(d)
                    if ref is None:
                        skipped_halt += 1     # baostock 无此日或当日成交额为 0
                        continue
                    new_amt, new_vol = ref
                    if old_amt and abs(new_amt - old_amt) > 1e-4 * max(abs(new_amt), 1):
                        amt_changed += 1
                        amt_errs.append((old_amt - new_amt) / new_amt * 100.0)
                    if old_vol is not None and abs(new_vol - (old_vol or 0)) > 0.5:
                        vol_changed += 1
                    if not args.dry_run:
                        cur.execute(
                            "UPDATE kline SET amount=?, volume=?, amt_src='exact' "
                            "WHERE code=? AND date=?", (new_amt, new_vol, code, d))
                    updated += 1
            if (i + 1) % COMMIT_EVERY == 0 and not args.dry_run:
                con.commit()
            if (i + 1) % RECONNECT_EVERY == 0:
                print(f'  进度 {i+1}/{len(codes)} elapsed={time.time()-t0:.0f}s '
                      f'updated={updated} amt_changed={amt_changed} '
                      f'vol_changed={vol_changed} no_data={len(no_data)}', flush=True)
                try:
                    bs.logout()
                except Exception:
                    pass
                bs.login()
    finally:
        if not args.dry_run:
            con.commit()
        try:
            bs.logout()
        except Exception:
            pass

    print(f'\n处理 {len(codes)} 只 / {time.time()-t0:.0f}s', flush=True)
    print(f'  更新行数        {updated}')
    print(f'  amount 有变化    {amt_changed}')
    print(f'  volume 有变化    {vol_changed}')
    print(f'  跳过（停牌/无该日）{skipped_halt}')
    print(f'  查不到数据的代码  {len(no_data)}'
          + (f'  样例 {no_data[:5]}' if no_data else ''))
    if amt_errs:
        amt_errs.sort()
        n = len(amt_errs)
        def q(p):
            return amt_errs[min(n - 1, int(n * p))]
        print(f'  amount 原值相对偏差 P5={q(.05):+.3f}% P50={q(.50):+.3f}% '
              f'P95={q(.95):+.3f}% |max|={max(abs(amt_errs[0]), abs(amt_errs[-1])):.3f}%')
    if not args.dry_run:
        dist = dict(con.execute(
            "SELECT COALESCE(amt_src,'NULL'), COUNT(*) FROM kline GROUP BY 1"))
        print(f'  回标后 amt_src 分布 {dist}')
    con.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())


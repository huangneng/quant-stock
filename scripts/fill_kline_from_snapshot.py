#!/usr/bin/env python3
"""用新浪盘后快照按日期批量补齐日 K 行（精确 OHLCV + 成交额）。

用法:
    python3 scripts/fill_kline_from_snapshot.py 2026-09-01

为什么需要这条路：所有日K源（腾讯/mootdx/akshare/baostock）都只能
逐票请求，而快照端点是批量的（600 只/请求）。实测对比同一批数据：

    腾讯日K 逐票   5207 次请求   34 分钟   只落 553 只（WAF 拦截）
    baostock 兜底  5207 次请求   4.5 小时  0 行
    新浪快照       9 次请求      ~2 秒     5189 行，成交额为精确值

适用窗口：目标交易日收盘后，到下一交易日开盘前。这段时间里快照持有的
就是目标日的定型值。开盘后快照变成当日盘中值，就补不了前一天了。

安全约束：
- 只写快照日期等于目标日期的行。日期不符占比 > 1% 判定为「拿到的不是
  目标日定型快照」，整体中止不写库——少量不符是退市股（末次报价停在
  几个月前），实测恒定 4 只。
- close/volume/amount 任一 <= 0 视为停牌，跳过。
- 覆盖率 < 95% 不写库，宁可不写也不留半份。
- pctChg 用快照的昨收算，不依赖库内前一行。
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import data_hub.api as hub
from data_hub.store.kline_db import KlineDB
from daily_select import get_stock_list, _is_real_stock

MIN_COVERAGE = 0.95
MAX_BAD_DATE_RATIO = 0.01
UNIFIED = ['code', 'date', 'open', 'high', 'low', 'close',
           'volume', 'amount', 'turn', 'pctChg']


def fill_from_snapshot(target, dry_run=False):
    """用快照补齐 target 日的全市场日 K 行。可复用（CLI 与例行任务共用）。

    返回 dict：
      wrote          实际写入行数（dry_run 或中止时为 0）
      rows           通过守卫、可写的行数
      coverage       rows / 目标股票数
      bad_date       快照日期不符 target 的行数
      halted         价/量/额<=0 被跳过的行数
      aborted_reason 中止原因（None 表示正常）
    """
    stock_list = [(c, n) for c, n in get_stock_list() if _is_real_stock(c)]
    codes = [c for c, _ in stock_list]
    t0 = time.time()
    snapshot = hub.get_market_snapshot(codes)
    rows, st = collect(snapshot, target, codes)
    bad_ratio = st['bad_date'] / max(1, len(codes))
    cov = len(rows) / max(1, len(codes))
    out = {'wrote': 0, 'rows': len(rows), 'coverage': cov,
           'bad_date': st['bad_date'], 'halted': st['halted'],
           'aborted_reason': None, 'elapsed_s': 0.0}
    if bad_ratio > MAX_BAD_DATE_RATIO:
        out['aborted_reason'] = (f'日期不符占比 {bad_ratio:.2%} > {MAX_BAD_DATE_RATIO:.0%}'
                                 f'（快照非 {target} 定型值）')
    elif cov < MIN_COVERAGE:
        out['aborted_reason'] = f'覆盖率 {cov:.1%} < {MIN_COVERAGE:.0%}'
    elif not dry_run:
        # 快照直接返回成交额（元），标 exact，避免日后被腾讯近似值覆盖。
        out['wrote'] = KlineDB().upsert_kline(pd.DataFrame(rows)[UNIFIED], amt_src='exact')
    out['elapsed_s'] = round(time.time() - t0, 1)
    return out


def collect(snapshot, target, codes):
    """从快照里挑出目标日期的可用行。返回 (rows, 统计字典)。"""
    valid = set(codes)
    rows, halted, bad_date, bad_samples = [], 0, 0, []
    for code, info in snapshot.items():
        if code not in valid:
            continue
        if str(info.get('date')) != target:
            bad_date += 1
            if len(bad_samples) < 6:
                bad_samples.append(f"{code}/{info.get('name', '')}/{info.get('date')}")
            continue
        close = float(info.get('close') or 0)
        vol = float(info.get('volume') or 0)
        amt = float(info.get('amount') or 0)
        if close <= 0 or vol <= 0 or amt <= 0:
            halted += 1
            continue
        rows.append({
            'code': code, 'date': target,
            'open': float(info.get('open') or 0),
            'high': float(info.get('high') or 0),
            'low': float(info.get('low') or 0),
            'close': close, 'volume': vol, 'amount': amt,
            'turn': 0.0, 'pctChg': float(info.get('pctChg') or 0.0),
        })
    return rows, {'halted': halted, 'bad_date': bad_date, 'bad_samples': bad_samples}


def main(argv=None):
    ap = argparse.ArgumentParser(description='按日期用新浪快照补齐日 K 行')
    ap.add_argument('date', help='目标交易日，如 2026-09-01')
    ap.add_argument('--dry-run', action='store_true', help='只报告，不写库')
    args = ap.parse_args(argv)
    target = args.date

    r = fill_from_snapshot(target, dry_run=args.dry_run)
    print(f'目标日 {target}: 可写 {r["rows"]} 行 | 停牌跳过 {r["halted"]} | '
          f'日期不符 {r["bad_date"]} | 覆盖率 {r["coverage"]:.1%} | {r["elapsed_s"]}s', flush=True)
    if r['aborted_reason']:
        print(f'中止不写库：{r["aborted_reason"]}')
        return 1
    if args.dry_run:
        print(f'--dry-run 未写库（覆盖率 {r["coverage"]:.1%}）')
        return 0
    print(f'已写入/更新 {r["wrote"]} 行')
    return 0


if __name__ == '__main__':
    sys.exit(main())


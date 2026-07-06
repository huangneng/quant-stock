#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T+1 日集合竞价采集脚本。

在交易日 9:25 之后（北京时间）运行：对「上一交易日选股、次日为今日」的记录，
拉取今日开盘集合竞价成交额并写入 next_auction_* 字段（含真实竞价强度）。

时区守卫：仅在北京时间交易日 09:25–09:35 推荐运行；非交易日或时间不符直接拒绝。
"""
from __future__ import annotations

import argparse
import sys
from datetime import time as dt_time, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BEIJING = timezone(timedelta(hours=8))


def _now_beijing() -> pd.Timestamp:
    return pd.Timestamp.now(tz=BEIJING)


def _load_trade_dates() -> list[str]:
    from scripts.backfill_next_auction import _load_trade_dates as _ltd
    return _ltd()


def main() -> None:
    parser = argparse.ArgumentParser(description='T+1 集合竞价采集')
    parser.add_argument('--force', action='store_true', help='跳过时区/交易日守卫，强制运行')
    parser.add_argument('--date', default=None, help='指定要补的选股日 YYYY-MM-DD（默认上一交易日）')
    args = parser.parse_args()

    now = _now_beijing()
    today_iso = now.strftime('%Y-%m-%d')

    if not args.force:
        trade_dates = _load_trade_dates()
        if today_iso not in trade_dates:
            print(f'[竞价采集] 北京时间 {today_iso} 非交易日，拒绝执行（如需强制用 --force）')
            return
        if now.time() < dt_time(9, 25):
            print(f'[竞价采集] 北京时间 {now.strftime("%H:%M")} 早于 9:25，集合竞价未结束，拒绝执行')
            return
        if now.time() > dt_time(9, 40):
            print(f'[竞价采集] 警告：北京时间 {now.strftime("%H:%M")} 已晚于 9:40，'
                  f'成交额可能混入盘中数据，强度仅供近似参考')

    # 默认补「上一交易日」选股（其次日竞价即今日）
    sel_date = args.date
    if sel_date is None:
        trade_dates = _load_trade_dates()
        past = [d for d in trade_dates if d < today_iso]
        if not past:
            print('[竞价采集] 找不到上一交易日，退出')
            return
        sel_date = past[-1]

    print(f'[竞价采集] 选股日={sel_date} 次日竞价日={today_iso}（北京时间 {now.strftime("%H:%M")}）')
    from scripts.backfill_next_auction import backfill
    stats = backfill(start=sel_date, end=sel_date, overwrite=True)
    print('[竞价采集] ' + ' '.join(f'{k}={v}' for k, v in stats.items()))

    # 命中率：统计该日选股有多少只拿到了真实竞价强度
    try:
        import json
        from scripts.backfill_next_auction import SELECTIONS_FILE, _date_key
        data = json.loads(Path(SELECTIONS_FILE).read_text(encoding='utf-8'))
        stocks = data.get(_date_key(sel_date), {}).get('stocks', [])
        total = len(stocks)
        hit = sum(1 for s in stocks if s.get('next_auction_strength') is not None)
        if total:
            print(f'[竞价采集] 真实竞价强度命中 {hit}/{total}（{hit/total*100:.0f}%）'
                  + ('，命中偏低可稍后重试或走历史回溯' if hit / total < 0.5 else ''))
    except Exception:
        pass


if __name__ == '__main__':
    main()

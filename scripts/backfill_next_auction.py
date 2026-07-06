#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回填历史选股后一个交易日的竞价强度字段。

不覆盖原 auction_* 字段；新增 next_auction_* 字段供 tracker 展示使用。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SELECTIONS_FILE = ROOT / 'stock_data' / 'selections.json'
TRADE_CAL = ROOT / 'stock_data' / 'trade_calendar.json'

from stock_research.data_loader import fetch_ohlcv
from stock_research.feature_extractor import extract_features
from stock_research.recommender import score as recommender_score


def _iso(date_key: str) -> str:
    return f'{date_key[:4]}-{date_key[4:6]}-{date_key[6:8]}'


def _date_key(iso: str) -> str:
    return iso.replace('-', '')


def _safe_float(value):
    try:
        if value is None:
            return None
        v = float(value)
        if v != v:
            return None
        return round(v, 4)
    except Exception:
        return None


def _load_json(path: Path):
    if not path.exists():
        raise SystemExit(f'[next-auction] 文件不存在：{path}')
    return json.loads(path.read_text(encoding='utf-8'))


def _save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _refresh_trade_calendar_if_needed() -> None:
    if TRADE_CAL.exists():
        return
    from scripts.check_trade_date import get_trade_dates
    get_trade_dates()


def _load_trade_dates() -> list[str]:
    _refresh_trade_calendar_if_needed()
    if not TRADE_CAL.exists():
        raise SystemExit(f'[next-auction] 交易日历缺失：{TRADE_CAL}')
    data = _load_json(TRADE_CAL)
    if isinstance(data, dict):
        dates = data.get('dates') if isinstance(data.get('dates'), list) else list(data.keys())
    elif isinstance(data, list):
        dates = data
    else:
        raise SystemExit(f'[next-auction] 交易日历格式异常：{type(data)}')
    return sorted(d for d in dates if isinstance(d, str) and len(d) == 10)


def _next_trade_date(date_key: str, trade_dates: list[str]) -> str | None:
    iso = _iso(date_key)
    for d in trade_dates:
        if d > iso:
            return d
    return None


def _in_range(date_key: str, start: str | None, end: str | None) -> bool:
    iso = _iso(date_key)
    if start and iso < start:
        return False
    if end and iso > end:
        return False
    return True


def _calc_next_auction(stock: dict, entry_date_key: str, next_date: str,
                       auction_amounts: dict | None = None) -> dict | None:
    code = stock.get('code')
    if not code:
        return None
    today_iso = pd.Timestamp.now().strftime('%Y-%m-%d')
    require_today = (next_date == today_iso)
    start_date = (datetime.strptime(_iso(entry_date_key), '%Y-%m-%d') - pd.Timedelta(days=260)).strftime('%Y-%m-%d')
    hist = fetch_ohlcv(code, start_date, next_date, require_today=require_today)
    if hist is None or hist.empty:
        return None
    hist = hist[hist['date'] <= next_date].copy()
    if hist[hist['date'] == next_date].empty:
        return None

    sample = {
        'code': code,
        'entry_date': next_date,
        'signal_type': stock.get('signal_type', 'breakthrough'),
        'is_limit_up': bool(stock.get('is_limit_up', False)),
        'hist': hist,
    }
    # 注入真实竞价成交额（若已采集）
    auc = (auction_amounts or {}).get(code)
    if auc and auc.get('amount') is not None:
        sample['auction_amount'] = auc['amount']
        if auc.get('volume_ratio') is not None:
            sample['auction_volume_ratio'] = auc['volume_ratio']
    else:
        # 实时未采到：尝试近5日历史回溯（东财分钟 9:30 首根）
        try:
            from data_hub.api import get_auction_amount_hist
            hist_amount = get_auction_amount_hist(code, next_date)
        except Exception:
            hist_amount = None
        if hist_amount is not None:
            sample['auction_amount'] = hist_amount

    feat = extract_features(sample)
    if feat is None:
        return None

    # auction_gap_pct / breakout 可能为 None（盘中快照未含开盘价时）
    # 降级：直接从 K 线的 open/close 计算
    gap = _safe_float(feat.get('auction_gap_pct'))
    breakout = _safe_float(feat.get('auction_breakout_pct'))
    if gap is None:
        prev_rows = hist[hist['date'] < next_date]
        if not prev_rows.empty:
            prev_close = float(prev_rows.iloc[-1]['close'])
            open_price = float(hist[hist['date'] == next_date].iloc[0]['open'])
            if prev_close:
                gap = _safe_float((open_price - prev_close) / prev_close)
    if breakout is None and gap is not None:
        entry_iso = _iso(entry_date_key)
        pre_entry = hist[hist['date'] < entry_iso]
        if not pre_entry.empty:
            pre_high = float(pre_entry['high'].max())
            open_price = float(hist[hist['date'] == next_date].iloc[0]['open'])
            if pre_high:
                breakout = _safe_float((open_price - pre_high) / pre_high)

    # 竞价强度：有真实竞价额时用 vs20 映射，否则保持 None（待采集）
    strength = None
    vs20 = _safe_float(feat.get('auction_amount_vs_20d'))
    if vs20 is not None:
        from stock_research.recommender import _auction_vs20_to_strength
        strength = _safe_float(_auction_vs20_to_strength(vs20))

    return {
        'next_auction_date': next_date,
        'next_auction_strength': strength,
        'next_auction_gap_pct': gap,
        'next_auction_breakout_pct': breakout,
    }


def backfill(start: str | None = None, end: str | None = None, overwrite: bool = False) -> dict:
    selections = _load_json(SELECTIONS_FILE)
    trade_dates = _load_trade_dates()
    stats = {'dates': 0, 'stocks': 0, 'updated': 0, 'skipped_complete': 0, 'skipped_no_next': 0, 'skipped_no_data': 0}

    today_iso = pd.Timestamp.now().strftime('%Y-%m-%d')

    for date_key in sorted(selections.keys()):
        if not _in_range(date_key, start, end):
            continue
        payload = selections.get(date_key, {})
        stocks = payload.get('stocks', []) if isinstance(payload, dict) else []
        if not stocks:
            continue
        next_date = _next_trade_date(date_key, trade_dates)
        stats['dates'] += 1
        if next_date is None:
            stats['skipped_no_next'] += len(stocks)
            continue

        # 若次日即今日，拉取真实竞价成交额一次（全市场快照），供本批次复用
        auction_amounts = {}
        if next_date == today_iso:
            try:
                from data_hub.api import get_auction_amount
                auction_amounts = get_auction_amount()
            except Exception:
                auction_amounts = {}

        for stock in stocks:
            stats['stocks'] += 1
            # 不遗漏保障：仅当 gap 与 strength 都已有值（记录完整）且未指定 overwrite 才跳过
            complete = (stock.get('next_auction_gap_pct') is not None
                        and stock.get('next_auction_strength') is not None)
            if not overwrite and complete:
                stats['skipped_complete'] += 1
                continue
            result = _calc_next_auction(stock, date_key, next_date, auction_amounts=auction_amounts)
            if result is None:
                stats['skipped_no_data'] += 1
                continue
            # 不覆盖已有的非空值（除非 overwrite）：保留已采集的真实强度
            if not overwrite:
                for k, v in list(result.items()):
                    if v is None and stock.get(k) is not None:
                        result[k] = stock.get(k)
            stock.update(result)
            stats['updated'] += 1

    _save_json(SELECTIONS_FILE, selections)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description='回填历史选股后一个交易日竞价强度字段')
    parser.add_argument('--start', default=None, help='开始选股日 YYYY-MM-DD')
    parser.add_argument('--end', default=None, help='结束选股日 YYYY-MM-DD')
    parser.add_argument('--overwrite', action='store_true', help='覆盖已有 next_auction_* 字段')
    args = parser.parse_args()

    stats = backfill(start=args.start, end=args.end, overwrite=args.overwrite)
    print('[next-auction] ' + ' '.join(f'{k}={v}' for k, v in stats.items()))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回填历史选股的行业板块共振新高字段。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SELECTIONS_FILE = ROOT / 'stock_data' / 'selections.json'

from stock_research.sector_resonance import (
    build_sector_member_map,
    detect_sector_resonance,
    load_trade_dates,
)


def _iso(date_key: str) -> str:
    return f'{date_key[:4]}-{date_key[4:6]}-{date_key[6:8]}'


def _load_json(path: Path):
    if not path.exists():
        raise SystemExit(f'[sector-backfill] 文件不存在：{path}')
    return json.loads(path.read_text(encoding='utf-8'))


def _save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _in_range(date_key: str, start: str | None, end: str | None) -> bool:
    iso = _iso(date_key)
    if start and iso < start:
        return False
    if end and iso > end:
        return False
    return True


def backfill(start: str | None = None, end: str | None = None, overwrite: bool = False, force_refresh_members: bool = False) -> dict:
    selections = _load_json(SELECTIONS_FILE)
    trade_dates = load_trade_dates()
    member_map = build_sector_member_map(force_refresh=force_refresh_members)
    stats = {
        'dates': 0,
        'stocks': 0,
        'updated_true': 0,
        'updated_false': 0,
        'skipped_existing': 0,
        'skipped_no_mapping': 0,
    }

    if not member_map:
        print('[sector-backfill] 板块成分映射为空，将只写入 false 或跳过已有记录')

    for date_key in sorted(selections.keys()):
        if not _in_range(date_key, start, end):
            continue
        payload = selections.get(date_key, {})
        stocks = payload.get('stocks', []) if isinstance(payload, dict) else []
        if not stocks:
            continue
        stats['dates'] += 1
        pick_date = _iso(date_key)
        for stock in stocks:
            stats['stocks'] += 1
            if not overwrite and 'sector_resonance' in stock:
                stats['skipped_existing'] += 1
                continue
            code = stock.get('code')
            if not code:
                stock['sector_resonance'] = False
                stats['skipped_no_mapping'] += 1
                stats['updated_false'] += 1
                continue
            result = detect_sector_resonance(code, pick_date, member_map=member_map, trade_dates=trade_dates)
            if result:
                stock.update(result)
                stats['updated_true'] += 1
            else:
                if code not in member_map:
                    stats['skipped_no_mapping'] += 1
                for k in ('sector_resonance', 'sector_resonance_type', 'sector_resonance_name',
                          'sector_resonance_date', 'sector_resonance_breakout_pct'):
                    stock.pop(k, None)
                stock['sector_resonance'] = False
                stats['updated_false'] += 1

    _save_json(SELECTIONS_FILE, selections)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description='回填历史选股行业/概念板块共振新高字段')
    parser.add_argument('--start', default=None, help='开始选股日 YYYY-MM-DD')
    parser.add_argument('--end', default=None, help='结束选股日 YYYY-MM-DD')
    parser.add_argument('--overwrite', action='store_true', help='覆盖已有 sector_resonance 字段')
    parser.add_argument('--force-refresh-members', action='store_true', help='强制刷新行业成分缓存')
    args = parser.parse_args()

    stats = backfill(
        start=args.start,
        end=args.end,
        overwrite=args.overwrite,
        force_refresh_members=args.force_refresh_members,
    )
    print('[sector-backfill] ' + ' '.join(f'{k}={v}' for k, v in stats.items()))


if __name__ == '__main__':
    main()

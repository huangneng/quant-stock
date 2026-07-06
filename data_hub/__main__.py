#!/usr/bin/env python3
"""CLI: python -m data_hub sync_today

增量同步今日 KlineDB，供 run_daily.sh 和 launchd 调用。
"""
import argparse
from datetime import date, timedelta

def sync_today():
    from data_hub import api as hub
    today = date.today()
    start = (today - timedelta(days=5)).isoformat()
    end = today.isoformat()
    print(f"[sync_kline] incremental {start} ~ {end}")
    result = hub.sync_kline_db(start, end, full=False)
    print(f"  synced={result.get('synced',0)} failed={result.get('failed',0)} elapsed={result.get('elapsed_s',0):.1f}s")
    return result


def main():
    parser = argparse.ArgumentParser(description='data_hub KlineDB 同步工具')
    parser.add_argument('command', choices=['sync_today'], help='sync_today: 增量同步')
    args = parser.parse_args()
    if args.command == 'sync_today':
        sync_today()


if __name__ == '__main__':
    main()

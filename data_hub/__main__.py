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
    print(f"  synced={result.get('synced',0)} failed={result.get('failed',0)} "
          f"fail_rate={result.get('fail_rate',0):.1%} marked_failed={result.get('marked_failed',0)} "
          f"skipped_dead={result.get('skipped_dead',0)} elapsed={result.get('elapsed_s',0):.1f}s")
    if result.get('failed') and not result.get('marked_failed'):
        print("  注意：本轮失败未计入 failed_codes（判定为上游故障，避免死码名单自锁）")
    if result.get('aborted'):
        print(f"  本轮已中止：{result['aborted']}")
        print("  last_sync_date 未推进，上游恢复后需重跑本轮")
    elif not result.get('last_sync_advanced', True):
        print(f"  本轮 skipped_unsettled={result.get('skipped_unsettled',0)}，一行未落库，"
              f"last_sync_date 未推进（盘中跑批属正常，收盘后需重跑）")
    fc = result.get('failed_codes') or []
    if fc:
        print(f"  failed_sample={','.join(fc)}")
    tripped = {n: s for n, s in (result.get('breaker') or {}).items() if s.get('tripped')}
    if tripped:
        detail = ' '.join(f"{n}(skipped={s['skipped']},probes={s['probes']},"
                          f"slow={s.get('slow_calls', 0)})"
                          for n, s in tripped.items())
        print(f"  breaker_tripped={detail}")
    recovered = {n: s for n, s in (result.get('breaker') or {}).items() if s.get('recovered')}
    if recovered:
        detail = ' '.join(f"{n}(x{s['recovered']})" for n, s in recovered.items())
        print(f"  breaker_recovered={detail}")
    timeouts = {n: c for n, c in (result.get('timeouts') or {}).items() if c}
    if timeouts:
        detail = ' '.join(f"{n}(x{c})" for n, c in timeouts.items())
        print(f"  call_timeouts={detail}（单次取数超时被打断并降级）")
    return result


def main():
    parser = argparse.ArgumentParser(description='data_hub KlineDB 同步工具')
    parser.add_argument('command', choices=['sync_today'], help='sync_today: 增量同步')
    args = parser.parse_args()
    if args.command == 'sync_today':
        sync_today()


if __name__ == '__main__':
    main()

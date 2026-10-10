#!/usr/bin/env python3
"""CLI: python -m data_hub sync_today

收盘后例行同步今日 KlineDB，供 run_daily.sh 和 launchd 调用。

快照优先：先用新浪快照批量补当日（秒级、精确成交额、不碰腾讯 WAF）；
快照成功即推进 last_sync_date 并对少量漏掉的 code 走 bounded 腾讯逐票补零头；
快照整体不可用时退回腾讯逐票全量（旧行为）作兜底。
"""
import argparse
from datetime import date, timedelta


def _print_sync_result(result):
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
    timeouts = {n: c for n, c in (result.get('timeouts') or {}).items() if c}
    if timeouts:
        detail = ' '.join(f"{n}(x{c})" for n, c in timeouts.items())
        print(f"  call_timeouts={detail}（单次取数超时被打断并降级）")


def _sync_via_tencent():
    """腾讯逐票全量兜底（快照不可用时）。即改造前的旧行为。"""
    from data_hub import api as hub
    today = date.today()
    start = (today - timedelta(days=5)).isoformat()
    end = today.isoformat()
    print(f"[sync_kline] 兜底：腾讯逐票增量 {start} ~ {end}")
    result = hub.sync_kline_db(start, end, full=False)
    _print_sync_result(result)
    return result


def sync_today():
    """快照优先的收盘后例行同步。"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from data_hub import api as hub
    from data_hub.store.kline_db import KlineDB
    from scripts.fill_kline_from_snapshot import fill_from_snapshot

    today = date.today().isoformat()
    print(f"[sync_today] 快照优先，目标日 {today}")
    r = fill_from_snapshot(today)
    print(f"  快照：可写 {r['rows']} 行 覆盖率 {r['coverage']:.1%} "
          f"停牌 {r['halted']} 日期不符 {r['bad_date']} 耗时 {r['elapsed_s']}s")

    if r['aborted_reason'] is not None:
        # 快照不可用（空 / 日期不符 / 覆盖率不足）→ 退回腾讯逐票全量
        print(f"  快照不可用（{r['aborted_reason']}），退回腾讯逐票兜底")
        return _sync_via_tencent()

    # 快照成功：当日行已入库（exact），推进 last_sync_date
    print(f"  快照成功，已写入/更新 {r['wrote']} 行（amt_src=exact）")
    KlineDB().meta_set('last_sync_date', today)
    print(f"  last_sync_date 推进至 {today}")

    # 补零头：快照漏掉的少量 code（多为停牌/新上市）走 bounded 腾讯逐票，非致命
    stragglers = _codes_missing_today(today)
    if stragglers:
        print(f"  补零头：{len(stragglers)} 只缺当日行，bounded 腾讯逐票（紧预算，非致命）")
        res = hub.sync_kline_db(today, today, codes=stragglers, full=False,
                                early_stop_min_samples=50, early_stop_fail_rate=0.9,
                                max_round_seconds=300, slow_avg_seconds=5.0,
                                slow_min_samples=40)
        print(f"    零头 synced={res.get('synced',0)} failed={res.get('failed',0)} "
              f"elapsed={res.get('elapsed_s',0):.1f}s"
              + (f" aborted={res['aborted']}" if res.get('aborted') else ""))
    else:
        print("  无缺口，当日全市场已齐")
    return r


def _codes_missing_today(today):
    """返回当日仍无 K 线行的真实个股代码（供补零头用）。"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from daily_select import get_stock_list, _is_real_stock
    from data_hub.store.kline_db import KlineDB
    codes = [c for c, _ in get_stock_list() if _is_real_stock(c)]
    db = KlineDB()
    with db._conn() as c:
        have = {r[0] for r in c.execute(
            "SELECT code FROM kline WHERE date=?", (today,))}
    return [c for c in codes if c not in have]


def main():
    parser = argparse.ArgumentParser(description='data_hub KlineDB 同步工具')
    parser.add_argument('command', choices=['sync_today'], help='sync_today: 收盘后快照优先同步')
    args = parser.parse_args()
    if args.command == 'sync_today':
        sync_today()


if __name__ == '__main__':
    main()

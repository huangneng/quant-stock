"""交易日校验脚本

功能：判断今日是否为 A 股交易日。
- 是交易日 → exit 0
- 非交易日 → exit 1（调用方据此跳过后续步骤）

数据源：akshare tool_trade_date_hist_sina（缓存到本地，避免每次拉取）
"""
import os
import sys
import json
from datetime import date, datetime, timedelta

CACHE_FILE = 'stock_data/trade_calendar.json'
# 交易日历每年才更新一次，按"是否覆盖未来 30 天"判断是否需要刷新即可
CACHE_LOOKAHEAD_DAYS = 30


def _load_cache():
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, encoding='utf-8') as f:
            data = json.load(f)
        return set(data['dates'])
    except Exception:
        return None


def _save_cache(dates: set):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            'cached_at': datetime.now().isoformat(),
            'dates': sorted(dates),
        }, f, ensure_ascii=False)


def _cache_is_fresh(dates: set) -> bool:
    """缓存只要覆盖到「今天 + LOOKAHEAD」就算新鲜，避免每周强刷网络。"""
    if not dates:
        return False
    horizon = (date.today() + timedelta(days=CACHE_LOOKAHEAD_DAYS)).strftime('%Y-%m-%d')
    max_date = max(dates)
    return max_date >= horizon


def get_trade_dates() -> set:
    cached = _load_cache()
    if cached is not None and _cache_is_fresh(cached):
        return cached
    # 缓存过期或不存在 → 尝试 akshare 刷新；akshare 不可用时降级用旧缓存
    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        dates = {str(d) for d in df['trade_date']}
        _save_cache(dates)
        return dates
    except Exception as e:
        if cached is not None:
            print(f'[check_trade_date] akshare 不可用（{e}），降级使用旧缓存', file=sys.stderr)
            return cached
        raise


def is_trade_day(d: date) -> bool:
    return d.strftime('%Y-%m-%d') in get_trade_dates()


def main():
    today = date.today()

    # 先检查是否为交易日
    if not is_trade_day(today):
        print(f'[check_trade_date] {today} 非交易日（周末/节假日），跳过')
        sys.exit(1)

    # 再检查是否已收盘（15:00 之后数据才可用）
    from trade_utils import is_market_closed
    if not is_market_closed(today):
        print(f'[check_trade_date] {today} 是交易日但尚未收盘（北京时间 15:00 前），跳过扫描')
        sys.exit(2)

    print(f'[check_trade_date] {today} 是 A 股交易日且已收盘，继续执行扫描')
    sys.exit(0)


if __name__ == '__main__':
    main()

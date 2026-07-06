"""交易时间感知工具

统一处理：
- 市场是否已收盘（15:00 后才是有效交易日）
- 当前有效的扫描日期
"""
from datetime import datetime, timezone, timedelta, date

# 北京时间 = UTC+8
CST = timezone(timedelta(hours=8))
MARKET_CLOSE_HOUR = 15  # A股收盘时间（15:00）


def now_cst() -> datetime:
    """返回当前北京时间"""
    return datetime.now(CST)


def is_market_closed(d: date = None) -> bool:
    """
    判断指定日期的 A 股市场是否已收盘。
    - 如果 d 是过去日期 → True
    - 如果 d 是今天且当前北京时刻 >= 15:00 → True
    - 如果 d 是未来日期或今天但未到 15:00 → False
    """
    if d is None:
        d = date.today()
    today_cst = now_cst().date()
    if d < today_cst:
        return True  # 历史日期，数据必然已存在
    if d > today_cst:
        return False  # 未来日期
    # 今天：判断是否已过 15:00
    return now_cst().hour >= MARKET_CLOSE_HOUR


def get_effective_scan_date() -> str:
    """
    返回当前应扫描的最新日期（YYYYMMDD）。
    - 已收盘 → 返回今天
    - 未收盘 → 返回最近一个交易日（暂简化为昨天，交易日历校准由 check_trade_date 负责）
    """
    today = date.today()
    if is_market_closed(today):
        return today.strftime('%Y%m%d')
    # 未收盘，退回到昨天
    yesterday = today - timedelta(days=1)
    return yesterday.strftime('%Y%m%d')


def should_push_today() -> bool:
    """今天是否应该推送（已收盘的交易日才推送）"""
    return is_market_closed(date.today())
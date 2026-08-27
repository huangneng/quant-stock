"""data_hub 公共门面。所有调用方应仅使用此模块。"""
from __future__ import annotations
from typing import Optional
import pandas as pd


def get_universe(force_refresh: bool = False) -> pd.DataFrame:
    """返回全市场股票列表（已过滤指数/ETF），列：[code, name]。"""
    from data_hub.router import get_router
    return get_router().get_universe(force_refresh=force_refresh)


def get_kline(code: str, start: str, end: str, *, require_today: bool = False) -> Optional[pd.DataFrame]:
    """获取历史日线（自动 KlineDB→Baostock→Akshare 路由）。

    require_today=True：若 end 为今日且 KlineDB/baostock 缺今日 K 线，
    自动用 Sina 实时快照拼一行进 DataFrame。
    """
    from data_hub.router import get_router
    return get_router().get_kline(code, start, end, require_today=require_today)


def get_market_snapshot(codes: Optional[list] = None) -> dict:
    """全市场（或指定列表）实时/收盘快照（Sina）。
    返回 {bs_code: {date,open,high,low,close,volume,amount,turn,pctChg}}。
    """
    from data_hub.router import get_router
    return get_router().get_market_snapshot(codes)


def check_completeness(codes: list, end_date: str, min_rows: int = 100) -> dict:
    """检查 KlineDB 中给定 codes 截至 end_date 的完整性与历史深度。
    返回 {total, present, missing_codes, missing_pct, shallow_count, shallow_codes,
    shallow_pct, min_rows, last_sync_date}。
    """
    from data_hub.completeness import check_completeness as _impl
    return _impl(codes, end_date, min_rows=min_rows)


def sync_kline_db(start: str, end: str, codes: Optional[list] = None,
                  full: bool = False, skip_retry_gte: int = 5,
                  skip_window_days: int = 7, breaker_fail_threshold: int = 20,
                  breaker_probe_interval: int = 200,
                  breaker_slow_call_s: float = 3.0,
                  mark_failed_max_fail_rate: float = 0.2) -> dict:
    """增量/全量同步 KlineDB。

    返回 {synced, failed, fail_rate, marked_failed, skipped_dead, breaker,
    failed_codes, elapsed_s}。breaker 为每源轮内熔断统计。
    失败率超过 mark_failed_max_fail_rate 时判定为上游故障，本轮失败不写 failed_codes。
    """
    from data_hub.router import get_router
    return get_router().sync_kline_db(start, end, codes=codes, full=full,
                                      skip_retry_gte=skip_retry_gte,
                                      skip_window_days=skip_window_days,
                                      breaker_fail_threshold=breaker_fail_threshold,
                                      breaker_probe_interval=breaker_probe_interval,
                                      breaker_slow_call_s=breaker_slow_call_s,
                                      mark_failed_max_fail_rate=mark_failed_max_fail_rate)


def get_new_high_stocks(symbols=('历史新高', '一年新高')) -> set:
    """当日同花顺创新高个股集合（sh./sz. 前缀）。选股安全网用，异常返回空集。"""
    from data_hub.router import get_router
    return get_router().get_new_high_stocks(symbols=symbols)



def get_sector_boards(board_type: str, force_refresh: bool = False) -> pd.DataFrame:
    """获取行业/概念板块列表，列：[type, code, name]。"""
    from data_hub.router import get_router
    return get_router().get_sector_boards(board_type, force_refresh=force_refresh)


def get_sector_members(board_type: str, board_name: str | None = None,
                       board_code: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """获取行业/概念板块成分，列：[board_type, board_code, board_name, code, name]。"""
    from data_hub.router import get_router
    return get_router().get_sector_members(board_type, board_name=board_name, board_code=board_code,
                                           force_refresh=force_refresh)


def get_sector_kline(board_type: str, board_name: str | None, board_code: str | None,
                     start: str, end: str, force_refresh: bool = False) -> pd.DataFrame:
    """获取行业/概念板块指数日线，列：[date, open, high, low, close, volume, amount, pctChg]。"""
    from data_hub.router import get_router
    return get_router().get_sector_kline(board_type, board_name=board_name, board_code=board_code,
                                         start=start, end=end, force_refresh=force_refresh)

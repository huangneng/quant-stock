"""数据源抽象基类。"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional
import pandas as pd

UNIFIED_COLS = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'turn', 'pctChg']


class SourceUnavailable(Exception):
    """源整体不可用（被封禁 / 限流 / 认证失效）。

    与「这只票没数据」是两件事，必须区分：
    - `get_kline` 返回 None：该标的在本源查无数据（退市、停牌、代码不存在），
      是正常业务结果，不能计入熔断——否则退市票扎堆时会把好源误判为故障。
    - 抛本异常：本源现在谁都查不了，应立即计入熔断，让后续标的直接跳过该源。

    只在能明确归因到源侧的场景抛出（如 WAF 拦截页），
    解析失败这类可能只是单只票脏数据的情况仍返回 None。
    """


class DataSource(ABC):
    name: str = 'base'

    def login(self) -> bool:
        return True

    def logout(self) -> None:
        pass

    @abstractmethod
    def get_kline(self, code: str, start: str, end: str) -> Optional[pd.DataFrame]:
        """返回 UNIFIED_COLS 格式的 DataFrame，失败返回 None。"""
        ...


class SnapshotSource(ABC):
    """支持实时/收盘快照的源。"""

    @abstractmethod
    def get_market_snapshot(self, codes: list) -> dict:
        """返回 {bs_code: {date,open,high,low,close,volume,amount,turn,pctChg}}。"""
        ...

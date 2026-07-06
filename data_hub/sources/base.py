"""数据源抽象基类。"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional
import pandas as pd

UNIFIED_COLS = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'turn', 'pctChg']


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

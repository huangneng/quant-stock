# -*- coding: utf-8 -*-
"""统一数据访问层 - 已迁移到 data_hub。

DataProvider 保留作为薄包装，所有调用转发到 data_hub.api。
新代码请直接使用 data_hub.api。
"""
import pandas as pd
from typing import List, Tuple, Optional


UNIFIED_COLS = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pctChg']


class DataProvider:
    """兼容旧接口的薄包装。底层路由由 data_hub 决定。"""

    def __init__(self, primary: str = 'baostock', error_threshold: int = 10, verbose: bool = True):
        self.verbose = verbose
        self._primary_name = primary

    @property
    def current_source_name(self) -> str:
        return 'data_hub'

    def login(self) -> bool:
        return True  # data_hub 内部按需登录

    def logout(self):
        pass

    def get_kline(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        from data_hub import api as hub
        s = _to_iso(start_date)
        e = _to_iso(end_date)
        df = hub.get_kline(code, s, e, require_today=False)
        if df is None or df.empty:
            return pd.DataFrame(columns=UNIFIED_COLS)
        # 旧 schema 不含 turn
        return df[['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pctChg']].copy()

    def get_stock_list(self) -> List[Tuple[str, str]]:
        from data_hub import api as hub
        df = hub.get_universe()
        if df is None or df.empty:
            return []
        return list(zip(df['code'].tolist(), df['name'].tolist()))


def _to_iso(d: str) -> str:
    if '-' in d:
        return d
    return f'{d[:4]}-{d[4:6]}-{d[6:8]}'


_default_provider: Optional[DataProvider] = None


def get_default_provider() -> DataProvider:
    global _default_provider
    if _default_provider is None:
        _default_provider = DataProvider()
        _default_provider.login()
    return _default_provider

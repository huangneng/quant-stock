"""mootdx / 通达信历史日线备源。

作为 Baostock 之后、Akshare 之前的 K 线 fallback。
未安装 mootdx 或 TCP 不可用时自动返回 None，不影响主流程。
"""
from __future__ import annotations

from typing import Optional
import pandas as pd

from data_hub.sources.base import DataSource, UNIFIED_COLS

try:
    from mootdx.quotes import Quotes
    HAS_MOOTDX = True
except ImportError:
    Quotes = None
    HAS_MOOTDX = False


def _code6(code: str) -> str:
    return str(code).split('.')[-1]


def _market(code: str) -> Optional[int]:
    code = str(code)
    if code.startswith('sh.'):
        return 1
    if code.startswith('sz.'):
        return 0
    return None


class MootdxSource(DataSource):
    name = 'mootdx'

    def __init__(self):
        self.client = None

    def login(self) -> bool:
        if not HAS_MOOTDX:
            return False
        if self.client is not None:
            return True
        try:
            self.client = Quotes.factory(market='std')
            return self.client is not None
        except Exception:
            self.client = None
            return False

    def get_kline(self, code: str, start: str, end: str) -> Optional[pd.DataFrame]:
        market = _market(code)
        if market is None:
            return None
        if not self.login():
            return None
        try:
            df = self.client.bars(symbol=_code6(code), frequency=9, market=market, offset=0, count=800)
        except Exception:
            return None
        if df is None or df.empty:
            return None

        df = df.copy()
        date_col = None
        for cand in ('date', 'datetime'):
            if cand in df.columns:
                date_col = cand
                break
        if date_col is None:
            if isinstance(df.index, pd.DatetimeIndex):
                df = df.reset_index().rename(columns={'index': 'date'})
                date_col = 'date'
            else:
                return None

        rename = {}
        if date_col != 'date':
            rename[date_col] = 'date'
        if 'vol' in df.columns and 'volume' not in df.columns:
            rename['vol'] = 'volume'
        df = df.rename(columns=rename)

        for col in ('open', 'high', 'low', 'close'):
            if col not in df.columns:
                return None
        if 'volume' not in df.columns:
            df['volume'] = 0.0
        if 'amount' not in df.columns:
            df['amount'] = 0.0
        if 'turn' not in df.columns:
            df['turn'] = 0.0

        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        for col in ['open', 'high', 'low', 'close', 'volume', 'amount', 'turn']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        if 'pctChg' not in df.columns:
            df['pctChg'] = df['close'].pct_change() * 100.0
        else:
            df['pctChg'] = pd.to_numeric(df['pctChg'], errors='coerce')

        df = df[(df['date'] >= start) & (df['date'] <= end)]
        if df.empty:
            return pd.DataFrame(columns=UNIFIED_COLS)
        return df[UNIFIED_COLS].dropna(subset=['date', 'close']).sort_values('date').reset_index(drop=True)

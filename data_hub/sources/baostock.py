"""Baostock 历史日线数据源。"""
from __future__ import annotations
from typing import Optional
import time
import pandas as pd

from data_hub.sources.base import DataSource

try:
    import baostock as bs
    HAS_BS = True
except ImportError:
    HAS_BS = False

FIELDS = "date,code,open,high,low,close,volume,amount,turn,pctChg"


class BaostockSource(DataSource):
    name = 'baostock'

    def __init__(self):
        self._logged_in = False
        self._query_count = 0

    def login(self) -> bool:
        if not HAS_BS:
            return False
        try:
            rc = bs.login()
            self._logged_in = (rc.error_code == '0')
            return self._logged_in
        except Exception:
            return False

    def logout(self) -> None:
        if self._logged_in:
            try:
                bs.logout()
            except Exception:
                pass
            self._logged_in = False

    def _reconnect_if_needed(self):
        # 长连接易超时；每 500 次重连
        self._query_count += 1
        if self._query_count >= 500:
            self.logout()
            self.login()
            self._query_count = 0

    def get_kline(self, code: str, start: str, end: str) -> Optional[pd.DataFrame]:
        if not self._logged_in:
            self.login()
        self._reconnect_if_needed()
        for attempt in range(2):
            try:
                rs = bs.query_history_k_data_plus(
                    code, FIELDS, start_date=start, end_date=end,
                    frequency='d', adjustflag='2',
                )
                if rs.error_code != '0':
                    # baostock 报错（如"日期格式不正确"），不重试，立刻返回 None
                    return None
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if not rows:
                    return pd.DataFrame(columns=FIELDS.split(','))
                df = pd.DataFrame(rows, columns=rs.fields)
                for c in ['open', 'high', 'low', 'close', 'volume', 'amount', 'turn', 'pctChg']:
                    df[c] = pd.to_numeric(df[c], errors='coerce')
                df = df.dropna(subset=['close']).sort_values('date').reset_index(drop=True)
                return df
            except Exception:
                # 仅网络/异常时重试一次，不重试 baostock 业务错误
                time.sleep(0.2)
        return None

    def get_universe(self) -> Optional[pd.DataFrame]:
        if not self._logged_in:
            self.login()
        try:
            rs = bs.query_stock_basic()
            if rs.error_code != '0':
                return None
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
            if not rows:
                return None
            df = pd.DataFrame(rows, columns=rs.fields)
            # 仅 type==1 (股票)，status==1 (上市)
            df = df[(df['type'] == '1') & (df['status'] == '1')]
            return df[['code', 'code_name']].rename(columns={'code_name': 'name'}).reset_index(drop=True)
        except Exception:
            return None

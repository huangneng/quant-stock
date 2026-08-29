"""Akshare 备用数据源。"""
from __future__ import annotations
from typing import Optional
import pandas as pd

from data_hub.sources.base import DataSource

try:
    import akshare as ak
    HAS_AK = True
except ImportError:
    HAS_AK = False


def _to_ak(bs_code: str) -> str:
    return bs_code.split('.')[1] if '.' in bs_code else bs_code


class AkshareSource(DataSource):
    name = 'akshare'

    def login(self) -> bool:
        return HAS_AK

    def get_kline(self, code: str, start: str, end: str) -> Optional[pd.DataFrame]:
        if not HAS_AK:
            return None
        try:
            df = ak.stock_zh_a_hist(
                symbol=_to_ak(code), period='daily',
                start_date=start.replace('-', ''), end_date=end.replace('-', ''),
                adjust='qfq',
            )
            if df is None or df.empty:
                return None
            df = df.rename(columns={
                '日期': 'date', '开盘': 'open', '收盘': 'close',
                '最高': 'high', '最低': 'low', '成交量': 'volume',
                '成交额': 'amount', '换手率': 'turn', '涨跌幅': 'pctChg',
            })
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            for c in ['open', 'high', 'low', 'close', 'volume', 'amount', 'turn', 'pctChg']:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors='coerce')
                else:
                    df[c] = 0.0
            # 东财 stock_zh_a_hist 的「成交量」单位是手、「成交额」是元，
            # 而统一 schema 要求 volume 是股——漏掉这步换算会让 volume 小 100 倍，
            # 污染所有量能类特征（amount 是对的，所以成交额预筛不受影响）。
            # 同类换算见 tencent_kline.py 的 vol_multiplier。
            df['volume'] = df['volume'] * 100.0
            return df[['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'turn', 'pctChg']]
        except Exception:
            return None

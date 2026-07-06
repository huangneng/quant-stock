"""同花顺板块数据源。

提供行业/概念板块列表和指数日线。当前 akshare 无稳定同花顺成分股接口，
因此 get_members() 明确返回空表，避免覆盖本地映射缓存。
"""
from __future__ import annotations

import pandas as pd


class TonghuashunSectorSource:
    name = 'tonghuashun_sector'

    @staticmethod
    def _normalize_board_type(board_type: str) -> str:
        return 'concept' if board_type == 'concept' else 'industry'

    @staticmethod
    def _empty_boards() -> pd.DataFrame:
        return pd.DataFrame(columns=['type', 'code', 'name'])

    @staticmethod
    def _empty_members() -> pd.DataFrame:
        return pd.DataFrame(columns=['board_type', 'board_code', 'board_name', 'code', 'name'])

    @staticmethod
    def _empty_kline() -> pd.DataFrame:
        return pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pctChg'])

    def get_boards(self, board_type: str) -> pd.DataFrame:
        board_type = self._normalize_board_type(board_type)
        try:
            import akshare as ak
            if board_type == 'concept':
                df = ak.stock_board_concept_name_ths()
            else:
                df = ak.stock_board_industry_name_ths()
            if df is None or df.empty:
                return self._empty_boards()
            rename = {'代码': 'code', '名称': 'name'}
            df = df.rename(columns=rename).copy()
            if 'name' not in df.columns or 'code' not in df.columns:
                return self._empty_boards()
            out = df[['code', 'name']].dropna().copy()
            out['type'] = board_type
            out['code'] = out['code'].astype(str)
            out['name'] = out['name'].astype(str)
            return out[['type', 'code', 'name']].drop_duplicates(['type', 'code', 'name']).reset_index(drop=True)
        except Exception:
            return self._empty_boards()

    def get_members(self, board_type: str, board_name: str | None = None, board_code: str | None = None) -> pd.DataFrame:
        return self._empty_members()

    def get_kline(self, board_type: str, board_name: str | None, board_code: str | None, start: str, end: str) -> pd.DataFrame:
        board_type = self._normalize_board_type(board_type)
        symbol = board_name
        if not symbol and board_code:
            boards = self.get_boards(board_type)
            if not boards.empty:
                matched = boards[boards['code'].astype(str) == str(board_code)]
                if not matched.empty:
                    symbol = str(matched.iloc[0]['name'])
        if not symbol:
            return self._empty_kline()
        try:
            import akshare as ak
            start_date = start.replace('-', '')
            end_date = end.replace('-', '')
            if board_type == 'concept':
                df = ak.stock_board_concept_index_ths(symbol=str(symbol), start_date=start_date, end_date=end_date)
            else:
                df = ak.stock_board_industry_index_ths(symbol=str(symbol), start_date=start_date, end_date=end_date)
            if df is None or df.empty:
                return self._empty_kline()
            rename = {
                '日期': 'date',
                '开盘价': 'open',
                '最高价': 'high',
                '最低价': 'low',
                '收盘价': 'close',
                '成交量': 'volume',
                '成交额': 'amount',
                '涨跌幅': 'pctChg',
            }
            df = df.rename(columns=rename).copy()
            if 'date' not in df.columns:
                return self._empty_kline()
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            for col in ['open', 'high', 'low', 'close', 'volume', 'amount', 'pctChg']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                else:
                    df[col] = pd.NA
            return df[['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pctChg']].dropna(subset=['date', 'close']).sort_values('date')
        except Exception:
            return self._empty_kline()

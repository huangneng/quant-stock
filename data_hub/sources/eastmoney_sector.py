"""东方财富板块数据源。

直接请求东方财富原始接口，服务行业/概念板块列表、成分和指数 K 线。
失败返回空 DataFrame，不影响主流程。
"""
from __future__ import annotations

import re
from typing import Optional

import pandas as pd

from data_hub.sources.eastmoney_client import em_get_json


class EastmoneySectorSource:
    name = 'eastmoney_sector'

    BASE = 'https://push2.eastmoney.com/api/qt/clist/get'
    KLINE = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36',
        'Referer': 'https://quote.eastmoney.com/center/boardlist.html',
    }

    # 东方财富 fs 口径会调整，保留多组候选，优先使用能返回数据的组合。
    BOARD_FS = {
        'industry': ['m:90+t:2+f:!50', 'm:90+t:2'],
        'concept': ['m:90+t:3+f:!50', 'm:90+t:3'],
    }

    def _request_json(self, url: str, params: dict, timeout: int = 12) -> Optional[dict]:
        return em_get_json(url, params=params, headers=self.HEADERS, timeout=timeout)

    @staticmethod
    def _bs_code(raw) -> str | None:
        s = str(raw).strip()
        m = re.search(r'(\d{6})', s)
        if not m:
            return None
        num = m.group(1)
        if num.startswith(('6', '9')):
            return 'sh.' + num
        if num.startswith(('0', '2', '3')):
            return 'sz.' + num
        if num.startswith(('4', '8')):
            return 'bj.' + num
        return None

    @staticmethod
    def _normalize_board_type(board_type: str) -> str:
        return 'concept' if board_type == 'concept' else 'industry'

    def get_boards(self, board_type: str) -> pd.DataFrame:
        board_type = self._normalize_board_type(board_type)
        for fs in self.BOARD_FS[board_type]:
            params = {
                'pn': 1,
                'pz': 1000,
                'po': 1,
                'np': 1,
                'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
                'fltt': 2,
                'invt': 2,
                'fid': 'f3',
                'fs': fs,
                'fields': 'f12,f14',
            }
            data = self._request_json(self.BASE, params)
            rows = data.get('data', {}).get('diff', []) if data else []
            if not rows:
                continue
            out = []
            for row in rows:
                code = row.get('f12')
                name = row.get('f14')
                if code and name:
                    out.append({'type': board_type, 'code': str(code), 'name': str(name)})
            if out:
                return pd.DataFrame(out).drop_duplicates(['type', 'code', 'name'])
        return pd.DataFrame(columns=['type', 'code', 'name'])

    def _find_board_code(self, board_type: str, board_name: str | None, board_code: str | None) -> tuple[str | None, str | None]:
        if board_code:
            return board_code, board_name
        if not board_name:
            return None, None
        boards = self.get_boards(board_type)
        if boards.empty:
            return None, board_name
        matched = boards[boards['name'] == board_name]
        if matched.empty:
            matched = boards[boards['name'].astype(str).str.contains(str(board_name), regex=False, na=False)]
        if matched.empty:
            return None, board_name
        row = matched.iloc[0]
        return str(row['code']), str(row['name'])

    def get_members(self, board_type: str, board_name: str | None = None, board_code: str | None = None) -> pd.DataFrame:
        board_type = self._normalize_board_type(board_type)
        code, name = self._find_board_code(board_type, board_name, board_code)
        if not code:
            return pd.DataFrame(columns=['board_type', 'board_code', 'board_name', 'code', 'name'])
        params = {
            'pn': 1,
            'pz': 1000,
            'po': 1,
            'np': 1,
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': 2,
            'invt': 2,
            'fid': 'f3',
            'fs': f'b:{code}',
            'fields': 'f12,f14',
        }
        data = self._request_json(self.BASE, params)
        rows = data.get('data', {}).get('diff', []) if data else []
        out = []
        for row in rows:
            stock_code = self._bs_code(row.get('f12'))
            stock_name = row.get('f14')
            if stock_code:
                out.append({
                    'board_type': board_type,
                    'board_code': code,
                    'board_name': name or board_name or code,
                    'code': stock_code,
                    'name': str(stock_name) if stock_name is not None else '',
                })
        if not out:
            return pd.DataFrame(columns=['board_type', 'board_code', 'board_name', 'code', 'name'])
        return pd.DataFrame(out).drop_duplicates(['board_type', 'board_code', 'code'])

    def get_kline(self, board_type: str, board_name: str | None, board_code: str | None, start: str, end: str) -> pd.DataFrame:
        board_type = self._normalize_board_type(board_type)
        code, name = self._find_board_code(board_type, board_name, board_code)
        if not code:
            return pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pctChg'])
        secid = '90.' + code
        params = {
            'secid': secid,
            'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'klt': 101,
            'fqt': 0,
            'beg': start.replace('-', ''),
            'end': end.replace('-', ''),
        }
        data = self._request_json(self.KLINE, params)
        klines = data.get('data', {}).get('klines', []) if data else []
        out = []
        for item in klines:
            parts = str(item).split(',')
            if len(parts) < 7:
                continue
            out.append({
                'date': parts[0],
                'open': parts[1],
                'close': parts[2],
                'high': parts[3],
                'low': parts[4],
                'volume': parts[5],
                'amount': parts[6],
                'pctChg': parts[8] if len(parts) > 8 else 0,
            })
        if not out:
            return pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pctChg'])
        df = pd.DataFrame(out)
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        for col in ['open', 'high', 'low', 'close', 'volume', 'amount', 'pctChg']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        return df[['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pctChg']].dropna(subset=['date', 'close']).sort_values('date')

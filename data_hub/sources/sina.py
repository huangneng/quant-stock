"""Sina 实时/收盘快照数据源。

- 全市场快照 ~1.5s（5500 只 / 600 一批 / GBK）
- 字段：name,open,prev_close,close,high,low,_,_,volume,amount,...
"""
from __future__ import annotations
from typing import Optional
import pandas as pd
import requests

from data_hub.sources.base import SnapshotSource, DataSource

BATCH = 600
SINA_URL = 'https://hq.sinajs.cn/list='
HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.sina.com.cn/'}


def _to_sina(bs_code: str) -> str:
    return bs_code.replace('.', '')


def _to_bs(sina_code: str) -> Optional[str]:
    if sina_code.startswith(('sh', 'sz', 'bj')):
        return f'{sina_code[:2]}.{sina_code[2:]}'
    return None


class SinaSource(SnapshotSource, DataSource):
    name = 'sina'

    def __init__(self):
        self._sess = requests.Session()
        self._sess.headers.update(HEADERS)

    def get_market_snapshot(self, codes: list) -> dict:
        today_iso = pd.Timestamp.now().strftime('%Y-%m-%d')
        sina_codes = [_to_sina(c) for c in codes]
        out = {}
        for i in range(0, len(sina_codes), BATCH):
            batch = sina_codes[i:i + BATCH]
            url = SINA_URL + ','.join(batch)
            try:
                r = self._sess.get(url, timeout=15)
                r.encoding = 'gbk'
                text = r.text
            except Exception as e:
                print(f"  [sina] batch {i//BATCH+1} failed: {e}")
                continue
            for line in text.strip().split('\n'):
                if '="' not in line:
                    continue
                head, body = line.split('="', 1)
                body = body.rstrip('";').rstrip('"')
                f = body.split(',')
                if len(f) < 10:
                    continue
                bs_code = _to_bs(head.split('_')[-1].strip())
                if not bs_code:
                    continue
                try:
                    open_ = float(f[1])
                    prev_close = float(f[2])
                    close = float(f[3])
                    high = float(f[4])
                    low = float(f[5])
                    volume = float(f[8])
                    amount = float(f[9])
                except (ValueError, IndexError):
                    continue
                if close <= 0 or amount <= 0 or prev_close <= 0:
                    continue
                pct = (close - prev_close) / prev_close * 100.0
                out[bs_code] = {
                    'date': today_iso,
                    'code': bs_code,
                    'name': f[0],
                    'open': open_,
                    'high': high,
                    'low': low,
                    'close': close,
                    'volume': volume,
                    'amount': amount,
                    'turn': 0.0,
                    'pctChg': pct,
                }
        return out

    # 仅作为快照源；完整 K 线由其他源负责
    def get_kline(self, code: str, start: str, end: str):
        snap = self.get_market_snapshot([code])
        row = snap.get(code)
        if not row:
            return None
        return pd.DataFrame([{k: row[k] for k in
            ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'turn', 'pctChg']}])

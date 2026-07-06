"""Tencent 实时/收盘快照数据源。

- HTTP 接口稳定，适合作为 Sina 快照 fallback。
- 输出字段统一为 SnapshotSource 约定格式。
"""
from __future__ import annotations

from typing import Optional
import pandas as pd
import requests

from data_hub.sources.base import SnapshotSource

BATCH = 50
TENCENT_URL = 'https://qt.gtimg.cn/q='
HEADERS = {
    'User-Agent': 'Mozilla/5.0',
    'Referer': 'https://gu.qq.com/',
}


def _to_tencent(bs_code: str) -> str:
    return str(bs_code).replace('.', '')


def _to_bs(code6: str) -> Optional[str]:
    code6 = str(code6).strip()
    if len(code6) != 6 or not code6.isdigit():
        return None
    if code6.startswith(('6', '9')):
        return 'sh.' + code6
    if code6.startswith(('0', '2', '3')):
        return 'sz.' + code6
    if code6.startswith(('4', '8')):
        return 'bj.' + code6
    return None


def _to_float(fields: list[str], idx: int, default: float = 0.0) -> float:
    try:
        value = float(fields[idx])
    except (TypeError, ValueError, IndexError):
        return default
    return value if value == value else default


class TencentSource(SnapshotSource):
    name = 'tencent'

    def __init__(self):
        self._sess = requests.Session()
        self._sess.headers.update(HEADERS)

    def get_market_snapshot(self, codes: list) -> dict:
        if not codes:
            return {}
        today_iso = pd.Timestamp.now().strftime('%Y-%m-%d')
        out: dict = {}
        want = list(dict.fromkeys(codes))
        for i in range(0, len(want), BATCH):
            batch = want[i:i + BATCH]
            query = ','.join(_to_tencent(c) for c in batch)
            try:
                resp = self._sess.get(TENCENT_URL + query, timeout=8)
                resp.encoding = 'gbk'
                text = resp.text
            except Exception as e:
                print(f"  [tencent] batch {i//BATCH+1} failed: {e}")
                continue
            for line in text.strip().split(';'):
                line = line.strip()
                if not line or '="' not in line:
                    continue
                payload = line.split('="', 1)[1].rstrip('"')
                fields = payload.split('~')
                if len(fields) < 38:
                    continue
                bs_code = _to_bs(fields[2])
                if not bs_code:
                    continue
                name = fields[1] if len(fields) > 1 else ''
                close = _to_float(fields, 3)
                prev_close = _to_float(fields, 4)
                open_ = _to_float(fields, 5)
                pct = _to_float(fields, 31)
                high = _to_float(fields, 33)
                low = _to_float(fields, 34)
                volume = _to_float(fields, 36) * 100.0  # 手 -> 股
                amount = _to_float(fields, 37) * 1e4    # 万元 -> 元
                turn = _to_float(fields, 38)
                if close <= 0 or amount <= 0:
                    continue
                if pct == 0.0 and prev_close > 0:
                    pct = (close - prev_close) / prev_close * 100.0
                out[bs_code] = {
                    'date': today_iso,
                    'code': bs_code,
                    'name': name,
                    'open': open_,
                    'high': high,
                    'low': low,
                    'close': close,
                    'volume': volume,
                    'amount': amount,
                    'turn': turn,
                    'pctChg': pct,
                }
        return out

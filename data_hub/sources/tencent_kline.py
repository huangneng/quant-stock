"""腾讯历史日 K 线源（HTTP，前复权）。

走 HTTPS 443 端口，绕开当前网络封锁的通达信 7709 / baostock TCP 端口。
接口: https://web.ifzq.gtimg.cn/appstock/app/fqkline/get

返回字段 [date, open, close, high, low, volume(手)]，不含成交额；
amount 用当日均价 × 成交量近似（仅供量比类特征使用，预筛成交额仍取实时快照）。
"""
from __future__ import annotations

from typing import Optional
import json
import pandas as pd
import requests

from data_hub.sources.base import DataSource, UNIFIED_COLS

KLINE_URL = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
HEADERS = {
    'User-Agent': 'Mozilla/5.0',
    'Referer': 'https://gu.qq.com/',
}


def _to_tencent(bs_code: str) -> Optional[str]:
    code = str(bs_code)
    if code.startswith('sh.'):
        return 'sh' + code[3:]
    if code.startswith('sz.'):
        return 'sz' + code[3:]
    if code.startswith('bj.'):
        return 'bj' + code[3:]
    return None


class TencentKlineSource(DataSource):
    name = 'tencent_kline'

    def __init__(self):
        self._sess = requests.Session()
        self._sess.headers.update(HEADERS)

    def login(self) -> bool:
        return True

    def get_kline(self, code: str, start: str, end: str) -> Optional[pd.DataFrame]:
        tc = _to_tencent(code)
        if tc is None:
            return None
        # 依据自然日跨度估算取数条数（含冗余），封顶 1500 根
        try:
            span_days = (pd.to_datetime(end) - pd.to_datetime(start)).days
        except Exception:
            span_days = 400
        count = min(max(int(span_days * 0.75) + 30, 60), 1500)
        param = f'{tc},day,,,{count},qfq'
        try:
            resp = self._sess.get(KLINE_URL, params={'param': param}, timeout=10)
            data = json.loads(resp.text)
        except Exception:
            return None

        node = (data or {}).get('data', {}).get(tc, {})
        rows = node.get('qfqday') or node.get('day')
        if not rows:
            return None

        recs = []
        for r in rows:
            if len(r) < 6:
                continue
            try:
                d = str(r[0])
                o = float(r[1])
                c = float(r[2])
                h = float(r[3])
                low = float(r[4])
                vol_hand = float(r[5])
            except (ValueError, TypeError):
                continue
            volume = vol_hand * 100.0            # 手 -> 股
            avg = (o + h + low + c) / 4.0        # 均价近似
            amount = avg * volume                # 成交额近似（元）
            recs.append({
                'date': d, 'open': o, 'high': h, 'low': low,
                'close': c, 'volume': volume, 'amount': amount, 'turn': 0.0,
            })
        if not recs:
            return None

        df = pd.DataFrame(recs)
        df['pctChg'] = df['close'].pct_change() * 100.0
        df = df[(df['date'] >= start) & (df['date'] <= end)]
        if df.empty:
            return pd.DataFrame(columns=UNIFIED_COLS)
        return df[UNIFIED_COLS].dropna(subset=['date', 'close']).sort_values('date').reset_index(drop=True)

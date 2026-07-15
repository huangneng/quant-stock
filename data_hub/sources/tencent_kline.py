<file>
     1→"""腾讯历史日 K 线源（HTTP，前复权）。
     2→
     3→走 HTTPS 443 端口，绕开当前网络封锁的通达信 7709 / baostock TCP 端口。
     4→接口: https://web.ifzq.gtimg.cn/appstock/app/fqkline/get
     5→
     6→返回字段 [date, open, close, high, low, volume(手)]，不含成交额；
     7→amount 用当日均价 × 成交量近似（仅供量比类特征使用，预筛成交额仍取实时快照）。
     8→"""
     9→from __future__ import annotations
    10→
    11→from typing import Optional
    12→import json
    13→import pandas as pd
    14→import requests
    15→
    16→from data_hub.sources.base import DataSource, UNIFIED_COLS
    17→
    18→KLINE_URL = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
    19→HEADERS = {
    20→    'User-Agent': 'Mozilla/5.0',
    21→    'Referer': 'https://gu.qq.com/',
    22→}
    23→
    24→
    25→def _to_tencent(bs_code: str) -> Optional[str]:
    26→    code = str(bs_code)
    27→    if code.startswith('sh.'):
    28→        return 'sh' + code[3:]
    29→    if code.startswith('sz.'):
    30→        return 'sz' + code[3:]
    31→    if code.startswith('bj.'):
    32→        return 'bj' + code[3:]
    33→    return None
    34→
    35→
    36→class TencentKlineSource(DataSource):
    37→    name = 'tencent_kline'
    38→
    39→    def __init__(self):
    40→        self._sess = requests.Session()
    41→        self._sess.headers.update(HEADERS)
    42→
    43→    def login(self) -> bool:
    44→        return True
    45→
    46→    def get_kline(self, code: str, start: str, end: str) -> Optional[pd.DataFrame]:
    47→        tc = _to_tencent(code)
    48→        if tc is None:
    49→            return None
    50→        # 腾讯该接口对科创板(sh.688/689)返回的成交量单位是"股"，其余板块是"手"
        vol_multiplier = 1.0 if code.startswith(('sh.688', 'sh.689')) else 100.0
        # 依据自然日跨度估算取数条数（含冗余），封顶 1500 根
    51→        try:
    52→            span_days = (pd.to_datetime(end) - pd.to_datetime(start)).days
    53→        except Exception:
    54→            span_days = 400
    55→        count = min(max(int(span_days * 0.75) + 30, 60), 1500)
    56→        param = f'{tc},day,,,{count},qfq'
    57→        try:
    58→            resp = self._sess.get(KLINE_URL, params={'param': param}, timeout=10)
    59→            data = json.loads(resp.text)
    60→        except Exception:
    61→            return None
    62→
    63→        node = (data or {}).get('data', {}).get(tc, {})
    64→        rows = node.get('qfqday') or node.get('day')
    65→        if not rows:
    66→            return None
    67→
    68→        recs = []
    69→        for r in rows:
    70→            if len(r) < 6:
    71→                continue
    72→            try:
    73→                d = str(r[0])
    74→                o = float(r[1])
    75→                c = float(r[2])
    76→                h = float(r[3])
    77→                low = float(r[4])
    78→                vol_hand = float(r[5])
    79→            except (ValueError, TypeError):
    80→                continue
    81→            volume = vol_hand * vol_multiplier   # 手 -> 股（科创板已是股）
    82→            avg = (o + h + low + c) / 4.0        # 均价近似
    83→            amount = avg * volume                # 成交额近似（元）
    84→            recs.append({
    85→                'date': d, 'open': o, 'high': h, 'low': low,
    86→                'close': c, 'volume': volume, 'amount': amount, 'turn': 0.0,
    87→            })
    88→        if not recs:
    89→            return None
    90→
    91→        df = pd.DataFrame(recs)
    92→        df['pctChg'] = df['close'].pct_change() * 100.0
    93→        df = df[(df['date'] >= start) & (df['date'] <= end)]
    94→        if df.empty:
    95→            return pd.DataFrame(columns=UNIFIED_COLS)
    96→        return df[UNIFIED_COLS].dropna(subset=['date', 'close']).sort_values('date').reset_index(drop=True)
    97→
</file>
<metadata>The file has 97 lines in total.</metadata>
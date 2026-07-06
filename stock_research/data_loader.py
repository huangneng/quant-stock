"""历史 K 线拉取（已迁移到 data_hub，保留旧 API 以兼容下游脚本）。

缓存与数据源由 data_hub.api.get_kline 统一管理（KlineDB + Sina/Baostock/Akshare 路由）。
"""
from __future__ import annotations
import json
import time
from datetime import datetime
import pandas as pd

from .config import SELECTIONS_FILE, PRE_DAYS, POST_DAYS

# 以下两个变量保留为兼容老脚本，新代码不要再依赖
_BS_LOGGED_IN = True


def _login():
    return  # noop: data_hub 内部按需登录


FIELDS = 'date,open,high,low,close,volume,amount,turn,pctChg'


def fetch_ohlcv(code: str, start: str, end: str, require_today: bool = False) -> pd.DataFrame | None:
    """code 形如 sz.002361 / sh.603629，start/end 为 YYYY-MM-DD。返回 DataFrame 或 None。"""
    from data_hub import api as hub
    df = hub.get_kline(code, start, end, require_today=require_today)
    if df is None or df.empty:
        return None
    return df


def _yyyymmdd_to_iso(s: str) -> str:
    return f'{s[:4]}-{s[4:6]}-{s[6:8]}'


def _shift_date(iso: str, days: int) -> str:
    return (datetime.strptime(iso, '%Y-%m-%d') + pd.Timedelta(days=days)).strftime('%Y-%m-%d')


def load_selections() -> list[dict]:
    """从 selections.json 平铺为样本列表。"""
    with open(SELECTIONS_FILE, encoding='utf-8') as f:
        data = json.load(f)
    samples = []
    for date_key, record in data.items():
        for s in record.get('stocks', []):
            samples.append({
                'entry_date_key': date_key,
                'entry_date': _yyyymmdd_to_iso(date_key),
                'code': s['code'],
                'name': s['name'],
                'buy_price': s['buy_price'],
                'price': s.get('price'),
                'signal_type': s.get('signal_type'),
                'is_limit_up': s.get('is_limit_up', False),
                'amount': s.get('amount'),
            })
    return samples


def fetch_for_sample(sample: dict, refresh: bool = False) -> pd.DataFrame | None:
    """对单个入选样本拉取 entry-PRE_DAYS ~ entry+POST_DAYS+缓冲 区间日线。"""
    entry = sample['entry_date']
    start = _shift_date(entry, -int(PRE_DAYS * 1.6) - 5)
    end = _shift_date(entry, int(POST_DAYS * 1.6) + 5)
    today = datetime.now().strftime('%Y-%m-%d')
    if end > today:
        end = today
    return fetch_ohlcv(sample['code'], start, end)


def load_all(refresh: bool = False, throttle: float = 0.0) -> list[dict]:
    """批量加载所有入选样本，附加 'hist' 字段（DataFrame 或 None）。"""
    samples = load_selections()
    print(f'[data_loader] {len(samples)} samples to load (via data_hub)')
    out = []
    for i, s in enumerate(samples):
        df = fetch_for_sample(s, refresh=refresh)
        s = {**s, 'hist': df}
        out.append(s)
        if (i + 1) % 50 == 0:
            print(f'[data_loader] loaded {i + 1}/{len(samples)}')
        if throttle:
            time.sleep(throttle)
    miss = sum(1 for s in out if s['hist'] is None)
    print(f'[data_loader] done. miss={miss}/{len(out)}')
    return out


def fetch_hs300(start: str = '2025-01-01', end: str | None = None) -> pd.DataFrame | None:
    """拉取沪深 300 指数日线。"""
    if end is None:
        end = datetime.now().strftime('%Y-%m-%d')
    return fetch_ohlcv('sh.000300', start, end)


if __name__ == '__main__':
    s = load_all()
    print(f'first sample: code={s[0]["code"]} hist_len={len(s[0]["hist"]) if s[0]["hist"] is not None else 0}')

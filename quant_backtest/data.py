# -*- coding: utf-8 -*-
"""数据获取模块 - 已迁移到 data_hub，本文件保留兼容旧接口。

新代码请使用 data_hub.api。
"""
import pandas as pd
from datetime import datetime


def _norm_code(stock_code: str) -> str:
    if '.' in stock_code:
        return stock_code
    if stock_code.startswith('6'):
        return f"sh.{stock_code}"
    return f"sz.{stock_code}"


def _to_iso(d: str) -> str:
    if '-' in d:
        return d
    return f'{d[:4]}-{d[4:6]}-{d[6:8]}'


def get_stock_data(stock_code: str, start_date: str, end_date: str, source: str = "auto") -> pd.DataFrame:
    """获取单只股票历史行情。返回 DataFrame，date 为 index，列含 pct_change。"""
    from data_hub import api as hub
    code = _norm_code(stock_code)
    df = hub.get_kline(code, _to_iso(start_date), _to_iso(end_date), require_today=False)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename(columns={'pctChg': 'pct_change'}).copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    return df


def get_stock_list() -> list:
    """返回 [(code, name), ...]。"""
    from data_hub import api as hub
    df = hub.get_universe()
    if df is None or df.empty:
        return []
    # 只保留沪深 A 股
    df = df[df['code'].str.startswith(('sh.6', 'sz.0', 'sz.3'))]
    print(f"获取到 {len(df)} 只A股股票")
    return list(zip(df['code'].tolist(), df['name'].tolist()))


if __name__ == "__main__":
    print("测试 data_hub 数据获取...")
    df = get_stock_data("600519", "20260401", "20260511")
    if not df.empty:
        print(f"成功获取 {len(df)} 条数据")

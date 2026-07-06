# -*- coding: utf-8 -*-
"""
批量扫描增量版 - 本地缓存 + 增量拉取 + 进度显示
"""
import os
import sys
import json
import time
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import baostock as bs
from quant_backtest.data import get_stock_list
from quant_backtest.data_provider import DataProvider
from quant_backtest.strategy import MomentumBreakthroughStrategy

CACHE_DIR = "stock_data/cache"
os.makedirs(CACHE_DIR, exist_ok=True)


def _load_cache(code):
    """加载缓存，返回 DataFrame 或 None"""
    path = os.path.join(CACHE_DIR, f"{code.replace('.', '_')}.pkl")
    if os.path.exists(path):
        try:
            df = pd.read_pickle(path)
            df['date'] = pd.to_datetime(df['date'])
            return df
        except Exception:
            return None
    return None


def _save_cache(code, df):
    """保存缓存到 pickle"""
    path = os.path.join(CACHE_DIR, f"{code.replace('.', '_')}.pkl")
    df.to_pickle(path)


def fetch_stock_data(code, start_date, end_date, provider: DataProvider):
    """
    获取单只股票 K 线，优先读缓存，增量补充新数据
    返回 DataFrame(date, open, high, low, close, volume, amount, pctChg)
    """
    end_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
    end_dt = pd.to_datetime(end_fmt)

    cached = _load_cache(code)
    if cached is not None and not cached.empty:
        last_date = cached['date'].max()
        if last_date >= end_dt:
            df = cached[cached['date'] <= end_dt].copy()
            return df.reset_index(drop=True)
        # 增量补充
        inc_start = (last_date + timedelta(days=1)).strftime('%Y%m%d')
        inc_df = provider.get_kline(code, inc_start, end_date)
        if inc_df is not None and not inc_df.empty:
            merged = pd.concat([cached, inc_df], ignore_index=True)
            merged = merged.drop_duplicates(subset=['date']).sort_values('date').reset_index(drop=True)
            _save_cache(code, merged)
            df = merged[merged['date'] <= end_dt].copy()
            return df.reset_index(drop=True)
        else:
            df = cached[cached['date'] <= end_dt].copy()
            return df.reset_index(drop=True)

    # 无缓存，全量请求
    df = provider.get_kline(code, start_date, end_date)
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.sort_values('date').reset_index(drop=True)
    # 仅当有合理量数据时才写缓存（避免把请求失败的空结果当成"无数据"缓存）
    if len(df) >= 30:
        _save_cache(code, df)
    return df


def batch_scan(start_date, end_date, target_dates, min_amount=1e9, max_stocks=None,
               reuse_existing=True):
    """
    一次登录，批量扫描所有股票在多个目标日期的信号

    Args:
        start_date: 数据起始日期 '20260101'
        end_date: 数据结束日期 '20260522'
        target_dates: 需要判断信号的目标日期列表 ['20260415', ...]
        min_amount: 当日最低成交额（元），默认50亿
        max_stocks: 最多扫描股票数（None=全部）
        reuse_existing: 是否复用 selections.json 中已有的日期结果

    Returns:
        {target_date: [stock_dicts]}
    """
    stock_list = get_stock_list()
    if max_stocks:
        stock_list = stock_list[:max_stocks]

    print(f"准备扫描 {len(stock_list)} 只股票")
    print(f"数据区间: {start_date} ~ {end_date}")
    print(f"目标信号日期: {target_dates}")

    target_dts = set(pd.to_datetime(d) for d in target_dates)

    # 尝试复用已有结果
    existing = {}
    selections_file = "stock_data/selections.json"
    if reuse_existing and os.path.exists(selections_file):
        try:
            with open(selections_file, 'r', encoding='utf-8') as f:
                existing = json.load(f)
            reused = [d for d in target_dates if d in existing]
            if reused:
                print(f"复用已有结果: {len(reused)} 个日期 ({', '.join(reused[:5])}{'...' if len(reused) > 5 else ''})")
        except Exception:
            existing = {}

    results = {d: existing.get(d, {}).get('stocks', [])[:] for d in target_dates}
    missing_dates = [d for d in target_dates if d not in existing or not existing[d].get('stocks')]

    if not missing_dates:
        print("所有目标日期结果均已存在，无需扫描")
        return results

    print(f"需要计算的新日期: {missing_dates}")

    # 创建 DataProvider（baostock 主源 + akshare 备源）
    provider = DataProvider()
    provider.login()

    strategy = MomentumBreakthroughStrategy(min_amount=min_amount)

    scanned = 0
    matched_count = 0
    total = len(stock_list)
    t0 = time.time()

    for i, (code, name) in enumerate(stock_list):
        # 过滤指数
        if code.startswith('sh.000') or code.startswith('sz.399'):
            continue

        # 进度显示（每 100 只或最后一只）
        if (i + 1) % 100 == 0 or i == total - 1:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            remain = (total - i - 1) / rate if rate > 0 else 0
            print(f"  [{i+1}/{total}] 已扫描 {scanned} 只, 命中 {matched_count} 次 | "
                  f"耗时 {elapsed:.0f}s | 预计剩余 {remain/60:.1f}min | 数据源: {provider.current_source_name}")

        try:
            df = fetch_stock_data(code, start_date, end_date, provider)
            if len(df) < 30:
                continue

            # 前置快速过滤
            if df['amount'].max() < min_amount:
                continue

            scanned += 1

            df = df.set_index('date').sort_index()
            df = df.rename(columns={'pctChg': 'pct_change'})

            signals = strategy.generate_signals(df)

            for td_str in missing_dates:
                td = pd.to_datetime(td_str)
                if td not in signals.index:
                    continue
                row = signals.loc[td]
                if int(row['signal_final']) > 0:
                    buy_price = float(row['buy_price']) if pd.notna(row.get('buy_price')) else float(row['close'])
                    pct_chg = float(row.get('pct_change', 0))
                    signal_type = str(row.get('signal_type') or 'breakthrough')
                    is_limit_up = signal_type == 'one_word'
                    amount_val = float(row['amount']) if pd.notna(row.get('amount')) else 0.0
                    results[td_str].append({
                        'code': code,
                        'name': name,
                        'price': float(row['close']),
                        'buy_price': buy_price,
                        'signal_type': signal_type,
                        'is_limit_up': is_limit_up,
                        'pct_change': pct_chg,
                        'amount': amount_val,
                        'conditions': {
                            'prev_limit_up': bool(row.get('prev_limit_up', False)),
                            'today_high_gain': bool(row.get('today_high_gain', False)),
                            'gap_up_with_gain': bool(row.get('gap_up_with_gain', False)),
                            'new_100d_high': bool(row.get('new_100d_high', False)),
                            'new_all_time_high': bool(row.get('new_all_time_high', False))
                        }
                    })
                    matched_count += 1
                    tag_map = {'one_word': '一字涨停', 'gap': '跳空突破', 'breakthrough': '突破'}
                    tag = tag_map.get(signal_type, signal_type)
                    print(f"  ✓ {td_str} {name} ({code}) 买入¥{buy_price:.2f} 收盘¥{row['close']:.2f} {pct_chg:+.2f}% [{tag}]")
        except Exception as e:
            continue

    provider.logout()

    print(f"\n扫描完成：共扫描 {scanned} 只成交额>={min_amount/1e8:.0f}亿股票，命中 {matched_count} 次 | 最终数据源: {provider.current_source_name}")
    return results


def save_results(results):
    """保存到 selections.json"""
    data_dir = "stock_data"
    os.makedirs(data_dir, exist_ok=True)
    selections_file = os.path.join(data_dir, "selections.json")

    # 合并已有数据（如果存在）
    if os.path.exists(selections_file):
        try:
            with open(selections_file, 'r', encoding='utf-8') as f:
                old = json.load(f)
        except Exception:
            old = {}
    else:
        old = {}

    for date, stocks in results.items():
        old[date] = {
            'scan_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'stocks': stocks
        }

    with open(selections_file, 'w', encoding='utf-8') as f:
        json.dump(old, f, ensure_ascii=False, indent=2)

    print(f"\n已保存到 {selections_file}")


if __name__ == "__main__":
    import os
    from datetime import datetime as _dt, timedelta as _td

    # 支持环境变量 SCAN_END_DATE 指定截止日期（YYYYMMDD），默认今日
    env_end = os.environ.get('SCAN_END_DATE')
    if env_end:
        end_date = env_end
    else:
        end_date = _dt.now().strftime('%Y%m%d')

    # 起始日期：截止日期向前回溯约 240 天（含 100 日新高判定 + 缓冲）
    end_dt = _dt.strptime(end_date, '%Y%m%d')
    start_date = (end_dt - _td(days=240)).strftime('%Y%m%d')

    # 仅扫描"截止日期当天"，历史回扫请显式传 target_dates
    env_targets = os.environ.get('SCAN_TARGET_DATES')
    if env_targets:
        target_dates = [d.strip() for d in env_targets.split(',') if d.strip()]
    else:
        target_dates = [end_date]

    print(f"扫描配置: start={start_date}, end={end_date}, targets={target_dates}")

    results = batch_scan(
        start_date=start_date,
        end_date=end_date,
        target_dates=target_dates,
        min_amount=1e9
    )

    save_results(results)

    # 打印汇总
    print("\n" + "=" * 60)
    print("选股汇总")
    print("=" * 60)
    for date in target_dates:
        stocks = results.get(date, [])
        print(f"{date}: {len(stocks)} 只")
        for s in stocks:
            print(f"    {s['name']} ({s['code']}) ¥{s['price']:.2f} {s['pct_change']:+.2f}%")

# -*- coding: utf-8 -*-
"""历史信号样本回填

对最近 N 个交易日，复用 daily_select 的预筛 + 信号判定流程，
对每个命中样本提取特征 + 后 30 个交易日收益，落盘 signal_samples.parquet
供 weight_tuner.py 学习权重 + 校准阈值。

Usage:
    python3 stock_research/signal_backfill.py --days 60
    python3 stock_research/signal_backfill.py --days 180 --end 2026-06-04

输出：
    stock_research/output/signal_samples.parquet
    stock_research/output/signal_samples_shards/{date}.parquet（每日分片，断点续跑）
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from daily_select import prefilter_by_amount, detect_today_signal
from quant_backtest.data import get_stock_list
from stock_research.data_loader import fetch_ohlcv
from stock_research.feature_extractor import extract_features

OUTPUT_DIR = ROOT / 'stock_research' / 'output'
SHARD_DIR = OUTPUT_DIR / 'signal_samples_shards'
TRADE_CAL = ROOT / 'stock_data' / 'trade_calendar.json'

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SHARD_DIR.mkdir(parents=True, exist_ok=True)


def _load_trade_dates() -> list[str]:
    """读取 stock_data/trade_calendar.json，返回升序的交易日列表。

    兼容三种格式：
    1. {"cached_at": "...", "dates": ["YYYY-MM-DD", ...]}  ← 当前实际格式
    2. ["YYYY-MM-DD", ...]
    3. {"YYYY-MM-DD": ..., ...}
    """
    import json
    if not TRADE_CAL.exists():
        raise SystemExit(f"[backfill] 交易日历缺失：{TRADE_CAL}，先跑 scripts/check_trade_date.py")
    data = json.loads(TRADE_CAL.read_text(encoding='utf-8'))
    if isinstance(data, dict):
        if 'dates' in data and isinstance(data['dates'], list):
            dates = data['dates']
        else:
            dates = list(data.keys())
    elif isinstance(data, list):
        dates = list(data)
    else:
        raise SystemExit(f"[backfill] 交易日历格式异常：{type(data)}")
    return sorted(d for d in dates if isinstance(d, str) and len(d) == 10)


def _backfill_one_day(stock_list, today: str, min_amount: float, full_date_list: list[str]) -> pd.DataFrame:
    """回填某一交易日的命中样本 + 后 30 日收益，返回 DataFrame。"""
    rows = []

    # 1. 预筛
    candidates = prefilter_by_amount(stock_list, today, min_amount=min_amount)
    if not candidates:
        return pd.DataFrame()

    # 2. 计算后 30 日的目标日（用 today 的索引 + 30）
    if today not in full_date_list:
        # today 不是交易日，跳过
        return pd.DataFrame()
    idx = full_date_list.index(today)
    fwd_target_idx = idx + 30
    has_fwd = fwd_target_idx < len(full_date_list)
    fwd_end = full_date_list[fwd_target_idx] if has_fwd else full_date_list[-1]

    # 3. 信号判定 + 特征提取（拉到 fwd_end，覆盖 ret_30 计算）
    start_date = (datetime.strptime(today, '%Y-%m-%d') - pd.Timedelta(days=220)).strftime('%Y-%m-%d')
    end_date = fwd_end

    skip = {'no_data': 0, 'no_sig': 0, 'no_feat': 0}
    for i, (code, name) in enumerate(candidates):
        try:
            hist = fetch_ohlcv(code, start_date, end_date)
        except Exception:
            skip['no_data'] += 1
            continue
        if hist is None or hist.empty:
            skip['no_data'] += 1
            continue

        sig = detect_today_signal(code, hist, today)
        if sig is None:
            skip['no_sig'] += 1
            continue

        # ret_30：当日 close → 30 个交易日后 close
        today_rows = hist[hist['date'] == today]
        if today_rows.empty:
            skip['no_data'] += 1
            continue
        close_t = float(today_rows.iloc[0]['close'])

        ret_30 = float('nan')
        if has_fwd:
            after = hist[hist['date'] > today].sort_values('date')
            if len(after) >= 30:
                close_fwd = float(after.iloc[29]['close'])
                if close_t > 0:
                    ret_30 = close_fwd / close_t - 1.0

        sample = {
            'code': code,
            'name': name,
            'entry_date': today,
            'signal_type': sig['signal_type'],
            'is_limit_up': bool(sig.get('is_limit_up', False)),
            'hist': hist[hist['date'] <= today],  # 特征提取只用 today 之前+当日
        }
        feats = extract_features(sample)
        if feats is None:
            skip['no_feat'] += 1
            continue

        row = {
            'code': code,
            'name': name,
            'entry_date': today,
            'signal_type': sig['signal_type'],
            'is_limit_up': bool(sig.get('is_limit_up', False)),
            'price': float(sig['price']),
            'pct': float(sig['pct']),
            'amount': float(sig['amount']),
            'ret_30': ret_30,
        }
        # 把 feature_extractor 返回的全部数值字段铺平
        for k, v in feats.items():
            if k in row or k == 'hist':
                continue
            try:
                row[k] = float(v) if v is not None else float('nan')
            except (TypeError, ValueError):
                row[k] = v
        rows.append(row)

    print(f"  [{today}] candidates={len(candidates)} signals={len(rows)} "
          f"skip(no_data={skip['no_data']}/no_sig={skip['no_sig']}/no_feat={skip['no_feat']})")
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description='历史信号样本回填')
    parser.add_argument('--days', type=int, default=60, help='回填交易日数（默认 60）')
    parser.add_argument('--end', default=None, help='结束交易日 YYYY-MM-DD（默认今日）')
    parser.add_argument('--min-amount', type=float, default=3e9, help='预筛成交额下限')
    parser.add_argument('--force', action='store_true', help='忽略已存在分片，强制重跑')
    args = parser.parse_args()

    end_iso = args.end or datetime.now().strftime('%Y-%m-%d')
    full_dates = _load_trade_dates()
    if end_iso not in full_dates:
        # 取小于等于 end_iso 的最大交易日
        candidates = [d for d in full_dates if d <= end_iso]
        if not candidates:
            raise SystemExit(f"[backfill] 交易日历中没有 ≤ {end_iso} 的日期")
        end_iso = candidates[-1]
        print(f"[backfill] {args.end} 非交易日，使用最近交易日 {end_iso}")

    end_idx = full_dates.index(end_iso)
    start_idx = max(0, end_idx - args.days + 1)
    target_dates = full_dates[start_idx:end_idx + 1]
    print(f"[backfill] 窗口 {target_dates[0]} → {target_dates[-1]}（{len(target_dates)} 个交易日）")

    print(f"[backfill] 加载全市场股票...")
    stock_list = get_stock_list()
    # 仅保留 A 股个股（与 daily_select 一致的规则）
    from daily_select import _is_real_stock
    stock_list = [(c, n) for c, n in stock_list if _is_real_stock(c)]
    print(f"[backfill] 全市场（仅个股）{len(stock_list)} 只")

    for i, today in enumerate(target_dates, 1):
        shard_path = SHARD_DIR / f'{today}.parquet'
        if shard_path.exists() and not args.force:
            try:
                exist_df = pd.read_parquet(shard_path)
                print(f"[{i}/{len(target_dates)}] {today} 命中分片：{len(exist_df)} 行（跳过）")
                continue
            except Exception:
                pass

        print(f"[{i}/{len(target_dates)}] {today} 回填中...")
        df = _backfill_one_day(stock_list, today, args.min_amount, full_dates)
        if df.empty:
            # 写一个空分片，避免下次重跑（用一个特殊 marker 列）
            pd.DataFrame({'__empty__': [True]}).to_parquet(shard_path)
        else:
            df.to_parquet(shard_path, index=False)
            print(f"  → 落盘 {shard_path.name} ({len(df)} 行)")

    # 合并分片
    print(f"\n[backfill] 合并分片...")
    parts = []
    for shard in sorted(SHARD_DIR.glob('*.parquet')):
        try:
            df = pd.read_parquet(shard)
            if '__empty__' in df.columns:
                continue
            parts.append(df)
        except Exception as e:
            print(f"  跳过损坏分片 {shard.name}: {e}")

    if not parts:
        print("[backfill] 无样本，退出")
        return

    merged = pd.concat(parts, ignore_index=True)
    merged = merged.sort_values(['entry_date', 'code']).reset_index(drop=True)
    out_path = OUTPUT_DIR / 'signal_samples.parquet'
    merged.to_parquet(out_path, index=False)

    n_total = len(merged)
    n_with_ret = int(merged['ret_30'].notna().sum())
    print(f"\n[backfill] 总样本 {n_total}，可用于训练（有 ret_30）{n_with_ret}")
    print(f"[backfill] 信号类型分布：")
    print(merged['signal_type'].value_counts())
    if n_with_ret > 0:
        print(f"[backfill] ret_30 mean={merged['ret_30'].mean():.4f} median={merged['ret_30'].median():.4f}")
    print(f"[backfill] → {out_path}")


if __name__ == '__main__':
    main()

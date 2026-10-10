"""一键串联 load → label → feature → analyze → report"""
from __future__ import annotations
import argparse
import shutil
import time

import pandas as pd

from .config import CACHE_DIR, OUTPUT_DIR
from .data_loader import load_all
from .label_generator import label_all
from .feature_extractor import extract_all
from .analyzer import (analyze, merge_label_feature, feature_ranking, fit_tree,
                       time_split_validation, analyze_post3_signals)
from .report_builder import build_report
from . import strategy_validator
from . import recommender_backtest
from . import multi_backtest


def run(refresh: bool = False):
    if refresh and CACHE_DIR.exists():
        print('[pipeline] clear cache')
        shutil.rmtree(CACHE_DIR)
        CACHE_DIR.mkdir(exist_ok=True)

    t0 = time.time()
    print('==== [1/5] load ====')
    samples = load_all(refresh=refresh)
    t1 = time.time()
    print(f'  -> {t1 - t0:.1f}s')

    print('==== [2/5] label ====')
    labels = label_all(samples)
    t2 = time.time()
    print(f'  -> {t2 - t1:.1f}s')

    print('==== [3/5] feature ====')
    features = extract_all(samples)
    t3 = time.time()
    print(f'  -> {t3 - t2:.1f}s')

    print('==== [4/5] analyze ====')
    merged = merge_label_feature(labels, features)
    if merged.empty:
        print('[pipeline] empty merged set, abort')
        return
    merged.to_parquet(OUTPUT_DIR / 'merged.parquet')
    ranking = feature_ranking(merged)
    _, rules = fit_tree(merged)
    split = time_split_validation(merged)
    analyze_post3_signals(merged)
    # 上影线过滤回测
    try:
        strategy_validator.run()
    except Exception as e:
        print(f'[pipeline] validator failed: {e}')
    # 推荐指数事后回测（按星级复核单调性）
    try:
        recommender_backtest.run()
    except Exception as e:
        print(f'[pipeline] rec_backtest failed: {e}')
    # 多维度回测（持有期/板块/切片/交叉/风险/cohort/findings）
    try:
        multi_backtest.run(samples=samples)
    except Exception as e:
        print(f'[pipeline] multi_backtest failed: {e}')
    t4 = time.time()
    print(f'  -> {t4 - t3:.1f}s')

    print('==== [5/5] report ====')
    build_report(merged, ranking, rules, split)
    t5 = time.time()
    print(f'  -> {t5 - t4:.1f}s')

    print(f'==== done in {t5 - t0:.1f}s ====')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--refresh', action='store_true', help='clear baostock cache')
    args = p.parse_args()
    run(refresh=args.refresh)


if __name__ == '__main__':
    main()

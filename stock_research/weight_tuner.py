# -*- coding: utf-8 -*-
"""权重优化 + 阈值校准

加载 signal_samples.parquet，时序前向划分（前 75% train / 后 25% test），
COBYLA 优化 7 维权重以最大化训练集 Spearman IC，然后用训练集分位数校准 1~5★ 阈值。

Usage:
    python3 stock_research/weight_tuner.py

输出（output/）：
    recommender_weights.json      {7 dims, sum=1}
    recommender_calibration.json  {star_thresholds: [t1..t4]}
    recommender_validation.json   {ic_train, ic_test, per_star_stats, monotonic}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stock_research.recommender import score as score_one, DEFAULT_WEIGHTS, DEFAULT_THRESHOLDS

OUTPUT_DIR = ROOT / 'stock_research' / 'output'
SAMPLES = OUTPUT_DIR / 'signal_samples.parquet'

DIM_KEYS = list(DEFAULT_WEIGHTS.keys())  # 7 维顺序
TRAIN_RATIO = 0.75
MIN_TRAIN = 200


def _compute_dims(df: pd.DataFrame) -> pd.DataFrame:
    """对每条样本调用 score()，提取 7 维 dims。返回 DataFrame[DIM_KEYS]。"""
    rows = []
    for _, r in df.iterrows():
        s = score_one(r.to_dict())
        rows.append(s['dims'])
    return pd.DataFrame(rows, columns=DIM_KEYS)


def _score_with_weights(dims_arr: np.ndarray, w: np.ndarray) -> np.ndarray:
    """dims_arr shape (n, 7), w shape (7,), 返回 score shape (n,)。"""
    return dims_arr @ w


def _neg_ic(w: np.ndarray, dims_arr: np.ndarray, ret: np.ndarray) -> float:
    s = w.sum()
    if s <= 0:
        return 1.0
    w_norm = w / s
    scores = _score_with_weights(dims_arr, w_norm)
    if np.isnan(scores).any():
        # 用 0.5 兜底
        scores = np.where(np.isnan(scores), 0.5, scores)
    rho, _ = spearmanr(scores, ret)
    if np.isnan(rho):
        return 1.0
    return -float(rho)


def _per_star_stats(scores: np.ndarray, ret: np.ndarray, thresholds: list[float]) -> dict:
    """按阈值切到 1~5 星，返回每星的统计。"""
    t1, t2, t3, t4 = thresholds
    stars = np.where(scores >= t4, 5,
            np.where(scores >= t3, 4,
            np.where(scores >= t2, 3,
            np.where(scores >= t1, 2, 1))))
    out = {}
    for star in [1, 2, 3, 4, 5]:
        mask = stars == star
        n = int(mask.sum())
        if n == 0:
            out[str(star)] = {'n': 0, 'ret_mean': None, 'ret_median': None}
        else:
            sub = ret[mask]
            sub = sub[~np.isnan(sub)]
            if len(sub) == 0:
                out[str(star)] = {'n': n, 'ret_mean': None, 'ret_median': None}
            else:
                out[str(star)] = {
                    'n': n,
                    'ret_mean': float(np.mean(sub)),
                    'ret_median': float(np.median(sub)),
                }
    return out


MANUAL_WEIGHTS = {
    'upper_short':    0.28,
    'body_long':      0.25,
    'volume_amp':     0.15,
    'new_high':       0.02,
    'ma_dev_health':  0.10,
    'pre3_setup':     0.10,
    'pre3_vol_slope': 0.07,
}

FEATURES_FILE = OUTPUT_DIR / 'features.parquet'
MANUAL_QUANTILES = [0.20, 0.40, 0.65, 0.85]


def manual_calibrate(weights: dict | None = None) -> None:
    """基于分析结论手工重校权重，并用 features.parquet 全量数据重标定分位数阈值。

    不依赖 ret_30，适用于样本量不足以跑 COBYLA 的场景。
    """
    if weights is None:
        weights = MANUAL_WEIGHTS

    # 归一化
    s = sum(weights.values())
    if s <= 0:
        raise ValueError("weights sum <= 0")
    w_norm = {k: v / s for k, v in weights.items()}

    if not FEATURES_FILE.exists():
        raise SystemExit(f"[tune] features.parquet 缺失：{FEATURES_FILE}，先跑 pipeline")

    feats = pd.read_parquet(FEATURES_FILE)
    n = len(feats)
    if n == 0:
        raise SystemExit("[tune] features.parquet 为空，无法标定阈值")
    print(f"[tune/manual] 加载 features.parquet：{n} 条")

    # 用新权重计算全量 score（复用 recommender.score 的 dims 计算逻辑）
    from stock_research.recommender import score as score_one
    scores = []
    for _, row in feats.iterrows():
        result = score_one(row.to_dict())
        # 用 w_norm 重新加权（绕过模块级 WEIGHTS）
        base = sum(result['dims'].get(k, 0.5) * w_norm.get(k, 0) for k in w_norm)
        bonus = result['dims'].get('signal_bonus', 0.0)
        total = max(0.0, min(1.0, base + bonus))
        scores.append(total)
    scores_arr = np.array(scores)

    print(f"[tune/manual] score 分布：min={np.nanmin(scores_arr):.3f}  "
          f"mean={np.nanmean(scores_arr):.3f}  max={np.nanmax(scores_arr):.3f}")

    # 分位数阈值
    thresholds = [float(np.nanquantile(scores_arr, q)) for q in MANUAL_QUANTILES]
    # 单调性修复
    for i in range(3):
        if thresholds[i] > thresholds[i + 1]:
            thresholds[i + 1] = thresholds[i]
    print(f"[tune/manual] 新阈值（分位数 {MANUAL_QUANTILES}）：{[f'{t:.4f}' for t in thresholds]}")

    # 各星级分布
    t1, t2, t3, t4 = thresholds
    stars = np.where(scores_arr >= t4, 5,
            np.where(scores_arr >= t3, 4,
            np.where(scores_arr >= t2, 3,
            np.where(scores_arr >= t1, 2, 1))))
    print("[tune/manual] 各星级样本分布：")
    for st in [1, 2, 3, 4, 5]:
        cnt = int((stars == st).sum())
        pct = cnt / n * 100
        print(f"  {'★' * st:<7s}  n={cnt:4d}  ({pct:.1f}%)")

    # 落盘
    (OUTPUT_DIR / 'recommender_weights.json').write_text(
        json.dumps(w_norm, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    (OUTPUT_DIR / 'recommender_calibration.json').write_text(
        json.dumps({
            'star_thresholds': thresholds,
            'quantiles': MANUAL_QUANTILES,
            'train_score_stats': {
                'min': float(np.nanmin(scores_arr)),
                'max': float(np.nanmax(scores_arr)),
                'mean': float(np.nanmean(scores_arr)),
            },
            'source': 'manual_calibrate',
        }, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(f"[tune/manual] → {OUTPUT_DIR / 'recommender_weights.json'}")
    print(f"[tune/manual] → {OUTPUT_DIR / 'recommender_calibration.json'}")


def main():
    if not SAMPLES.exists():
        raise SystemExit(f"[tune] 样本缺失：{SAMPLES}，先跑 signal_backfill.py")

    df = pd.read_parquet(SAMPLES)
    n_all = len(df)
    df = df[df['ret_30'].notna()].copy()
    df = df.sort_values('entry_date').reset_index(drop=True)
    n_usable = len(df)
    print(f"[tune] 总样本 {n_all}，有 ret_30 可用于训练 {n_usable}")

    if n_usable < MIN_TRAIN:
        print(f"[tune] 样本量 {n_usable} < {MIN_TRAIN}，跳过 COBYLA，改用手工重校权重")
        manual_calibrate()
        # 写一份 validation.json 记录情况
        validation = {
            'status': 'manual_calibrate',
            'n_samples': n_usable,
            'min_required': MIN_TRAIN,
        }
        (OUTPUT_DIR / 'recommender_validation.json').write_text(
            json.dumps(validation, ensure_ascii=False, indent=2), encoding='utf-8'
        )
        return

    # 时序划分
    n_train = int(n_usable * TRAIN_RATIO)
    train = df.iloc[:n_train].copy()
    test = df.iloc[n_train:].copy()
    print(f"[tune] 时序划分：train={len(train)} ({train['entry_date'].iloc[0]} → {train['entry_date'].iloc[-1]}), "
          f"test={len(test)} ({test['entry_date'].iloc[0]} → {test['entry_date'].iloc[-1]})")

    # 提取 dims
    print(f"[tune] 提取 dims...")
    train_dims = _compute_dims(train).values
    test_dims = _compute_dims(test).values
    train_ret = train['ret_30'].values
    test_ret = test['ret_30'].values

    # 默认权重 IC
    w_default = np.array([DEFAULT_WEIGHTS[k] for k in DIM_KEYS])
    ic_default_train = -_neg_ic(w_default, train_dims, train_ret)
    ic_default_test = -_neg_ic(w_default, test_dims, test_ret)
    print(f"[tune] 默认权重 IC: train={ic_default_train:+.4f}, test={ic_default_test:+.4f}")

    # COBYLA 优化（约束：sum=1, w_i ≥ 0）
    print(f"[tune] COBYLA 优化中...")
    constraints = [
        {'type': 'eq', 'fun': lambda w: w.sum() - 1.0},
        *[{'type': 'ineq', 'fun': (lambda w, i=i: w[i])} for i in range(len(DIM_KEYS))],
    ]
    res = minimize(
        _neg_ic, w_default,
        args=(train_dims, train_ret),
        method='COBYLA',
        constraints=constraints,
        options={'rhobeg': 0.05, 'maxiter': 500, 'disp': False},
    )
    w_learned = np.maximum(res.x, 0)
    if w_learned.sum() <= 0:
        print(f"[tune] 优化失败（全零），保留默认权重")
        w_learned = w_default
    w_learned = w_learned / w_learned.sum()

    ic_learned_train = -_neg_ic(w_learned, train_dims, train_ret)
    ic_learned_test = -_neg_ic(w_learned, test_dims, test_ret)
    print(f"[tune] 优化后 IC:  train={ic_learned_train:+.4f}, test={ic_learned_test:+.4f}")

    print(f"[tune] 权重对比：")
    for i, k in enumerate(DIM_KEYS):
        marker = '  ←' if abs(w_learned[i] - w_default[i]) > 0.03 else ''
        print(f"  {k:18s}  default={w_default[i]:.3f}  learned={w_learned[i]:.3f}{marker}")

    # 阈值校准（训练集分位数）
    train_scores = _score_with_weights(train_dims, w_learned)
    quantiles = [0.20, 0.50, 0.80, 0.95]
    thresholds = [float(np.nanquantile(train_scores, q)) for q in quantiles]
    # 安全检查：单调（COBYLA 后 score 排名应正常）
    for i in range(3):
        if thresholds[i] > thresholds[i + 1]:
            thresholds[i + 1] = thresholds[i]
    print(f"[tune] 阈值（训练集分位数 {quantiles}）：{thresholds}")

    # 验证集分组统计
    test_scores = _score_with_weights(test_dims, w_learned)
    per_star = _per_star_stats(test_scores, test_ret, thresholds)
    print(f"[tune] 验证集每星 ret_30：")
    for star in ['1', '2', '3', '4', '5']:
        s = per_star[star]
        if s['n'] == 0 or s['ret_mean'] is None:
            print(f"  {'★' * int(star):<7s}  n={s['n']:4d}  -")
        else:
            print(f"  {'★' * int(star):<7s}  n={s['n']:4d}  mean={s['ret_mean']:+.2%}  median={s['ret_median']:+.2%}")

    # 单调性检查（mean 单调递增）
    means = [per_star[str(st)]['ret_mean'] for st in [1, 2, 3, 4, 5]]
    valid_means = [m for m in means if m is not None]
    monotonic = all(valid_means[i] <= valid_means[i + 1] for i in range(len(valid_means) - 1)) if len(valid_means) >= 2 else None
    if monotonic is True:
        print(f"[tune] 单调性 ✓")
    elif monotonic is False:
        print(f"[tune] 单调性 ✗（局部反转）")

    # 过拟合警告
    overfit_warn = False
    if ic_learned_train > 0.05 and abs(ic_learned_train - ic_learned_test) > 0.5 * abs(ic_learned_train):
        print(f"[tune] ⚠️ 训练/验证 IC 差距大于 50%，可能过拟合")
        overfit_warn = True

    # 落盘
    weights_dict = {k: float(w_learned[i]) for i, k in enumerate(DIM_KEYS)}
    (OUTPUT_DIR / 'recommender_weights.json').write_text(
        json.dumps(weights_dict, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    (OUTPUT_DIR / 'recommender_calibration.json').write_text(
        json.dumps({
            'star_thresholds': thresholds,
            'quantiles': quantiles,
            'train_score_stats': {
                'min': float(np.nanmin(train_scores)),
                'max': float(np.nanmax(train_scores)),
                'mean': float(np.nanmean(train_scores)),
            },
        }, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    (OUTPUT_DIR / 'recommender_validation.json').write_text(
        json.dumps({
            'status': 'ok',
            'n_samples': n_usable,
            'n_train': len(train),
            'n_test': len(test),
            'ic_default_train': ic_default_train,
            'ic_default_test': ic_default_test,
            'ic_learned_train': ic_learned_train,
            'ic_learned_test': ic_learned_test,
            'monotonic': monotonic,
            'overfit_warn': overfit_warn,
            'per_star_test': per_star,
            'weights': weights_dict,
            'thresholds': thresholds,
        }, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(f"[tune] → {OUTPUT_DIR / 'recommender_weights.json'}")
    print(f"[tune] → {OUTPUT_DIR / 'recommender_calibration.json'}")
    print(f"[tune] → {OUTPUT_DIR / 'recommender_validation.json'}")


if __name__ == '__main__':
    main()

"""推荐指数：根据规则把入选样本打分为 1~5 星

输入字段（来自 features.parquet 或现场计算）：
  upper_shadow_pct, body_pct, amount_ratio_20d, is_60d_high, is_120d_high,
  ma20_deviation, pre3_red_count, pre3_amplitude_avg, pre3_volume_slope

字段缺失时该维度按 0.5 兜底；总分 → 星级映射见 doc。

权重与阈值优先从产物加载，缺失时回退默认值：
  output/recommender_weights.json     ← 由 weight_tuner.py 学习产生
  output/recommender_calibration.json ← 由 weight_tuner.py 校准产生
"""
from __future__ import annotations
from typing import Iterable
import json
import math
import os
from pathlib import Path

import pandas as pd
import numpy as np


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return float('nan')
    return max(lo, min(hi, float(x)))


def _get(d, k, default=np.nan):
    v = d.get(k, default) if isinstance(d, dict) else getattr(d, k, default)
    if v is None:
        return np.nan
    try:
        if isinstance(v, float) and math.isnan(v):
            return np.nan
    except Exception:
        pass
    return v


def _dim_or_default(value: float, default: float = 0.5) -> float:
    return default if (value is None or (isinstance(value, float) and math.isnan(value))) else float(value)


# ---------- 权重 / 阈值加载（运行时优先用学习产物）----------
_OUTPUT_DIR = Path(__file__).resolve().parent / 'output'

DEFAULT_WEIGHTS = {
    'upper_short':   0.22,   # 0.25 * 0.88
    'body_long':     0.176,  # 0.20 * 0.88
    'volume_amp':    0.132,  # 0.15 * 0.88
    'new_high':      0.088,  # 0.10 * 0.88
    'ma_dev_health': 0.088,  # 0.10 * 0.88
    'pre3_setup':    0.088,  # 0.10 * 0.88
    'pre3_vol_slope':0.088,  # 0.10 * 0.88
    'auction':       0.12,   # 新增竞价维度
}
DEFAULT_THRESHOLDS = [0.30, 0.45, 0.60, 0.80]  # → 1/2/3/4/5★ 切分点


def _load_weights():
    p = _OUTPUT_DIR / 'recommender_weights.json'
    if not p.exists():
        return DEFAULT_WEIGHTS, 'default'
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        if not isinstance(d, dict) or set(d.keys()) != set(DEFAULT_WEIGHTS.keys()):
            return DEFAULT_WEIGHTS, 'default(invalid_file)'
        s = sum(d.values())
        if s <= 0 or any(v < 0 for v in d.values()):
            return DEFAULT_WEIGHTS, 'default(non_positive)'
        return {k: float(d[k]) / s for k in DEFAULT_WEIGHTS}, 'learned'
    except Exception:
        return DEFAULT_WEIGHTS, 'default(parse_error)'


def _load_thresholds():
    p = _OUTPUT_DIR / 'recommender_calibration.json'
    if not p.exists():
        return DEFAULT_THRESHOLDS, 'default'
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        ts = d.get('star_thresholds')
        if not isinstance(ts, list) or len(ts) != 4:
            return DEFAULT_THRESHOLDS, 'default(invalid_file)'
        ts = [float(x) for x in ts]
        if not all(ts[i] <= ts[i+1] for i in range(3)):
            return DEFAULT_THRESHOLDS, 'default(non_monotonic)'
        return ts, 'learned'
    except Exception:
        return DEFAULT_THRESHOLDS, 'default(parse_error)'


WEIGHTS, _W_SOURCE = _load_weights()
STAR_THRESHOLDS, _T_SOURCE = _load_thresholds()
print(f'[recommender] weights={_W_SOURCE} thresholds={_T_SOURCE}')


def _score_auction_strength(s: float) -> float:
    """竞价强度评分。甜区 [0.3, 0.7]，过低无量，过高散户哄抢均扣分。"""
    if s is None or s != s:
        return 0.5
    s = float(s)
    if s <= 0.3:
        return 0.5 + s / 0.3 * 0.3        # 0→0.50, 0.3→0.80
    if s <= 0.7:
        return 1.0 - abs(s - 0.5) / 0.2 * 0.2  # 0.5→1.0, 0.3/0.7→0.80
    return max(0.2, 1.0 - (s - 0.7) / 0.3 * 0.6)  # 0.7→0.80, 1.0→0.20


def _score_auction_gap(gap: float, is_limit: bool = False) -> float:
    """竞价跳空幅度评分。
    涨停信号：低/平开是正面信号（说明没过度追高），高开扣分。
    非涨停信号：高开是跳空动能，保持原曲线。
    """
    if gap is None or gap != gap:
        return 0.5
    gap = float(gap)
    if is_limit:
        if gap < -0.005:
            return 0.75   # 低开：次日开盘未追高，趋势更稳
        if gap <= 0.005:
            return 0.85   # 平开：最优
        if gap <= 0.03:
            return 0.60
        if gap <= 0.07:
            return 0.35
        return 0.15       # 过度高开：透支动能
    else:
        # 非涨停（breakthrough / gap_up）：高开是正面信号
        if gap < 0:
            return 0.3
        if gap < 0.02:
            return 0.5
        if gap < 0.05:
            return 0.8
        if gap < 0.08:
            return 1.0
        if gap < 0.12:
            return 0.7
        return 0.4


def _score_auction_breakout(x: float) -> float:
    """开盘价相对前高距离评分。x>=0 表示已越过前高。"""
    if x is None or x != x:
        return 0.5
    x = float(x)
    if x >= 0:
        return 1.0
    dist = -x
    if dist <= 0.02:
        return 0.8
    if dist <= 0.05:
        return 0.5
    return 0.2


def _score_auction(features: dict | pd.Series) -> float:
    gap = _get(features, 'auction_gap_pct')
    breakout = _get(features, 'auction_breakout_pct')
    sig = _get(features, 'signal_type', '')
    is_limit = str(sig) in ('limit_up', 'one_word')

    # 竞价强度优先用真实竞价额/近20日均额比值映射；缺失时回退到已有 auction_strength
    vs20 = _get(features, 'auction_amount_vs_20d')
    if vs20 is not None and vs20 == vs20:
        # 竞价额占比映射到 [0,1]：5% 偏弱→0.3，15% 甜区→1.0，>30% 过热回落
        strength = _auction_vs20_to_strength(float(vs20))
    else:
        strength = _get(features, 'auction_strength')

    gap_score = _score_auction_gap(gap, is_limit=is_limit)
    breakout_score = _score_auction_breakout(breakout)
    strength_score = _score_auction_strength(strength)
    # gap 方向 40%，突破位置 35%，量能强度 25%
    return 0.40 * gap_score + 0.35 * breakout_score + 0.25 * strength_score


def _auction_vs20_to_strength(vs20: float) -> float:
    """竞价额 / 近20日均成交额 → 竞价强度 [0,1]。
    竞价额通常占全天的 3%~10%；占比越高说明早盘资金越积极，但过高（>30%）可能是异动。
    """
    if vs20 != vs20:
        return 0.5
    if vs20 <= 0:
        return 0.0
    if vs20 <= 0.15:
        return min(1.0, vs20 / 0.15)          # 0→0, 0.15→1.0
    if vs20 <= 0.30:
        return 1.0                             # 甜区
    return max(0.4, 1.0 - (vs20 - 0.30) / 0.30 * 0.6)  # 过热回落


def score(features: dict | pd.Series) -> dict:
    """对单条样本打分，返回 {'score': float, 'star': int, 'dims': {...}}"""
    f = features

    # 1. 上影线短：阈值 5%（pct = (h - max(o,c)) / o）
    us = _get(f, 'upper_shadow_pct')
    d_upper = _dim_or_default(1 - _clamp(us / 0.05, 0, 1) if us == us else np.nan)

    # 2. 实体长：阈值 10%
    body = _get(f, 'body_pct')
    d_body = _dim_or_default(_clamp(body / 0.10, 0, 1) if body == body else np.nan)

    # 3. 量能放大：amount_ratio_20d，封顶 4 倍量
    amr = _get(f, 'amount_ratio_20d')
    d_vol = _dim_or_default(_clamp((amr - 1) / 3, 0, 1) if amr == amr else np.nan)

    # 4. 创新高：60 / 120 日各 0.5 权重
    h60 = _get(f, 'is_60d_high')
    h120 = _get(f, 'is_120d_high')
    if h60 != h60 and h120 != h120:
        d_high = 0.5
    else:
        d_high = (0 if h60 != h60 else float(h60)) * 0.5 + (0 if h120 != h120 else float(h120)) * 0.5

    # 5. 均线偏离健康：ma20_deviation 偏离 5% 最佳，越偏离 0 或 15% 越差
    md = _get(f, 'ma20_deviation')
    d_ma = _dim_or_default(_clamp(1 - abs(md - 0.05) / 0.10, 0, 1) if md == md else np.nan)

    # 6. 前 3 日蓄势：连阳 + 小振幅
    rc = _get(f, 'pre3_red_count')
    amp = _get(f, 'pre3_amplitude_avg')
    if rc != rc and amp != amp:
        d_setup = 0.5
    else:
        rc_term = (0 if rc != rc else _clamp(float(rc) / 3, 0, 1)) * 0.5
        amp_term = (0.5 if amp != amp else _clamp(1 - float(amp) / 0.05, 0, 1) * 0.5)
        d_setup = _clamp(rc_term + amp_term, 0, 1)

    # 7. 前 3 日量能渐放：normalize slope ∈ [-0.3, 0.3] → [0, 1]
    sl = _get(f, 'pre3_volume_slope')
    d_slope = _dim_or_default(_clamp((float(sl) + 0.3) / 0.6, 0, 1) if sl == sl else np.nan)

    d_auction = _dim_or_default(_score_auction(f))

    # 信号类型奖励（叠加在加权总分之外）
    sig_type = str(_get(f, 'signal_type', ''))
    if sig_type in ('limit_up', 'one_word'):
        signal_bonus = 0.04
    elif sig_type == 'gap_up':
        signal_bonus = 0.02
    else:
        signal_bonus = 0.00

    dims = {
        'upper_short': d_upper,
        'body_long': d_body,
        'volume_amp': d_vol,
        'new_high': d_high,
        'ma_dev_health': d_ma,
        'pre3_setup': d_setup,
        'pre3_vol_slope': d_slope,
        'auction': d_auction,
        'signal_bonus': signal_bonus,
    }
    base_total = sum(dims[k] * WEIGHTS[k] for k in WEIGHTS)
    total = _clamp(base_total + signal_bonus)
    return {'score': float(total), 'star': total_to_star(total), 'dims': dims}


def total_to_star(total: float) -> int:
    if total != total:  # NaN
        return 0
    t1, t2, t3, t4 = STAR_THRESHOLDS
    if total >= t4:
        return 5
    if total >= t3:
        return 4
    if total >= t2:
        return 3
    if total >= t1:
        return 2
    return 1


def batch_score(features_df: pd.DataFrame) -> pd.DataFrame:
    """对 features.parquet 批量打分，返回 [code, entry_date, score, star] DataFrame"""
    rows = []
    for _, r in features_df.iterrows():
        s = score(r.to_dict())
        rows.append({
            'code': r.get('code'),
            'entry_date': r.get('entry_date'),
            'score': s['score'],
            'star': s['star'],
        })
    return pd.DataFrame(rows)


if __name__ == '__main__':
    from .config import OUTPUT_DIR
    feats = pd.read_parquet(OUTPUT_DIR / 'features.parquet')
    out = batch_score(feats)
    out.to_csv(OUTPUT_DIR / 'recommend_scores.csv', index=False)
    print(out['star'].value_counts().sort_index())
    print(f'mean={out["score"].mean():.3f}, std={out["score"].std():.3f}')

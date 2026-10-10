"""关键发现自动提炼

扫描所有 slice 表，按 |Δret_30| * sqrt(min_n) 评分，取 Top 5 输出中文描述。
"""
from __future__ import annotations
import math
import pandas as pd

from .config import OUTPUT_DIR


def extract(slices: dict[str, pd.DataFrame], min_n: int = 5) -> list[str]:
    findings = []
    for dim, s in slices.items():
        if s is None or s.empty:
            continue
        valid = s[(s['n'] >= min_n) & (s['ret_30_mean'].notna())]
        if len(valid) < 2:
            continue
        best = valid.iloc[valid['ret_30_mean'].argmax()]
        worst = valid.iloc[valid['ret_30_mean'].argmin()]
        delta = float(best['ret_30_mean']) - float(worst['ret_30_mean'])
        if abs(delta) < 0.05:  # 差距 < 5pp 不报告
            continue
        bucket_min_n = int(min(best['n'], worst['n']))
        score = abs(delta) * math.sqrt(bucket_min_n)
        bd_best = best.get('breakdown_ratio')
        bd_worst = worst.get('breakdown_ratio')
        bd_phrase = ''
        if pd.notna(bd_best) and pd.notna(bd_worst):
            bd_phrase = f'，breakdown {float(bd_best):.0%}→{float(bd_worst):.0%}'
        wr_best = best.get('win_30')
        wr_worst = worst.get('win_30')
        wr_phrase = ''
        if pd.notna(wr_best) and pd.notna(wr_worst):
            wr_phrase = f'，胜率 {float(wr_best):.0%}→{float(wr_worst):.0%}'
        msg = (f'[{dim}] {best["bucket"]}(n={int(best["n"])}) vs {worst["bucket"]}(n={int(worst["n"])}) '
               f'ret_30 {float(best["ret_30_mean"]):.1%} vs {float(worst["ret_30_mean"]):.1%} '
               f'(Δ {delta * 100:+.1f}pp){bd_phrase}{wr_phrase}')
        findings.append((score, msg))

    findings.sort(key=lambda x: -x[0])
    top = [f for _, f in findings[:5]]
    out_path = OUTPUT_DIR / 'top_findings.txt'
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('# 关键发现 Top 5\n\n')
        for i, msg in enumerate(top, 1):
            f.write(f'{i}. {msg}\n')
    print(f'[findings] -> {out_path}')
    for i, msg in enumerate(top, 1):
        print(f'  {i}. {msg}')
    return top


if __name__ == '__main__':
    from . import slicer
    df = pd.read_parquet(OUTPUT_DIR / 'fullframe.parquet')
    slices = slicer.run(df)
    extract(slices)

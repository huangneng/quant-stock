#!/usr/bin/env python3
"""kline 表一致性巡检（可选修复成交量单位错误）。

判定依据：真实关系是 amount = VWAP × 股数，所以 amount/(close*volume)
正常应在 1 附近。若该比值稳定落在 100 附近，说明 volume 存的是「手」而非「股」
（东财 stock_zh_a_hist 的 成交量 单位是手，成交额 是元）。

用法:
    python3 scripts/audit_kline_integrity.py                 # 只巡检
    python3 scripts/audit_kline_integrity.py --fix           # 预览将修复的行数
    python3 scripts/audit_kline_integrity.py --fix --yes     # 实际写库

退出码：0 = 无异常，1 = 发现异常行。
"""
import argparse
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / 'stock_data' / 'kline.db'

# 可判定行：三个字段都为正才能算比值
JUDGABLE = 'volume > 0 AND close > 0 AND amount > 0'
RATIO = 'amount / (close * volume)'
# 腾讯源的 amount 是 均价×volume 算出来的近似值，据此归因
TENCENT_APPROX = 'ABS(amount - (open+high+low+close)/4.0*volume) <= 0.001*ABS(amount)'

# 单位错误的判定区间：上下界留足 VWAP 偏离 close 的余量，
# 且与正常群体（比值 <2）之间有巨大空隙，不会误判
FIX_LO, FIX_HI = 50, 200

BUCKETS = [
    ('比值 <0.5   量偏大',    f'{RATIO} < 0.5'),
    ('比值 0.5~2  正常',      f'{RATIO} >= 0.5 AND {RATIO} < 2'),
    ('比值 2~50   可疑',      f'{RATIO} >= 2 AND {RATIO} < 50'),
    ('比值 50~200 手/股错误', f'{RATIO} >= {FIX_LO} AND {RATIO} < {FIX_HI}'),
    ('比值 ≥200   未知',      f'{RATIO} >= {FIX_HI}'),
]
ABNORMAL = f'{RATIO} < 0.5 OR {RATIO} >= 2'


def audit(cur):
    total = cur.execute('SELECT COUNT(*) FROM kline').fetchone()[0]
    judgable = cur.execute(f'SELECT COUNT(*) FROM kline WHERE {JUDGABLE}').fetchone()[0]
    print(f'总行数 {total:,}  可判定 {judgable:,}  不可判定 {total-judgable:,}'
          f'（停牌/零成交，跳过）')
    lo, hi = cur.execute('SELECT MIN(date), MAX(date) FROM kline').fetchone()
    print(f'日期范围 {lo} ~ {hi}   股票数 '
          f'{cur.execute("SELECT COUNT(DISTINCT code) FROM kline").fetchone()[0]:,}')

    print('\n=== amount/(close*volume) 分布 ===')
    for label, cond in BUCKETS:
        n = cur.execute(f'SELECT COUNT(*) FROM kline WHERE {JUDGABLE} AND {cond}').fetchone()[0]
        tx = cur.execute(f'SELECT COUNT(*) FROM kline WHERE {JUDGABLE} AND {cond} '
                         f'AND {TENCENT_APPROX}').fetchone()[0]
        pct = n / judgable if judgable else 0
        print(f'  {label:22s} {n:8,}  ({pct:6.2%})   疑似腾讯近似 {tx:,}')
    print('  （「疑似腾讯近似」= amount 与 均价×volume 相差 <0.1%。这是弱归因：'
          '任何源的正常行只要 均价 恰好接近 VWAP 也会命中，仅在排查单位错误时有参考价值）')

    bad = cur.execute(f'SELECT COUNT(*) FROM kline WHERE {JUDGABLE} AND '
                      f'{RATIO} >= {FIX_LO} AND {RATIO} < {FIX_HI}').fetchone()[0]
    if not bad:
        return 0

    print(f'\n=== 手/股单位错误明细（{bad:,} 行）===')
    codes, d0, d1 = cur.execute(
        f'SELECT COUNT(DISTINCT code), MIN(date), MAX(date) FROM kline WHERE {JUDGABLE} '
        f'AND {RATIO} >= {FIX_LO} AND {RATIO} < {FIX_HI}').fetchone()
    print(f'  波及 {codes:,} 只票，{d0} ~ {d1}')
    turn_nonzero = cur.execute(
        f'SELECT COUNT(*) FROM kline WHERE {JUDGABLE} AND {RATIO} >= {FIX_LO} '
        f'AND {RATIO} < {FIX_HI} AND turn > 0').fetchone()[0]
    print(f'  turn>0 的行 {turn_nonzero:,}/{bad:,}'
          f'（turn 仅由 akshare / baostock 填充，可用于归因）')
    print('  按年月分布:')
    for ym, n in cur.execute(
            f'SELECT SUBSTR(date,1,7), COUNT(*) FROM kline WHERE {JUDGABLE} '
            f'AND {RATIO} >= {FIX_LO} AND {RATIO} < {FIX_HI} GROUP BY 1 ORDER BY 1'):
        print(f'    {ym}  {n:,}')
    print('  受影响最多的票:')
    # 必须先 fetchall：循环体内复用同一个 cursor 执行查询会重置迭代器，只能拿到第一行
    top = cur.execute(
        f'SELECT code, COUNT(*) FROM kline WHERE {JUDGABLE} AND {RATIO} >= {FIX_LO} '
        f'AND {RATIO} < {FIX_HI} GROUP BY code ORDER BY 2 DESC LIMIT 5').fetchall()
    for code, n in top:
        tot = cur.execute('SELECT COUNT(*) FROM kline WHERE code=?', (code,)).fetchone()[0]
        print(f'    {code}  {n}/{tot} 行')
    return bad


def fix(con, cur, bad, do_write, db_path):
    print(f'\n=== 修复 ===')
    print(f'待修复 {bad:,} 行：volume = volume * 100（amount / turn / 价格字段不动）')
    if not do_write:
        print('这是预览。加 --yes 才会写库。')
        return
    backup = db_path.with_suffix(f'.db.bak_before_volfix_{time.strftime("%Y%m%d_%H%M%S")}')
    shutil.copy2(db_path, backup)
    print(f'已备份 -> {backup.name}')
    cur.execute(f'UPDATE kline SET volume = volume * 100 WHERE {JUDGABLE} '
                f'AND {RATIO} >= {FIX_LO} AND {RATIO} < {FIX_HI}')
    print(f'已更新 {cur.rowcount:,} 行')
    con.commit()


def _sina_latest(codes, batch=600):
    """批量拉新浪快照，返回 {code: (date, volume_shares)}。

    日期以响应自带的字段为准——不能假设「今天」，周末/节假日快照给的是
    最后一个交易日。
    """
    import requests
    sess = requests.Session()
    sess.headers.update({'User-Agent': 'Mozilla/5.0',
                         'Referer': 'https://finance.sina.com.cn/'})
    out = {}
    for i in range(0, len(codes), batch):
        chunk = codes[i:i + batch]
        url = 'https://hq.sinajs.cn/list=' + ','.join(c.replace('.', '') for c in chunk)
        resp = sess.get(url, timeout=15)
        resp.encoding = 'gbk'
        for line, code in zip(resp.text.strip().splitlines(), chunk):
            try:
                p = line.split('"')[1].split(',')
            except IndexError:
                continue
            if len(p) < 32:
                continue
            try:
                out[code] = (p[30], float(p[8]))
            except ValueError:
                continue
        time.sleep(0.3)
    return out


def check_latest(cur, selected_codes):
    """用新浪快照比对最后一个交易日的成交量，检测盘中写入的半截 K 线。

    库内自洽性检查发现不了半截行：amount 是用同一个偏小的 volume 算出来的，
    amount/(close*volume) 仍然是 1。只能靠外部参照。
    """
    codes = [r[0] for r in cur.execute('SELECT code FROM universe ORDER BY code')]
    print(f'\n=== 半截 K 线检测（新浪快照比对，{len(codes):,} 只）===')
    ref = _sina_latest(codes)
    if not ref:
        print('  新浪快照取数失败，无法检测')
        return -1
    dates = {}
    for d, _ in ref.values():
        dates[d] = dates.get(d, 0) + 1
    target = max(dates, key=dates.get)
    print(f'  快照主日期 {target}（{dates[target]:,} 只），参照 {len(ref):,} 只')

    rows = dict(cur.execute('SELECT code, volume FROM kline WHERE date = ?', (target,)).fetchall())
    if not rows:
        print(f'  库内没有 {target} 的数据，无法比对')
        return -1
    print(f'  库内 {target} 有 {len(rows):,} 行')

    buckets = {'一致(<1%)': 0, '偏小1~50%': 0, '偏小50~90%': 0, '偏小>90%': 0, '库偏大': 0}
    detail = []
    for code, (d, vol_ref) in ref.items():
        if d != target or code not in rows:
            continue
        vol_db = rows[code]
        if not vol_db or vol_db <= 0 or vol_ref <= 0:
            continue
        short = 1 - vol_db / vol_ref          # 库比参照少的比例
        if short < -0.01:
            buckets['库偏大'] += 1
        elif short <= 0.01:
            buckets['一致(<1%)'] += 1
        else:
            if short <= 0.5:
                buckets['偏小1~50%'] += 1
            elif short <= 0.9:
                buckets['偏小50~90%'] += 1
            else:
                buckets['偏小>90%'] += 1
            detail.append((short, code, vol_db, vol_ref))
    for k, v in buckets.items():
        print(f'    {k:12s} {v:6,}')
    if not detail:
        print('  未发现半截 K 线')
        return 0
    detail.sort(reverse=True)
    print(f'  偏差最严重的 {min(10, len(detail))} 只:')
    for short, code, vdb, vref in detail[:10]:
        mark = '  ← 历史选股标的' if code in selected_codes else ''
        print(f'    {code}  库={vdb:>15,.0f}  实际={vref:>15,.0f}  少 {short:6.1%}{mark}')
    hit = sum(1 for _, c, _, _ in detail if c in selected_codes)
    print(f'  其中历史选股标的 {hit} 只')
    return len(detail)


def _load_selected_codes():
    """读 selections.json 里出现过的代码，用于在报告里标注影响面。"""
    import json
    p = ROOT / 'stock_data' / 'selections.json'
    if not p.exists():
        return set()
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return set()
    out = set()
    for v in d.values():
        for st in (v.get('stocks') or []):
            if st.get('code'):
                out.add(st['code'])
    return out


def main():
    ap = argparse.ArgumentParser(description='kline 表一致性巡检')
    ap.add_argument('--fix', action='store_true', help='修复手/股单位错误的行')
    ap.add_argument('--yes', action='store_true', help='与 --fix 同用时才真正写库')
    ap.add_argument('--check-latest', action='store_true',
                    help='用新浪快照比对最后一个交易日成交量，检测盘中半截 K 线')
    ap.add_argument('--db', default=str(DB_PATH), help='库路径（便于在备份库上演练）')
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f'库不存在: {db_path}')
        return 2
    print(f'库: {db_path}')
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    bad = audit(cur)
    if args.fix and bad:
        fix(con, cur, bad, args.yes, db_path)
        print('\n=== 修复后复查 ===')
        bad = audit(cur)
    partial = 0
    if args.check_latest:
        partial = check_latest(cur, _load_selected_codes())
    con.close()
    return 1 if (bad or partial) else 0


if __name__ == '__main__':
    sys.exit(main())



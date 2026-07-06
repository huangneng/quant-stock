"""数据完整性异常 & 工具。"""


class DataHubError(Exception):
    pass


class MissingTodayBar(DataHubError):
    """analyze 阶段需要今日 K 线但 hist 中找不到。"""


class InsufficientHistory(DataHubError):
    """历史 K 线长度不足以做信号判定。"""


def check_completeness(codes, end_date, min_rows=100):
    """检查 KlineDB 中 codes 截至 end_date 的覆盖率与历史深度。

    - missing：近窗口内 0 行（完全缺失）。
    - shallow：近窗口内行数 < min_rows（历史不足，无法支撑 PRE_DAYS 信号判定）。
    - present：近窗口内行数 >= min_rows。
    历史不足仅作可观测性预警，实际补拉由 router 读取时自愈。
    """
    import pandas as pd
    from data_hub.store.kline_db import KlineDB
    db = KlineDB()

    # 近窗口起点：min_rows 个交易日 ≈ min_rows*1.6 自然日，留足缓冲
    win_days = int(min_rows * 1.6) + 10
    win_start = (pd.Timestamp(end_date) - pd.Timedelta(days=win_days)).strftime('%Y-%m-%d')

    missing, shallow, present = [], [], []
    for c in codes:
        df = db.query_kline(c, win_start, end_date)
        n = 0 if df is None else len(df)
        if n == 0:
            missing.append(c)
        elif n < min_rows:
            shallow.append(c)
        else:
            present.append(c)
    total = len(codes)
    return {
        'total': total,
        'present': len(present),
        'missing_count': len(missing),
        'missing_codes': missing[:50],
        'missing_pct': round(100.0 * len(missing) / total, 2) if total else 0.0,
        'shallow_count': len(shallow),
        'shallow_codes': shallow[:50],
        'shallow_pct': round(100.0 * len(shallow) / total, 2) if total else 0.0,
        'min_rows': min_rows,
        'last_sync_date': db.meta_get('last_sync_date'),
    }

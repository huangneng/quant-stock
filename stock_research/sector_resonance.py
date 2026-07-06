# -*- coding: utf-8 -*-
"""板块/行业共振新高判定。

该模块隔离于主选股流程：只服务离线回填脚本，所有外部接口失败时使用缓存或安全跳过。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / 'stock_data' / 'cache' / 'sector'
INDUSTRY_NAME_CACHE = CACHE_DIR / 'industry_names.json'
INDUSTRY_MEMBERS_CACHE = CACHE_DIR / 'industry_members.json'
INDUSTRY_HIST_DIR = CACHE_DIR / 'industry_hist'
CONCEPT_NAME_CACHE = CACHE_DIR / 'concept_names.json'
CONCEPT_MEMBERS_CACHE = CACHE_DIR / 'concept_members.json'
CONCEPT_HIST_DIR = CACHE_DIR / 'concept_hist'
TRADE_CAL = ROOT / 'stock_data' / 'trade_calendar.json'
MANUAL_RESONANCE_FILE = CACHE_DIR / 'manual_resonance.json'

# 噪音板块黑名单：动态轮动池，不代表真实行业/主题，排除在板块共振之外
_BOARD_BLOCKLIST = {
    '东方财富热股',
    '昨日打二板以上表现',
    '题材股',
    'AH股',
    '金融地产风格',
}

CACHE_DIR.mkdir(parents=True, exist_ok=True)
INDUSTRY_HIST_DIR.mkdir(parents=True, exist_ok=True)
CONCEPT_HIST_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        pass
    return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _bs_code(raw: Any) -> str | None:
    s = str(raw).strip()
    m = re.search(r'(\d{6})', s)
    if not m:
        return None
    num = m.group(1)
    if num.startswith(('6', '9')):
        return 'sh.' + num
    if num.startswith(('0', '2', '3')):
        return 'sz.' + num
    if num.startswith(('4', '8')):
        return 'bj.' + num
    return None


def _safe_float(value):
    try:
        if value is None:
            return None
        v = float(value)
        if v != v:
            return None
        return v
    except Exception:
        return None


def _cache_file_name(name: str) -> str:
    return re.sub(r'[^0-9A-Za-z\u4e00-\u9fff._-]+', '_', name)[:80] + '.csv'


def _default_manual_events() -> list[dict]:
    return [
        {
            'code': 'sz.300475',
            'type': 'concept',
            'name': '存储芯片',
            'note': '用户确认：香农芯创属于存储芯片概念；共振日期和突破幅度由板块指数自动计算。',
        }
    ]


def load_manual_resonance_events() -> list[dict]:
    events = _load_json(MANUAL_RESONANCE_FILE, None)
    if events is None:
        events = _default_manual_events()
        _save_json(MANUAL_RESONANCE_FILE, events)
    if not isinstance(events, list):
        return []
    return events


def manual_boards_for_code(code: str) -> list[dict]:
    boards = []
    seen = set()
    for event in load_manual_resonance_events():
        if event.get('code') != code:
            continue
        name = event.get('name')
        board_type = event.get('type', 'concept')
        if not name:
            continue
        key = (board_type, name)
        if key in seen:
            continue
        boards.append({'type': board_type, 'name': name, 'source': 'manual'})
        seen.add(key)
    return boards


def load_trade_dates() -> list[str]:
    data = _load_json(TRADE_CAL, None)
    if data is None:
        try:
            from scripts.check_trade_date import get_trade_dates
            dates = sorted(get_trade_dates())
            return dates
        except Exception:
            return []
    if isinstance(data, dict):
        dates = data.get('dates') if isinstance(data.get('dates'), list) else list(data.keys())
    elif isinstance(data, list):
        dates = data
    else:
        return []
    return sorted(d for d in dates if isinstance(d, str) and len(d) == 10)


def trade_window(date_iso: str, before: int = 2, after: int = 2, trade_dates: list[str] | None = None, max_date: str | None = None) -> list[str]:
    dates = trade_dates or load_trade_dates()
    if max_date:
        dates = [d for d in dates if d <= max_date]
    if not dates:
        return []
    if date_iso not in dates:
        candidates = [d for d in dates if d <= date_iso]
        if not candidates:
            return []
        date_iso = candidates[-1]
    idx = dates.index(date_iso)
    lo = max(0, idx - before)
    hi = min(len(dates), idx + after + 1)
    return dates[lo:hi]


def get_industry_names(force_refresh: bool = False) -> list[str]:
    cached = _load_json(INDUSTRY_NAME_CACHE, [])
    if cached and not force_refresh:
        return cached
    try:
        from data_hub.api import get_sector_boards
        df = get_sector_boards('industry', force_refresh=force_refresh)
        if df is not None and not df.empty and 'name' in df.columns:
            names = [str(x) for x in df['name'].dropna().tolist()]
            if names:
                _save_json(INDUSTRY_NAME_CACHE, names)
                return names
    except Exception as e:
        print(f'[sector] data_hub 行业列表获取失败，尝试 akshare：{e}')
    try:
        import akshare as ak
        df = ak.stock_board_industry_name_em()
        if df is None or df.empty or '板块名称' not in df.columns:
            return cached
        names = [str(x) for x in df['板块名称'].dropna().tolist()]
        if names:
            _save_json(INDUSTRY_NAME_CACHE, names)
            return names
    except Exception as e:
        print(f'[sector] 行业列表获取失败，使用缓存：{e}')
    return cached


def get_concept_names(force_refresh: bool = False) -> list[str]:
    cached = _load_json(CONCEPT_NAME_CACHE, [])
    if cached and not force_refresh:
        return cached
    try:
        from data_hub.api import get_sector_boards
        df = get_sector_boards('concept', force_refresh=force_refresh)
        if df is not None and not df.empty and 'name' in df.columns:
            names = [str(x) for x in df['name'].dropna().tolist()]
            if names:
                _save_json(CONCEPT_NAME_CACHE, names)
                return names
    except Exception as e:
        print(f'[sector] data_hub 概念列表获取失败，尝试 akshare：{e}')
    try:
        import akshare as ak
        df = ak.stock_board_concept_name_em()
        if df is None or df.empty or '板块名称' not in df.columns:
            return cached
        names = [str(x) for x in df['板块名称'].dropna().tolist()]
        if names:
            _save_json(CONCEPT_NAME_CACHE, names)
            return names
    except Exception as e:
        print(f'[sector] 概念列表获取失败，使用缓存：{e}')
    return cached


def _extract_members(df: pd.DataFrame) -> list[str]:
    codes = set()
    for col in df.columns:
        col_s = str(col)
        if '代码' in col_s or col_s.lower() in {'code', 'symbol'}:
            for value in df[col].dropna().tolist():
                code = _bs_code(value)
                if code:
                    codes.add(code)
    if not codes:
        for _, row in df.iterrows():
            for value in row.tolist():
                code = _bs_code(value)
                if code:
                    codes.add(code)
    return sorted(codes)


def _build_member_map(
    *,
    board_type: str,
    names: list[str],
    cache_path: Path,
    cons_func_name: str,
    force_refresh: bool = False,
    sleep: float = 0.2,
    max_boards: int | None = None,
) -> dict[str, list[dict]]:
    cached = _load_json(cache_path, {})
    if cached and not force_refresh:
        return cached
    if not names:
        return cached
    mapping: dict[str, list[dict]] = {}
    try:
        import akshare as ak
        cons_func = getattr(ak, cons_func_name)
    except Exception as e:
        print(f'[sector] akshare 不可用，使用{board_type}缓存：{e}')
        return cached

    ok = 0
    fail = 0
    for name in (names[:max_boards] if max_boards else names):
        try:
            try:
                from data_hub.api import get_sector_members
                hub_df = get_sector_members(board_type, board_name=name, force_refresh=force_refresh)
                if hub_df is not None and not hub_df.empty and 'code' in hub_df.columns:
                    for code in hub_df['code'].dropna().astype(str).tolist():
                        mapping.setdefault(code, []).append({'type': board_type, 'name': name})
                    ok += 1
                    if sleep:
                        time.sleep(sleep)
                    continue
            except Exception:
                pass
            df = cons_func(symbol=name)
            if df is None or df.empty:
                fail += 1
                continue
            for code in _extract_members(df):
                mapping.setdefault(code, []).append({'type': board_type, 'name': name})
            ok += 1
        except Exception as e:
            fail += 1
            if cached:
                continue
            print(f'[sector] {board_type}成分获取失败 {name}: {e}')
        if sleep:
            time.sleep(sleep)
    if mapping:
        _save_json(cache_path, mapping)
        print(f'[sector] {board_type}成分缓存完成 boards_ok={ok} boards_fail={fail} stocks={len(mapping)}')
        return mapping
    return cached


def build_industry_member_map(force_refresh: bool = False, sleep: float = 0.2, max_boards: int | None = None) -> dict[str, list[dict]]:
    return _build_member_map(
        board_type='industry',
        names=get_industry_names(force_refresh=force_refresh),
        cache_path=INDUSTRY_MEMBERS_CACHE,
        cons_func_name='stock_board_industry_cons_em',
        force_refresh=force_refresh,
        sleep=sleep,
        max_boards=max_boards,
    )


def build_concept_member_map(force_refresh: bool = False, sleep: float = 0.2, max_boards: int | None = None) -> dict[str, list[dict]]:
    return _build_member_map(
        board_type='concept',
        names=get_concept_names(force_refresh=force_refresh),
        cache_path=CONCEPT_MEMBERS_CACHE,
        cons_func_name='stock_board_concept_cons_em',
        force_refresh=force_refresh,
        sleep=sleep,
        max_boards=max_boards,
    )


def build_sector_member_map(force_refresh: bool = False, sleep: float = 0.2, max_boards: int | None = None) -> dict[str, list[dict]]:
    industry = build_industry_member_map(force_refresh=force_refresh, sleep=sleep, max_boards=max_boards)
    concept = build_concept_member_map(force_refresh=force_refresh, sleep=sleep, max_boards=max_boards)
    merged: dict[str, list[dict]] = {}
    for source in [industry, concept]:
        for code, boards in source.items():
            merged.setdefault(code, [])
            seen = {(b.get('type'), b.get('name')) for b in merged[code]}
            for board in boards:
                key = (board.get('type'), board.get('name'))
                if key not in seen:
                    merged[code].append(board)
                    seen.add(key)
    return merged


def _normalize_hist(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    rename = {
        '日期': 'date', '开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low',
        '成交额': 'amount', '成交量': 'volume', '涨跌幅': 'pctChg',
    }
    df = df.rename(columns=rename).copy()
    if 'date' not in df.columns:
        return pd.DataFrame()
    df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
    for c in ['open', 'high', 'low', 'close', 'amount', 'volume', 'pctChg']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        else:
            df[c] = pd.NA
    return df[['date', 'open', 'high', 'low', 'close', 'amount', 'volume', 'pctChg']].dropna(subset=['date', 'close']).sort_values('date')


def _get_board_hist(
    *,
    board_type: str,
    name: str,
    start: str,
    end: str,
    hist_dir: Path,
    hist_func_name: str,
    force_refresh: bool = False,
) -> pd.DataFrame:
    path = hist_dir / _cache_file_name(name)
    cached = pd.DataFrame()
    if path.exists():
        try:
            cached = pd.read_csv(path, dtype={'date': str})
            if not force_refresh and not cached.empty and cached['date'].min() <= start and cached['date'].max() >= end:
                return cached[(cached['date'] >= start) & (cached['date'] <= end)].copy()
        except Exception:
            cached = pd.DataFrame()
    try:
        from data_hub.api import get_sector_kline
        hub_df = get_sector_kline(board_type, board_name=name, board_code=None, start=start, end=end, force_refresh=force_refresh)
        if hub_df is not None and not hub_df.empty:
            norm = hub_df.copy()
            if not cached.empty:
                norm = pd.concat([cached, norm], ignore_index=True).drop_duplicates('date', keep='last')
                norm = norm.sort_values('date')
            norm.to_csv(path, index=False)
            return norm[(norm['date'] >= start) & (norm['date'] <= end)].copy()
    except Exception:
        pass
    try:
        import akshare as ak
        hist_func = getattr(ak, hist_func_name)
        df = hist_func(
            symbol=name,
            start_date=start.replace('-', ''),
            end_date=end.replace('-', ''),
            period='日k',
            adjust='',
        )
        norm = _normalize_hist(df)
        if not norm.empty:
            if not cached.empty:
                norm = pd.concat([cached, norm], ignore_index=True).drop_duplicates('date', keep='last')
                norm = norm.sort_values('date')
            norm.to_csv(path, index=False)
            return norm[(norm['date'] >= start) & (norm['date'] <= end)].copy()
    except Exception as e:
        if cached.empty:
            print(f'[sector] {board_type}指数获取失败 {name}: {e}')
    if not cached.empty:
        return cached[(cached['date'] >= start) & (cached['date'] <= end)].copy()
    return pd.DataFrame()


def get_industry_hist(name: str, start: str, end: str, force_refresh: bool = False) -> pd.DataFrame:
    return _get_board_hist(
        board_type='industry',
        name=name,
        start=start,
        end=end,
        hist_dir=INDUSTRY_HIST_DIR,
        hist_func_name='stock_board_industry_hist_em',
        force_refresh=force_refresh,
    )


def get_concept_hist(name: str, start: str, end: str, force_refresh: bool = False) -> pd.DataFrame:
    return _get_board_hist(
        board_type='concept',
        name=name,
        start=start,
        end=end,
        hist_dir=CONCEPT_HIST_DIR,
        hist_func_name='stock_board_concept_hist_em',
        force_refresh=force_refresh,
    )


def get_board_hist(board_type: str, name: str, start: str, end: str, force_refresh: bool = False) -> pd.DataFrame:
    if board_type == 'concept':
        return get_concept_hist(name, start, end, force_refresh=force_refresh)
    return get_industry_hist(name, start, end, force_refresh=force_refresh)


def detect_sector_resonance(
    code: str,
    pick_date: str,
    *,
    member_map: dict[str, list[dict]] | None = None,
    trade_dates: list[str] | None = None,
    lookback: int = 100,
    min_history: int = 60,
) -> dict | None:
    mapping = member_map if member_map is not None else build_sector_member_map()
    boards = list(mapping.get(code, []))
    seen = {(b.get('type'), b.get('name')) for b in boards}
    for board in manual_boards_for_code(code):
        key = (board.get('type'), board.get('name'))
        if key not in seen:
            boards.append(board)
            seen.add(key)
    dates = trade_dates or load_trade_dates()
    max_date = dates[-1] if dates else None
    window = trade_window(pick_date, before=2, after=2, trade_dates=dates, max_date=max_date)
    if not window:
        return None
    start_idx = max(0, dates.index(window[0]) - lookback - 5) if window[0] in dates else 0
    start = dates[start_idx] if dates else (pd.Timestamp(pick_date) - pd.Timedelta(days=180)).strftime('%Y-%m-%d')
    end = window[-1]
    best = None
    for board in boards:
        name = board.get('name')
        if not name:
            continue
        if name in _BOARD_BLOCKLIST:
            continue
        board_type = board.get('type', 'industry')
        hist = get_board_hist(board_type, name, start, end)
        if hist.empty:
            continue
        hist = hist[hist['date'] <= end].sort_values('date').reset_index(drop=True)
        for d in window:
            pos = hist.index[hist['date'] == d].tolist()
            if not pos:
                continue
            idx = pos[0]
            pre = hist.iloc[:idx].tail(lookback)
            if len(pre) < min_history:
                continue
            ref_high = _safe_float(pre['high'].max())
            close = _safe_float(hist.iloc[idx]['close'])
            if not ref_high or not close:
                continue
            if close >= ref_high:
                breakout_pct = close / ref_high - 1.0
                result = {
                    'sector_resonance': True,
                    'sector_resonance_type': board.get('type', 'industry'),
                    'sector_resonance_name': name,
                    'sector_resonance_date': d,
                    'sector_resonance_breakout_pct': round(float(breakout_pct), 4),
                }
                if best is None or result['sector_resonance_breakout_pct'] > best['sector_resonance_breakout_pct']:
                    best = result
    return best

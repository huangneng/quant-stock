"""智能路由：根据请求类型选源、组合本地库 + 在线源。"""
from __future__ import annotations
from typing import Optional, List
import time
import re
import pandas as pd

from data_hub.sources.base import UNIFIED_COLS
from data_hub.sources.sina import SinaSource
from data_hub.sources.tencent import TencentSource
from data_hub.sources.baostock import BaostockSource
from data_hub.sources.mootdx_source import MootdxSource
from data_hub.sources.akshare import AkshareSource
from data_hub.sources.eastmoney_sector import EastmoneySectorSource
from data_hub.sources.tonghuashun_sector import TonghuashunSectorSource
from data_hub.sources.ths_newhigh import NewHighSource
from data_hub.store.kline_db import KlineDB

_SNAPSHOT_CACHE: dict = {}

# 统一日期格式：所有入参先归一化为 YYYY-MM-DD
_DATE_PAT = re.compile(r'^\d{8}$')


def _iso(d: str) -> str:
    """YYYYMMDD → YYYY-MM-DD，其他原样返回。"""
    if _DATE_PAT.match(d):
        return f'{d[:4]}-{d[4:6]}-{d[6:8]}'
    return d


class Router:
    def __init__(self):
        self.sina = SinaSource()
        self.tencent = TencentSource()
        self.bs = BaostockSource()
        self.mootdx = MootdxSource()
        self.ak = AkshareSource()
        self.em_sector = EastmoneySectorSource()
        self.ths_sector = TonghuashunSectorSource()
        self.newhigh = NewHighSource()
        self.db = KlineDB()
        self._bs_logged_in = False
        self._mootdx_logged_in = False
        self._ak_logged_in = False

    # ---------- snapshot ----------
    def get_market_snapshot(self, codes: Optional[list] = None) -> dict:
        if codes is None:
            codes = self.get_universe()['code'].tolist()
        # 10 分钟桶缓存
        now = pd.Timestamp.now()
        bucket = now.strftime('%Y-%m-%d') + f"_{now.hour:02d}{(now.minute // 10) * 10:02d}"
        cached = _SNAPSHOT_CACHE.get(bucket)
        if cached and set(codes).issubset(cached.keys()):
            return {c: cached[c] for c in codes if c in cached}
        snap = self.sina.get_market_snapshot(codes)
        missing = [c for c in codes if c not in snap]
        if missing:
            try:
                fallback = self.tencent.get_market_snapshot(missing)
            except Exception:
                fallback = {}
            if fallback:
                snap.update(fallback)
        _SNAPSHOT_CACHE[bucket] = snap
        # 清掉旧桶
        for k in list(_SNAPSHOT_CACHE.keys()):
            if k != bucket:
                _SNAPSHOT_CACHE.pop(k, None)
        return snap

    # ---------- universe ----------
    def get_universe(self, force_refresh: bool = False) -> pd.DataFrame:
        if not force_refresh:
            df = self.db.get_universe()
            if df is not None and not df.empty:
                return df
        # 从 baostock 拉 + 入库
        if not self._bs_logged_in:
            self._bs_logged_in = self.bs.login()
        df = self.bs.get_universe()
        if df is not None and not df.empty:
            self.db.upsert_universe(df)
        return df if df is not None else pd.DataFrame(columns=['code', 'name'])

    # ---------- kline ----------
    def get_kline(self, code: str, start: str, end: str,
                  *, require_today: bool = False) -> Optional[pd.DataFrame]:
        # 统一日期格式为 YYYY-MM-DD
        start = _iso(start)
        end = _iso(end)
        today_iso = pd.Timestamp.now().strftime('%Y-%m-%d')

        # 1) 从 KlineDB 读
        df = self.db.query_kline(code, start, end)
        if df is None:
            df = pd.DataFrame(columns=UNIFIED_COLS)

        # 2) 判断 KlineDB 是否覆盖到 (end 或 today-1)，并检查历史起始是否足够
        target_last = min(end, today_iso) if end >= today_iso else end
        last_in_db = df['date'].max() if not df.empty else None
        first_in_db = df['date'].min() if not df.empty else None
        need_online_fill = (
            (last_in_db is None) or (last_in_db < target_last)
            or (first_in_db is not None and first_in_db > start)
        )

        # 3) 不够则用 baostock 拉缺口
        if need_online_fill:
            # 如果历史起点不足 start，必须从 start 全量补拉，不能从 last_in_db 补
            if first_in_db is not None and first_in_db > start:
                fill_start = start
            elif last_in_db and last_in_db >= start:
                fill_start = last_in_db
            else:
                fill_start = start
            online = self._fetch_kline_online(code, fill_start, end)
            if online is not None and not online.empty:
                online_in = online[(online['date'] >= start) & (online['date'] <= end)].copy()
                if not online_in.empty:
                    online_in['code'] = code
                    self.db.upsert_kline(online_in)
                df = self.db.query_kline(code, start, end)

        # 4) require_today：拼今日 Sina 行
        if require_today and end >= today_iso:
            if df.empty or today_iso not in set(df['date'].tolist()):
                snap = self.get_market_snapshot([code])
                row = snap.get(code)
                if row:
                    new_row = {k: row[k] for k in UNIFIED_COLS}
                    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                    df = df.sort_values('date').reset_index(drop=True)

        # 5) 类型规整
        if not df.empty:
            for c in ['open', 'high', 'low', 'close', 'volume', 'amount', 'turn', 'pctChg']:
                df[c] = pd.to_numeric(df[c], errors='coerce')
        return df

    def _fetch_kline_online(self, code: str, start: str, end: str) -> Optional[pd.DataFrame]:
        # baostock -> mootdx -> akshare，任一源成功即返回
        if not self._bs_logged_in:
            self._bs_logged_in = self.bs.login()
        df = self.bs.get_kline(code, start, end)
        if df is not None and not df.empty:
            return df

        if not self._mootdx_logged_in:
            self._mootdx_logged_in = self.mootdx.login()
        if self._mootdx_logged_in:
            df = self.mootdx.get_kline(code, start, end)
            if df is not None and not df.empty:
                return df

        if not self._ak_logged_in:
            self._ak_logged_in = self.ak.login()
        df = self.ak.get_kline(code, start, end)
        return df

    # ---------- sector / board ----------
    def get_sector_boards(self, board_type: str, force_refresh: bool = False) -> pd.DataFrame:
        try:
            df = self.em_sector.get_boards(board_type)
            if df is not None and not df.empty:
                return df
        except Exception:
            pass
        try:
            df = self.ths_sector.get_boards(board_type)
            if df is not None and not df.empty:
                return df
        except Exception:
            pass
        return pd.DataFrame(columns=['type', 'code', 'name'])

    def get_sector_members(self, board_type: str, board_name: str | None = None,
                           board_code: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
        try:
            return self.em_sector.get_members(board_type, board_name=board_name, board_code=board_code)
        except Exception:
            return pd.DataFrame(columns=['board_type', 'board_code', 'board_name', 'code', 'name'])

    def get_sector_kline(self, board_type: str, board_name: str | None,
                         board_code: str | None, start: str, end: str,
                         force_refresh: bool = False) -> pd.DataFrame:
        start_iso = _iso(start)
        end_iso = _iso(end)
        try:
            df = self.em_sector.get_kline(board_type, board_name=board_name, board_code=board_code,
                                          start=start_iso, end=end_iso)
            if df is not None and not df.empty:
                return df
        except Exception:
            pass
        try:
            df = self.ths_sector.get_kline(board_type, board_name=board_name, board_code=board_code,
                                           start=start_iso, end=end_iso)
            if df is not None and not df.empty:
                return df
        except Exception:
            pass
        return pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pctChg'])

    # ---------- new high (safety net) ----------
    def get_new_high_stocks(self, symbols=('历史新高', '一年新高')) -> set:
        try:
            return self.newhigh.get_new_high(symbols=symbols)
        except Exception:
            return set()

    # ---------- sync ----------
    def sync_kline_db(self, start: str, end: str, codes: Optional[List[str]] = None,
                      full: bool = False) -> dict:
        start = _iso(start)
        end = _iso(end)
        if codes is None:
            codes = self.get_universe()['code'].tolist()
        if not self._bs_logged_in:
            self._bs_logged_in = self.bs.login()
        synced = 0
        failed = []
        t0 = time.time()
        for i, code in enumerate(codes):
            real_start = start
            if not full:
                last = self.db.get_last_date(code)
                if last and last >= end:
                    continue
                if last:
                    real_start = (pd.Timestamp(last) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
            df = self._fetch_kline_online(code, real_start, end)
            if df is None or df.empty:
                failed.append(code)
                continue
            df = df.copy()
            df['code'] = code
            self.db.upsert_kline(df)
            synced += 1
            if (i + 1) % 200 == 0:
                print(f"  [sync] {i+1}/{len(codes)} synced={synced} failed={len(failed)} elapsed={time.time()-t0:.0f}s")
        self.db.meta_set('last_sync_date', end)
        return {'synced': synced, 'failed': len(failed), 'elapsed_s': round(time.time() - t0, 1)}


_router_singleton: Optional[Router] = None


def get_router() -> Router:
    global _router_singleton
    if _router_singleton is None:
        _router_singleton = Router()
    return _router_singleton

"""智能路由：根据请求类型选源、组合本地库 + 在线源。"""
from __future__ import annotations
from typing import Optional, List
from datetime import time as dt_time
import signal
import threading
import time
import re
import pandas as pd

from data_hub.sources.base import UNIFIED_COLS, SourceUnavailable, SourceCallTimeout
from data_hub.sources.sina import SinaSource
from data_hub.sources.tencent import TencentSource
from data_hub.sources.baostock import BaostockSource
from data_hub.sources.tencent_kline import TencentKlineSource
from data_hub.sources.mootdx_source import MootdxSource
from data_hub.sources.akshare import AkshareSource
from data_hub.sources.eastmoney_sector import EastmoneySectorSource
from data_hub.sources.tonghuashun_sector import TonghuashunSectorSource
from data_hub.sources.ths_newhigh import NewHighSource
from data_hub.store.kline_db import KlineDB

_SNAPSHOT_CACHE: dict = {}

# 统一日期格式：所有入参先归一化为 YYYY-MM-DD
_DATE_PAT = re.compile(r'^\d{8}$')

# 收盘时间。集合竞价 15:00 结束，快照时间戳实测在 15:34 左右，
# 取 15:00 作分界是保守的——15:00~15:34 之间落库的行可能仍不完整，
# 由「跳过规则只跳 last > end」的重取兜住。
_MARKET_CLOSE = dt_time(15, 0)


def _iso(d: str) -> str:
    """YYYYMMDD → YYYY-MM-DD，其他原样返回。"""
    if _DATE_PAT.match(d):
        return f'{d[:4]}-{d[4:6]}-{d[6:8]}'
    return d


def _now() -> pd.Timestamp:
    """当前时间。单独抽出来是为了让「是否已收盘」的判定可测。"""
    return pd.Timestamp.now()


def _is_unsettled(date_str: str) -> bool:
    """该日期的 K 线是否还没定型：当日且尚未收盘。

    盘中拿到的当日 K 线只含到当时为止的成交量，落库会被后续同步跳过而永久固化
    （2026-08-28 有 302 只票因此量偏小 1.01~9 倍）。这种行可以返回给调用方用于
    实时判断，但绝不能写进历史库。
    """
    now = _now()
    return date_str == now.strftime('%Y-%m-%d') and now.time() < _MARKET_CLOSE


def _drop_unsettled(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """剔除尚未定型的当日行；无该类行时原样返回，避免无谓拷贝。"""
    if df is None or df.empty or 'date' not in df.columns:
        return df
    mask = df['date'].astype(str).map(_is_unsettled)
    if not mask.any():
        return df
    return df[~mask]


def _try_login(source) -> bool:
    """登录单个数据源，失败只返回 False，不让异常向上冲。"""
    try:
        return bool(source.login())
    except Exception as e:
        print(f"  [{type(source).__name__}] login 失败: {type(e).__name__}: {e}")
        return False


class _SourceBreaker:
    """单个数据源的轮内熔断状态。仅在一轮 sync 内有效，不跨轮持久化。

    上游可用性是分钟级波动的，跨轮记忆只会让下一轮误判；跨轮的"死码"名单由
    KlineDB.failed_codes 负责，两者维度不同。
    """

    def __init__(self, name: str, fail_threshold: int = 20, probe_interval: int = 200,
                 slow_call_s: float = 3.0, recover_threshold: int = 3):
        self.name = name
        self.fail_threshold = fail_threshold
        self.probe_interval = probe_interval
        self.slow_call_s = slow_call_s
        self.recover_threshold = recover_threshold
        self.consecutive_fails = 0
        self.consecutive_successes = 0
        self.tripped = False
        self.calls_since_probe = 0
        self.skipped = 0
        self.probes = 0
        self.slow_calls = 0
        self.recovered = 0

    def should_skip(self) -> bool:
        """熔断期内是否跳过本次调用；到达试探间隔时放行一次（half_open）。"""
        if not self.tripped:
            return False
        self.calls_since_probe += 1
        if self.calls_since_probe >= self.probe_interval:
            self.calls_since_probe = 0
            self.probes += 1
            return False
        self.skipped += 1
        return True

    def on_success(self):
        self.consecutive_fails = 0
        self.consecutive_successes += 1
        if not self.tripped:
            return
        if self.consecutive_successes >= self.recover_threshold:
            print(f"  [breaker] {self.name} 连续 {self.consecutive_successes} 次成功，解除熔断")
            self.tripped = False
            self.calls_since_probe = 0
            self.recovered += 1
        else:
            # 试探成功但还不够判定恢复：把计数顶满，让紧邻的下一只票继续试探，
            # 形成一小段连续探测。真健康时几只票就能恢复；时好时坏的源
            # （baostock 的慢失败夹快速空返回）不会再靠单次侥幸解除熔断
            self.calls_since_probe = self.probe_interval

    def on_error(self):
        self.consecutive_successes = 0
        self.consecutive_fails += 1
        if not self.tripped and self.consecutive_fails >= self.fail_threshold:
            self.tripped = True
            self.calls_since_probe = 0
            print(f"  [breaker] {self.name} 连续失败 {self.consecutive_fails} 次，"
                  f"本轮熔断（每 {self.probe_interval} 只试探一次）")

    def on_call(self, elapsed: float, raised: bool):
        """按"是否抛异常 + 单次耗时"判定本次调用的健康度。

        只看异常不够——各源都在内部吞掉了异常（如 mootdx 静默超时后返回 None），
        2026-08-21 的同步就是全程 0 次异常却跑了 15.6 小时。正常成功调用是毫秒级，
        静默超时是秒级，所以耗时才是可靠信号。退市票的空返回是快速返回，
        不会被误判。
        """
        if elapsed >= self.slow_call_s:
            self.slow_calls += 1
        if raised or elapsed >= self.slow_call_s:
            self.on_error()
        else:
            self.on_success()

    def stats(self) -> dict:
        return {'tripped': self.tripped, 'skipped': self.skipped,
                'probes': self.probes, 'slow_calls': self.slow_calls,
                'recovered': self.recovered}


class _CallTimeout:
    """给单次取数调用套硬超时的上下文管理器。

    为什么必须有：熔断器只能评估**已完成**的调用。mootdx 不给 socket 设超时，
    半关闭的连接会让 recv 永久阻塞，这种调用连 on_call 都进不去，
    2026-08-29 的同步因此挂死 35 小时、累计 CPU 只有 8.38 秒。
    逐个源加超时行不通——mootdx 的 bars() 不收 timeout，akshare 内部
    大量端点不传 timeout，baostock 是自实现 socket 协议。只能在外层兜。

    SIGALRM 会打断阻塞的系统调用，Python 随即在调用点抛异常。
    限制：只能在主线程用，且 Windows 没有 SIGALRM——不满足时静默退化为
    无超时，绝不能因为拿不到看门狗就让取数整体失败。
    """

    def __init__(self, seconds: float):
        self.seconds = seconds
        self.armed = False
        self._old = None

    def _fire(self, sig, frm):
        raise SourceCallTimeout(f'取数调用超过 {self.seconds:g}s 未返回')

    def __enter__(self):
        if self.seconds <= 0 or not hasattr(signal, 'SIGALRM'):
            return self
        if threading.current_thread() is not threading.main_thread():
            return self
        self._old = signal.signal(signal.SIGALRM, self._fire)
        signal.setitimer(signal.ITIMER_REAL, self.seconds)
        self.armed = True
        return self

    def __exit__(self, *exc):
        # 无条件恢复：调用体自己抛异常时也必须清掉 itimer 和 handler，
        # 否则闹钟会在后续任意位置炸开，污染全局信号状态
        if self.armed:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self._old)
            self.armed = False
        return False


class _Throttle:
    """单个数据源的最小请求间隔控制。

    2026-08-27/28 的封禁是重试风暴打出来的：每轮 5207 只票 × 最多 4 个源，
    无任何间隔地打同一个域名，腾讯 WAF 直接封 IP。节流把请求速率压到
    人类可解释的范围，代价是每轮多几分钟——相比封禁一整天完全值得。

    按源独立计时：腾讯被节流不该拖慢 baostock。
    """

    def __init__(self, min_interval_s: float = 0.1):
        self.min_interval_s = min_interval_s
        self._last_call = 0.0

    def wait(self):
        if self.min_interval_s <= 0:
            return
        gap = time.time() - self._last_call
        if gap < self.min_interval_s:
            time.sleep(self.min_interval_s - gap)
        self._last_call = time.time()


class Router:
    def __init__(self, min_request_interval_s: float = 0.3,
                 source_call_timeout_s: float = 30.0):
        self.sina = SinaSource()
        self.tencent = TencentSource()
        self.bs = BaostockSource()
        self.tx_kline = TencentKlineSource()
        self.mootdx = MootdxSource()
        self.ak = AkshareSource()
        self.em_sector = EastmoneySectorSource()
        self.ths_sector = TonghuashunSectorSource()
        self.newhigh = NewHighSource()
        self.db = KlineDB()
        self._bs_logged_in = False
        self._mootdx_logged_in = False
        self._ak_logged_in = False
        self.min_request_interval_s = min_request_interval_s
        self._throttles: dict = {}
        # 单次取数调用的硬超时上限。逐个源加超时行不通（第三方库内部不传 timeout），
        # 只能在取数层统一兜底，否则一个永不返回的调用能挂死整条流水线。
        self.source_call_timeout_s = source_call_timeout_s
        self._timeouts: dict = {}

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
                    # 盘中的当日行不落库，但下面第 4 步仍会把实时行拼进返回值
                    to_store = _drop_unsettled(online_in)
                    if to_store is not None and not to_store.empty:
                        self.db.upsert_kline(to_store)
                df = self.db.query_kline(code, start, end)
                if online_in is not None and not online_in.empty:
                    # 库里被守卫拦掉的当日行，补回到返回值里供实时判断使用
                    unsettled = online_in[online_in['date'].astype(str).map(_is_unsettled)]
                    if not unsettled.empty:
                        if df is None:
                            df = pd.DataFrame(columns=UNIFIED_COLS)
                        keep = [c for c in unsettled.columns if c in df.columns or df.empty]
                        df = pd.concat([df, unsettled[keep]], ignore_index=True)
                        df = df.drop_duplicates(subset=['date'], keep='last').sort_values('date')
                        df = df.reset_index(drop=True)

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

    def _kline_source_chain(self):
        """日K取数的降级链：腾讯HTTP日K(443端口，最稳) -> mootdx -> akshare -> baostock 兜底。

        每项为 (名称, 源对象, 登录态属性名或 None, 登录失败是否跳过该源)。
        mootdx 未登录成功时无法取数，故 gate=True；akshare/baostock 的 login
        只是可用性探测，失败也照常尝试，保持既有行为。
        """
        return [
            ('tencent',  self.tx_kline, None,                   False),
            ('mootdx',   self.mootdx,   '_mootdx_logged_in',    True),
            ('akshare',  self.ak,       '_ak_logged_in',        False),
            ('baostock', self.bs,       '_bs_logged_in',        False),
        ]

    def _ensure_login(self, src, attr: Optional[str]) -> bool:
        """按需登录并缓存登录态；无需登录的源直接返回 True。"""
        if attr is None:
            return True
        if not getattr(self, attr):
            setattr(self, attr, _try_login(src))
        return getattr(self, attr)

    def _throttle_for(self, name: str) -> _Throttle:
        t = self._throttles.get(name)
        if t is None:
            t = _Throttle(self.min_request_interval_s)
            self._throttles[name] = t
        return t

    def _fetch_kline_online(self, code: str, start: str, end: str,
                            breakers: Optional[dict] = None) -> Optional[pd.DataFrame]:
        # 每个源单独兜异常：单只票在某个源上解析失败只降级到下一个源，
        # 不能让异常冲出 sync_kline_db 的循环导致整轮同步中断。
        # breakers 为 None 时（如按需补拉路径）行为与无熔断时完全一致。
        for name, src, login_attr, gate in self._kline_source_chain():
            br = breakers.get(name) if breakers else None
            if br is not None and br.should_skip():
                continue
            # 登录与取数是两个阶段，登录失败不计入熔断的连续失败计数
            if not self._ensure_login(src, login_attr) and gate:
                continue
            # 节流放在真正要发请求之前——被熔断跳过的源不付延迟成本，
            # 否则熔断省下的时间会被节流原封不动吃回去
            self._throttle_for(name).wait()
            t_call = time.time()
            try:
                with _CallTimeout(self.source_call_timeout_s):
                    df = src.get_kline(code, start, end)
            except SourceCallTimeout as e:
                # 硬超时：这次调用卡住了，不代表整个源已死，交给熔断器统计
                self._timeouts[name] = self._timeouts.get(name, 0) + 1
                print(f"  [{code}] {name} {e}，降级")
                if br is not None:
                    br.on_call(time.time() - t_call, raised=True)
                continue
            except SourceUnavailable:
                # 源自己已经打过告警，这里再打一遍会按票数刷屏（实测同一句印了 380+ 次）
                if br is not None:
                    br.on_call(time.time() - t_call, raised=True)
                continue
            except Exception as e:
                print(f"  [{code}] {name} 取数异常，降级: {type(e).__name__}: {e}")
                if br is not None:
                    br.on_call(time.time() - t_call, raised=True)
                continue
            # 耗时超阈值时即使拿到了数据也记为失败信号——取数正确性与源健康度
            # 是两件独立的事，数据照常使用
            if br is not None:
                br.on_call(time.time() - t_call, raised=False)
            if df is not None and not df.empty:
                return df
        return None

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
                      full: bool = False, skip_retry_gte: int = 5,
                      skip_window_days: int = 7, breaker_fail_threshold: int = 20,
                      breaker_probe_interval: int = 200,
                      breaker_slow_call_s: float = 3.0,
                      breaker_recover_threshold: int = 3,
                      mark_failed_max_fail_rate: float = 0.2,
                      early_stop_min_samples: int = 300,
                      early_stop_fail_rate: float = 0.9,
                      source_call_timeout_s: Optional[float] = None) -> dict:
        start = _iso(start)
        end = _iso(end)
        if source_call_timeout_s is not None:
            self.source_call_timeout_s = source_call_timeout_s
        self._timeouts = {}
        if codes is None:
            codes = self.get_universe()['code'].tolist()
        if not self._bs_logged_in:
            # 预登录也要套超时：baostock 不可用时 login 本身就要 ~75s（实测），
            # 极端情况下可能永久阻塞——那会在进入循环之前就挂死，
            # 取数层的看门狗根本来不及生效
            try:
                with _CallTimeout(self.source_call_timeout_s):
                    self._bs_logged_in = self.bs.login()
            except Exception as e:
                print(f"  [sync] baostock 预登录失败（不影响其他源）: {type(e).__name__}: {e}")
                self._bs_logged_in = False
        # 增量模式下跳过"死码"：连续失败达阈值且近期仍在失败的标的（多为退市/长期停牌）
        skip_set = set()
        if not full and skip_retry_gte > 0:
            fdf = self.db.get_failed(min_retry=skip_retry_gte)
            cutoff = (pd.Timestamp(end) - pd.Timedelta(days=skip_window_days)).strftime('%Y-%m-%d')
            skip_set = {r.code for r in fdf.itertuples() if str(r.updated_at)[:10] >= cutoff}
            if skip_set:
                print(f"  [sync] 跳过死码 {len(skip_set)} 只（retry_cnt>={skip_retry_gte} 且 {skip_window_days} 日内仍失败）")
        # 源级熔断：每轮新建，不跨轮持久化。与上面的死码名单是两个维度——
        # skip_set 记"这只票取不到"，breaker 记"这个源现在不通"。
        breakers = {name: _SourceBreaker(name, fail_threshold=breaker_fail_threshold,
                                        probe_interval=breaker_probe_interval,
                                        slow_call_s=breaker_slow_call_s,
                                        recover_threshold=breaker_recover_threshold)
                    for name, _, _, _ in self._kline_source_chain()}
        synced = 0
        failed = []
        skipped_dead = 0
        skipped_unsettled = 0
        aborted = None
        t0 = time.time()
        for i, code in enumerate(codes):
            # 整轮早停：样本足够且失败率极高时，说明是上游整体不可用而非个股问题，
            # 继续跑完剩下几千只只会浪费几小时并把 IP 送进 WAF 名单。
            # 只统计真正尝试过的票（skipped_dead / 已是最新的不计入），避免稀释失败率。
            attempted_now = synced + len(failed)
            if (early_stop_min_samples > 0 and attempted_now >= early_stop_min_samples
                    and len(failed) / attempted_now > early_stop_fail_rate):
                aborted = (f'early_stop: 已尝试 {attempted_now} 只，失败率 '
                           f'{len(failed) / attempted_now:.1%} > {early_stop_fail_rate:.0%}，'
                           f'判定上游整体不可用，剩余 {len(codes) - i} 只跳过')
                print(f"  [sync] {aborted}")
                break
            if code in skip_set:
                skipped_dead += 1
                continue
            real_start = start
            if not full:
                last = self.db.get_last_date(code)
                # 只跳过「库里已有超过 end 的数据」的票。
                # 不能用 last >= end：盘中写入的 date==end 行只含到当时为止的成交量，
                # 收盘后若因此跳过，这条半截 K 线就被永久固化——2026-08-28 有 302 只
                # sh.600 的量因此偏小 1.01~9 倍，其中 17 只是历史选股标的。
                if last and last > end:
                    continue
                if last and last < end:
                    real_start = (pd.Timestamp(last) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                elif last:
                    # last == end：重取当天，起点就取 end 本身
                    real_start = end
            df = self._fetch_kline_online(code, real_start, end, breakers=breakers)
            if df is None or df.empty:
                # 仅累积，落库延后到轮末按整体失败率判定：连续失败可能是"这只票死了"，
                # 也可能是"上游挂了"，后者不该把全市场写进死码名单（会自锁）
                failed.append(code)
                continue
            df = df.copy()
            df['code'] = code
            # 盘中的当日行不落库：它只含到当时为止的成交量，写进去会被后续同步
            # 跳过而永久固化
            to_store = _drop_unsettled(df)
            if to_store is None or to_store.empty:
                skipped_unsettled += 1
                continue
            self.db.upsert_kline(to_store)
            self.db.clear_failed(code)  # 成功即清零，保持即时——这是自锁的唯一出口
            synced += 1
            if (i + 1) % 200 == 0:
                print(f"  [sync] {i+1}/{len(codes)} synced={synced} failed={len(failed)} "
                      f"skipped_dead={skipped_dead} elapsed={time.time()-t0:.0f}s")
        attempted = synced + len(failed)
        fail_rate = (len(failed) / attempted) if attempted else 0.0
        marked = 0
        if failed and fail_rate <= mark_failed_max_fail_rate:
            for code in failed:
                self.db.mark_failed(code, 'empty_from_all_sources')
            marked = len(failed)
        elif failed:
            print(f"  [sync] 失败率 {fail_rate:.1%} > {mark_failed_max_fail_rate:.0%}，"
                  f"判定为上游故障而非个股问题，本轮 {len(failed)} 只失败不计入 failed_codes")
        # 早停意味着这一轮没跑完，绝不能推进 last_sync_date——否则下次增量会
        # 从一个从未真正同步过的日期起算，中间的空洞永久留在库里
        if aborted is None:
            self.db.meta_set('last_sync_date', end)
        return {'synced': synced, 'failed': len(failed), 'skipped_dead': skipped_dead,
                'skipped_unsettled': skipped_unsettled,
                'fail_rate': round(fail_rate, 4), 'marked_failed': marked,
                'aborted': aborted,
                'timeouts': dict(self._timeouts),
                'breaker': {n: b.stats() for n, b in breakers.items()},
                'failed_codes': failed[:20], 'elapsed_s': round(time.time() - t0, 1)}


_router_singleton: Optional[Router] = None


def get_router() -> Router:
    global _router_singleton
    if _router_singleton is None:
        _router_singleton = Router()
    return _router_singleton

# -*- coding: utf-8 -*-
"""每日选股入口（与回测解耦）

流程：
  1. 全市场 stock_list（baostock）
  2. 当日成交额预筛（≥ min_amount，缓存 prefilter_amount_{date}.csv）
  3. 对预筛通过的票，拉近 60 天日线（stock_research.data_loader.fetch_ohlcv 已带 parquet 缓存）
  4. 仅判定"今日"信号：limit_up / gap_up / breakthrough
  5. feature_extractor.extract_features → recommender.score
  6. CSV 落盘 stock_research/output/daily_selections_{date}.csv

推荐星级权重表与 stock_research/recommender.py 共享，与 recommender_backtest 一致。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, time as dt_time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from quant_backtest.data import get_stock_list
from stock_research.feature_extractor import extract_features
from stock_research.recommender import score as recommender_score
from data_hub import api as hub


PREFILTER_CACHE_DIR = ROOT / 'stock_data' / 'cache'
OUTPUT_DIR = ROOT / 'stock_research' / 'output'
SELECTIONS_FILE = ROOT / 'stock_data' / 'selections.json'
PREFILTER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 预筛取数护栏。快照是 9 个批量请求，重试极便宜；baostock 兜底是 5207 次
# 逐票请求，2026-09-01 实测跑满要 4.5 小时且拿到 0 行，必须能早退。
SNAPSHOT_RETRIES = 3
SNAPSHOT_BACKOFF_S = 2.0
PREFILTER_MIN_SAMPLES = 200
PREFILTER_FAIL_RATE = 0.9


# ---------- 1. 当日成交额预筛 ----------
def _is_real_stock(code: str) -> bool:
    """仅保留真正的 A 股个股，排除指数/ETF/可转债等。
    保留：sh.60xxxx 主板、sh.68xxxx 科创板、
          sz.000/001/002/003 主板+中小板、sz.300/301 创业板。
    排除：sh.000xxx 上证指数、sh.5xxxxx ETF/基金、sh.9xxxxx B股、
          sz.39xxxx 深证指数、sz.1xxxxx LOF/ETF、sz.2xxxxx B股。
    """
    if code.startswith('sh.6'):
        return True
    if code.startswith('sz.00'):  # sz.000/001/002/003
        return True
    if code.startswith('sz.30'):  # sz.300/301，注意 sz.39 是指数
        return True
    return False


def _prefilter_cache_has_bad_zero_amount(cache_df: pd.DataFrame, end_date: str, min_amount: float) -> bool:
    """识别预筛缓存中异常的 0 成交额记录。

    历史盘后缓存如果把近期高成交股票写成 0，会导致候选池漏选。
    只用于判断缓存是否可信，不直接修改选股结果。
    """
    if cache_df is None or cache_df.empty or 'amount' not in cache_df.columns:
        return False
    zero_df = cache_df[cache_df['amount'].fillna(0) <= 0]
    if zero_df.empty:
        return False
    zero_ratio = len(zero_df) / max(1, len(cache_df))
    if zero_ratio > 0.01:
        print(f"[预筛] 缓存零成交额比例异常 {zero_ratio:.2%}（{len(zero_df)}/{len(cache_df)}），重新扫描")
        return True

    # 单只零值也可能造成漏选；逐只回查目标日当天到底有没有成交。
    #
    # 判据只能看「目标日当天」。原先用的是「近 5 日最高成交额」，那必然把
    # 真停牌股全部误判成坏缓存：停牌前成交额通常不低，于是整份缓存被删、
    # 全市场重扫一遍。2026-09-03 实测 6 只真停牌股（雪天盐业、有研硅、
    # ST萃华、香山股份、*ST元道、宇邦新材）就这样让预筛白跑了一遍。
    #
    # 真停牌的特征是「目标日无行，或目标日成交额为 0」；
    # 缓存真有问题的特征是「目标日 K 线明明有成交额，缓存里却记成 0」。
    for _, row in zero_df.head(80).iterrows():
        code = str(row.get('code', ''))
        name = str(row.get('name', ''))
        if not code:
            continue
        try:
            hist = hub.get_kline(code, end_date, end_date)
            if hist is None or hist.empty or 'amount' not in hist.columns:
                continue  # 目标日无行 -> 真停牌
            day_rows = hist[hist['date'] == end_date]
            if day_rows.empty:
                continue  # 同上
            day_amount = float(pd.to_numeric(day_rows.iloc[-1]['amount'], errors='coerce') or 0)
            if day_amount <= 0:
                continue  # 当日确实没有成交 -> 真停牌
            print(
                f"[预筛] 缓存疑似异常：{code} {name} 缓存 amount=0，"
                f"但 {end_date} K线成交额 {day_amount/1e8:.2f} 亿，重新扫描"
            )
            return True
        except Exception:
            continue
    return False


def prefilter_by_amount(stock_list, end_date: str, min_amount: float = 2.5e9):
    """对 stock_list 在 end_date 当日做成交额预筛（统一走 data_hub.api）。
    缓存：stock_data/cache/prefilter_amount_{end_date}.csv
    返回 [(code, name), ...]
    """
    today_str = pd.Timestamp.now().strftime('%Y-%m-%d')
    is_post_close = end_date == today_str and pd.Timestamp.now().time() >= dt_time(15, 0)
    if is_post_close:
        cache_path = PREFILTER_CACHE_DIR / f'prefilter_amount_{end_date}_final.csv'
    else:
        cache_path = PREFILTER_CACHE_DIR / f'prefilter_amount_{end_date}.csv'

    # 校验缓存完整性
    if cache_path.exists():
        try:
            cache_df = pd.read_csv(cache_path, dtype={'code': str, 'name': str, 'amount': float})
            if 'amount' in cache_df.columns and len(cache_df) > 0:
                valid_codes = {c for c, _ in stock_list}
                cached_codes = set(cache_df['code'].astype(str))
                covered = len(cached_codes & valid_codes)
                coverage = covered / max(1, len(valid_codes))
                if coverage < 0.95:
                    missing = len(valid_codes) - covered
                    print(f"[预筛] 缓存覆盖率不足 {coverage:.1%}（缺失 {missing}/{len(valid_codes)}），重新扫描")
                    cache_path.unlink(missing_ok=True)
                elif _prefilter_cache_has_bad_zero_amount(cache_df, end_date, min_amount):
                    cache_path.unlink(missing_ok=True)
                else:
                    kept = cache_df[cache_df['amount'] >= min_amount].sort_values('amount', ascending=False)
                    print(f"[预筛] 命中缓存 {cache_path.name}：覆盖率 {coverage:.1%}，{len(cache_df)} 只 → 阈值 {min_amount/1e8:.0f} 亿过滤后 {len(kept)} 只")
                    return list(zip(kept['code'].tolist(), kept['name'].tolist()))
            else:
                print(f"[预筛] 缓存损坏/为空，重新扫描")
                cache_path.unlink()
        except Exception as e:
            print(f"[预筛] 缓存读取失败: {e}，重新扫描")
            cache_path.unlink(missing_ok=True)

    # 优先走 data_hub 实时快照（Sina，全市场 ~1.5s）。
    # 不再要求 end_date == today：快照返回的是行情自带日期，收盘后到次日
    # 开盘前它持有的正是上一交易日的定型值，那个窗口补历史日期完全可用。
    # 实测对比：快照 9 个请求 ~1.5s，baostock 逐票兜底 5207 次要 4.5 小时。
    print(f"[预筛] 走 data_hub.get_market_snapshot ...")
    t0 = time.time()
    codes = [c for c, _ in stock_list]
    valid_codes = {c for c, _ in stock_list}
    rows = []
    for attempt in range(SNAPSHOT_RETRIES):
        snapshot = hub.get_market_snapshot(codes)
        rows = []
        stale = 0
        for bs_code, info in snapshot.items():
            if bs_code not in valid_codes:
                continue
            # 日期必须对得上。退市股的末次报价停在几个月前，
            # 盘后跑历史日期时快照里也可能是别的交易日——混进来就是错数据。
            if str(info.get('date')) != end_date:
                stale += 1
                continue
            if info.get('amount', 0) > 0:
                rows.append({'code': bs_code, 'name': info.get('name', ''),
                             'amount': info['amount']})
        if rows:
            break
        # 09-01 的实测：18:43 全源取不到，次日 08:10 同一端点秒出。
        # 重试成本只有 9 个请求，比掉进逐票兜底便宜几个数量级。
        print(f"[预筛] 快照第 {attempt+1}/{SNAPSHOT_RETRIES} 次为空"
              f"（日期不符 {stale} 只）")
        if attempt < SNAPSHOT_RETRIES - 1:
            time.sleep(SNAPSHOT_BACKOFF_S * (2 ** attempt))
    if rows:
        cache_df = pd.DataFrame(rows)
        cache_df.to_csv(cache_path, index=False)
        coverage = len(cache_df) / max(1, len(valid_codes))
        kept = cache_df[cache_df['amount'] >= min_amount].sort_values('amount', ascending=False)
        print(f"[预筛] data_hub 完成 {len(cache_df)} 只 / 覆盖率 {coverage:.1%} / "
              f"{time.time()-t0:.1f}s → 阈值 {min_amount/1e8:.0f} 亿过滤后 {len(kept)} 只")
        return list(zip(kept['code'].tolist(), kept['name'].tolist()))
    print("[预筛] 快照重试后仍为空，回退 baostock 单只查询")

    # 兜底：非今日日期 / Sina 不可用时走 baostock 逐只查询
    print(f"[预筛] {end_date} 当日成交额（首次扫描，结果将缓存）")
    import baostock as bs
    bs.login()
    rows = []
    cache_df = None
    aborted = None
    try:
        for i, (code, name) in enumerate(stock_list):
            # 兜底早停：与 sync_kline_db 同一套语义——样本够了且失败率极高，
            # 说明是上游整体不可用而非个股问题，继续跑完只是白耗几小时。
            attempted = i
            if attempted >= PREFILTER_MIN_SAMPLES:
                fail_rate = (attempted - len(rows)) / attempted
                if fail_rate > PREFILTER_FAIL_RATE:
                    aborted = (f'已尝试 {attempted} 只，失败率 {fail_rate:.1%} > '
                               f'{PREFILTER_FAIL_RATE:.0%}，判定上游整体不可用，'
                               f'剩余 {len(stock_list) - i} 只跳过')
                    print(f"  [预筛] {aborted}")
                    break
            for retry in range(3):
                try:
                    rs = bs.query_history_k_data_plus(
                        code, "date,amount",
                        start_date=end_date, end_date=end_date,
                        frequency="d", adjustflag="3",
                    )
                    drows = []
                    while rs.next():
                        drows.append(rs.get_row_data())
                    if not drows:
                        break
                    amount = float(drows[-1][1] or 0)
                    rows.append({'code': code, 'name': name, 'amount': amount})
                    break
                except Exception as e:
                    if retry == 2:
                        print(f"  [预筛] {code} 查询失败: {e}")
                    else:
                        try:
                            bs.logout()
                        except Exception:
                            pass
                        bs.login()
            if (i + 1) % 500 == 0:
                if rows:
                    pd.DataFrame(rows).to_csv(cache_path, index=False)
                print(f"  [预筛] 进度 {i+1}/{len(stock_list)}（已落盘 {len(rows)} 行）")
                try:
                    bs.logout()
                except Exception:
                    pass
                bs.login()
    finally:
        try:
            bs.logout()
        except Exception:
            pass
        cache_df = pd.DataFrame(rows)
        # 空结果绝不落盘。以前无条件 to_csv 会留下一个 1 字节的空缓存文件，
        # 下次靠"缓存为空"校验删掉才自愈——纯噪音。
        if rows:
            cache_df.to_csv(cache_path, index=False)
        else:
            cache_path.unlink(missing_ok=True)

    # 上游全挂时 rows 为空，pd.DataFrame([]) 是无列空表，直接取 'amount' 会 KeyError。
    # 此时应优雅返回 0 只候选，让 daily_select 正常产出空结果并触发推送——
    # 崩溃会让 run_daily.sh 判定 rc=1 跳过推送，反而收不到"今天上游挂了"的通知。
    if cache_df.empty or 'amount' not in cache_df.columns:
        print(f"[预筛] {end_date} 全市场取数均失败（0 行），上游可能整体不可用 → 0 只候选")
        return []

    kept = cache_df[cache_df['amount'] >= min_amount].sort_values('amount', ascending=False)
    print(f"[预筛] 完成 → 阈值 {min_amount/1e8:.0f} 亿过滤后 {len(kept)} 只（缓存 {cache_path.name}）")
    return list(zip(kept['code'].tolist(), kept['name'].tolist()))


# ---------- 2.5 数据完整性守卫 ----------
def _warn_completeness(today: str, codes=None, scope: str = '候选池'):
    """盘后模式检查 KlineDB 对当前选股范围的覆盖情况。"""
    try:
        from data_hub import api as hub
        if codes is None:
            codes = [c for c, _ in get_stock_list() if _is_real_stock(c)]
        codes = [c for c in codes if _is_real_stock(c)]
        if not codes:
            return
        report = hub.check_completeness(codes, today)
        missing_pct = report.get('missing_pct', 100)
        missing_count = report.get('missing_count', len(report.get('missing_codes', [])))
        total = report.get('total', len(codes))
        if missing_pct > 5:
            print(f"[警告] KlineDB {scope}缺失 {missing_pct:.1f}%（{missing_count}/{total} 只），"
                  f"缺失股票将自动回退在线数据源")
        shallow_count = report.get('shallow_count', 0)
        shallow_pct = report.get('shallow_pct', 0.0)
        if shallow_count > 0:
            sample = '、'.join(report.get('shallow_codes', [])[:10])
            print(f"[警告] KlineDB {scope}历史不足 {shallow_pct:.1f}%"
                  f"（{shallow_count}/{total} 只 < {report.get('min_rows')} 行），"
                  f"读取时将自动全量补拉；样例: {sample}")
    except Exception as e:
        print(f"[警告] 完整性检查失败: {e}")


# ---------- 2. 今日信号判定 ----------
def _board_limit_pct(code: str) -> float:
    """各板块涨停幅度（不含 ST）。
    科创板 sh.688 / 创业板 sz.30 → 20%
    北交所 bj.* → 30%
    其余主板/中小板 → 10%
    """
    if code.startswith('sh.688') or code.startswith('sz.30'):
        return 20.0
    if code.startswith('bj.'):
        return 30.0
    return 10.0


def detect_today_signal(code: str, hist: pd.DataFrame, today: str):
    """判定 hist 中 today 是否触发买入信号（与 quant_backtest/strategy.py 双门槛口径一致）。

    入选条件 = 条件1 AND 条件2：
      条件1（动量启动，任一即可）:
        - prev_limit_up    昨日涨停（pct_prev ≥ 9.9）
        - today_high_gain  今日大涨（pct > 9.5）
        - gap_up_with_gain 跳空高开 ≥2% 且涨幅 > 5%
      条件2（创新高，任一即可）:
        - new_100d_high     close > 过去 100 日最高
        - new_all_time_high close ≥ 历史最高

    再细化输出 signal_type：
      - one_word    一字涨停（按板块涨停幅度严格判定）
      - limit_up    普通涨停（达到涨停幅度但盘中曾打开）
      - gap         跳空突破
      - breakthrough 普通创新高
    返回 dict 或 None。
    """
    if hist is None or hist.empty:
        return None
    today_rows = hist[hist['date'] == today]
    if today_rows.empty:
        return None
    pre = hist[hist['date'] < today]
    if len(pre) < 100:
        return None

    today_row = today_rows.iloc[0]
    prev_row = pre.iloc[-1]
    pct = float(today_row['pctChg']) if pd.notna(today_row['pctChg']) else 0.0
    pct_prev = float(prev_row['pctChg']) if pd.notna(prev_row['pctChg']) else 0.0
    open_ = float(today_row['open'])
    high = float(today_row['high'])
    low = float(today_row['low'])
    close = float(today_row['close'])
    prev_close = float(prev_row['close'])

    # ---- 条件1：动量启动 ----
    prev_limit_up = pct_prev >= 9.9
    today_high_gain = pct > 9.5
    gap_pct = (open_ - prev_close) / prev_close * 100.0 if prev_close > 0 else 0.0
    gap_up_with_gain = gap_pct >= 2.0 and pct > 5.0
    cond1 = prev_limit_up or today_high_gain or gap_up_with_gain

    # ---- 条件2：创新高 ----
    pre100_high = float(pre.tail(100)['high'].max())
    all_time_high = float(pre['high'].max())
    new_100d_high = close > pre100_high
    new_all_time_high = close >= all_time_high
    cond2 = new_100d_high or new_all_time_high

    if not (cond1 and cond2):
        return None

    # ---- 涨停 / 一字涨停判定（按板块严格阈值）----
    limit_pct = _board_limit_pct(code)
    is_limit_up = (limit_pct - 0.3) <= pct <= (limit_pct + 0.5)
    is_one_word = False
    if is_limit_up and close > 0:
        rng = (high - low) / close
        gap_oc = abs(open_ - close) / close
        is_one_word = rng <= 0.001 and gap_oc <= 0.001

    # ---- signal_type 决定优先级 ----
    if is_one_word:
        primary = 'one_word'
    elif is_limit_up:
        primary = 'limit_up'
    elif gap_up_with_gain:
        primary = 'gap_up'
    else:
        primary = 'breakthrough'

    subtypes = []
    if prev_limit_up:
        subtypes.append('prev_limit_up')
    if today_high_gain:
        subtypes.append('today_high_gain')
    if gap_up_with_gain:
        subtypes.append('gap_up')
    if new_100d_high:
        subtypes.append('new_100d_high')
    if new_all_time_high:
        subtypes.append('new_all_time_high')

    return {
        'signal_type': primary,
        'signal_subtypes': '+'.join(subtypes),
        'is_limit_up': is_limit_up,
        'is_one_word': is_one_word,
        'price': close,
        'pct': pct,
        'amount': float(today_row['amount']),
    }


# ---------- 3. 主流程 ----------
def select(today: str, min_amount: float = 2.5e9, throttle: float = 0.02):
    """运行选股流程，返回 DataFrame。"""
    full_list = get_stock_list()
    full_list = [(c, n) for c, n in full_list if _is_real_stock(c)]
    print(f"[选股] 全市场（仅个股，排除指数/ETF）{len(full_list)} 只")

    candidates = prefilter_by_amount(full_list, today, min_amount=min_amount)
    candidates = [(c, n) for c, n in candidates if _is_real_stock(c)]
    _warn_completeness(today, [c for c, _ in candidates], scope='候选池')
    if not candidates:
        print("[选股] 预筛后为空，结束")
        return pd.DataFrame()

    # 新高榜安全网：把当日创新高、但被成交额预筛挡掉的票补入候选，避免漏选。
    # 接口异常降级为空集，不影响主流程。
    # 安全网补入的票同样须满足 min_amount 门槛，从预筛缓存中查实际成交额。
    cand_codes = {c for c, _ in candidates}
    try:
        nh = hub.get_new_high_stocks()
    except Exception:
        nh = set()
    if nh:
        # 从预筛缓存读成交额（_final 优先，否则用当日普通缓存）
        _amount_map: dict = {}
        for _cache_suffix in (f'prefilter_amount_{today}_final.csv',
                              f'prefilter_amount_{today}.csv'):
            _cp = PREFILTER_CACHE_DIR / _cache_suffix
            if not _cp.exists():
                continue
            try:
                _cdf = pd.read_csv(_cp, dtype={'code': str})
                _amount_map = dict(zip(_cdf['code'], _cdf['amount'].astype(float)))
            except Exception:
                pass
            # 只有真的读出成交额才停止找下一个候选文件。
            # 以前 break 无条件执行：一个损坏/空的 _final 缓存会让 _amount_map
            # 留空，于是下面「成交额不足不补入」形同废止，新高榜整张表被无条件
            # 放行。2026-09-01 实测因此多补入 11 只（候选 14 而非 3），
            # 其中最小的成交额只有 0.39 亿，远在 25 亿门槛之下。
            if _amount_map:
                break

        name_map = dict(full_list)
        extra = []
        for c in nh:
            if c not in name_map or c in cand_codes or not _is_real_stock(c):
                continue
            amt = _amount_map.get(c, None)
            if amt is not None and amt < min_amount:
                continue  # 成交额不足，不补入
            extra.append((c, name_map.get(c, '')))
        if extra:
            print(f"[安全网] 新高榜补入 {len(extra)} 只（绕过成交额预筛，成交额≥{min_amount/1e8:.0f}亿或无数据）")
            candidates = candidates + extra

    today_iso = pd.Timestamp.now().strftime('%Y-%m-%d')
    require_today = (today == today_iso)

    # 拉 ~ 220 个自然日（≈150 交易日），保证 PRE_DAYS=100 充足
    start_date = (datetime.strptime(today, '%Y-%m-%d') - pd.Timedelta(days=220)).strftime('%Y-%m-%d')

    rows = []
    skipped = {'no_signal': 0, 'no_hist': 0, 'no_features': 0}

    for i, (code, name) in enumerate(candidates):
        try:
            hist = hub.get_kline(code, start_date, today, require_today=require_today)
        except Exception as e:
            print(f"  [{code}] fetch 失败: {e}")
            skipped['no_hist'] += 1
            continue
        if hist is None or hist.empty:
            skipped['no_hist'] += 1
            continue

        sig = detect_today_signal(code, hist, today)
        if sig is None:
            skipped['no_signal'] += 1
            continue

        sample = {
            'code': code,
            'entry_date': today,
            'signal_type': sig['signal_type'],
            'is_limit_up': sig['is_limit_up'],
            'hist': hist,
        }
        feat = extract_features(sample)
        if feat is None:
            skipped['no_features'] += 1
            continue

        sc = recommender_score(feat)
        rows.append({
            'code': code,
            'name': name,
            'signal_type': sig['signal_type'],
            'signal_subtypes': sig['signal_subtypes'],
            'is_limit_up': bool(sig['is_limit_up']),
            'price': round(sig['price'], 2),
            'pct': round(sig['pct'], 2),
            'amount_yi': round(sig['amount'] / 1e8, 2),
            'score': round(sc['score'], 4),
            'star': sc['star'],
            **{k: round(v, 4) for k, v in sc['dims'].items()},
        })

        time.sleep(throttle)
        if (i + 1) % 50 == 0:
            print(f"  [选股] 进度 {i+1}/{len(candidates)} 已命中 {len(rows)}")

    print(f"[选股] 完成：候选 {len(rows)} | skip "
          f"no_signal={skipped['no_signal']} no_hist={skipped['no_hist']} no_features={skipped['no_features']}")

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).sort_values(['star', 'score'], ascending=[False, False]).reset_index(drop=True)
    return df


# ---------- 4. CSV 输出 ----------
def write_csv(df: pd.DataFrame, today: str):
    out_path = OUTPUT_DIR / f'daily_selections_{today}.csv'
    df.to_csv(out_path, index=False)
    print(f"[选股] CSV → {out_path}（{len(df)} 行）")

    latest = OUTPUT_DIR / 'daily_selections_latest.csv'
    try:
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        latest.symlink_to(out_path.name)
    except OSError:
        df.to_csv(latest, index=False)
    return out_path


# ---------- 5. 写入 selections.json + 刷新 tracker_report/index.html ----------
# tracker 端使用的 signal_type 词表：one_word / gap / breakthrough
_SIGNAL_TO_TRACKER = {
    'one_word': 'one_word',
    'limit_up': 'breakthrough',  # 普通涨停降级为"突破"标签（一字才显示一字涨停）
    'gap_up': 'gap',
    'breakthrough': 'breakthrough',
}


def update_selections_json(df: pd.DataFrame, today_iso: str):
    """将今日候选合并写入 stock_data/selections.json（key = YYYYMMDD）。
    schema 与 daily_tracker 保持一致：
        {"YYYYMMDD": {"scan_time": "...", "stocks": [{...}, ...]}}
    """
    import json
    today_key = today_iso.replace('-', '')
    data = {}
    if SELECTIONS_FILE.exists():
        try:
            with open(SELECTIONS_FILE, encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {}

    stocks = []
    if df is not None and not df.empty:
        for _, s in df.iterrows():
            sig = _SIGNAL_TO_TRACKER.get(s['signal_type'], 'breakthrough')
            price = float(s['price'])
            stocks.append({
                'code': s['code'],
                'name': s['name'],
                'price': price,
                'buy_price': price,
                'signal_type': sig,
                'is_limit_up': bool(s.get('is_limit_up', sig == 'one_word')),
                'pct_change': float(s['pct']),
                'amount': float(s['amount_yi']) * 1e8,
                'star': int(s.get('star', 0)),
                'score': float(s.get('score', 0)),
                'conditions': {},
            })

    data[today_key] = {
        'scan_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'stocks': stocks,
    }
    with open(SELECTIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[选股] selections.json 已更新（{today_key} → {len(stocks)} 只）")


def refresh_tracker_report():
    """调用现有 quant_backtest.tracker_report.generate_full_report 刷新总览页。"""
    try:
        from quant_backtest.tracker_report import generate_full_report
        generate_full_report()
    except Exception as e:
        print(f"[选股] 刷新 tracker_report 失败：{e}")



def main():
    parser = argparse.ArgumentParser(description='每日选股 + 推荐星级')
    parser.add_argument('--date', default=None, help='交易日 YYYY-MM-DD，默认今日')
    parser.add_argument('--min-amount', type=float, default=None, help='当日成交额下限，默认 25 亿')
    args = parser.parse_args()

    today = args.date or datetime.now().strftime('%Y-%m-%d')
    min_amount = args.min_amount if args.min_amount is not None else 2.5e9
    print(f"[daily_select] {today}  min_amount={min_amount/1e8:.0f}亿")

    df = select(today, min_amount=min_amount)
    if df.empty:
        print("[选股] 今日 0 只候选")
        empty = pd.DataFrame(columns=['code', 'name', 'signal_type', 'signal_subtypes',
                                      'price', 'pct', 'amount_yi', 'score', 'star'])
        write_csv(empty, today)
        update_selections_json(empty, today)
        refresh_tracker_report()
        return

    write_csv(df, today)
    update_selections_json(df, today)
    refresh_tracker_report()

    # 控制台摘要
    print("\n[Top 候选]")
    cols = ['code', 'name', 'signal_type', 'pct', 'amount_yi', 'star', 'score']
    print(df[cols].head(15).to_string(index=False))


if __name__ == '__main__':
    main()

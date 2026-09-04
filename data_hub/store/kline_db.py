"""SQLite 全市场日线本地库。"""
from __future__ import annotations
from pathlib import Path
import sqlite3
import threading
from typing import Optional, List
import pandas as pd

DB_PATH = Path(__file__).resolve().parents[2] / 'stock_data' / 'kline.db'

SCHEMA = """
CREATE TABLE IF NOT EXISTS kline (
    code     TEXT NOT NULL,
    date     TEXT NOT NULL,
    open     REAL,
    high     REAL,
    low      REAL,
    close    REAL,
    volume   REAL,
    amount   REAL,
    turn     REAL,
    pctChg   REAL,
    PRIMARY KEY (code, date)
);
CREATE INDEX IF NOT EXISTS idx_kline_code_date ON kline(code, date);
CREATE INDEX IF NOT EXISTS idx_kline_date ON kline(date);

CREATE TABLE IF NOT EXISTS universe (
    code TEXT PRIMARY KEY,
    name TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS failed_codes (
    code      TEXT PRIMARY KEY,
    last_err  TEXT,
    retry_cnt INTEGER DEFAULT 0,
    updated_at TEXT
);
"""


class KlineDB:
    _lock = threading.Lock()

    def __init__(self, path: Optional[Path] = None):
        self.path = path or DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self):
        c = sqlite3.connect(str(self.path), timeout=30)
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA synchronous=NORMAL')
        return c

    def _init_schema(self):
        with self._conn() as c:
            c.executescript(SCHEMA)
            self._migrate(c)

    def _migrate(self, c):
        """幂等迁移。ALTER TABLE 在列已存在时会报错，必须先查 table_info。"""
        cols = {r[1] for r in c.execute('PRAGMA table_info(kline)')}
        if 'amt_src' not in cols:
            # 记录 amount 的精度来源：'exact'（源直接返回成交额）/
            # 'approx'（均价×volume 估算）/ NULL（历史行，来源未知）。
            # NULL 必须按「可被覆盖」处理——若当成 exact，历史里那些
            # 腾讯写进去的近似值就再也刷不掉了。
            c.execute('ALTER TABLE kline ADD COLUMN amt_src TEXT')

    # -------- kline --------
    def upsert_kline(self, df: pd.DataFrame, amt_src: Optional[str] = None) -> int:
        """写入日 K 行。

        amt_src 标注本批 amount 的精度：'exact' / 'approx' / None（未知）。
        近似值不得覆盖已有的精确值——腾讯不返回成交额，amount 由 均价×volume
        估出，每次 daily_select 或生成报告触发按需补拉，就会把新浪/baostock
        的精确值改写成近似值。09-01/02/03 连续三天分别被改写 246 / 109 / 3221 行，
        偏差最大 4.63%，只能人工修，而快照补数在次日 09:00 就过窗口。
        其余字段（OHLC/volume/turn/pctChg）不受此限制，照常覆盖——
        近似只发生在 amount 上。
        """
        if df is None or df.empty:
            return 0
        cols = ['code', 'date', 'open', 'high', 'low', 'close',
                'volume', 'amount', 'turn', 'pctChg']
        df = df.copy()
        for c in cols:
            if c not in df.columns:
                df[c] = None
        df['amt_src'] = amt_src
        rows = df[cols + ['amt_src']].itertuples(index=False, name=None)
        with self._lock, self._conn() as c:
            c.executemany(
                "INSERT INTO kline "
                "(code,date,open,high,low,close,volume,amount,turn,pctChg,amt_src) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(code,date) DO UPDATE SET "
                "  open=excluded.open, high=excluded.high, low=excluded.low, "
                "  close=excluded.close, volume=excluded.volume, "
                "  turn=excluded.turn, pctChg=excluded.pctChg, "
                "  amount = CASE "
                "    WHEN excluded.amt_src = 'exact' THEN excluded.amount "
                "    WHEN kline.amt_src    = 'exact' THEN kline.amount "
                "    ELSE excluded.amount END, "
                "  amt_src = CASE "
                "    WHEN excluded.amt_src = 'exact' THEN 'exact' "
                "    WHEN kline.amt_src    = 'exact' THEN 'exact' "
                "    ELSE excluded.amt_src END",
                rows,
            )
            return c.total_changes

    def query_kline(self, code: str, start: str, end: str) -> pd.DataFrame:
        with self._conn() as c:
            df = pd.read_sql_query(
                "SELECT date,open,high,low,close,volume,amount,turn,pctChg "
                "FROM kline WHERE code=? AND date>=? AND date<=? ORDER BY date",
                c, params=(code, start, end),
            )
        return df

    def get_last_date(self, code: str) -> Optional[str]:
        with self._conn() as c:
            row = c.execute(
                "SELECT MAX(date) FROM kline WHERE code=?", (code,)
            ).fetchone()
        return row[0] if row and row[0] else None

    def list_codes(self) -> List[str]:
        with self._conn() as c:
            rows = c.execute("SELECT DISTINCT code FROM kline").fetchall()
        return [r[0] for r in rows]

    # -------- universe --------
    def upsert_universe(self, df: pd.DataFrame) -> int:
        if df is None or df.empty:
            return 0
        ts = pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')
        rows = [(r['code'], r['name'], ts) for _, r in df.iterrows()]
        with self._lock, self._conn() as c:
            c.executemany(
                "INSERT OR REPLACE INTO universe (code,name,updated_at) VALUES (?,?,?)",
                rows,
            )
            return len(rows)

    def get_universe(self) -> pd.DataFrame:
        with self._conn() as c:
            return pd.read_sql_query("SELECT code,name FROM universe ORDER BY code", c)

    # -------- failed_codes --------
    def mark_failed(self, code: str, err: str):
        ts = pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO failed_codes (code,last_err,retry_cnt,updated_at) "
                "VALUES (?,?,1,?) "
                "ON CONFLICT(code) DO UPDATE SET "
                "last_err=excluded.last_err, retry_cnt=retry_cnt+1, "
                "updated_at=excluded.updated_at",
                (code, (err or '')[:200], ts),
            )

    def clear_failed(self, code: str):
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM failed_codes WHERE code=?", (code,))

    def get_failed(self, min_retry: int = 1) -> pd.DataFrame:
        with self._conn() as c:
            return pd.read_sql_query(
                "SELECT code,last_err,retry_cnt,updated_at FROM failed_codes "
                "WHERE retry_cnt>=? ORDER BY retry_cnt DESC",
                c, params=(min_retry,),
            )

    # -------- meta --------
    def meta_set(self, key: str, value: str):
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO meta (key,value) VALUES (?,?)", (key, value))

    def meta_get(self, key: str) -> Optional[str]:
        with self._conn() as c:
            row = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def stats(self) -> dict:
        with self._conn() as c:
            n_codes = c.execute("SELECT COUNT(DISTINCT code) FROM kline").fetchone()[0]
            n_rows = c.execute("SELECT COUNT(*) FROM kline").fetchone()[0]
            min_d = c.execute("SELECT MIN(date) FROM kline").fetchone()[0]
            max_d = c.execute("SELECT MAX(date) FROM kline").fetchone()[0]
        return {'codes': n_codes, 'rows': n_rows, 'min_date': min_d, 'max_date': max_d}

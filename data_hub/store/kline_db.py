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

    # -------- kline --------
    def upsert_kline(self, df: pd.DataFrame) -> int:
        if df is None or df.empty:
            return 0
        cols = ['code', 'date', 'open', 'high', 'low', 'close',
                'volume', 'amount', 'turn', 'pctChg']
        df = df.copy()
        for c in cols:
            if c not in df.columns:
                df[c] = None
        rows = df[cols].itertuples(index=False, name=None)
        with self._lock, self._conn() as c:
            c.executemany(
                f"INSERT OR REPLACE INTO kline ({','.join(cols)}) "
                f"VALUES (?,?,?,?,?,?,?,?,?,?)",
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

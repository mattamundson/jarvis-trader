"""
JARVIS TRADER — Bar Persistence Repository
============================================
Reads/writes OHLCV bars from/to the market_data_bars SQLite table.
Schema is created by migration_024 in engine/database/migrations.py.

All writes use INSERT OR IGNORE — duplicate bars (same symbol+interval+ts_utc)
are silently skipped so repeat fetches are cheap and idempotent.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Default DB path: two levels up from this file → engine/data/jarvis_trader.db
_DEFAULT_DB_PATH: Path = Path(__file__).resolve().parent / "jarvis_trader.db"

# Normalised interval labels that match what MarketDataManager uses
_INTERVAL_ALIASES: dict[str, str] = {
    "1m": "1m", "5m": "5m", "15m": "15m",
    "1h": "1h", "4h": "4h", "1d": "1d",
}

_INSERT_SQL = """
    INSERT OR IGNORE INTO market_data_bars
        (symbol, interval, ts_utc, open, high, low, close, volume, source, fetched_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def save_bars(
    df: pd.DataFrame,
    symbol: str,
    interval: str,
    source: str,
    db_path: Optional[Path] = None,
) -> int:
    """Write OHLCV rows to market_data_bars. Returns count of new rows inserted.

    Expects df to have columns: timestamp, open, high, low, close, volume (volume optional).
    timestamp must be parseable by pd.to_datetime.
    Empty df is silently skipped (returns 0).
    """
    if df is None or df.empty:
        return 0
    required = {"timestamp", "open", "high", "low", "close"}
    if not required.issubset(df.columns):
        logger.debug("[bars_repo] save_bars skipped — missing columns (have: %s)", list(df.columns))
        return 0

    db = db_path or _DEFAULT_DB_PATH
    interval = _INTERVAL_ALIASES.get(interval, interval)
    fetched_at = _utcnow_iso()

    rows = []
    for _, row in df.iterrows():
        try:
            ts = pd.to_datetime(row["timestamp"])
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            ts_iso = ts.strftime("%Y-%m-%dT%H:%M:%S")
            rows.append((
                symbol.upper(),
                interval,
                ts_iso,
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                float(row["volume"]) if "volume" in df.columns and row["volume"] == row["volume"] else None,
                source,
                fetched_at,
            ))
        except Exception as exc:
            logger.debug("[bars_repo] skipping malformed row: %s", exc)
            continue

    if not rows:
        return 0

    # Write-time quality gate: screen out contaminated ticks (impossible bars,
    # range explosions, lone neighbour jumps, blocked sources) before persist.
    # Shadow by default (logs only); BAR_QUALITY_GATE_ENFORCE=1 drops the rows.
    from data.bar_quality_gate import apply_gate

    rows, _rejects = apply_gate(rows, symbol=symbol, interval=interval)
    if not rows:
        return 0

    try:
        conn = _connect(db)
        cur = conn.executemany(_INSERT_SQL, rows)
        conn.commit()
        inserted = cur.rowcount
        conn.close()
        logger.debug("[bars_repo] save_bars %s %s: %d rows offered, %d new", symbol, interval, len(rows), inserted)
        return max(inserted, 0)
    except Exception as exc:
        logger.warning("[bars_repo] save_bars failed for %s %s: %s", symbol, interval, exc)
        return 0


def load_bars(
    symbol: str,
    interval: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Load persisted bars in [start, end] window. start/end are ISO date strings (YYYY-MM-DD or full ISO).

    Returns DataFrame with columns: timestamp, open, high, low, close, volume, source.
    Returns empty DataFrame if table missing or no rows match.
    """
    db = db_path or _DEFAULT_DB_PATH
    if not db.exists():
        return pd.DataFrame()

    interval = _INTERVAL_ALIASES.get(interval, interval)
    params: list = [symbol.upper(), interval]
    where = "symbol = ? AND interval = ?"

    if start:
        where += " AND ts_utc >= ?"
        params.append(start)
    if end:
        where += " AND ts_utc <= ?"
        params.append(end)

    sql = f"""
        SELECT ts_utc AS timestamp, open, high, low, close, volume, source
        FROM market_data_bars
        WHERE {where}
        ORDER BY ts_utc
    """
    try:
        conn = _connect(db)
        df = pd.read_sql_query(sql, conn, params=params, parse_dates=["timestamp"])
        conn.close()
        return df
    except Exception as exc:
        logger.warning("[bars_repo] load_bars failed for %s %s: %s", symbol, interval, exc)
        return pd.DataFrame()


def latest_bar(
    symbol: str,
    interval: str,
    db_path: Optional[Path] = None,
) -> Optional[dict]:
    """Return the most recent persisted bar for symbol+interval, or None."""
    db = db_path or _DEFAULT_DB_PATH
    if not db.exists():
        return None

    interval = _INTERVAL_ALIASES.get(interval, interval)
    sql = """
        SELECT ts_utc AS timestamp, open, high, low, close, volume, source
        FROM market_data_bars
        WHERE symbol = ? AND interval = ?
        ORDER BY ts_utc DESC
        LIMIT 1
    """
    try:
        conn = _connect(db)
        row = conn.execute(sql, (symbol.upper(), interval)).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as exc:
        logger.warning("[bars_repo] latest_bar failed for %s %s: %s", symbol, interval, exc)
        return None

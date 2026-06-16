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

# ── Write-time sanity gate ────────────────────────────────────────────────────
# Added after the 2026-06 contamination incident: 2,550 MCL rows at the IB
# snapshot-initialization sentinel price (100.5) and 100 MES placeholder rows
# (close < 1000 vs a real ~6-7k market) sat in this table for ~3 months and
# poisoned every backtest that touched them ("PF 22" bad-tick harvesting).
# Every production writer funnels through save_bars, so this is the one choke
# point where implausible rows can be refused before they exist.

# IB snapshot paths emit O=H=L=C=100.5 flat bars while the quote is still
# initializing. 100.5 is the literal sentinel constant observed in all 2,550
# contaminated rows — a real flat bar at exactly this price across all four
# OHLC fields is vanishingly unlikely for any traded future.
_IB_SNAPSHOT_SENTINEL = 100.5

# Per-symbol plausible close bands, ~10x wide in both directions from 2026
# price levels so they never false-positive on real moves, while catching
# wrong-instrument / wrong-scale writes outright. Unknown symbols only get the
# generic checks.
_SANE_PRICE_BANDS: dict[str, tuple[float, float]] = {
    "MES": (500.0, 50_000.0),
    "ES": (500.0, 50_000.0),
    "MNQ": (1_000.0, 200_000.0),
    "NQ": (1_000.0, 200_000.0),
    "MGC": (400.0, 30_000.0),
    "GC": (400.0, 30_000.0),
    "MCL": (3.0, 500.0),
    "CL": (3.0, 500.0),
    "M2K": (200.0, 20_000.0),
}

# A close-to-close move beyond this fraction between consecutive bars in one
# batch (or vs the latest persisted bar when appending) is treated as a bad
# tick. Index/metal/energy futures do not move 50% bar-over-bar; the MCL
# 65 → 100.5 sentinel jump (+54%) and the MES 7,400 → 100.5 collapse (-98%)
# both trip this.
_MAX_CONSECUTIVE_JUMP = 0.50


def _row_rejection(symbol: str, o: float, h: float, low: float, c: float,
                   ref_close: Optional[float]) -> Optional[str]:
    """Return a rejection reason for an implausible bar, or None if sane."""
    for name, v in (("open", o), ("high", h), ("low", low), ("close", c)):
        if not (v == v) or v in (float("inf"), float("-inf")) or v <= 0:
            return f"non-positive/non-finite {name}={v}"
    if h < low:
        return f"high {h} < low {low}"
    if not (low <= o <= h) or not (low <= c <= h):
        return f"open/close outside [low, high] ({o}/{c} vs [{low}, {h}])"
    if o == h == low == c == _IB_SNAPSHOT_SENTINEL:
        return f"IB snapshot sentinel flat bar at {_IB_SNAPSHOT_SENTINEL}"
    band = _SANE_PRICE_BANDS.get(symbol)
    if band and not (band[0] <= c <= band[1]):
        return f"close {c} outside plausible band {band} for {symbol}"
    if ref_close is not None and ref_close > 0:
        jump = abs(c - ref_close) / ref_close
        if jump > _MAX_CONSECUTIVE_JUMP:
            return (
                f"close {c} is a {jump:.0%} jump vs reference {ref_close} "
                f"(max {_MAX_CONSECUTIVE_JUMP:.0%})"
            )
    return None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def _categorize_sanity_reason(reason: str) -> str:
    """Map a free-text _row_rejection reason to a machine category that lines up
    with bar_quality_gate's BarReject.reason values where the checks overlap."""
    r = reason.lower()
    if "sentinel" in r:
        return "IB_SENTINEL"
    if "plausible band" in r:
        return "PRICE_BAND"
    if "jump vs reference" in r:
        return "NEIGHBOR_JUMP"
    if "outside [low, high]" in r or "high" in r and "< low" in r:
        return "OHLC_LOGIC"
    if "non-positive" in r or "non-finite" in r:
        return "NONFINITE"
    return "OTHER"


def _record_rejections(
    symbol: str,
    interval: str,
    source: str,
    path: str,
    items: list[tuple[str, str]],
    db_path: Path,
) -> None:
    """Best-effort persist of rejection counts for dashboard observability.

    ``items`` is a list of (reason_category, sample_detail). Aggregates by
    category into one row per category with a count + first-seen sample. Never
    raises — a missing table (DB predating migration 039) or any write error is
    swallowed so the gate's primary job (refusing bad bars) is never affected.
    """
    if not items:
        return
    try:
        agg: dict[str, list] = {}
        for category, detail in items:
            slot = agg.setdefault(category, [0, detail])
            slot[0] += 1
        ts = _utcnow_iso()
        records = [
            (ts, symbol, interval, source, path, category, detail, count)
            for category, (count, detail) in agg.items()
        ]
        conn = _connect(db_path)
        try:
            conn.executemany(
                "INSERT INTO bar_quality_rejections "
                "(ts_utc, symbol, interval, source, path, reason, detail, count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                records,
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 — observability must never break writes
        logger.debug("[bars_repo] rejection recording skipped: %s", exc)


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
    sym = symbol.upper()

    parsed = []
    for _, row in df.iterrows():
        try:
            ts = pd.to_datetime(row["timestamp"])
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            ts_iso = ts.strftime("%Y-%m-%dT%H:%M:%S")
            vol = float(row["volume"]) if "volume" in df.columns and row["volume"] == row["volume"] else None
            parsed.append((
                ts_iso,
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                vol,
            ))
        except Exception as exc:
            logger.debug("[bars_repo] skipping malformed row: %s", exc)
            continue

    # Sanity gate: validate in timestamp order so the consecutive-jump check
    # compares true neighbours. The DB's latest bar only anchors the first row
    # when this batch appends after it — for backfills older than the latest
    # persisted bar there is no valid neighbour in the DB.
    parsed.sort(key=lambda r: r[0])
    ref_close: Optional[float] = None
    if parsed:
        prev = latest_bar(sym, interval, db_path=db)
        if prev and str(prev.get("timestamp", "")) < parsed[0][0]:
            try:
                ref_close = float(prev["close"])
            except (TypeError, ValueError):
                ref_close = None

    rows = []
    rejected: list[str] = []
    sanity_items: list[tuple[str, str]] = []
    for ts_iso, o, h, low, c, vol in parsed:
        reason = _row_rejection(sym, o, h, low, c, ref_close)
        if reason:
            rejected.append(f"{ts_iso}: {reason}")
            sanity_items.append((_categorize_sanity_reason(reason), reason))
            continue
        rows.append((sym, interval, ts_iso, o, h, low, c, vol, source, fetched_at))
        ref_close = c

    if rejected:
        logger.warning(
            "[bars_repo] sanity gate REJECTED %d/%d %s %s bar(s) from source=%s — "
            "first: %s%s",
            len(rejected), len(parsed), sym, interval, source,
            rejected[0],
            f" (+{len(rejected) - 1} more)" if len(rejected) > 1 else "",
        )
        _record_rejections(sym, interval, source, "sanity", sanity_items, db)

    if not rows:
        return 0

    # Write-time quality gate: screen out contaminated ticks (impossible bars,
    # range explosions, lone neighbour jumps, blocked sources) before persist.
    # Shadow by default (logs only); BAR_QUALITY_GATE_ENFORCE=1 drops the rows.
    from data.bar_quality_gate import apply_gate

    rows, _rejects = apply_gate(rows, symbol=symbol, interval=interval)
    if _rejects:
        _record_rejections(
            sym, interval, source, "gate",
            [(rj.reason, rj.detail) for rj in _rejects], db,
        )
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

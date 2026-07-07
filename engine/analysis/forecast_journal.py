"""
Forecast journal — persistence for the self-improving morning briefing.

One row per (trading date, symbol). The *forecast* side (levels + JARVIS's Read)
is written pre-open; the *outcome* side (actual OHLC + scores) is filled by the
evening scorer (Phase D). The calibrator (Phase E) reads accumulated rows.

Self-contained schema via CREATE TABLE IF NOT EXISTS (mirrors
engine/discord/storage.py) — no coupling to the central migration runner. A JSON
backup of each forecast is also written to data/morning_forecasts/<date>.json.

Display/journal only — nothing here is consumed by risk/ or order execution.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_ENGINE_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_DB_PATH = _ENGINE_DIR / "data" / "jarvis_trader.db"
_DEFAULT_JSON_DIR = _ENGINE_DIR / "data" / "morning_forecasts"

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS morning_forecast_journal (
    date            TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    forecast_ts     TEXT NOT NULL,
    levels_json     TEXT NOT NULL,
    read_json       TEXT,
    conviction      REAL,
    read_bias       TEXT,
    actual_open     REAL,
    actual_high     REAL,
    actual_low      REAL,
    actual_close    REAL,
    level_scores_json TEXT,
    read_score      REAL,
    read_brier      REAL,
    outcome_ts      TEXT,
    PRIMARY KEY (date, symbol)
);
"""


def _connect(db_path: Path | str | None) -> sqlite3.Connection:
    path = str(db_path or _DEFAULT_DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_journal_table(db_path: Path | str | None = None) -> None:
    """Create the journal table if absent. Idempotent."""
    conn = _connect(db_path)
    try:
        conn.executescript(_CREATE_SQL)
        conn.commit()
    finally:
        conn.close()  # explicit close — Windows holds the file lock otherwise


def upsert_forecast(
    date: str,
    symbol: str,
    levels: dict[str, Any],
    forecast_ts: str,
    read: Optional[dict[str, Any]] = None,
    db_path: Path | str | None = None,
) -> None:
    """Insert/update the forecast side of a (date, symbol) row.

    Outcome columns are left untouched on update so a re-run of the morning
    brief never clobbers an already-scored evening outcome.
    """
    init_journal_table(db_path)
    conviction = None
    read_bias = None
    if read:
        conviction = read.get("conviction")
        read_bias = read.get("bias")
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO morning_forecast_journal
                (date, symbol, forecast_ts, levels_json, read_json, conviction, read_bias)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date, symbol) DO UPDATE SET
                forecast_ts = excluded.forecast_ts,
                levels_json = excluded.levels_json,
                read_json   = excluded.read_json,
                conviction  = excluded.conviction,
                read_bias   = excluded.read_bias
            """,
            (
                date,
                symbol,
                forecast_ts,
                json.dumps(levels),
                json.dumps(read) if read is not None else None,
                conviction,
                read_bias,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def update_outcome(
    date: str,
    symbol: str,
    actual: dict[str, float],
    outcome_ts: str,
    level_scores: Optional[dict[str, Any]] = None,
    read_score: Optional[float] = None,
    read_brier: Optional[float] = None,
    db_path: Path | str | None = None,
) -> bool:
    """Fill the outcome side of an existing row (Phase D). Returns True if a row matched."""
    init_journal_table(db_path)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            """
            UPDATE morning_forecast_journal SET
                actual_open = ?, actual_high = ?, actual_low = ?, actual_close = ?,
                level_scores_json = ?, read_score = ?, read_brier = ?, outcome_ts = ?
            WHERE date = ? AND symbol = ?
            """,
            (
                actual.get("open"),
                actual.get("high"),
                actual.get("low"),
                actual.get("close"),
                json.dumps(level_scores) if level_scores is not None else None,
                read_score,
                read_brier,
                outcome_ts,
                date,
                symbol,
            ),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for k in ("levels_json", "read_json", "level_scores_json"):
        if d.get(k):
            try:
                d[k[:-5]] = json.loads(d[k])  # levels_json -> levels, etc.
            except (TypeError, ValueError):
                d[k[:-5]] = None
        else:
            d[k[:-5]] = None
    return d


def get_forecast(
    date: str, symbol: str, db_path: Path | str | None = None
) -> Optional[dict[str, Any]]:
    """Return one journal row as a dict (parsed JSON fields), or None."""
    init_journal_table(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM morning_forecast_journal WHERE date = ? AND symbol = ?",
            (date, symbol),
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def list_journal(
    start_date: str | None = None,
    end_date: str | None = None,
    db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Return journal rows in [start_date, end_date] (inclusive), oldest first."""
    init_journal_table(db_path)
    conn = _connect(db_path)
    try:
        sql = "SELECT * FROM morning_forecast_journal"
        params: list[Any] = []
        clauses = []
        if start_date:
            clauses.append("date >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("date <= ?")
            params.append(end_date)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY date ASC, symbol ASC"
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def write_json_backup(
    date: str, payload: dict[str, Any], json_dir: Path | str | None = None
) -> Path:
    """Write a JSON backup of the day's forecast bundle. Returns the file path."""
    out_dir = Path(json_dir or _DEFAULT_JSON_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{date}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path

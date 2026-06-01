"""
JARVIS TRADER — Engine Uptime Calculator
=========================================
Computes engine uptime percentage from the health_snapshots table over an
arbitrary UTC window.

Usage:
    from engine.scripts.health_uptime import compute_uptime
    result = compute_uptime(start_utc, end_utc)

Returns a dict:
    {
        "polls_total":     int,
        "polls_reachable": int,
        "uptime_pct":      float,   # 0.0 – 100.0
    }
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

_ENGINE_DIR = Path(__file__).resolve().parent.parent
_DB_PATH = _ENGINE_DIR / "data" / "jarvis_trader.db"


def compute_uptime(
    start_utc: datetime,
    end_utc: datetime,
    db_path: Path = _DB_PATH,
) -> dict:
    """
    Query health_snapshots for rows with ts_utc in [start_utc, end_utc) and
    return poll counts and uptime percentage.

    Note: G6 in backtest/roi_readiness.py uses pnl_snapshots row presence as a
    day-level uptime proxy.  This function provides intraday (5-min granularity)
    uptime and should be used as the source of truth once G6 is refactored.
    TODO: refactor roi_readiness._eval_g6_engine_uptime to call compute_uptime
    with a per-day trading-hours window instead of the pnl_snapshots proxy.
    """
    start_iso = start_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = end_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    if not Path(db_path).exists():
        return {"polls_total": 0, "polls_reachable": 0, "uptime_pct": 0.0}

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(reachable) AS reachable
            FROM health_snapshots
            WHERE ts_utc >= ? AND ts_utc < ?
            """,
            (start_iso, end_iso),
        )
        row = cur.fetchone()
    finally:
        conn.close()

    total = row[0] if row else 0
    reachable = int(row[1] or 0) if row else 0
    uptime_pct = (reachable / total * 100.0) if total > 0 else 0.0

    return {
        "polls_total": total,
        "polls_reachable": reachable,
        "uptime_pct": round(uptime_pct, 2),
    }

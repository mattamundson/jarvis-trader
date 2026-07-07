#!/usr/bin/env python3
"""
Initialize capital allocation table with $10,000 across futures instruments.

Runs migration_007 (creates the table if absent) then upserts the four
MES/MNQ/MGC/MCL rows.  Safe to run multiple times — idempotent.

Usage
-----
    cd C:\\Users\\mattm\\ThinkorSwim\\jarvis-trader\\engine
    python -m scripts.init_capital
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

TOTAL_CAPITAL: float = 10_000.0

ALLOCATIONS: list[dict] = [
    {
        "symbol": "MES",
        "market": "futures",
        "allocation": 4_000.0,
        "allocation_pct": 0.40,
        "notes": "Micro E-mini S&P 500 — primary trend-following vehicle",
    },
    {
        "symbol": "MNQ",
        "market": "futures",
        "allocation": 3_000.0,
        "allocation_pct": 0.30,
        "notes": "Micro E-mini Nasdaq-100 — tech/momentum overlay",
    },
    {
        "symbol": "MGC",
        "market": "futures",
        "allocation": 2_000.0,
        "allocation_pct": 0.20,
        "notes": "Micro Gold — safe-haven / risk-off hedge",
    },
    {
        "symbol": "MCL",
        "market": "futures",
        "allocation": 1_000.0,
        "allocation_pct": 0.10,
        "notes": "Micro WTI Crude Oil — commodity diversifier",
    },
]

# ── DB path resolution ────────────────────────────────────────────────────────

_CANDIDATE_PATHS: list[str] = [
    # Absolute path (works from any cwd)
    r"C:/Users/mattm/ThinkorSwim/jarvis-trader/data/jarvis_trader.db",
    # Relative — when run from engine/ directory
    "data/jarvis_trader.db",
    # Relative — when run from jarvis-trader/ root
    "data/jarvis_trader.db",
]


def _find_db() -> Path:
    """Return the first candidate DB path that already exists."""
    for candidate in _CANDIDATE_PATHS:
        p = Path(candidate)
        if p.exists():
            return p.resolve()

    # Fall back: resolve relative to this script's engine root
    engine_root = Path(__file__).parent.parent
    fallback = engine_root / "data" / "jarvis_trader.db"
    if fallback.exists():
        return fallback.resolve()

    # Last resort: use the absolute path even if the file doesn't exist yet
    # (the migration will create it)
    return Path(r"C:/Users/mattm/ThinkorSwim/jarvis-trader/data/jarvis_trader.db").resolve()


# ── Migration (inline — avoids import gymnastics when run standalone) ─────────

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS capital_allocation (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT    NOT NULL UNIQUE,
    market          TEXT    NOT NULL DEFAULT 'futures',
    allocation      REAL    NOT NULL DEFAULT 0.0,
    allocation_pct  REAL    NOT NULL DEFAULT 0.0,
    total_capital   REAL    NOT NULL DEFAULT 10000.0,
    notes           TEXT    DEFAULT '',
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now', 'utc')),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'utc'))
)
"""

_CREATE_INDEX_SQL = "CREATE INDEX IF NOT EXISTS idx_ca_market ON capital_allocation(market)"


def _ensure_table(conn: sqlite3.Connection) -> None:
    """Create capital_allocation table if it doesn't already exist."""
    conn.execute(_CREATE_TABLE_SQL)
    conn.execute(_CREATE_INDEX_SQL)
    conn.commit()


# ── Upsert logic ──────────────────────────────────────────────────────────────

_UPSERT_SQL = """
INSERT INTO capital_allocation
    (symbol, market, allocation, allocation_pct, total_capital, notes, updated_at)
VALUES
    (:symbol, :market, :allocation, :allocation_pct, :total_capital, :notes, :updated_at)
ON CONFLICT(symbol) DO UPDATE SET
    market          = excluded.market,
    allocation      = excluded.allocation,
    allocation_pct  = excluded.allocation_pct,
    total_capital   = excluded.total_capital,
    notes           = excluded.notes,
    updated_at      = excluded.updated_at
"""


def _upsert_allocations(conn: sqlite3.Connection) -> int:
    """Insert or replace all allocation rows.  Returns count of rows affected."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    rows_affected = 0
    for alloc in ALLOCATIONS:
        conn.execute(
            _UPSERT_SQL,
            {
                "symbol": alloc["symbol"],
                "market": alloc["market"],
                "allocation": alloc["allocation"],
                "allocation_pct": alloc["allocation_pct"],
                "total_capital": TOTAL_CAPITAL,
                "notes": alloc.get("notes", ""),
                "updated_at": now,
            },
        )
        rows_affected += 1
    conn.commit()
    return rows_affected


# ── Verification ──────────────────────────────────────────────────────────────


def _verify(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT symbol, market, allocation, allocation_pct, total_capital, notes, updated_at "
        "FROM capital_allocation ORDER BY allocation DESC"
    ).fetchall()
    return [dict(r) for r in rows]


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    db_path = _find_db()
    print(f"Database : {db_path}")

    # Validate total adds up
    total_check = sum(a["allocation"] for a in ALLOCATIONS)
    pct_check = sum(a["allocation_pct"] for a in ALLOCATIONS)
    if abs(total_check - TOTAL_CAPITAL) > 0.01:
        print(
            f"ERROR: allocations sum to ${total_check:,.2f}, expected ${TOTAL_CAPITAL:,.2f}",
            file=sys.stderr,
        )
        sys.exit(1)
    if abs(pct_check - 1.0) > 0.0001:
        print(
            f"ERROR: allocation_pct values sum to {pct_check:.4f}, expected 1.0000",
            file=sys.stderr,
        )
        sys.exit(1)

    # Open connection
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    try:
        # Ensure table exists (idempotent)
        _ensure_table(conn)
        print("Table    : capital_allocation — OK (created or already existed)")

        # Upsert rows
        count = _upsert_allocations(conn)
        print(f"Upserted : {count} rows")

        # Verify
        rows = _verify(conn)
        print()
        print(f"{'Symbol':<8} {'Market':<10} {'Allocation':>12} {'Pct':>6}  Notes")
        print("-" * 70)
        for r in rows:
            print(
                f"{r['symbol']:<8} {r['market']:<10} "
                f"${r['allocation']:>10,.2f} {r['allocation_pct']:>5.0%}  {r['notes']}"
            )
        print("-" * 70)
        total_alloc = sum(r["allocation"] for r in rows)
        total_pct = sum(r["allocation_pct"] for r in rows)
        print(f"{'TOTAL':<8} {'':<10} ${total_alloc:>10,.2f} {total_pct:>5.0%}")
        print()
        print(f"Total capital : ${TOTAL_CAPITAL:,.2f}")
        print(f"Rows in table : {len(rows)}")
        print("Done.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()

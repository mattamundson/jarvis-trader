"""
US-1703 — Migrate JSONL paper trades to SQLite.

Reads all trade records from engine/portfolio/trades.jsonl and inserts them
into the paper_trades table in engine/data/jarvis_trader.db.

Deduplication strategy: the JSONL file is append-only — each trade may appear
twice (once when opened, once when closed).  The migration keeps only the LAST
record per trade_id (the closed record supersedes the open record).

PnL recomputation: closed trades with NULL pnl have their pnl computed using
INSTRUMENT_MULTIPLIERS so every migrated closed record has a dollar value.

Usage (run AFTER US-1702 merges to avoid NULL pnl conflicts):
    cd engine
    .venv/Scripts/python scripts/migrate_json_to_sqlite.py

    # Dry-run (show what would be inserted, touch nothing):
    .venv/Scripts/python scripts/migrate_json_to_sqlite.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths — resolved relative to this file so the script works from any cwd
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_ENGINE_DIR = _SCRIPT_DIR.parent  # engine/
_JSONL_PATH = _ENGINE_DIR / "portfolio" / "trades.jsonl"
_DB_PATH = _ENGINE_DIR / "data" / "jarvis_trader.db"

# ---------------------------------------------------------------------------
# Contract multipliers — mirrors portfolio/tracker.py INSTRUMENT_MULTIPLIERS
# ---------------------------------------------------------------------------
INSTRUMENT_MULTIPLIERS: dict[str, float] = {
    "MCL": 100.0,
    "MNQ": 2.0,
    "MES": 5.0,
    "MGC": 10.0,
    "ES": 50.0,
    "NQ": 20.0,
    "CL": 1000.0,
    "GC": 100.0,
}
_DEFAULT_MULTIPLIER = 1.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("migrate_json_to_sqlite")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_pnl(record: dict) -> float | None:
    """
    Compute dollar P&L for a closed trade that has a NULL pnl field.

    Returns None if the record is missing required fields (open trade or
    incomplete data).
    """
    entry_price = record.get("entry_price")
    exit_price = record.get("exit_price")
    quantity = record.get("quantity")
    action = str(record.get("action") or "").lower()
    symbol = str(record.get("symbol") or "").upper()

    if entry_price is None or exit_price is None or quantity is None:
        return None

    multiplier = INSTRUMENT_MULTIPLIERS.get(symbol, _DEFAULT_MULTIPLIER)
    is_short = "sell" in action or "short" in action

    if is_short:
        return (float(entry_price) - float(exit_price)) * float(quantity) * multiplier
    return (float(exit_price) - float(entry_price)) * float(quantity) * multiplier


def _map_action_to_side(action: str) -> str:
    """Normalise JSONL 'action' field to SQLite 'side' column value."""
    a = action.lower()
    if "sell" in a or "short" in a:
        return "sell"
    return "buy"


def _load_jsonl(path: Path) -> dict[str, dict]:
    """
    Load all records from the JSONL file, keeping LAST record per trade_id.

    The JSONL is append-only so a closed trade has two entries; taking the
    last entry ensures we use the record that has exit_price / pnl populated.
    """
    if not path.exists():
        log.error("JSONL file not found: %s", path)
        return {}

    by_id: dict[str, dict] = {}
    raw_line_count = 0

    with path.open("r", encoding="utf-8") as fh:
        for line_num, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            raw_line_count += 1
            try:
                record = json.loads(line)
                trade_id = record.get("trade_id")
                if trade_id:
                    by_id[trade_id] = record  # last write wins
                else:
                    log.warning("Line %d: missing trade_id — skipped", line_num)
            except json.JSONDecodeError as exc:
                log.warning("Line %d: JSON parse error — skipped (%s)", line_num, exc)

    log.info(
        "JSONL: %d raw lines → %d unique trade_ids",
        raw_line_count,
        len(by_id),
    )
    return by_id


def _get_existing_trade_ids(conn: sqlite3.Connection) -> set[str]:
    """Return the set of trade_ids already present in paper_trades."""
    rows = conn.execute("SELECT trade_id FROM paper_trades").fetchall()
    return {r[0] for r in rows}


def _insert_trade(conn: sqlite3.Connection, record: dict, dry_run: bool) -> bool:
    """
    Insert a single trade record into paper_trades.

    Returns True if inserted, False on conflict / skip.
    """
    trade_id = record.get("trade_id")
    symbol = str(record.get("symbol") or "").upper()
    action = str(record.get("action") or "")
    side = _map_action_to_side(action)
    quantity = record.get("quantity")
    entry_price = record.get("entry_price")
    exit_price = record.get("exit_price")
    entry_time = record.get("entry_time")
    exit_time = record.get("exit_time")
    notes = record.get("notes") or ""
    is_open = record.get("is_open", exit_price is None)

    # Determine P&L — use existing value if present, otherwise recompute
    pnl = record.get("pnl")
    if pnl is None and not is_open:
        pnl = _compute_pnl(record)
        if pnl is not None:
            log.debug(
                "Recomputed pnl for %s: %.2f",
                str(trade_id)[:8],
                pnl,
            )

    # Map is_open → status string for SQLite 'status' column
    status = "open" if is_open else "closed"

    sql = """
        INSERT OR IGNORE INTO paper_trades
            (trade_id, symbol, side, quantity, entry_price, exit_price,
             entry_time, exit_time, pnl, status, notes)
        VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = (
        trade_id,
        symbol,
        side,
        float(quantity) if quantity is not None else None,
        float(entry_price) if entry_price is not None else None,
        float(exit_price) if exit_price is not None else None,
        entry_time,
        exit_time,
        float(pnl) if pnl is not None else None,
        status,
        notes,
    )

    if dry_run:
        log.info(
            "[DRY-RUN] would insert %s  %s  %s  pnl=%s  status=%s",
            str(trade_id)[:8],
            symbol,
            side,
            f"{pnl:.2f}" if pnl is not None else "NULL",
            status,
        )
        return True

    conn.execute(sql, params)
    return conn.execute("SELECT changes()").fetchone()[0] > 0  # 0 = ON CONFLICT IGNORE fired


# ---------------------------------------------------------------------------
# Main migration logic
# ---------------------------------------------------------------------------


def migrate(dry_run: bool = False) -> int:
    """
    Run the migration.  Returns the number of records inserted.
    """
    log.info("=== US-1703 JSONL → SQLite migration ===")
    log.info("Source : %s", _JSONL_PATH)
    log.info("Target : %s", _DB_PATH)
    if dry_run:
        log.info("MODE   : DRY-RUN (no writes)")

    # --- Load source records ---
    records = _load_jsonl(_JSONL_PATH)
    if not records:
        log.warning("No records found in JSONL — nothing to migrate.")
        return 0

    # --- Connect to SQLite ---
    if not _DB_PATH.exists():
        log.error("SQLite database not found: %s", _DB_PATH)
        log.error("Ensure US-1701 has run and SQLITE_DB_PATH points to the real DB.")
        sys.exit(1)

    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    existing_ids = _get_existing_trade_ids(conn)
    log.info("SQLite: %d existing trade_ids in paper_trades", len(existing_ids))

    inserted = 0
    skipped_duplicate = 0
    skipped_invalid = 0

    try:
        conn.execute("BEGIN")

        for trade_id, record in records.items():
            if trade_id in existing_ids:
                log.debug("Skipping duplicate trade_id: %s", trade_id[:8])
                skipped_duplicate += 1
                continue

            if not record.get("entry_price") or not record.get("symbol"):
                log.warning(
                    "Skipping invalid record %s — missing required fields",
                    str(trade_id)[:8],
                )
                skipped_invalid += 1
                continue

            was_inserted = _insert_trade(conn, record, dry_run=dry_run)
            if was_inserted:
                inserted += 1
            else:
                skipped_duplicate += 1

        if not dry_run:
            conn.commit()
            log.info("Committed %d records to SQLite.", inserted)
        else:
            conn.rollback()

    except Exception as exc:
        conn.rollback()
        log.error("Migration failed — rolled back: %s", exc)
        raise
    finally:
        conn.close()

    # --- Summary ---
    log.info("")
    log.info("=== Migration Summary ===")
    log.info("  Records read (unique trade_ids) : %d", len(records))
    log.info("  Records inserted                 : %d", inserted)
    log.info("  Records skipped (duplicate)      : %d", skipped_duplicate)
    log.info("  Records skipped (invalid)        : %d", skipped_invalid)
    if dry_run:
        log.info("  [DRY-RUN] No changes were written to disk.")

    return inserted


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="US-1703: Migrate engine/portfolio/trades.jsonl → SQLite paper_trades"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be inserted without writing to SQLite",
    )
    args = parser.parse_args()

    migrate(dry_run=args.dry_run)

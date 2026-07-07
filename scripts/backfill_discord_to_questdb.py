#!/usr/bin/env python
"""One-shot backfill: reads Discord tables from SQLite and writes to QuestDB.

Usage
-----
    python scripts/backfill_discord_to_questdb.py --table all
    python scripts/backfill_discord_to_questdb.py --table bot_signals --batch-size 500
    python scripts/backfill_discord_to_questdb.py --table corey_commentary --dry-run

Requirements
------------
- QuestDB must be running at QUESTDB_HOST:QUESTDB_PORT (default localhost:9000).
- engine/.env must exist with DB_PATH pointing to the SQLite database.
- Run from the jarvis-trader root directory.

This script does NOT run on commit and is NOT part of the engine startup.
Matt invokes it manually after starting QuestDB for the first time.

Idempotent: skips rows whose message_id is already present in the QuestDB table
by querying QuestDB before each batch.  Safe to re-run after a partial failure.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Iterator

# ---------------------------------------------------------------------------
# Path bootstrap — allow running from repo root without installing the package
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENGINE_DIR = _REPO_ROOT / "engine"
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Load .env so DB_PATH, QUESTDB_HOST, QUESTDB_PORT are available
try:
    from dotenv import load_dotenv

    load_dotenv(_ENGINE_DIR / ".env")
except ImportError:
    pass  # dotenv optional — rely on environment variables being set externally

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
QUESTDB_HOST = os.environ.get("QUESTDB_HOST", "localhost")
QUESTDB_PORT = os.environ.get("QUESTDB_PORT", "9000")
QUESTDB_BASE_URL = f"http://{QUESTDB_HOST}:{QUESTDB_PORT}"

DB_PATH = os.environ.get("DB_PATH", str(_ENGINE_DIR / "data" / "jarvis_trader.db"))

DEFAULT_BATCH_SIZE = 1000

TABLES = {
    "bot_signals": {
        "sqlite_table": "discord_bot_signals",
        "questdb_table": "discord_bot_signals_ts",
        "sqlite_cols": [
            "message_id",
            "timestamp",
            "symbol",
            "timeframe",
            "direction",
            "signal_type",
            "entry_price",
            "target1",
            "target2",
            "stop1",
            "stop2",
            "win_rate",
            "wins",
            "losses",
            "mfe",
            "mae",
            "rr",
            "gain",
            "draw",
            "net",
            "last_price",
            "source_channel",
        ],
        "ts_col": "timestamp",
        "id_col": "message_id",
    },
    "corey_commentary": {
        "sqlite_table": "discord_corey_commentary",
        "questdb_table": "discord_corey_commentary_ts",
        "sqlite_cols": ["message_id", "timestamp", "content", "channel", "author_id"],
        "ts_col": "timestamp",
        "id_col": "message_id",
    },
    "ib_reports": {
        "sqlite_table": "discord_ib_reports",
        "questdb_table": "discord_ib_reports_ts",
        "sqlite_cols": [
            "message_id",
            "timestamp",
            "symbol",
            "timeframe",
            "ib_open",
            "ib_high",
            "ib_low",
            "ib_close",
            "ib_range",
            "ibu50",
            "ibu100",
            "ibd50",
            "ibd100",
            "auction_context",
            "source_channel",
        ],
        "ts_col": "timestamp",
        "id_col": "message_id",
    },
    "daily_sentiment": {
        "sqlite_table": "discord_daily_sentiment",
        "questdb_table": "discord_daily_sentiment_ts",
        "sqlite_cols": [
            "date",
            "sentiment_score",
            "post_count",
            "source",
            "computed_at",
        ],
        "ts_col": "date",  # will be converted to midnight UTC timestamp
        "id_col": "date",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _esc(value) -> str:
    """Escape a value for embedding in a QuestDB SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def _ts_literal(iso_str: str | None) -> str:
    """Convert an ISO-8601 string to a QuestDB timestamp literal, or NULL."""
    if not iso_str:
        return "NULL"
    # Append midnight if only a date (YYYY-MM-DD)
    if "T" not in iso_str and " " not in iso_str and len(iso_str) == 10:
        iso_str = iso_str + "T00:00:00"
    cleaned = iso_str.replace("Z", "").replace(" ", "T").strip()
    if "." not in cleaned:
        cleaned = cleaned + ".000000"
    return f"'{cleaned}'"


def _fetch_existing_ids(
    client: httpx.Client, questdb_table: str, id_col: str
) -> set[str]:
    """Fetch the set of existing message_id / date values from QuestDB.

    Returns an empty set if the table doesn't exist yet (which is expected
    on first run — QuestDB will create the table on first INSERT).
    """
    sql = f"SELECT {id_col} FROM {questdb_table}"
    try:
        resp = client.get("/exec", params={"query": sql}, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        if "dataset" not in data:
            return set()
        return {str(row[0]) for row in data["dataset"] if row[0] is not None}
    except Exception:
        return set()  # table doesn't exist yet or other error — start fresh


def _sqlite_rows(db_path: str, table: str, cols: list[str]) -> Iterator[dict]:
    """Yield all rows from a SQLite table as dicts."""
    conn = sqlite3.connect(db_path)
    try:
        col_str = ", ".join(cols)
        cursor = conn.execute(f"SELECT {col_str} FROM {table} ORDER BY rowid ASC")
        for row in cursor:
            yield dict(zip(cols, row))
    finally:
        conn.close()


def _build_insert_sql(row: dict, cfg: dict) -> str:
    """Build a QuestDB INSERT SQL for one row based on table config."""
    questdb_table = cfg["questdb_table"]
    ts_col = cfg["ts_col"]
    cols = cfg["sqlite_cols"]

    # Build column list for QuestDB (ts is always first)
    qdb_cols = ["ts"] + [c for c in cols if c != ts_col]
    ts_value = _ts_literal(row.get(ts_col))

    values = [ts_value]
    for col in cols:
        if col == ts_col:
            continue
        if col == "computed_at":
            values.append(_ts_literal(row.get(col)))
        else:
            values.append(_esc(row.get(col)))

    return (
        f"INSERT INTO {questdb_table} ({', '.join(qdb_cols)}) "
        f"VALUES ({', '.join(values)});"
    )


def _backfill_table(
    client: httpx.Client,
    cfg: dict,
    db_path: str,
    batch_size: int,
    dry_run: bool,
) -> tuple[int, int, int]:
    """Backfill one table.  Returns (total, written, skipped)."""
    questdb_table = cfg["questdb_table"]
    sqlite_table = cfg["sqlite_table"]
    id_col = cfg["id_col"]

    print(f"\n[{sqlite_table}] -> [{questdb_table}]")

    if not dry_run:
        print(f"  Fetching existing IDs from QuestDB...", end=" ", flush=True)
        existing = _fetch_existing_ids(client, questdb_table, id_col)
        print(f"{len(existing):,} already present")
    else:
        existing = set()
        print("  DRY-RUN: skipping existing-ID check")

    total = 0
    written = 0
    skipped = 0
    batch: list[str] = []

    def _flush_batch():
        nonlocal written
        if dry_run or not batch:
            return
        # QuestDB exec endpoint: send each INSERT separately (no multi-statement
        # support in older builds). For performance, send them individually but
        # report progress per batch.
        for sql in batch:
            try:
                resp = client.get("/exec", params={"query": sql}, timeout=10.0)
                resp.raise_for_status()
                written += 1
            except Exception as exc:
                print(f"\n  WARNING: insert failed: {exc}")
        batch.clear()

    for row in _sqlite_rows(db_path, sqlite_table, cfg["sqlite_cols"]):
        total += 1
        row_id = str(row.get(id_col, ""))

        if row_id in existing:
            skipped += 1
        else:
            if dry_run:
                written += 1  # count as "would write" in dry-run
            else:
                batch.append(_build_insert_sql(row, cfg))

        if len(batch) >= batch_size:
            _flush_batch()

        if total % batch_size == 0:
            status = "DRY-RUN" if dry_run else f"written={written:,}"
            print(
                f"  Progress: {total:,} rows processed ({status}, skipped={skipped:,})"
            )

    _flush_batch()

    if dry_run:
        print(
            f"  DRY-RUN complete: {total:,} total, would write {written:,}, skip {skipped:,}"
        )
    else:
        print(f"  Done: {total:,} total, {written:,} written, {skipped:,} skipped")

    return total, written, skipped


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill Discord SQLite tables to QuestDB time-series shadow tables.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--table",
        choices=list(TABLES.keys()) + ["all"],
        default="all",
        help="Table to backfill (default: all)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        metavar="N",
        help=f"Rows per progress report (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report row counts without writing to QuestDB",
    )
    parser.add_argument(
        "--db-path",
        default=DB_PATH,
        help=f"Path to SQLite database (default: {DB_PATH})",
    )
    args = parser.parse_args()

    db_path = args.db_path
    if not Path(db_path).exists():
        print(f"ERROR: SQLite database not found at {db_path}")
        print("Set DB_PATH in engine/.env or pass --db-path explicitly.")
        sys.exit(1)

    print(f"QuestDB target : {QUESTDB_BASE_URL}")
    print(f"SQLite source  : {db_path}")
    print(f"Batch size     : {args.batch_size:,}")
    print(f"Dry-run        : {args.dry_run}")

    if not args.dry_run:
        # Sanity-check QuestDB connectivity before committing to a long run
        try:
            resp = httpx.get(
                f"{QUESTDB_BASE_URL}/exec", params={"query": "SELECT 1"}, timeout=5.0
            )
            resp.raise_for_status()
            print("QuestDB connection: OK\n")
        except Exception as exc:
            print(f"ERROR: Cannot reach QuestDB at {QUESTDB_BASE_URL}: {exc}")
            print("Start QuestDB first: docker run -p 9000:9000 questdb/questdb")
            sys.exit(1)
    else:
        print()

    selected = list(TABLES.keys()) if args.table == "all" else [args.table]

    grand_total = grand_written = grand_skipped = 0
    with httpx.Client(base_url=QUESTDB_BASE_URL, timeout=10.0) as client:
        for table_key in selected:
            cfg = TABLES[table_key]
            t, w, s = _backfill_table(
                client, cfg, db_path, args.batch_size, args.dry_run
            )
            grand_total += t
            grand_written += w
            grand_skipped += s

    print("\n" + "=" * 60)
    print(f"BACKFILL {'DRY-RUN ' if args.dry_run else ''}COMPLETE")
    print(f"  Total rows   : {grand_total:,}")
    print(f"  Written      : {grand_written:,}")
    print(f"  Skipped      : {grand_skipped:,}")
    if args.dry_run:
        print("\nRerun without --dry-run to execute the writes.")


if __name__ == "__main__":
    main()

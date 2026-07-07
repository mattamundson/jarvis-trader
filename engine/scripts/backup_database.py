"""
backup_database.py — SQLite backup for jarvis_trader.db.

Usage:
    python engine/scripts/backup_database.py [--db-path PATH] [--dest-dir DIR] [--retention-days N] [--dry-run]

Defaults:
    --db-path      engine/data/jarvis_trader.db   (relative to repo root)
    --dest-dir     ~/OneDrive/jarvis-trader-backups/
    --retention-days 30
"""

from __future__ import annotations

import argparse
import gzip
import logging
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB = _REPO_ROOT / "engine" / "data" / "jarvis_trader.db"
_DEFAULT_DEST = Path.home() / "OneDrive" / "jarvis-trader-backups"
_DEFAULT_RETENTION_DAYS = 30


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SQLite .backup of jarvis_trader.db")
    p.add_argument("--db-path", type=Path, default=_DEFAULT_DB,
                   help="Path to the source SQLite database")
    p.add_argument("--dest-dir", type=Path, default=_DEFAULT_DEST,
                   help="Destination directory for backups")
    p.add_argument("--retention-days", type=int, default=_DEFAULT_RETENTION_DAYS,
                   help="Delete backups older than this many days")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would happen without doing it")
    return p.parse_args()


def _utc_date_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def backup(
    db_path: Path,
    dest_dir: Path,
    retention_days: int,
    dry_run: bool = False,
) -> Path:
    """
    1. SQLite hot-backup using sqlite3.Connection.backup() → temp file
    2. Compress with gzip
    3. Prune files older than retention_days
    Returns the path to the created backup file.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Source database not found: {db_path}")

    dest_dir = dest_dir.expanduser()
    date_str = _utc_date_str()
    dest_file = dest_dir / f"jarvis_trader_{date_str}.db.gz"

    logger.info("Source:      %s (%.1f MB)", db_path, db_path.stat().st_size / 1_048_576)
    logger.info("Destination: %s", dest_file)

    if dry_run:
        logger.info("[DRY-RUN] Would create backup at %s", dest_file)
        logger.info("[DRY-RUN] Would prune backups older than %d days from %s", retention_days, dest_dir)
        return dest_file

    # Create destination dir if needed
    dest_dir.mkdir(parents=True, exist_ok=True)

    if dest_file.exists():
        logger.info("Backup already exists for today (%s) — overwriting", date_str)

    # Hot-backup to a temp file, then gzip it
    tmp_path = dest_dir / f"_tmp_jarvis_backup_{date_str}.db"
    try:
        src_conn = sqlite3.connect(str(db_path))
        try:
            dst_conn = sqlite3.connect(str(tmp_path))
            try:
                src_conn.backup(dst_conn, pages=256)
                logger.info("SQLite hot-backup complete (%.1f MB)", tmp_path.stat().st_size / 1_048_576)
            finally:
                dst_conn.close()
        finally:
            src_conn.close()

        # Compress
        with tmp_path.open("rb") as f_in, gzip.open(dest_file, "wb", compresslevel=9) as f_out:
            shutil.copyfileobj(f_in, f_out)

        compressed_mb = dest_file.stat().st_size / 1_048_576
        logger.info("Compressed to %.2f MB → %s", compressed_mb, dest_file)

    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    # Prune old backups
    _prune_old_backups(dest_dir, retention_days)

    return dest_file


def _prune_old_backups(dest_dir: Path, retention_days: int) -> None:
    """Delete jarvis_trader_*.db.gz files older than retention_days."""
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    pruned = 0
    for backup_file in sorted(dest_dir.glob("jarvis_trader_*.db.gz")):
        # Parse date from filename: jarvis_trader_YYYY-MM-DD.db.gz
        stem = backup_file.stem  # jarvis_trader_YYYY-MM-DD.db
        parts = stem.rsplit("_", 1)
        if len(parts) != 2:
            continue
        try:
            file_date = datetime.strptime(parts[1].rstrip(".db"), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if file_date < cutoff:
            backup_file.unlink()
            logger.info("Pruned old backup: %s", backup_file.name)
            pruned += 1
    if pruned:
        logger.info("Pruned %d backup(s) older than %d days", pruned, retention_days)
    else:
        logger.info("No backups to prune (retention: %d days)", retention_days)


def main() -> int:
    args = _parse_args()
    try:
        dest = backup(
            db_path=args.db_path,
            dest_dir=args.dest_dir,
            retention_days=args.retention_days,
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            logger.info("Backup complete: %s", dest)
        return 0
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1
    except Exception as exc:
        logger.exception("Backup failed: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())

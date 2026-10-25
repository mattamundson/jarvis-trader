"""
Database Backup Implementation
===============================

Provides crash-safe SQLite backups using the backup API with configurable
retention policy and async execution.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Retention policy constants. Each copy is a full snapshot (~0.45 GB as of
# 2026-10), so 30 days held ~13.5 GB on C: and helped fill the disk on
# 2026-10-25. Override with DB_BACKUP_RETENTION_DAYS.
DEFAULT_RETENTION_DAYS = 7
RETENTION_ENV_VAR = "DB_BACKUP_RETENTION_DAYS"
DEFAULT_BACKUP_DIR = "data/backups"


def _resolve_retention_days() -> int:
    """Return DB_BACKUP_RETENTION_DAYS if it is a positive integer, else the default.

    A malformed or non-positive value must never disable pruning, so it falls
    back to DEFAULT_RETENTION_DAYS with a warning instead of raising.
    """
    raw = os.getenv(RETENTION_ENV_VAR)
    if raw is None:
        return DEFAULT_RETENTION_DAYS
    try:
        days = int(raw.strip())
    except ValueError:
        days = 0
    if days < 1:
        logger.warning(
            f"Invalid {RETENTION_ENV_VAR}={raw!r}; using default {DEFAULT_RETENTION_DAYS}d"
        )
        return DEFAULT_RETENTION_DAYS
    return days


class DatabaseBackup:
    """
    Manages SQLite database backups with retention policy.

    Parameters
    ----------
    db_path : str
        Path to the database file to back up.
    backup_dir : str
        Directory where backups are stored. Defaults to ``data/backups``.
    retention_days : int, optional
        Number of days to keep backups. Defaults to ``DB_BACKUP_RETENTION_DAYS``
        if set to a positive integer, else 7.
    """

    def __init__(
        self,
        db_path: str = "data/jarvis_trader.db",
        backup_dir: str = DEFAULT_BACKUP_DIR,
        retention_days: Optional[int] = None,
    ) -> None:
        if retention_days is None:
            retention_days = _resolve_retention_days()
        engine_root = Path(__file__).parent.parent
        self._db_path = Path(db_path) if Path(db_path).is_absolute() else engine_root / db_path
        self._backup_dir = (
            Path(backup_dir) if Path(backup_dir).is_absolute() else engine_root / backup_dir
        )
        self._retention_days = retention_days
        self._lock = threading.Lock()
        self._last_backup_time: Optional[datetime] = None
        self._last_backup_size: Optional[int] = None
        self._backup_count = 0

        logger.info(
            f"DatabaseBackup initialised -- "
            f"db={self._db_path} backup_dir={self._backup_dir} "
            f"retention={retention_days}d"
        )

    def backup(self) -> Dict[str, Any]:
        """
        Perform a backup of the database using SQLite's backup API.

        Returns
        -------
        dict
            Status dict with keys: success, timestamp, backup_file, size_bytes,
            message.
        """
        with self._lock:
            try:
                self._backup_dir.mkdir(parents=True, exist_ok=True)

                # Generate timestamped filename
                now = datetime.utcnow()
                timestamp = now.strftime("%Y%m%d_%H%M%S")
                backup_file = self._backup_dir / f"paper_trades_{timestamp}.db"

                # Use SQLite backup API for crash-safe snapshot
                if not self._db_path.exists():
                    return {
                        "success": False,
                        "timestamp": now.isoformat(),
                        "message": f"Source database not found: {self._db_path}",
                    }

                source_conn = sqlite3.connect(str(self._db_path), timeout=30)
                backup_conn = sqlite3.connect(str(backup_file), timeout=30)

                try:
                    source_conn.backup(backup_conn)
                    backup_conn.commit()
                finally:
                    source_conn.close()
                    backup_conn.close()

                # Record backup metadata
                size_bytes = backup_file.stat().st_size
                self._last_backup_time = now
                self._last_backup_size = size_bytes
                self._backup_count += 1

                logger.info(
                    f"✅ Database backed up to {backup_file.name} " f"({size_bytes:,} bytes)"
                )

                return {
                    "success": True,
                    "timestamp": now.isoformat(),
                    "backup_file": backup_file.name,
                    "size_bytes": size_bytes,
                    "message": f"Backup successful: {backup_file.name}",
                }

            except Exception as e:
                logger.error(f"Backup failed: {e}", exc_info=True)
                return {
                    "success": False,
                    "timestamp": datetime.utcnow().isoformat(),
                    "message": f"Backup failed: {str(e)}",
                }

    def cleanup_old(self) -> Dict[str, Any]:
        """
        Delete backups older than the retention window.

        Returns
        -------
        dict
            Status dict with keys: deleted_count, deleted_files, message.
        """
        with self._lock:
            try:
                if not self._backup_dir.exists():
                    return {
                        "deleted_count": 0,
                        "deleted_files": [],
                        "message": "Backup directory does not exist.",
                    }

                cutoff = datetime.utcnow()
                from datetime import timedelta

                cutoff_delta = cutoff - timedelta(days=self._retention_days)

                deleted = []
                for backup_file in sorted(self._backup_dir.glob("paper_trades_*.db")):
                    try:
                        # Parse date from filename (paper_trades_YYYYMMDD_HHMMSS.db)
                        stem = backup_file.stem  # e.g. paper_trades_20200101_000000
                        parts = stem.split("_")
                        if len(parts) >= 4:
                            date_str = f"{parts[2]}_{parts[3]}"
                            file_date = datetime.strptime(date_str, "%Y%m%d_%H%M%S")
                        else:
                            file_date = datetime.fromtimestamp(backup_file.stat().st_mtime)
                        if file_date < cutoff_delta:
                            backup_file.unlink()
                            deleted.append(backup_file.name)
                            logger.info(f"🗑️ Deleted old backup: {backup_file.name}")
                    except Exception as e:
                        logger.warning(f"Failed to delete {backup_file.name}: {e}")

                return {
                    "deleted_count": len(deleted),
                    "deleted_files": deleted,
                    "message": f"Cleanup complete: deleted {len(deleted)} old backups.",
                }

            except Exception as e:
                logger.error(f"Cleanup failed: {e}", exc_info=True)
                return {
                    "deleted_count": 0,
                    "deleted_files": [],
                    "message": f"Cleanup failed: {str(e)}",
                }

    def get_status(self) -> Dict[str, Any]:
        """
        Return backup status and statistics.

        Returns
        -------
        dict
            Status dict with keys: last_backup_time, last_backup_size,
            backup_count, backup_dir, retention_days, available_backups.
        """
        with self._lock:
            try:
                available = []
                if self._backup_dir.exists():
                    for f in sorted(self._backup_dir.glob("paper_trades_*.db")):
                        stat = f.stat()
                        available.append(
                            {
                                "filename": f.name,
                                "size_bytes": stat.st_size,
                                "created_utc": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                            }
                        )

                return {
                    "last_backup_time": (
                        self._last_backup_time.isoformat() if self._last_backup_time else None
                    ),
                    "last_backup_size": self._last_backup_size,
                    "backup_count": self._backup_count,
                    "backup_dir": str(self._backup_dir),
                    "retention_days": self._retention_days,
                    "available_backups": available,
                }
            except Exception as e:
                logger.error(f"Status check failed: {e}", exc_info=True)
                return {
                    "last_backup_time": None,
                    "last_backup_size": None,
                    "backup_count": self._backup_count,
                    "backup_dir": str(self._backup_dir),
                    "retention_days": self._retention_days,
                    "available_backups": [],
                    "error": str(e),
                }


# -- Singleton factory --------------------------------------------------------

_backup_instance: Optional[DatabaseBackup] = None
_backup_lock = threading.Lock()


def get_backup_manager(
    db_path: Optional[str] = None,
    backup_dir: Optional[str] = None,
    retention_days: Optional[int] = None,
) -> DatabaseBackup:
    """
    Create (or return) the module-level DatabaseBackup singleton.

    Parameters
    ----------
    db_path : str, optional
        Path to database. Only used on first call.
    backup_dir : str, optional
        Backup directory. Only used on first call.
    retention_days : int, optional
        Retention window. Only used on first call.

    Returns
    -------
    DatabaseBackup
        The initialised singleton instance.
    """
    global _backup_instance
    with _backup_lock:
        if _backup_instance is None:
            kwargs: Dict[str, Any] = {}
            if db_path is not None:
                kwargs["db_path"] = db_path
            if backup_dir is not None:
                kwargs["backup_dir"] = backup_dir
            if retention_days is not None:
                kwargs["retention_days"] = retention_days
            _backup_instance = DatabaseBackup(**kwargs)
            logger.info("DatabaseBackup singleton created.")
        return _backup_instance


# -- Module-level async helpers -----------------------------------------------


async def run_nightly_backup(db_path: str) -> Dict[str, Any]:
    """
    Async wrapper: run backup + prune via the singleton manager.

    Parameters
    ----------
    db_path : str
        Path to the SQLite database file to back up.

    Returns
    -------
    dict
        Status dict with keys: status, path/error, timestamp, cleanup.
    """
    import asyncio

    manager = get_backup_manager(db_path=db_path)
    loop = asyncio.get_event_loop()
    backup_result = await loop.run_in_executor(None, manager.backup)
    cleanup_result = await loop.run_in_executor(None, manager.cleanup_old)

    if backup_result.get("success"):
        return {
            "status": "ok",
            "path": backup_result.get("backup_file"),
            "timestamp": backup_result.get("timestamp"),
            "size_bytes": backup_result.get("size_bytes"),
            "cleanup": cleanup_result,
        }
    return {
        "status": "error",
        "error": backup_result.get("message"),
        "timestamp": backup_result.get("timestamp"),
        "cleanup": cleanup_result,
    }


def get_backup_status() -> Dict[str, Any]:
    """
    Return backup status from the singleton manager.

    Returns
    -------
    dict
        Status dict with backup count, last backup info, and retention policy.
    """
    manager = get_backup_manager()
    raw = manager.get_status()
    last_backup = raw.get("available_backups", [])
    last = last_backup[-1] if last_backup else None
    return {
        "backup_count": len(last_backup),
        "last_backup": last.get("created_utc") if last else None,
        "last_backup_path": last.get("filename") if last else None,
        "retention_days": raw.get("retention_days", DEFAULT_RETENTION_DAYS),
        "backup_dir": raw.get("backup_dir"),
        "available_backups": last_backup,
    }

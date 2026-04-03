"""
JARVIS TRADER -- Database Backup Module
========================================

Automated nightly backups of the trading database with retention policy.

Design decisions
----------------
- Uses SQLite backup API (conn.backup()) for crash-safe snapshots
- Runs asynchronously in a thread executor to avoid blocking event loop
- Scheduled via APScheduler for reliability and auditability
- Keeps 30 daily backups; older backups are automatically deleted
- Backup files are timestamped: paper_trades_YYYYMMDD_HHMMSS.db
"""

from .db_backup import DatabaseBackup, get_backup_manager

__all__ = ["DatabaseBackup", "get_backup_manager"]

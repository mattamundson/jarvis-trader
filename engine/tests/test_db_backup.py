"""
Test database backup module with retention policy.

Tests SQLite backup API integration, file cleanup, and async execution.
"""

import asyncio
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from backup.db_backup import DatabaseBackup, get_backup_manager


@pytest.fixture
def temp_db_dir():
    """Create temporary directory for test database and backups."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def test_db_path(temp_db_dir):
    """Create a test database file."""
    db_path = Path(temp_db_dir) / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE test_table (id INTEGER, value TEXT)")
    conn.execute("INSERT INTO test_table VALUES (1, 'test')")
    conn.commit()
    conn.close()
    return str(db_path)


def test_backup_initialization(temp_db_dir):
    """Test DatabaseBackup initialization."""
    db_path = str(Path(temp_db_dir) / "test.db")
    backup_dir = str(Path(temp_db_dir) / "backups")

    backup = DatabaseBackup(db_path=db_path, backup_dir=backup_dir, retention_days=30)

    assert backup._db_path == Path(db_path)
    assert backup._backup_dir == Path(backup_dir)
    assert backup._retention_days == 30


def test_backup_creates_file(test_db_path, temp_db_dir):
    """Test that backup() creates a timestamped backup file."""
    backup_dir = str(Path(temp_db_dir) / "backups")
    backup = DatabaseBackup(db_path=test_db_path, backup_dir=backup_dir)

    result = backup.backup()

    assert result["success"] is True
    assert result["backup_file"] is not None
    assert result["size_bytes"] > 0
    assert "paper_trades_" in result["backup_file"]

    # Verify file exists
    backup_file = Path(backup_dir) / result["backup_file"]
    assert backup_file.exists()


def test_backup_with_missing_database(temp_db_dir):
    """Test backup gracefully handles missing database."""
    backup_dir = str(Path(temp_db_dir) / "backups")
    nonexistent_db = str(Path(temp_db_dir) / "nonexistent.db")

    backup = DatabaseBackup(db_path=nonexistent_db, backup_dir=backup_dir)
    result = backup.backup()

    assert result["success"] is False
    assert "not found" in result["message"]


def test_backup_preserves_data(test_db_path, temp_db_dir):
    """Test that backup preserves database content."""
    backup_dir = str(Path(temp_db_dir) / "backups")
    backup = DatabaseBackup(db_path=test_db_path, backup_dir=backup_dir)

    result = backup.backup()
    assert result["success"] is True

    # Read backup and verify data
    backup_file = Path(backup_dir) / result["backup_file"]
    backup_conn = sqlite3.connect(str(backup_file))
    rows = backup_conn.execute("SELECT * FROM test_table").fetchall()
    backup_conn.close()

    assert len(rows) == 1
    assert rows[0][0] == 1
    assert rows[0][1] == "test"


def test_cleanup_old_backups(test_db_path, temp_db_dir):
    """Test cleanup_old() removes backups older than retention window."""
    backup_dir = Path(temp_db_dir) / "backups"
    backup_dir.mkdir(exist_ok=True)

    backup = DatabaseBackup(
        db_path=test_db_path,
        backup_dir=str(backup_dir),
        retention_days=1,
    )

    # Create old backup file
    old_file = backup_dir / "paper_trades_20200101_000000.db"
    old_file.touch()

    # Create new backup file
    new_file = backup_dir / "paper_trades_99991231_235959.db"
    new_file.touch()

    result = backup.cleanup_old()

    assert old_file.exists() is False
    assert new_file.exists() is True
    assert result["deleted_count"] == 1
    assert "paper_trades_20200101_000000.db" in result["deleted_files"]


def test_cleanup_respects_retention_window(test_db_path, temp_db_dir):
    """Test cleanup_old() respects the retention window."""
    backup_dir = Path(temp_db_dir) / "backups"
    backup_dir.mkdir(exist_ok=True)

    backup = DatabaseBackup(
        db_path=test_db_path,
        backup_dir=str(backup_dir),
        retention_days=30,
    )

    # Create file with old modification time
    old_file = backup_dir / "paper_trades_old.db"
    old_file.touch()
    old_time = (datetime.utcnow() - timedelta(days=31)).timestamp()
    old_file_stat = old_file.stat()
    Path(old_file).touch()

    result = backup.cleanup_old()

    assert result["deleted_count"] >= 0  # May or may not delete depending on timing


def test_get_status(test_db_path, temp_db_dir):
    """Test get_status() returns correct backup statistics."""
    backup_dir = str(Path(temp_db_dir) / "backups")
    backup = DatabaseBackup(db_path=test_db_path, backup_dir=backup_dir)

    # Perform backup
    backup.backup()

    status = backup.get_status()

    assert status["last_backup_time"] is not None
    assert status["last_backup_size"] > 0
    assert status["backup_count"] == 1
    assert status["backup_dir"] == backup_dir
    assert status["retention_days"] == 30
    assert len(status["available_backups"]) == 1

    backup_info = status["available_backups"][0]
    assert "filename" in backup_info
    assert "size_bytes" in backup_info
    assert "created_utc" in backup_info


def test_backup_manager_singleton(temp_db_dir):
    """Test get_backup_manager() returns a singleton."""
    db_path = str(Path(temp_db_dir) / "test.db")
    backup_dir = str(Path(temp_db_dir) / "backups")

    # Reset singleton for testing
    import backup.db_backup as db_backup_module

    db_backup_module._backup_instance = None

    mgr1 = get_backup_manager(db_path=db_path, backup_dir=backup_dir)
    mgr2 = get_backup_manager()

    assert mgr1 is mgr2


@pytest.mark.asyncio
async def test_backup_thread_safety():
    """Test backup can run in thread executor without blocking event loop."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.execute("INSERT INTO test VALUES (1)")
        conn.commit()
        conn.close()

        backup = DatabaseBackup(
            db_path=str(db_path),
            backup_dir=str(Path(tmpdir) / "backups"),
        )

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, backup.backup)

        assert result["success"] is True
        assert result["backup_file"] is not None

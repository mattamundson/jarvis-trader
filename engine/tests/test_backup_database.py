"""Tests for scripts.backup_database — SQLite hot-backup + prune logic.

All tests use pytest's tmp_path for isolation; no real OneDrive path is touched.
"""

from __future__ import annotations

import gzip
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_engine = Path(__file__).parent.parent
if str(_engine) not in sys.path:
    sys.path.insert(0, str(_engine))

from scripts.backup_database import _prune_old_backups, backup

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(path: Path) -> Path:
    """Create a minimal SQLite database at path."""
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE t (x INTEGER)")
    con.execute("INSERT INTO t VALUES (42)")
    con.commit()
    con.close()
    return path


# ---------------------------------------------------------------------------
# backup()
# ---------------------------------------------------------------------------


class TestBackup:
    def test_raises_when_source_missing(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            backup(tmp_path / "nonexistent.db", tmp_path / "dest", retention_days=30)

    def test_dry_run_creates_no_files(self, tmp_path: Path):
        db = _make_db(tmp_path / "jarvis_trader.db")
        dest = tmp_path / "backups"
        result = backup(db, dest, retention_days=30, dry_run=True)
        assert not dest.exists() or not any(dest.iterdir())
        assert result.suffix == ".gz"

    def test_creates_gzip_file(self, tmp_path: Path):
        db = _make_db(tmp_path / "jarvis_trader.db")
        dest = tmp_path / "backups"
        result = backup(db, dest, retention_days=30)
        assert result.exists()
        assert result.suffix == ".gz"
        assert result.stat().st_size > 0

    def test_backup_is_valid_sqlite(self, tmp_path: Path):
        db = _make_db(tmp_path / "jarvis_trader.db")
        dest = tmp_path / "backups"
        result = backup(db, dest, retention_days=30)

        # Decompress and open as SQLite
        decompressed = tmp_path / "check.db"
        with gzip.open(result, "rb") as f_in, decompressed.open("wb") as f_out:
            f_out.write(f_in.read())

        con = sqlite3.connect(str(decompressed))
        row = con.execute("SELECT x FROM t").fetchone()
        con.close()
        assert row == (42,)

    def test_backup_idempotent_overwrites_today(self, tmp_path: Path):
        db = _make_db(tmp_path / "jarvis_trader.db")
        dest = tmp_path / "backups"
        r1 = backup(db, dest, retention_days=30)
        r2 = backup(db, dest, retention_days=30)
        assert r1 == r2
        files = list(dest.glob("*.gz"))
        assert len(files) == 1

    def test_creates_dest_dir_if_missing(self, tmp_path: Path):
        db = _make_db(tmp_path / "jarvis_trader.db")
        nested = tmp_path / "a" / "b" / "c"
        backup(db, nested, retention_days=30)
        assert nested.is_dir()

    def test_no_tmp_file_left_after_success(self, tmp_path: Path):
        db = _make_db(tmp_path / "jarvis_trader.db")
        dest = tmp_path / "backups"
        backup(db, dest, retention_days=30)
        tmp_files = list(dest.glob("_tmp_*"))
        assert tmp_files == []


# ---------------------------------------------------------------------------
# _prune_old_backups()
# ---------------------------------------------------------------------------


class TestPruneOldBackups:
    def _make_backup_file(self, dest: Path, date_str: str) -> Path:
        f = dest / f"jarvis_trader_{date_str}.db.gz"
        f.write_bytes(b"fake")
        return f

    def test_prunes_files_older_than_retention(self, tmp_path: Path):
        old_date = (datetime.now(timezone.utc) - timedelta(days=35)).strftime("%Y-%m-%d")
        f_old = self._make_backup_file(tmp_path, old_date)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        f_new = self._make_backup_file(tmp_path, today)

        _prune_old_backups(tmp_path, retention_days=30)

        assert not f_old.exists()
        assert f_new.exists()

    def test_keeps_files_within_retention(self, tmp_path: Path):
        recent = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
        f = self._make_backup_file(tmp_path, recent)
        _prune_old_backups(tmp_path, retention_days=30)
        assert f.exists()

    def test_ignores_non_matching_files(self, tmp_path: Path):
        other = tmp_path / "some_other_file.gz"
        other.write_bytes(b"fake")
        _prune_old_backups(tmp_path, retention_days=0)
        assert other.exists()

    def test_no_error_when_dir_is_empty(self, tmp_path: Path):
        _prune_old_backups(tmp_path, retention_days=30)

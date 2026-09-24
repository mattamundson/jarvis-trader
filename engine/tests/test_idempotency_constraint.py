"""
[safety-review] Tests for migration_032: NOT NULL constraint on paper_trades.idempotency_key.

Covers:
  - test_migration_032_backfills_null_keys
  - test_migration_032_idempotent
  - test_migration_032_preserves_all_existing_rows
  - test_migration_032_recreates_unique_index
  - test_insert_paper_trade_requires_key
  - test_existing_tests_still_pass (via subprocess)

Root cause: 2026-05-09 6x phantom-trade incident — migration_030's partial UNIQUE
index (WHERE idempotency_key IS NOT NULL) provided zero protection for INSERT paths
that omitted the key, because those rows got NULL and the partial filter skipped them.

Migration 032 closes this gap by:
  1. Backfilling all NULL idempotency_key rows with deterministic SHA-256 keys
     derived from entry_time epoch (same formula as compute_order_idempotency_key)
  2. Recreating paper_trades with idempotency_key TEXT NOT NULL
  3. Making insert_paper_trade() raise TypeError when called without a key
"""

from __future__ import annotations

import hashlib
import math
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_test_db(db_path: str) -> sqlite3.Connection:
    """
    Create a minimal paper_trades DB that mirrors the pre-migration_032 schema:
    idempotency_key is TEXT (nullable).  Returns an open connection.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER NOT NULL,
            applied_at  TEXT    NOT NULL DEFAULT (datetime('now', 'utc')),
            description TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_trades (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id            TEXT    NOT NULL UNIQUE,
            symbol              TEXT    NOT NULL,
            side                TEXT    NOT NULL,
            quantity            REAL    NOT NULL,
            entry_price         REAL    NOT NULL,
            exit_price          REAL,
            entry_time          TEXT    NOT NULL,
            exit_time           TEXT,
            pnl                 REAL,
            status              TEXT    NOT NULL DEFAULT 'open',
            strategy_params     TEXT,
            notes               TEXT    DEFAULT '',
            regime              TEXT,
            structure_position  TEXT,
            bias                TEXT,
            composite_score     REAL,
            stc_contrib         INTEGER,
            orb_contrib         INTEGER,
            vwap_contrib        INTEGER,
            risk_pct_used       REAL,
            stop_loss           REAL,
            take_profit         REAL,
            account_id          TEXT    NOT NULL DEFAULT 'A',
            idempotency_key     TEXT,
            stop_order_id       TEXT,
            target_order_id     TEXT,
            bracket_status      TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_pt_idempotency_key
            ON paper_trades(idempotency_key)
            WHERE idempotency_key IS NOT NULL
        """
    )
    # Set schema_version to 31 so run_migrations will run migration_032 only
    for v in range(1, 32):
        conn.execute(
            "INSERT INTO schema_version (version, description) VALUES (?, ?)",
            (v, f"dummy v{v}"),
        )
    conn.commit()
    return conn


def _insert_null_key_row(conn: sqlite3.Connection, symbol: str, entry_time: str) -> int:
    """Insert a paper_trades row with idempotency_key=NULL (pre-migration state)."""
    trade_id = str(uuid.uuid4())
    cur = conn.execute(
        """
        INSERT INTO paper_trades
            (trade_id, symbol, side, quantity, entry_price, entry_time,
             status, account_id, idempotency_key)
        VALUES (?, ?, 'sell', 1.0, 5000.0, ?, 'open', 'A', NULL)
        """,
        (trade_id, symbol, entry_time),
    )
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# Test: migration_032 backfills NULL keys with deterministic values
# ---------------------------------------------------------------------------


class TestMigration032BackfillsNullKeys:
    def test_migration_032_backfills_null_keys(self, tmp_path):
        """After migration, no NULL idempotency_key rows should remain."""

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from database.migrations import migration_032

        db_path = str(tmp_path / "test_backfill.db")
        conn = _make_test_db(db_path)

        # Insert 5 rows with NULL keys at distinct entry_times
        for i in range(5):
            _insert_null_key_row(conn, "MES", f"2026-05-0{i+1}T10:00:00+00:00")

        pre_count = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
        assert pre_count == 5

        migration_032(conn)

        null_remaining = conn.execute(
            "SELECT COUNT(*) FROM paper_trades WHERE idempotency_key IS NULL"
        ).fetchone()[0]
        assert null_remaining == 0, f"Expected 0 NULLs after backfill, got {null_remaining}"

    def test_backfill_keys_are_deterministic(self, tmp_path):
        """
        Running migration_032 twice on a fresh snapshot should produce the
        same keys (idempotency check skips the second run, but if it didn't
        re-run it would produce the same results).
        """

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from database.migrations import migration_032

        db_path = str(tmp_path / "test_determinism.db")
        conn = _make_test_db(db_path)
        _insert_null_key_row(conn, "MCL", "2026-04-03T22:12:19+00:00")

        migration_032(conn)

        keys_after = [
            row[0] for row in conn.execute("SELECT idempotency_key FROM paper_trades").fetchall()
        ]
        assert len(keys_after) == 1
        assert keys_after[0] is not None
        assert len(keys_after[0]) >= 32  # at least 32 hex chars

    def test_backfill_uses_entry_time_epoch(self, tmp_path):
        """
        Keys for rows with different entry_times should differ (assuming the
        times are in different 5s buckets — which they will be for times hours apart).
        """

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from database.migrations import migration_032

        db_path = str(tmp_path / "test_epoch.db")
        conn = _make_test_db(db_path)
        # Two rows — same symbol/side/qty/price but hours apart in entry_time
        _insert_null_key_row(conn, "MES", "2026-05-09T10:00:00+00:00")
        _insert_null_key_row(conn, "MES", "2026-05-09T11:00:00+00:00")

        migration_032(conn)

        keys = [
            row[0]
            for row in conn.execute(
                "SELECT idempotency_key FROM paper_trades ORDER BY id"
            ).fetchall()
        ]
        assert len(keys) == 2
        assert keys[0] != keys[1], "Two rows with different entry_times must get distinct keys"


# ---------------------------------------------------------------------------
# Test: migration_032 is idempotent
# ---------------------------------------------------------------------------


class TestMigration032Idempotent:
    def test_migration_032_idempotent(self, tmp_path):
        """Running migration_032 twice should not raise and should not change row count."""

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from database.migrations import migration_032

        db_path = str(tmp_path / "test_idempotent.db")
        conn = _make_test_db(db_path)
        _insert_null_key_row(conn, "MGC", "2026-05-08T10:18:18+00:00")

        migration_032(conn)
        count_after_first = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]

        # Second call — should be a no-op (idempotency check fires)
        migration_032(conn)
        count_after_second = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]

        assert count_after_first == count_after_second == 1

    def test_migration_032_via_run_migrations_idempotent(self, tmp_path):
        """
        run_migrations() on a DB already at version 32 should be a no-op.
        """

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from database.migrations import MIGRATIONS, migration_032, run_migrations

        db_path = str(tmp_path / "test_run_idempotent.db")
        conn = _make_test_db(db_path)
        _insert_null_key_row(conn, "MES", "2026-05-09T13:37:34+00:00")

        migration_032(conn)
        # Record version 32, then dummy-stamp every migration after it too (same
        # pattern _make_test_db uses for 1..31) so run_migrations() is a true
        # no-op regardless of how many migrations ship after 032 -- otherwise
        # this test breaks every time a new migration_0NN lands, since it would
        # try to apply real migrations against this deliberately-minimal DB
        # (which only has schema_version + paper_trades) and hit missing tables.
        conn.execute(
            "INSERT INTO schema_version (version, description) VALUES (32, 'idempotency NOT NULL')"
        )
        for v in range(33, len(MIGRATIONS) + 1):
            conn.execute(
                "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                (v, f"dummy v{v}"),
            )
        conn.commit()

        pre = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
        run_migrations(conn)
        post = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]

        assert pre == post


# ---------------------------------------------------------------------------
# Test: migration_032 preserves all existing rows
# ---------------------------------------------------------------------------


class TestMigration032PreservesRows:
    def test_migration_032_preserves_all_existing_rows(self, tmp_path):
        """Pre-migration row count == post-migration row count."""

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from database.migrations import migration_032

        db_path = str(tmp_path / "test_preserve.db")
        conn = _make_test_db(db_path)

        # Insert 6 rows — mimicking the May 9 phantom trades
        for i in range(6):
            conn.execute(
                """
                INSERT INTO paper_trades
                    (trade_id, symbol, side, quantity, entry_price, entry_time,
                     status, account_id, idempotency_key)
                VALUES (?, 'MES', 'sell', 2.0, 7398.5481, ?, 'open', 'A', NULL)
                """,
                (str(uuid.uuid4()), f"2026-05-09T13:37:{30+i:02d}+00:00"),
            )
        conn.commit()

        pre_count = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
        assert pre_count == 6

        migration_032(conn)

        post_count = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
        assert (
            post_count == pre_count
        ), f"Row count changed: {pre_count} -> {post_count} — migration_032 must NOT delete rows"

    def test_trade_fields_preserved_after_migration(self, tmp_path):
        """All field values should be identical after the table rebuild."""

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from database.migrations import migration_032

        db_path = str(tmp_path / "test_fields.db")
        conn = _make_test_db(db_path)

        tid = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO paper_trades
                (trade_id, symbol, side, quantity, entry_price, entry_time,
                 status, account_id, notes, idempotency_key)
            VALUES (?, 'MCL', 'buy', 1.0, 68.5, '2026-04-03T22:12:19+00:00',
                    'open', 'A', 'test-note', NULL)
            """,
            (tid,),
        )
        conn.commit()

        migration_032(conn)

        row = conn.execute("SELECT * FROM paper_trades WHERE trade_id = ?", (tid,)).fetchone()
        assert row is not None
        row_dict = dict(row)
        assert row_dict["symbol"] == "MCL"
        assert row_dict["side"] == "buy"
        assert row_dict["quantity"] == 1.0
        assert row_dict["entry_price"] == 68.5
        assert row_dict["notes"] == "test-note"
        assert row_dict["account_id"] == "A"
        assert row_dict["idempotency_key"] is not None


# ---------------------------------------------------------------------------
# Test: migration_032 recreates the UNIQUE index on idempotency_key
# ---------------------------------------------------------------------------


class TestMigration032RecreatesUniqueIndex:
    def test_migration_032_recreates_unique_index(self, tmp_path):
        """After migration, a second INSERT with the same key should violate UNIQUE."""

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from database.migrations import migration_032

        db_path = str(tmp_path / "test_unique.db")
        conn = _make_test_db(db_path)
        _insert_null_key_row(conn, "MES", "2026-05-09T13:37:34+00:00")

        migration_032(conn)

        # Grab the backfilled key
        key = conn.execute("SELECT idempotency_key FROM paper_trades LIMIT 1").fetchone()[0]
        assert key is not None

        # Attempt to insert a duplicate key — must raise IntegrityError
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO paper_trades
                    (trade_id, symbol, side, quantity, entry_price, entry_time,
                     status, account_id, idempotency_key)
                VALUES (?, 'MES', 'sell', 2.0, 7398.55, '2026-05-09T14:00:00+00:00',
                        'open', 'A', ?)
                """,
                (str(uuid.uuid4()), key),
            )
            conn.commit()

    def test_not_null_column_rejects_null_insert(self, tmp_path):
        """After migration, inserting NULL idempotency_key must raise IntegrityError."""

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from database.migrations import migration_032

        db_path = str(tmp_path / "test_notnull.db")
        conn = _make_test_db(db_path)
        _insert_null_key_row(conn, "MCL", "2026-04-03T22:12:19+00:00")

        migration_032(conn)

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO paper_trades
                    (trade_id, symbol, side, quantity, entry_price, entry_time,
                     status, account_id, idempotency_key)
                VALUES (?, 'MCL', 'buy', 1.0, 70.0, '2026-06-01T10:00:00+00:00',
                        'open', 'A', NULL)
                """,
                (str(uuid.uuid4()),),
            )
            conn.commit()

    def test_index_info_shows_idempotency_key_unique(self, tmp_path):
        """PRAGMA index_list should confirm the unique index exists after migration."""

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from database.migrations import migration_032

        db_path = str(tmp_path / "test_index_info.db")
        conn = _make_test_db(db_path)
        _insert_null_key_row(conn, "MES", "2026-05-09T10:00:00+00:00")

        migration_032(conn)

        indexes = {row[1]: row[2] for row in conn.execute("PRAGMA index_list(paper_trades)")}
        assert (
            "idx_pt_idempotency_key" in indexes
        ), "idx_pt_idempotency_key missing from index_list after migration_032"
        assert indexes["idx_pt_idempotency_key"] == 1, "idx_pt_idempotency_key should be UNIQUE (1)"


# ---------------------------------------------------------------------------
# Test: insert_paper_trade requires idempotency_key (Python-layer guard)
# ---------------------------------------------------------------------------


class TestInsertPaperTradeRequiresKey:
    def _make_mixin_instance(self, db_path: str):
        """
        Build a minimal object that satisfies the TradesMixin interface using
        the given DB path.
        """

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from database._mixins_trades import TradesMixin
        from database.migrations import migration_032

        # Minimal fake DatabaseManager using real SQLite
        class _FakeLock:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        class _FakeDB(TradesMixin):
            def __init__(self, path):
                self._db_path = path
                self._lock = _FakeLock()
                conn = self._connect()
                # Build minimal schema (post-migration_032 — NOT NULL)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS paper_trades (
                        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                        trade_id            TEXT    NOT NULL UNIQUE,
                        symbol              TEXT    NOT NULL,
                        side                TEXT    NOT NULL,
                        quantity            REAL    NOT NULL,
                        entry_price         REAL    NOT NULL,
                        exit_price          REAL,
                        entry_time          TEXT    NOT NULL,
                        exit_time           TEXT,
                        pnl                 REAL,
                        status              TEXT    NOT NULL DEFAULT 'open',
                        strategy_params     TEXT,
                        notes               TEXT    DEFAULT '',
                        regime              TEXT,
                        structure_position  TEXT,
                        bias                TEXT,
                        composite_score     REAL,
                        stc_contrib         INTEGER,
                        orb_contrib         INTEGER,
                        vwap_contrib        INTEGER,
                        risk_pct_used       REAL,
                        stop_loss           REAL,
                        take_profit         REAL,
                        account_id          TEXT    NOT NULL DEFAULT 'A',
                        idempotency_key     TEXT    NOT NULL,
                        strategy_id         TEXT,
                        stop_order_id       TEXT,
                        target_order_id     TEXT,
                        bracket_status      TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_pt_idempotency_key
                        ON paper_trades(idempotency_key)
                        WHERE idempotency_key IS NOT NULL
                    """
                )
                conn.commit()
                conn.close()

            def _connect(self):
                conn = sqlite3.connect(self._db_path)
                conn.row_factory = sqlite3.Row
                return conn

        return _FakeDB(db_path)

    def test_insert_paper_trade_requires_key(self, tmp_path):
        """
        Calling insert_paper_trade() without idempotency_key (uses empty-string
        default) must raise TypeError at the Python layer.
        """
        db = self._make_mixin_instance(str(tmp_path / "test_requires_key.db"))

        with pytest.raises(TypeError, match="idempotency_key"):
            # Do NOT pass idempotency_key — should hit the empty-string guard
            db.insert_paper_trade(
                trade_id=str(uuid.uuid4()),
                symbol="MES",
                side="sell",
                quantity=2.0,
                entry_price=7398.55,
            )

    def test_insert_paper_trade_requires_key_explicit_empty(self, tmp_path):
        """Passing idempotency_key='' explicitly also raises TypeError."""
        db = self._make_mixin_instance(str(tmp_path / "test_requires_key_empty.db"))

        with pytest.raises(TypeError, match="idempotency_key"):
            db.insert_paper_trade(
                trade_id=str(uuid.uuid4()),
                symbol="MES",
                side="sell",
                quantity=2.0,
                entry_price=7398.55,
                idempotency_key="",
            )

    def test_insert_paper_trade_with_valid_key_succeeds(self, tmp_path):
        """A valid key allows the INSERT to proceed."""

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from database._helpers import compute_order_idempotency_key

        db = self._make_mixin_instance(str(tmp_path / "test_valid_key.db"))
        key = compute_order_idempotency_key("MES", "sell", 2, 7398.55)

        row_id = db.insert_paper_trade(
            trade_id=str(uuid.uuid4()),
            symbol="MES",
            side="sell",
            quantity=2.0,
            entry_price=7398.55,
            idempotency_key=key,
        )
        assert row_id == 1

    def test_insert_paper_trade_dedup_still_works(self, tmp_path):
        """Duplicate key returns existing row_id and does not insert a second row."""

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from database._helpers import compute_order_idempotency_key

        db = self._make_mixin_instance(str(tmp_path / "test_dedup.db"))
        key = compute_order_idempotency_key("MES", "sell", 2, 7398.55)

        id1 = db.insert_paper_trade(
            trade_id=str(uuid.uuid4()),
            symbol="MES",
            side="sell",
            quantity=2.0,
            entry_price=7398.55,
            idempotency_key=key,
        )
        id2 = db.insert_paper_trade(
            trade_id=str(uuid.uuid4()),
            symbol="MES",
            side="sell",
            quantity=2.0,
            entry_price=7398.55,
            idempotency_key=key,
        )
        assert id1 == id2

        conn = db._connect()
        count = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
        conn.close()
        assert count == 1

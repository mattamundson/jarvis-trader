"""Tests for migration_042: strategy_id column on paper_trades."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from database._mixins_trades import _derive_strategy_id  # noqa: E402
from database.migrations import migration_042  # noqa: E402


def _make_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_trades (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id        TEXT    NOT NULL UNIQUE,
            symbol          TEXT    NOT NULL,
            side            TEXT    NOT NULL,
            quantity        REAL    NOT NULL,
            entry_price     REAL    NOT NULL,
            exit_price      REAL,
            entry_time      TEXT    NOT NULL,
            exit_time       TEXT,
            pnl             REAL,
            status          TEXT    NOT NULL DEFAULT 'open',
            strategy_params TEXT,
            notes           TEXT    DEFAULT ''
        )
        """
    )
    return conn


def _insert(conn: sqlite3.Connection, trade_id: str, params: str | None) -> None:
    conn.execute(
        """
        INSERT INTO paper_trades
            (trade_id, symbol, side, quantity, entry_price, entry_time, status, strategy_params)
        VALUES (?, 'MGC', 'buy', 1.0, 4000.0, '2026-08-01T00:00:00+00:00', 'closed', ?)
        """,
        (trade_id, params),
    )


class TestMigration042StrategyId:
    def test_adds_column_and_backfills_known_config_hash(self, tmp_path: Path) -> None:
        conn = _make_db(tmp_path / "t.db")
        _insert(
            conn,
            "t1",
            json.dumps({"decision_identity": {"config_hash": "a5282c8c1234"}}),
        )
        conn.commit()

        migration_042(conn)

        row = conn.execute(
            "SELECT strategy_id FROM paper_trades WHERE trade_id = 't1'"
        ).fetchone()
        assert row[0] == "MGC_trend_rv_filter_rank1"

    def test_backfills_unknown_config_hash_as_config_prefix(self, tmp_path: Path) -> None:
        conn = _make_db(tmp_path / "t.db")
        _insert(conn, "t1", json.dumps({"decision_identity": {"config_hash": "deadbeef99"}}))
        conn.commit()

        migration_042(conn)

        row = conn.execute(
            "SELECT strategy_id FROM paper_trades WHERE trade_id = 't1'"
        ).fetchone()
        assert row[0] == "config:deadbeef"

    def test_backfills_stark_signal_when_no_config_hash(self, tmp_path: Path) -> None:
        conn = _make_db(tmp_path / "t.db")
        _insert(conn, "t1", json.dumps({"stark_signal": "LONG_GAP_FILL"}))
        conn.commit()

        migration_042(conn)

        row = conn.execute(
            "SELECT strategy_id FROM paper_trades WHERE trade_id = 't1'"
        ).fetchone()
        assert row[0] == "LONG_GAP_FILL"

    def test_leaves_null_when_params_not_parseable(self, tmp_path: Path) -> None:
        conn = _make_db(tmp_path / "t.db")
        _insert(conn, "t1", None)
        _insert(conn, "t2", "not-json")
        conn.commit()

        migration_042(conn)

        rows = conn.execute(
            "SELECT strategy_id FROM paper_trades ORDER BY trade_id"
        ).fetchall()
        assert rows == [(None,), (None,)]

    def test_idempotent_on_second_run(self, tmp_path: Path) -> None:
        conn = _make_db(tmp_path / "t.db")
        _insert(conn, "t1", json.dumps({"stark_signal": "LONG_GAP_FILL"}))
        conn.commit()

        migration_042(conn)
        migration_042(conn)

        rows = conn.execute(
            "SELECT strategy_id FROM paper_trades WHERE trade_id = 't1'"
        ).fetchall()
        assert rows == [("LONG_GAP_FILL",)]
        # index exists once; second CREATE INDEX IF NOT EXISTS is a no-op
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_pt_strategy'"
        ).fetchall()
        assert len(indexes) == 1


class TestDeriveStrategyId:
    def test_known_hash(self) -> None:
        assert _derive_strategy_id({"decision_identity": {"config_hash": "a5282c8cX"}}) == (
            "MGC_trend_rv_filter_rank1"
        )

    def test_unknown_hash_becomes_config_prefix(self) -> None:
        assert _derive_strategy_id({"config_hash": "00112233aa"}) == "config:00112233"

    def test_signal_fallback(self) -> None:
        assert _derive_strategy_id({"stark_signal": "LONG_MOMENTUM"}) == "LONG_MOMENTUM"

    def test_dict_or_json_string(self) -> None:
        assert _derive_strategy_id('{"stark_signal": "SHORT"}') == "SHORT"

    def test_none_and_garbage(self) -> None:
        assert _derive_strategy_id(None) is None
        assert _derive_strategy_id(123) is None
        assert _derive_strategy_id("{{{") is None

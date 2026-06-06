"""Tests for Task 1 — execution-fidelity validation repair (migration 038) and
entry-slippage persistence.

Covers the phantom-column bug: proactive_validation_router._load_closed_trades
SELECTed paper_trades.slippage_ticks, a column no migration created, so the
SELECT raised `no such column` and the fidelity validation silently saw zero
closed trades (INSUFFICIENT_DATA forever). Migration 038 adds the column;
execution.ibkr_reconciler.persist_entry_slippage populates it from matched real
IB fills.

Self-contained: builds a temp DB via run_migrations (no app/conftest fixture).
"""
import sqlite3
import tempfile
from pathlib import Path

import pytest

from database.migrations import run_migrations
from execution.ibkr_reconciler import persist_entry_slippage

# The exact column list _load_closed_trades selects (the one that used to throw).
_LOAD_CLOSED_TRADES_SQL = """
    SELECT symbol, side, quantity, entry_price, exit_price,
           entry_time, exit_time, pnl, slippage_ticks
    FROM   paper_trades
    WHERE  symbol = ? AND status = 'closed' AND pnl IS NOT NULL
    ORDER  BY exit_time ASC
"""


@pytest.fixture()
def migrated_db(tmp_path: Path) -> str:
    db = str(tmp_path / "j.db")
    conn = sqlite3.connect(db)
    run_migrations(conn)
    conn.close()
    return db


def _cols(db: str, table: str) -> list[str]:
    conn = sqlite3.connect(db)
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    finally:
        conn.close()


def _seed_match(db: str) -> None:
    """One JARVIS BOT fill @5000.50 + matching buy paper_trade @5000.00
    (MES tick 0.25 -> 2.0 ticks), plus an untagged demo-seed fill to be excluded."""
    conn = sqlite3.connect(db)
    conn.execute(
        """INSERT INTO ibkr_fills (exec_id, account, symbol, side, quantity, price,
            fill_time, order_ref, imported_at)
           VALUES ('E1','DU1','MES','BOT',1,5000.50,'2026-06-04T15:00:05+00:00',
                   'JARVIS-abc','2026-06-04T15:01:00+00:00')"""
    )
    conn.execute(
        """INSERT INTO ibkr_fills (exec_id, account, symbol, side, quantity, price,
            fill_time, order_ref, imported_at)
           VALUES ('E2','DUP662235','MES','BOT',1,4999.00,'2026-06-04T15:00:03+00:00',
                   '','2026-06-04T15:01:00+00:00')"""
    )
    conn.execute(
        """INSERT INTO paper_trades (trade_id, symbol, side, quantity, entry_price,
            entry_time, status, idempotency_key)
           VALUES ('T1','MES','buy',1,5000.00,'2026-06-04T15:00:00+00:00','open','idem-T1')"""
    )
    conn.commit()
    conn.close()


def test_migration_038_adds_slippage_ticks(migrated_db: str):
    assert "slippage_ticks" in _cols(migrated_db, "paper_trades")


def test_load_closed_trades_select_no_longer_throws(migrated_db: str):
    conn = sqlite3.connect(migrated_db)
    try:
        # Pre-038 this raised sqlite3.OperationalError: no such column: slippage_ticks
        conn.execute(_LOAD_CLOSED_TRADES_SQL, ("MES",)).fetchall()
    finally:
        conn.close()


def test_migration_idempotent(migrated_db: str):
    conn = sqlite3.connect(migrated_db)
    try:
        run_migrations(conn)  # second run must not raise
        ver = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        assert ver >= 38
    finally:
        conn.close()


def test_persist_entry_slippage_converts_points_to_ticks(migrated_db: str):
    _seed_match(migrated_db)
    res = persist_entry_slippage(migrated_db, "MES")
    assert res["n_matched"] == 1
    assert res["n_persisted"] == 1
    conn = sqlite3.connect(migrated_db)
    try:
        slip = conn.execute(
            "SELECT slippage_ticks FROM paper_trades WHERE trade_id='T1'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert slip == pytest.approx(2.0)  # 0.50 pts / 0.25 tick


def test_persist_idempotent(migrated_db: str):
    _seed_match(migrated_db)
    persist_entry_slippage(migrated_db, "MES")
    res2 = persist_entry_slippage(migrated_db, "MES")
    assert res2["n_persisted"] == 1
    conn = sqlite3.connect(migrated_db)
    try:
        slip = conn.execute(
            "SELECT slippage_ticks FROM paper_trades WHERE trade_id='T1'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert slip == pytest.approx(2.0)


def test_persist_excludes_demo_seed(migrated_db: str):
    """The untagged DUP662235 fill must never be matched (only n_matched=1)."""
    _seed_match(migrated_db)
    res = persist_entry_slippage(migrated_db, "MES")
    assert res["n_matched"] == 1  # the JARVIS fill only, not the demo-seed


def test_persist_unknown_symbol_graceful(migrated_db: str):
    res = persist_entry_slippage(migrated_db, "ZZZ")
    assert res["n_persisted"] == 0
    assert "skipped" in res


def test_persist_no_column_is_noop(tmp_path: Path):
    """Pre-migration DB (no slippage_ticks) -> persist is a silent no-op, no raise."""
    db = str(tmp_path / "bare.db")
    conn = sqlite3.connect(db)
    # Minimal tables WITHOUT slippage_ticks.
    conn.execute(
        "CREATE TABLE ibkr_fills (symbol TEXT, side TEXT, price REAL, fill_time TEXT, order_ref TEXT)"
    )
    conn.execute(
        "CREATE TABLE paper_trades (id INTEGER PRIMARY KEY, symbol TEXT, side TEXT, "
        "entry_price REAL, entry_time TEXT)"
    )
    conn.commit()
    conn.close()
    res = persist_entry_slippage(db, "MES")  # must not raise
    assert res["n_persisted"] == 0

"""
Blocker B (execution-fidelity forward-test) — fill reconciliation tests.

Covers:
  1. Migration 037 adds order_ref + parent_order_id to ibkr_fills and is
     idempotent (safe to re-run).
  2. compare_fills_to_trades() matches JARVIS-tagged real fills to paper_trades
     intent, measures entry slippage, excludes DUP662235 demo-seed activity
     (untagged fills), and honors the time-match window + side mapping.

All synthetic — no live IB, no real fills (the order path is inert until
ALLOW_PAPER_SIMULATED_ORDERS=True). This is the forward-test harness validated
on fixtures so it measures correctly once real fills accrue.

Run with:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_fill_reconciliation.py -v
"""

from __future__ import annotations

import os
import sqlite3
import sys

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _make_paper_trades(conn: sqlite3.Connection) -> None:
    """Minimal paper_trades with just the columns the reconciler reads."""
    conn.execute(
        """
        CREATE TABLE paper_trades (
            symbol      TEXT,
            side        TEXT,
            entry_price REAL,
            entry_time  TEXT
        )
        """
    )


def test_migration_037_adds_columns_idempotently(tmp_path):
    from database.migrations import migration_036, migration_037

    db = tmp_path / "m037.db"
    conn = sqlite3.connect(str(db))
    migration_036(conn)  # creates ibkr_fills (pre-037 schema)
    assert "order_ref" not in _columns(conn, "ibkr_fills")

    migration_037(conn)
    cols = _columns(conn, "ibkr_fills")
    assert "order_ref" in cols
    assert "parent_order_id" in cols

    # Idempotent: re-running must not raise (duplicate-column guard).
    migration_037(conn)
    conn.close()


def _seed_reconciliation_db(db_path: str) -> None:
    from database.migrations import migration_036, migration_037

    conn = sqlite3.connect(db_path)
    migration_036(conn)
    migration_037(conn)
    _make_paper_trades(conn)

    # paper_trades intent (entry legs).
    conn.executemany(
        "INSERT INTO paper_trades (symbol, side, entry_price, entry_time) VALUES (?, ?, ?, ?)",
        [
            ("MES", "buy", 5000.0, "2026-06-02T14:00:00+00:00"),
            ("MES", "buy", 5010.0, "2026-06-02T15:00:00+00:00"),
            ("MES", "sell", 5050.0, "2026-06-02T16:00:00+00:00"),  # no SLD fill -> unmatched
        ],
    )

    # ibkr_fills: 2 JARVIS buys (match the 2 buy trades) + 1 untagged demo buy.
    # fill_time uses a space separator (str(execution.time) shape) on purpose.
    fills = [
        # exec_id, account, symbol, sec_type, expiry, side, qty, price, avg, comm,
        # exch, ccy, fill_time, order_id, order_ref, parent_order_id, imported_at
        ("E1", "DUP662235", "MES", "FUT", "", "BOT", 1, 5000.5, 5000.5, 1.0,
         "GLOBEX", "USD", "2026-06-02 14:00:05+00:00", 11, "JARVIS-aaa111", None, "now"),
        ("E2", "DUP662235", "MES", "FUT", "", "BOT", 1, 5009.0, 5009.0, 1.0,
         "GLOBEX", "USD", "2026-06-02 15:00:10+00:00", 12, "JARVIS-bbb222", None, "now"),
        # Demo-seed: untagged -> must be excluded.
        ("E3", "DUP662235", "MES", "FUT", "", "BOT", 1, 4000.0, 4000.0, 1.0,
         "GLOBEX", "USD", "2026-06-02 10:00:00+00:00", 13, "", None, "now"),
    ]
    conn.executemany(
        """
        INSERT INTO ibkr_fills
            (exec_id, account, symbol, sec_type, expiry, side, quantity, price,
             avg_price, commission, exchange, currency, fill_time, order_id,
             order_ref, parent_order_id, imported_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        fills,
    )
    conn.commit()
    conn.close()


def test_compare_fills_matches_and_excludes_demo(tmp_path):
    from execution.ibkr_reconciler import compare_fills_to_trades

    db = tmp_path / "recon.db"
    _seed_reconciliation_db(str(db))

    cmp = compare_fills_to_trades(str(db), "MES")

    assert cmp["n_real_fills"] == 2, "only JARVIS-tagged fills counted"
    assert cmp["n_demo_excluded"] == 1, "untagged demo fill excluded"
    assert cmp["n_paper_trades"] == 3
    assert cmp["n_matched"] == 2, "two buy trades match two JARVIS buy fills"
    assert cmp["n_unmatched_trades"] == 1, "the sell trade has no SLD fill"
    assert cmp["n_unmatched_fills"] == 0

    # Slippage: |5000.5-5000.0|=0.5 and |5009.0-5010.0|=1.0 -> avg 0.75, max 1.0
    assert cmp["avg_abs_slippage_pts"] == 0.75
    assert cmp["max_abs_slippage_pts"] == 1.0
    # Signed slippage preserved in matches (one positive, one negative).
    slips = sorted(m["slippage_pts"] for m in cmp["matches"])
    assert slips == [-1.0, 0.5]


def test_compare_fills_respects_time_window(tmp_path):
    from execution.ibkr_reconciler import compare_fills_to_trades

    db = tmp_path / "recon_window.db"
    _seed_reconciliation_db(str(db))

    # 1-second window: both fills are >1s from their trade entry -> no match.
    cmp = compare_fills_to_trades(str(db), "MES", match_window_sec=1)
    assert cmp["n_matched"] == 0
    assert cmp["n_unmatched_trades"] == 3
    assert cmp["avg_abs_slippage_pts"] is None


def test_compare_fills_empty_when_no_table(tmp_path):
    """Resilient: missing ibkr_fills returns the empty scaffold, never raises."""
    from execution.ibkr_reconciler import compare_fills_to_trades

    db = tmp_path / "empty.db"
    sqlite3.connect(str(db)).close()  # no tables at all

    cmp = compare_fills_to_trades(str(db), "MES")
    assert cmp["n_real_fills"] == 0
    assert cmp["n_matched"] == 0
    assert cmp["avg_abs_slippage_pts"] is None
    assert cmp["matches"] == []

"""T1-09 regression: GET /trades/journal must exclude curated-out rows.

Background
----------
The 2026-07-08 dashboard-integrity audit (T1-09) found that
``engine/routers/trades_router.py``'s ``GET /trades/journal`` handler ran a
bare ``SELECT * FROM paper_trades WHERE 1=1`` with no status filter, while
sibling pages (Scorecard, most of Performance, Journal Review) already
consume a deduped/curated trade source. The sibling-page dedup source
(``dashboard/lib/honestTrades.ts`` -> external master-api) lives outside this
repo, so it cannot be reused directly by the FastAPI router. Investigating
the LIVE database (``engine/data/jarvis_trader.db``, 2026-07-09) showed the
gap is real: of 72 total ``paper_trades`` rows, 28 (39%) carry a curated-out
status --  18 ``cancelled_duplicate`` (the pre-#299 hourly re-emit bug),
4 ``cancelled_contaminated``, and 6 ``phantom`` (3 of which carry a
fabricated *negative* pnl). The unfiltered endpoint fed those rows straight
into the Journal page's client-side summary tiles
(``dashboard/app/journal/page.tsx`` -- Total / Wins / Losses / Total P&L),
inflating the trade count by 64% and leaking phantom pnl into the total.

Fix: filter to ``status IN ('open', 'closed')`` -- the SAME genuine-status
convention already established in this repo by
``engine/database/_mixins_trades.py`` (``get_open_trades`` /
``get_closed_trades``) and ``engine/backtest/live_readiness.py``
(``GENUINE_OPEN_STATUS`` / ``GENUINE_CLOSED_STATUS``). No new dedup
mechanism invented.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import database
from database.manager import DatabaseManager
from routers.trades_router import get_trades_journal

# Every status observed in the live DB export (2026-07-09), plus the two
# genuine lifecycle states.
_ALL_STATUSES = [
    "open",
    "closed",
    "phantom",
    "cancelled_duplicate",
    "cancelled_contaminated",
]


def _make_db(tmp_path: Path) -> DatabaseManager:
    db = DatabaseManager(str(tmp_path / "test_journal_status.db"))
    db.initialize()
    return db


def _insert_row(
    conn: sqlite3.Connection,
    *,
    trade_id: str,
    symbol: str,
    side: str,
    status: str,
    pnl: float | None,
    idempotency_key: str,
) -> None:
    conn.execute(
        """
        INSERT INTO paper_trades
            (trade_id, symbol, side, quantity, entry_price, exit_price,
             entry_time, exit_time, pnl, status, idempotency_key)
        VALUES (?, ?, ?, 1.0, 100.0, 100.0,
                '2026-07-01T00:00:00+00:00', '2026-07-01T01:00:00+00:00',
                ?, ?, ?)
        """,
        (trade_id, symbol, side, pnl, status, idempotency_key),
    )


@pytest.fixture
def journal_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DatabaseManager:
    """A DatabaseManager with one paper_trades row per known status, wired up
    as the module-level singleton ``database.get_db`` resolves to (the
    router does ``from database import get_db as get_db_manager`` at call
    time, so monkeypatching the package-level symbol is sufficient)."""
    db = _make_db(tmp_path)
    conn = db._connect()
    try:
        for i, status in enumerate(_ALL_STATUSES):
            pnl = -1.5 if status == "phantom" else (10.0 if status == "closed" else 0.0)
            _insert_row(
                conn,
                trade_id=f"trade-{status}",
                symbol="MES",
                side="buy",
                status=status,
                pnl=pnl,
                idempotency_key=f"key-{i}",
            )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(database, "get_db", lambda: db)
    return db


def test_journal_excludes_curated_out_statuses(journal_db: DatabaseManager) -> None:
    """Only status IN ('open', 'closed') rows come back -- phantom /
    cancelled_duplicate / cancelled_contaminated are curated out."""
    result = get_trades_journal(symbol=None, regime=None, limit=200)
    statuses = {t.status for t in result}

    assert statuses == {"open", "closed"}, (
        f"expected only genuine lifecycle statuses, got {statuses!r} -- "
        "curated-out rows leaked into GET /trades/journal"
    )
    assert len(result) == 2


def test_journal_phantom_pnl_does_not_leak_into_results(
    journal_db: DatabaseManager,
) -> None:
    """The phantom row's fabricated -1.5 pnl must not appear in the response
    at all -- it is exactly the value that corrupted the Journal page's
    client-side Total P&L tile before this fix."""
    result = get_trades_journal(symbol=None, regime=None, limit=200)
    pnls = [t.pnl for t in result]
    assert -1.5 not in pnls
    # The one genuine closed row is present with its real pnl.
    closed = [t for t in result if t.status == "closed"]
    assert len(closed) == 1
    assert closed[0].pnl == 10.0


def test_journal_symbol_filter_still_works(journal_db: DatabaseManager) -> None:
    """The pre-existing symbol filter composes correctly with the new status
    filter (regression guard against breaking the AND-chain)."""
    result = get_trades_journal(symbol="MES", regime=None, limit=200)
    assert len(result) == 2
    result_other = get_trades_journal(symbol="MGC", regime=None, limit=200)
    assert result_other == []

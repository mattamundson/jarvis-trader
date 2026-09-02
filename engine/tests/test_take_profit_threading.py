"""
JARVIS T7 regression test — take_profit/stop_loss threading (PR #731).

Before #731 the queue-approve path dropped stop/target before submit, so
paper entries landed in SQLite with stop_loss=NULL and take_profit=NULL.
This test drives the REAL production write chain (no mocks) against a temp
DB and proves the values survive every link:

    ib_gateway_connector market-fill payload
      -> PaperTradeLogger.log_trade({... stop_price, take_profit})
      -> _maybe_mirror_to_tracker()
      -> PortfolioTracker.open_trade(stop_loss=, take_profit=)
      -> DatabaseManager.insert_paper_trade()   [real INSERT]
      -> paper_trades row read back, values asserted

Also a negative control: an entry with no stop/TP must write NULLs (the
pre-fix behavior), so the assertions above cannot pass vacuously.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from database.manager import DatabaseManager
from execution.paper_trade_logger import PaperTradeLogger
from portfolio.tracker import PortfolioTracker


@pytest.fixture
def db(tmp_path: Path) -> DatabaseManager:
    db = DatabaseManager(str(tmp_path / "test.db"))
    db.initialize()
    return db


async def _log_entry(
    db: DatabaseManager,
    tmp_path: Path,
    payload: dict,
) -> PortfolioTracker:
    """Build the real tracker+logger wiring and log one entry."""
    tracker = PortfolioTracker(
        store_path=tmp_path / "trades.jsonl",
        db_manager=db,
    )
    # trades_file -> tmp so the deprecated JSON audit file stays out of the repo.
    # (The deprecation warning fires at construction, not on log_trade.)
    with pytest.warns(DeprecationWarning):
        logger_ = PaperTradeLogger(
            settings=None,
            portfolio_tracker=tracker,
            trades_file=tmp_path / "paper_trades.json",
        )
    await logger_.log_trade(payload)
    return tracker


def _row(db: DatabaseManager, symbol: str) -> tuple:
    conn = sqlite3.connect(str(db._db_path))
    try:
        return conn.execute(
            "SELECT symbol, side, entry_price, stop_loss, take_profit, status "
            "FROM paper_trades WHERE symbol = ? ORDER BY id DESC LIMIT 1",
            (symbol,),
        ).fetchone()
    finally:
        conn.close()


class TestTakeProfitThreading:
    def test_schema_has_bracket_columns(self, db: DatabaseManager) -> None:
        conn = sqlite3.connect(str(db._db_path))
        try:
            cols = [c[1] for c in conn.execute("PRAGMA table_info(paper_trades)")]
        finally:
            conn.close()
        assert "stop_loss" in cols
        assert "take_profit" in cols

    async def test_entry_with_bracket_populates_columns(
        self, db: DatabaseManager, tmp_path: Path
    ) -> None:
        await _log_entry(
            db,
            tmp_path,
            {
                "order_id": "tp-verify-entry",
                "symbol": "MES",
                "quantity": 1,
                "order_type": "market",
                "filled_price": 5300.25,
                "fill_time": "2026-08-24T12:00:00+00:00Z",
                "is_futures": True,
                "stop_price": 5280.00,
                "take_profit": 5400.00,
            },
        )
        row = _row(db, "MES")
        assert row is not None
        sym, side, entry, sl, tp, status = row
        assert (sym, status) == ("MES", "open")
        assert sl == 5280.00, f"stop_loss not populated: {sl!r}"
        assert tp == 5400.00, f"take_profit not populated: {tp!r}"

    async def test_entry_without_bracket_writes_nulls(
        self, db: DatabaseManager, tmp_path: Path
    ) -> None:
        """Negative control: no stop/TP in payload -> NULLs (pre-fix behavior)."""
        await _log_entry(
            db,
            tmp_path,
            {
                "order_id": "tp-verify-nobracket",
                "symbol": "SPY",
                "quantity": 1,
                "order_type": "market",
                "filled_price": 620.50,
                "fill_time": "2026-08-24T12:30:00+00:00Z",
                "is_futures": False,
            },
        )
        row = _row(db, "SPY")
        assert row is not None
        assert row[3] is None, f"stop_loss should be NULL, got {row[3]!r}"
        assert row[4] is None, f"take_profit should be NULL, got {row[4]!r}"

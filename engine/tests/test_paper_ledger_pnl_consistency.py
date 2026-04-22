"""RISK-006 / RISK-011: SQLite closed-trade P&L must match PortfolioTracker.get_performance()."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from database.schema import DatabaseManager
from portfolio.tracker import PortfolioTracker


def test_sqlite_closed_pnl_sum_matches_tracker_get_performance(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    db = DatabaseManager(str(db_path))
    db.initialize()
    store = tmp_path / "audit.jsonl"
    tracker = PortfolioTracker(store_path=store, db_manager=db)
    trade_id = tracker.open_trade("MES", "buy", 1, 5000.0)
    tracker.close_trade(trade_id, exit_price=5020.0)

    perf = tracker.get_performance()
    conn = sqlite3.connect(str(db_path))
    try:
        raw_sum = conn.execute(
            "SELECT COALESCE(SUM(pnl), 0) FROM paper_trades "
            "WHERE status = 'closed' AND pnl IS NOT NULL"
        ).fetchone()[0]
    finally:
        conn.close()

    assert float(raw_sum) == pytest.approx(perf["total_pnl"], rel=1e-9, abs=1e-6)
    assert perf["num_trades"] == 1

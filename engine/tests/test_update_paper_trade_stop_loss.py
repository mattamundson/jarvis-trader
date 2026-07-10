"""
DatabaseManager.update_paper_trade_stop_loss — naked-row backfill write path.

Background: OMS v2 bracket-executed trades are opened via
PortfolioTracker.open_trade(), so their paper_trades row persists
stop_loss=NULL even though the OMS holds the real stop_loss_price in-memory
(execution/oms_v2.py::resolve_stop_for_symbol, added alongside the trade #287
fix). main._monitor_open_stops() already resolves that in-memory value as a
read-time fallback every 5 minutes; update_paper_trade_stop_loss lets it also
persist the resolved value once, so subsequent reads (dashboard, other
monitors) see the real number instead of NULL.

This is a second write path onto the same safety-critical stop_loss column
insert_paper_trade guards (see test_stop_loss_invariants.py /
docs/incident-notes/2026-04-09-mcl-inverted-stop.md), so it must carry the
identical inverted-stop guard.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from database.manager import DatabaseManager  # noqa: E402


def _fresh_db(tmp_path) -> DatabaseManager:
    db = DatabaseManager(db_path=str(tmp_path / "backfill.db"))
    db.initialize()
    return db


def _open_trade(db: DatabaseManager, trade_id: str, side: str, entry_price: float) -> None:
    db.insert_paper_trade(
        trade_id=trade_id,
        symbol="MES",
        side=side,
        quantity=1,
        entry_price=entry_price,
        idempotency_key=f"test-backfill-key-{trade_id}",
    )


class TestUpdatePaperTradeStopLossBackfill:
    def test_backfills_valid_long_stop(self, tmp_path):
        db = _fresh_db(tmp_path)
        _open_trade(db, "long-1", "buy", 100.0)

        assert db.update_paper_trade_stop_loss("long-1", 95.0) is True

        rows = db.get_open_trades()
        row = next(r for r in rows if r["trade_id"] == "long-1")
        assert row["stop_loss"] == 95.0

    def test_backfills_valid_short_stop(self, tmp_path):
        db = _fresh_db(tmp_path)
        _open_trade(db, "short-1", "sell", 100.0)

        assert db.update_paper_trade_stop_loss("short-1", 105.0) is True

        rows = db.get_open_trades()
        row = next(r for r in rows if r["trade_id"] == "short-1")
        assert row["stop_loss"] == 105.0

    def test_rejects_inverted_long_stop(self, tmp_path):
        db = _fresh_db(tmp_path)
        _open_trade(db, "long-inverted", "buy", 100.0)

        with pytest.raises(ValueError, match="inverted stop"):
            db.update_paper_trade_stop_loss("long-inverted", 105.0)  # above entry — wrong

        rows = db.get_open_trades()
        row = next(r for r in rows if r["trade_id"] == "long-inverted")
        assert row["stop_loss"] is None  # rejected write must not land

    def test_rejects_inverted_short_stop(self, tmp_path):
        db = _fresh_db(tmp_path)
        _open_trade(db, "short-inverted", "sell", 100.0)

        with pytest.raises(ValueError, match="inverted stop"):
            db.update_paper_trade_stop_loss("short-inverted", 95.0)  # below entry — wrong

        rows = db.get_open_trades()
        row = next(r for r in rows if r["trade_id"] == "short-inverted")
        assert row["stop_loss"] is None

    def test_returns_false_for_unknown_trade_id(self, tmp_path):
        db = _fresh_db(tmp_path)
        assert db.update_paper_trade_stop_loss("does-not-exist", 95.0) is False

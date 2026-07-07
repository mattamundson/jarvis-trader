"""Contract tests for the DB-authoritative open-positions read (#2).

The trust bug: ``/portfolio/paper/positions`` read only the in-memory tracker,
which can drift from ``paper_trades`` (the durable source) — so the dashboard
could show "no positions" while a row was genuinely open. ``get_open_positions_
authoritative`` anchors the result to the DB and surfaces any drift.
"""

import pytest


class _FakeDB:
    """Minimal stand-in exposing only get_open_trades()."""

    def __init__(self, rows):
        self._rows = rows

    def get_open_trades(self, symbol=None):
        return list(self._rows)


def _tracker(tmp_path):
    from portfolio.tracker import PortfolioTracker

    return PortfolioTracker(store_path=tmp_path / "paper.jsonl", db_manager=None)


def _db_row(trade_id, symbol="MES", side="buy"):
    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "side": side,
        "quantity": 1,
        "entry_price": 7530.0,
        "exit_price": None,
        "entry_time": "2026-06-15T14:00:00",
        "exit_time": None,
        "pnl": None,
        "status": "open",
    }


def test_no_db_falls_back_to_memory(tmp_path):
    tracker = _tracker(tmp_path)
    tracker.open_trade("MES", "buy", 1, 7530.0)
    positions, recon = tracker.get_open_positions_authoritative()
    assert recon["source"] == "memory"
    assert recon["reconciled"] is True
    assert recon["count"] == 1 == len(positions)


def test_db_and_memory_agree(tmp_path):
    tracker = _tracker(tmp_path)
    tid = tracker.open_trade("MES", "buy", 1, 7530.0)
    tracker._db = _FakeDB([_db_row(tid)])
    positions, recon = tracker.get_open_positions_authoritative()
    assert recon["source"] == "db_authoritative"
    assert recon["reconciled"] is True
    assert recon["count"] == 1
    assert recon["only_in_db"] == [] and recon["only_in_memory"] == []


def test_db_has_position_memory_missing_is_surfaced_and_returned(tmp_path):
    """DB row absent from memory → returned anyway, flagged as drift."""
    tracker = _tracker(tmp_path)
    tid_mem = tracker.open_trade("MES", "buy", 1, 7530.0)
    tracker._db = _FakeDB([_db_row(tid_mem), _db_row("db-only-1", symbol="MGC")])

    positions, recon = tracker.get_open_positions_authoritative()
    assert recon["reconciled"] is False
    assert recon["count"] == 2  # DB is authoritative — both returned
    assert recon["only_in_db"] == ["db-only-1"]
    # The DB-only row is normalized so consumers reading `action` still work.
    db_only = next(p for p in positions if p.get("trade_id") == "db-only-1")
    assert db_only["action"] == "buy"
    assert db_only["symbol"] == "MGC"


def test_memory_has_position_db_missing_is_flagged(tmp_path):
    """Memory row absent from DB → DB authoritative drops it, drift flagged."""
    tracker = _tracker(tmp_path)
    tracker.open_trade("MES", "buy", 1, 7530.0)
    tracker._db = _FakeDB([])  # DB says nothing open
    positions, recon = tracker.get_open_positions_authoritative()
    assert recon["reconciled"] is False
    assert recon["count"] == 0  # trust the DB
    assert len(recon["only_in_memory"]) == 1


def test_db_error_falls_back_without_raising(tmp_path):
    class _BoomDB:
        def get_open_trades(self, symbol=None):
            raise RuntimeError("db down")

    tracker = _tracker(tmp_path)
    tracker.open_trade("MES", "buy", 1, 7530.0)
    tracker._db = _BoomDB()
    positions, recon = tracker.get_open_positions_authoritative()
    assert recon["source"] == "memory_db_error"
    assert recon["reconciled"] is False
    assert len(positions) == 1  # degrades to in-memory, never 500s

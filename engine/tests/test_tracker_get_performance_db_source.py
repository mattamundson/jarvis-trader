"""
Regression test for the get_performance() data-source bug.

PortfolioTracker stores the optional DatabaseManager handle as ``self._db``
(constructor arg ``db_manager``). get_performance() used to probe
``getattr(self, "db_manager", None)`` — an attribute that never exists — so the
check was always None and the method silently fell back to the in-memory
``_closed`` list, ignoring SQLite entirely. Every other method in the class uses
``self._db`` (e.g. _get_starting_balance at the same file).

These tests pin the fixed behavior: when a db_manager is wired, get_performance()
must compute from the DB rows, NOT from the in-memory list; with no db_manager it
must fall back cleanly to in-memory.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from portfolio.tracker import PortfolioTracker


class _FakeDB:
    """Minimal stand-in exposing only what get_performance() touches."""

    def __init__(self, rows: List[Dict[str, Any]]) -> None:
        self._rows = rows
        self.calls = 0

    def get_closed_trades(self, limit: int = 10000) -> List[Dict[str, Any]]:
        self.calls += 1
        return list(self._rows)


def test_get_performance_reads_from_db_not_memory(tmp_path: Path) -> None:
    # DB holds two winners totalling +300; in-memory _closed is deliberately
    # different (a single -50 loser) so the source is unambiguous.
    db = _FakeDB([
        {"trade_id": "A", "pnl": 100.0},
        {"trade_id": "B", "pnl": 200.0},
    ])
    tracker = PortfolioTracker(store_path=tmp_path / "audit.jsonl", db_manager=db)

    # Poison the in-memory list to prove it is NOT the source.
    from portfolio.tracker import PaperTrade

    t = PaperTrade.__new__(PaperTrade)
    t.trade_id = "MEM"
    t.pnl = -50.0
    tracker._closed = [t]

    perf = tracker.get_performance()

    # >=1: get_performance also calls _get_starting_balance(), which reads the
    # DB again — both are legitimate DB reads. The point is the DB IS queried.
    assert db.calls >= 1, "get_performance must query the DB handle"
    assert perf["num_trades"] == 2, "must reflect the 2 DB rows, not 1 in-memory row"
    assert perf["total_pnl"] == pytest.approx(300.0)
    assert perf["win_rate"] == pytest.approx(1.0)
    assert perf["worst_trade"] == pytest.approx(100.0)  # not the -50 memory row


def test_get_performance_falls_back_to_memory_without_db(tmp_path: Path) -> None:
    tracker = PortfolioTracker(store_path=tmp_path / "audit.jsonl")  # db_manager=None
    assert tracker._db is None

    from portfolio.tracker import PaperTrade

    t = PaperTrade.__new__(PaperTrade)
    t.trade_id = "MEM"
    t.pnl = 42.0
    tracker._closed = [t]

    perf = tracker.get_performance()

    assert perf["num_trades"] == 1
    assert perf["total_pnl"] == pytest.approx(42.0)


def test_get_performance_db_read_failure_falls_back(tmp_path: Path) -> None:
    class _BoomDB:
        def get_closed_trades(self, limit: int = 10000):
            raise RuntimeError("simulated SQLite failure")

    tracker = PortfolioTracker(store_path=tmp_path / "audit.jsonl", db_manager=_BoomDB())

    from portfolio.tracker import PaperTrade

    t = PaperTrade.__new__(PaperTrade)
    t.trade_id = "MEM"
    t.pnl = 7.0
    tracker._closed = [t]

    perf = tracker.get_performance()  # must not raise

    assert perf["num_trades"] == 1
    assert perf["total_pnl"] == pytest.approx(7.0)

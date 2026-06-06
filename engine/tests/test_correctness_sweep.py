"""Tests for Task 5 — correctness sweep.

Bug A: PortfolioTracker.get_performance() gated the SQLite read on a
non-existent attribute (getattr(self,'db_manager')) instead of self._db, so it
always fell back to the in-memory _closed list (empty after every restart) —
silently wrong/partial metrics.

Bug B: AUTONOMOUS_ACTIVE_SYMBOLS default (MCL,MNQ) is entirely inside
DO_NOT_TRADE_SYMBOLS, so the autonomous loop is dead-configured. A startup WARN
now names the dead config.
"""
import logging

import pytest

import scheduler.pipeline_autonomous as pa
from portfolio.tracker import PortfolioTracker

# --- Bug A: get_performance reads from self._db ---------------------------

class _StubDB:
    def __init__(self, rows):
        self._rows = rows

    def get_closed_trades(self, limit: int = 10000):
        return self._rows


def test_get_performance_reads_from_db(tmp_path):
    db = _StubDB([{"trade_id": "a", "pnl": 100.0}, {"trade_id": "b", "pnl": -50.0}])
    t = PortfolioTracker(store_path=tmp_path / "s.json", db_manager=db)
    perf = t.get_performance()
    # Was 0 before the fix (in-memory _closed is empty); now reads the 2 SQLite rows.
    assert perf["num_trades"] == 2


def test_get_performance_falls_back_when_no_db(tmp_path):
    t = PortfolioTracker(store_path=tmp_path / "s.json", db_manager=None)
    perf = t.get_performance()
    assert perf["num_trades"] == 0  # clean in-memory fallback, no crash


def test_get_performance_survives_db_error(tmp_path):
    class _BoomDB:
        def get_closed_trades(self, limit: int = 10000):
            raise RuntimeError("db down")

    t = PortfolioTracker(store_path=tmp_path / "s.json", db_manager=_BoomDB())
    perf = t.get_performance()  # must not raise; falls back to in-memory
    assert perf["num_trades"] == 0


# --- Bug B: dead-config WARN ----------------------------------------------

def test_warn_fires_for_blocked_symbols(monkeypatch, caplog):
    monkeypatch.setenv("AUTONOMOUS_ACTIVE_SYMBOLS", "MCL,MNQ")
    with caplog.at_level(logging.WARNING):
        pa._warn_blocked_active_symbols()
    assert any("DO_NOT_TRADE" in r.getMessage() for r in caplog.records)


def test_no_warn_for_tradeable_symbols(monkeypatch, caplog):
    monkeypatch.setenv("AUTONOMOUS_ACTIVE_SYMBOLS", "MES,MGC")
    with caplog.at_level(logging.WARNING):
        pa._warn_blocked_active_symbols()
    assert not any("DO_NOT_TRADE" in r.getMessage() for r in caplog.records)

"""Roadmap 0.6 — plausibility filtering on the confidence-scorer and
consolidator read paths.

A magnitude-corrupt P&L row (the real 2026-06-02 +$10,102.98 decoupled-NAV
artifact class) must not skew win-rate-derived confidence or the nightly
pattern extraction. Both read paths now route through
``analytics.outcome_hygiene.is_plausible_pnl`` — parity with the Brier/IC
calibration path, which already did. Hermetic: no config/LLM/network import.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.confidence_scorer import _fetch_symbol_trades  # noqa: E402
from learning.consolidator import TradingMemoryConsolidator  # noqa: E402

CORRUPT_PNL = 10102.98  # the real 2026-06-02 artifact magnitude (> $5,000 bound)


class _FakeDB:
    """Minimal db_manager exposing the sync fetch_all() the read paths probe."""

    def __init__(self, rows):
        self._rows = rows

    def fetch_all(self, sql, params):
        return [dict(r) for r in self._rows]


@pytest.mark.asyncio
async def test_confidence_fetch_excludes_implausible_pnl():
    rows = [{"pnl": 100.0}, {"pnl": -50.0}, {"pnl": CORRUPT_PNL}]
    trades = await _fetch_symbol_trades(_FakeDB(rows), "MES")
    assert len(trades) == 2
    assert all(abs(t["pnl"]) <= 5000 for t in trades)


@pytest.mark.asyncio
async def test_confidence_fetch_keeps_boundary_and_none():
    # $4,999 is within bound; None carries no magnitude to reject on.
    rows = [{"pnl": 4999.0}, {"pnl": None}, {"pnl": -4999.0}]
    trades = await _fetch_symbol_trades(_FakeDB(rows), "MES")
    assert len(trades) == 3


def test_consolidator_fetch_excludes_implausible_pnl():
    rows = [
        {"pnl": 120.0, "entry_time": "2026-07-21T10:00:00", "side": "buy", "symbol": "MES"},
        {"pnl": -80.0, "entry_time": "2026-07-21T11:00:00", "side": "sell", "symbol": "MES"},
        {"pnl": CORRUPT_PNL, "entry_time": "2026-07-21T12:00:00", "side": "buy", "symbol": "MES"},
    ]
    c = TradingMemoryConsolidator(db_manager=None)
    c._db = _FakeDB(rows)  # bypass promotion-engine construction with a live db
    trades = c._fetch_trades("2026-07-21")
    assert len(trades) == 2
    assert all(abs(t["pnl"]) <= 5000 for t in trades)

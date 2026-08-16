"""Regression test for the 2026-08-15 finding: GET /brokers/positions reported
avg_price=38589.0475 for a real 4-lot MES position whose actual entry price
was 7717.81 -- exactly 5x off, because IBKR's avgCost is multiplier-included
total cost per contract for futures, and _normalise_ibkr_position() in
brokers_router.py passed it straight through as "avg_price" without dividing
by the contract multiplier. Live-verified against the running engine's own
IBKR wrapper log: avgCost=38589.0475, multiplier='5', 38589.0475/5=7717.809,
matching that account's actual MES fills that week (7612-7772 range).

Run with:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_brokers_position_avg_price_multiplier.py -v
"""

from __future__ import annotations

import os
import sys

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

os.environ.setdefault("API_KEY", "test-key")

from routers.brokers_router import _normalise_ibkr_position  # noqa: E402


def test_futures_avg_price_divides_out_the_multiplier():
    """MES: avgCost=38589.0475, multiplier='5' -> avg_price=7717.809."""
    raw = {
        "symbol": "MES",
        "sec_type": "FUT",
        "position": 4.0,
        "avg_cost": 38589.0475,
        "multiplier": "5",
        "market_price": None,
        "unrealized_pnl": None,
    }
    out = _normalise_ibkr_position(raw)
    assert out["avg_price"] == 38589.0475 / 5
    assert abs(out["avg_price"] - 7717.809) < 0.001


def test_equity_avg_price_unchanged_when_multiplier_absent():
    """No multiplier field (equities) -> avg_price falls back to avg_cost as-is."""
    raw = {
        "symbol": "AAPL",
        "sec_type": "STK",
        "position": 10.0,
        "avg_cost": 302.87,
        "market_price": None,
        "unrealized_pnl": None,
    }
    out = _normalise_ibkr_position(raw)
    assert out["avg_price"] == 302.87


def test_zero_or_garbage_multiplier_falls_back_to_one():
    """A malformed/zero multiplier must not divide-by-zero or crash -- fall back to 1.0."""
    for bad_multiplier in ("0", "", None, "not-a-number"):
        raw = {
            "symbol": "MES",
            "sec_type": "FUT",
            "position": 1.0,
            "avg_cost": 7700.0,
            "multiplier": bad_multiplier,
        }
        out = _normalise_ibkr_position(raw)
        assert out["avg_price"] == 7700.0, f"failed for multiplier={bad_multiplier!r}"


def test_missing_avg_cost_stays_none():
    raw = {"symbol": "MES", "sec_type": "FUT", "position": 1.0, "multiplier": "5"}
    out = _normalise_ibkr_position(raw)
    assert out["avg_price"] is None

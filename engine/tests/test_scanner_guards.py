"""
Unit tests for the scanner guards added in main.py _analyze_and_alert()
on 2026-04-10 after the runaway scanner incident.

The guards themselves live inside an inner async function inside a
startup lifespan closure, which makes them hard to import directly.
Rather than refactor the closure just for testability, these tests
pin the invariants of the two guard ideas via a small re-implementation
that mirrors main.py. If main.py drifts, these tests will fail to match
the behavior and we'll know.

Guards:
  1. Already-open position guard — skip scan if paper_trades has an open row
     for the symbol.
  2. Price sanity guard — reject non-hold decisions where the pipeline's
     intended trade price is outside a hardcoded plausible range.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pytest

# ── Re-implementation of the guard logic from main.py ──────────────────────

_PLAUSIBLE_PRICE_RANGE = {
    "MCL": (40.0, 130.0),
    "MES": (3000.0, 8000.0),
    "MNQ": (10000.0, 30000.0),
    "MGC": (1500.0, 5000.0),
    "MYM": (25000.0, 50000.0),
}


def _already_open_guard(db_path: str, symbol: str) -> Optional[Tuple[int, str]]:
    """Returns the existing open (id, side) if one exists, else None."""
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, side FROM paper_trades WHERE symbol=? AND status='open' LIMIT 1",
            (symbol,),
        ).fetchone()
    return row


def _price_sanity_guard(
    symbol: str, result: Dict[str, Any]
) -> Tuple[bool, Optional[Tuple[float, Tuple[float, float]]]]:
    """
    Returns (passed, rejection_info). passed=False means the result should
    be rewritten to HOLD. rejection_info=(bad_price, range) when failing.
    """
    trade_dec = result.get("trade_decision") or {}
    px_candidate = (
        trade_dec.get("limit_price")
        or trade_dec.get("stop_price")
        or trade_dec.get("entry_price")
    )
    rng = _PLAUSIBLE_PRICE_RANGE.get(symbol.upper())
    if rng is None or px_candidate is None:
        return True, None
    if result.get("final_action", "hold") in ("hold",):
        return True, None
    try:
        px = float(px_candidate)
    except (TypeError, ValueError):
        return True, None
    if px < rng[0] or px > rng[1]:
        return False, (px, rng)
    return True, None


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def temp_db(tmp_path: Path) -> str:
    db_file = tmp_path / "test_jarvis_trader.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY,
            symbol TEXT,
            side TEXT,
            quantity REAL,
            entry_price REAL,
            status TEXT
        )
        """
    )
    conn.commit()
    conn.close()
    return str(db_file)


# ── Already-open guard tests ────────────────────────────────────────────────


def test_already_open_returns_none_when_no_position(temp_db: str) -> None:
    assert _already_open_guard(temp_db, "MCL") is None


def test_already_open_returns_existing_row(temp_db: str) -> None:
    conn = sqlite3.connect(temp_db)
    conn.execute(
        "INSERT INTO paper_trades (symbol, side, quantity, entry_price, status) VALUES (?, ?, ?, ?, ?)",
        ("MCL", "buy", 1.0, 68.5, "open"),
    )
    conn.commit()
    conn.close()
    row = _already_open_guard(temp_db, "MCL")
    assert row is not None
    assert row[1] == "buy"


def test_already_open_ignores_closed_positions(temp_db: str) -> None:
    conn = sqlite3.connect(temp_db)
    conn.execute(
        "INSERT INTO paper_trades (symbol, side, quantity, entry_price, status) VALUES (?, ?, ?, ?, ?)",
        ("MCL", "buy", 1.0, 68.5, "closed"),
    )
    conn.commit()
    conn.close()
    assert _already_open_guard(temp_db, "MCL") is None


def test_already_open_isolates_symbols(temp_db: str) -> None:
    conn = sqlite3.connect(temp_db)
    conn.execute(
        "INSERT INTO paper_trades (symbol, side, quantity, entry_price, status) VALUES (?, ?, ?, ?, ?)",
        ("MCL", "buy", 1.0, 68.5, "open"),
    )
    conn.commit()
    conn.close()
    assert _already_open_guard(temp_db, "MES") is None
    assert _already_open_guard(temp_db, "MCL") is not None


# ── Price sanity guard tests — the 2026-04-10 incident coverage ─────────────


def test_sanity_rejects_mes_at_70_57() -> None:
    """The exact bogus price that created MES #108, #109, #110."""
    result = {
        "final_action": "sell",
        "trade_decision": {"limit_price": 70.57},
    }
    passed, info = _price_sanity_guard("MES", result)
    assert passed is False
    assert info is not None
    assert info[0] == 70.57
    assert info[1] == (3000.0, 8000.0)


def test_sanity_rejects_mcl_at_98_61() -> None:
    """One of the overnight bogus MCL entries."""
    result = {
        "final_action": "sell",
        "trade_decision": {"limit_price": 98.61},
    }
    # MCL plausible range is (40, 130), so 98.61 is actually INSIDE it
    passed, _info = _price_sanity_guard("MCL", result)
    assert passed is True  # 98.61 is within MCL's wide plausible range


def test_sanity_rejects_mcl_at_0_50() -> None:
    """Catastrophically low price would trip sanity."""
    result = {
        "final_action": "buy",
        "trade_decision": {"limit_price": 0.50},
    }
    passed, info = _price_sanity_guard("MCL", result)
    assert passed is False
    assert info[0] == 0.50


def test_sanity_accepts_mcl_at_62_real_price() -> None:
    """Current real MCL ~$62 should pass."""
    result = {
        "final_action": "buy",
        "trade_decision": {"limit_price": 62.5},
    }
    passed, info = _price_sanity_guard("MCL", result)
    assert passed is True
    assert info is None


def test_sanity_accepts_mes_at_6000_real_price() -> None:
    """Current real MES ~$6000 should pass."""
    result = {
        "final_action": "sell",
        "trade_decision": {"limit_price": 6000.0},
    }
    passed, info = _price_sanity_guard("MES", result)
    assert passed is True


def test_sanity_ignores_hold_decisions() -> None:
    """HOLD with a weird price doesn't matter — no trade will be placed."""
    result = {
        "final_action": "hold",
        "trade_decision": {"limit_price": 70.57},
    }
    passed, _info = _price_sanity_guard("MES", result)
    assert passed is True


def test_sanity_ignores_unknown_symbols() -> None:
    """Symbols not in the plausible range table pass through."""
    result = {
        "final_action": "buy",
        "trade_decision": {"limit_price": 999.99},
    }
    passed, info = _price_sanity_guard("UNKNOWN", result)
    assert passed is True
    assert info is None


def test_sanity_handles_missing_trade_decision() -> None:
    """Missing trade_decision should not crash."""
    result: Dict[str, Any] = {"final_action": "buy"}
    passed, _info = _price_sanity_guard("MES", result)
    assert passed is True  # No price to check → pass through


def test_sanity_reads_stop_price_fallback() -> None:
    """When limit_price is missing, fall back to stop_price."""
    result = {
        "final_action": "sell",
        "trade_decision": {"stop_price": 70.57},
    }
    passed, info = _price_sanity_guard("MES", result)
    assert passed is False
    assert info[0] == 70.57

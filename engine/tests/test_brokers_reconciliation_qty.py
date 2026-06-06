"""Regression test for brokers_router._build_reconciliation quantity/sign drift.

Before the fix, _build_reconciliation compared only the SET of symbols on each
side, so a same-symbol size or sign divergence (paper LONG 2 vs broker SHORT 3)
read as "in sync" — a silent position-state divergence at GET /brokers/positions.

These tests pin the symbol-level qty_mismatch detection while preserving the
existing paper_only / live_only / blind behavior.

Run with:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_brokers_reconciliation_qty.py -v
"""

from __future__ import annotations

import os
import sys

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

from routers.brokers_router import _build_reconciliation  # noqa: E402


def _ibkr(symbol: str, quantity: float) -> dict:
    # IBKR normalised position: signed quantity (long +, short -).
    return {"symbol": symbol, "quantity": quantity}


def _paper(symbol: str, direction: str, quantity: float) -> dict:
    # Paper normalised position: unsigned quantity + LONG/SHORT direction.
    return {"symbol": symbol, "direction": direction, "quantity": quantity}


def _types(recon: dict) -> set[str]:
    return {d["type"] for d in recon["discrepancies"]}


def test_sign_divergence_is_flagged():
    """Paper LONG 2 vs broker SHORT 3 on the same symbol must NOT read as in-sync."""
    recon = _build_reconciliation(
        ibkr_positions=[_ibkr("MES", -3)],
        schwab_positions=[],
        paper_positions=[_paper("MES", "LONG", 2)],
        ibkr_connected=True,
        schwab_connected=True,
    )
    mism = [d for d in recon["discrepancies"] if d["type"] == "qty_mismatch"]
    assert len(mism) == 1
    d = mism[0]
    assert d["symbol"] == "MES"
    assert d["paper_qty"] == 2.0
    assert d["live_qty"] == -3.0
    assert d["delta"] == 5.0


def test_size_only_divergence_is_flagged():
    """Same direction, different size (paper LONG 1 vs broker LONG 4)."""
    recon = _build_reconciliation(
        ibkr_positions=[_ibkr("MNQ", 4)],
        schwab_positions=[],
        paper_positions=[_paper("MNQ", "LONG", 1)],
        ibkr_connected=True,
        schwab_connected=True,
    )
    assert _types(recon) == {"qty_mismatch"}


def test_matched_signed_quantity_is_clean():
    """Paper LONG 2 vs broker LONG 2 → no discrepancies (true in-sync)."""
    recon = _build_reconciliation(
        ibkr_positions=[_ibkr("MES", 2)],
        schwab_positions=[],
        paper_positions=[_paper("MES", "LONG", 2)],
        ibkr_connected=True,
        schwab_connected=True,
    )
    assert recon["discrepancies"] == []
    assert recon["health"] == "ok"


def test_matched_short_is_clean():
    """Paper SHORT 2 vs broker -2 → in-sync (sign convention honored)."""
    recon = _build_reconciliation(
        ibkr_positions=[_ibkr("MCL", -2)],
        schwab_positions=[],
        paper_positions=[_paper("MCL", "SHORT", 2)],
        ibkr_connected=True,
        schwab_connected=True,
    )
    assert recon["discrepancies"] == []


def test_paper_only_and_live_only_preserved():
    """Existing presence-based discrepancies still fire."""
    recon = _build_reconciliation(
        ibkr_positions=[_ibkr("MNQ", 1)],
        schwab_positions=[],
        paper_positions=[_paper("MES", "LONG", 1)],
        ibkr_connected=True,
        schwab_connected=True,
    )
    by_sym = {d["symbol"]: d["type"] for d in recon["discrepancies"]}
    assert by_sym["MES"] == "paper_only"
    assert by_sym["MNQ"] == "live_only"


def test_blind_state_unchanged():
    """Neither broker connected → blind state, never a silent clean state."""
    recon = _build_reconciliation(
        ibkr_positions=[],
        schwab_positions=[],
        paper_positions=[_paper("MES", "LONG", 1)],
        ibkr_connected=False,
        schwab_connected=False,
    )
    assert recon["health"] == "blind"
    assert _types(recon) == {"all_brokers_disconnected"}

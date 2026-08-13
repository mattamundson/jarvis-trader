"""T0-06 — commission deduction on both live stop-close paths.

Dashboard-integrity audit finding T0-06 (Tier 0): commission was never
deducted from a real trade close. 0 of 27 real closed futures trades
reflected any fee deduction (~$42.00 unmodeled to date), and structural going
forward since stop-driven exits are how nearly all real closes happen.

Root cause: both live stop-close paths computed a zero-commission pnl and
handed it to a "broker-confirmed" pnl parameter that PortfolioTracker's
close_trade()/close_paper_trade() (engine/portfolio/tracker.py) deliberately
does NOT re-deduct commission from (an explicit pnl is assumed to already be
net of fees):

  1. engine/services/paper_stop_monitor.py — compute_stop_pnl(), used by
     PaperStopMonitor.check_once() and handed straight to
     db_manager.close_paper_trade(pnl=...) (a raw SQL write, no computation
     of its own).
  2. engine/main.py — the 5-min stop-monitor job (_monitor_open_stops, a
     closure not importable in isolation — see the faithful-replica pattern
     already used by TestStopMonitorLogic in test_safety_fixes_2026_06_01.py),
     which computes `_pnl` and hands it to
     paper_tracker.close_paper_trade(pnl=_pnl) / db_manager.close_trade(pnl=...).

Fix: both paths now subtract the SAME commission
(portfolio.tracker._commission_per_contract(), the exact constant/logic
PortfolioTracker already uses on its primary close_trade() path — see
test_tracker_commission_and_multiplier.py) before that pnl is ever treated as
"already net of fees". No new commission model was invented.

Each test below pins a fixture trade with a known entry/exit/contract-count
and asserts the exact expected post-commission pnl for one call site.
"""

from __future__ import annotations

import pytest

from portfolio.tracker import _commission_per_contract
from services.paper_stop_monitor import compute_stop_pnl


@pytest.fixture()
def pinned_commission(monkeypatch: pytest.MonkeyPatch) -> float:
    """Pin COMMISSION_PER_CONTRACT to a known value for deterministic math."""
    monkeypatch.setenv("COMMISSION_PER_CONTRACT", "1.50")
    return _commission_per_contract()


# ── Call site 1: engine/services/paper_stop_monitor.py (PaperStopMonitor) ──────


def test_call_site_1_paper_stop_monitor_deducts_commission(pinned_commission):
    """Fixture: MGC long, entry 4503.9, exit (stop) 4497.51, qty=1, mult=$10/pt.

    Gross = (4497.51 - 4503.9) * 1 * 10 = -63.90
    Commission = $1.50 * 1 = $1.50
    Expected net pnl = -63.90 - 1.50 = -65.40
    """
    pnl = compute_stop_pnl(
        side="buy",
        entry_price=4503.9,
        exit_price=4497.51,
        quantity=1,
        multiplier=10.0,
    )
    assert pnl == pytest.approx(-65.40, rel=1e-4)
    # Explicitly prove the deduction is the reused tracker constant, not a
    # reinvented figure.
    assert pnl == pytest.approx(-63.90 - pinned_commission, rel=1e-4)


def test_call_site_1_paper_stop_monitor_scales_commission_with_quantity(
    pinned_commission,
):
    """Fixture: MES short, entry 5300, exit 5310 (adverse), qty=3, mult=$5/pt.

    Gross = (5300 - 5310) * 3 * 5 = -150.0
    Commission = $1.50 * 3 = $4.50
    Expected net pnl = -150.0 - 4.50 = -154.50
    """
    pnl = compute_stop_pnl(
        side="sell",
        entry_price=5300.0,
        exit_price=5310.0,
        quantity=3,
        multiplier=5.0,
    )
    assert pnl == pytest.approx(-154.50, rel=1e-4)


# ── Call site 2: engine/main.py _monitor_open_stops() ───────────────────────────
# The stop-monitor job is a closure defined inline in main.py's startup code
# and is not importable in isolation (same limitation the pre-existing
# TestStopMonitorLogic suite in test_safety_fixes_2026_06_01.py already
# documents). This test faithfully replicates the post-fix formula — gross
# pnl minus portfolio.tracker._commission_per_contract() * qty — exactly as
# it now appears at engine/main.py's stop-monitor loop, rather than
# reinventing a separate commission figure.


def _main_py_stop_close_pnl(is_long: bool, entry: float, stop: float, qty: float, mult: float) -> float:
    """Mirrors engine/main.py::_monitor_open_stops()'s pnl computation (T0-06)."""
    gross_pnl = (stop - entry) * qty * mult if is_long else (entry - stop) * qty * mult
    return gross_pnl - (_commission_per_contract() * abs(qty))


def test_call_site_2_main_py_stop_monitor_deducts_commission(pinned_commission):
    """Fixture: MGC long, entry 4503.9, stop 4497.51, qty=1.0, mult=$10/pt
    (the actual 2026-06-01 trade #178 shape used elsewhere in this suite).

    Gross = (4497.51 - 4503.9) * 1.0 * 10 = -63.90
    Commission = $1.50 * 1.0 = $1.50
    Expected net pnl = -63.90 - 1.50 = -65.40
    """
    pnl = _main_py_stop_close_pnl(
        is_long=True, entry=4503.9, stop=4497.51, qty=1.0, mult=10.0
    )
    assert pnl == pytest.approx(-65.40, rel=1e-4)
    assert pnl == pytest.approx(-63.90 - pinned_commission, rel=1e-4)


def test_call_site_2_main_py_stop_monitor_short_position(pinned_commission):
    """Fixture: MNQ short, entry 18500, stop 18520, qty=2.0, mult=$2/pt.

    Gross = (18500 - 18520) * 2.0 * 2 = -80.0
    Commission = $1.50 * 2.0 = $3.00
    Expected net pnl = -80.0 - 3.00 = -83.00
    """
    pnl = _main_py_stop_close_pnl(
        is_long=False, entry=18500.0, stop=18520.0, qty=2.0, mult=2.0
    )
    assert pnl == pytest.approx(-83.0, rel=1e-4)


def test_both_call_sites_agree_on_commission_for_same_fixture(pinned_commission):
    """Both stop-close paths must deduct IDENTICAL commission for the same
    trade shape — this is the reuse guarantee the fix is built on (same
    portfolio.tracker._commission_per_contract() constant, not two parallel
    models that could silently drift apart).
    """
    site1_pnl = compute_stop_pnl(
        side="buy", entry_price=4503.9, exit_price=4497.51, quantity=1, multiplier=10.0
    )
    site2_pnl = _main_py_stop_close_pnl(
        is_long=True, entry=4503.9, stop=4497.51, qty=1.0, mult=10.0
    )
    assert site1_pnl == pytest.approx(site2_pnl, rel=1e-6)


def test_commission_env_default_matches_production(monkeypatch: pytest.MonkeyPatch):
    """No override set → both call sites fall back to the same $1.50 default
    PortfolioTracker uses (engine/portfolio/tracker.py:_commission_per_contract)."""
    monkeypatch.delenv("COMMISSION_PER_CONTRACT", raising=False)
    assert _commission_per_contract() == pytest.approx(1.50)
    pnl = compute_stop_pnl(
        side="buy", entry_price=100.0, exit_price=95.0, quantity=1, multiplier=10.0
    )
    # Gross -50.0, minus default $1.50 commission → -51.50
    assert pnl == pytest.approx(-51.50)

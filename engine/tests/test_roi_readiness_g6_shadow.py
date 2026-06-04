"""
Tests for the G6 engine-uptime shadow-wire.

The day-level pnl_snapshots proxy stays authoritative (gating value unchanged);
scripts.health_uptime.compute_uptime() is computed in shadow, logged, and
surfaced in G6 notes for an A/B — but never gates readiness yet, and never
breaks the gate when health_snapshots coverage is missing.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from backtest.roi_readiness import _eval_g6_engine_uptime

# Past window (no `today`) so the live /health fallback path is not exercised.
_DAYS = [date(2026, 5, 1) + timedelta(days=i) for i in range(14)]
_ALL_PRESENT = {d: {"daily_pnl": 0.0} for d in _DAYS}


def test_proxy_stays_authoritative_when_shadow_disagrees():
    # Proxy says 100% (all days present) → PASS. Shadow says a terrible 40%.
    # The gate verdict must still be driven by the proxy, not the shadow.
    with patch(
        "scripts.health_uptime.compute_uptime",
        return_value={"polls_total": 100, "polls_reachable": 40, "uptime_pct": 40.0},
    ):
        res = _eval_g6_engine_uptime(_ALL_PRESENT, _DAYS)

    assert res.passed is True, "proxy (100%) must remain the gating value"
    assert "SHADOW poll-level uptime=40.0%" in res.notes
    assert "advisory-only" in res.notes


def test_shadow_absent_leaves_notes_clean_and_gate_working():
    # No poll coverage → shadow returns None → no SHADOW string, gate still PASS.
    with patch(
        "scripts.health_uptime.compute_uptime",
        return_value={"polls_total": 0, "polls_reachable": 0, "uptime_pct": 0.0},
    ):
        res = _eval_g6_engine_uptime(_ALL_PRESENT, _DAYS)

    assert res.passed is True
    assert "SHADOW" not in res.notes


def test_shadow_exception_does_not_break_gate():
    with patch("scripts.health_uptime.compute_uptime", side_effect=RuntimeError("boom")):
        res = _eval_g6_engine_uptime(_ALL_PRESENT, _DAYS)

    assert res.passed is True
    assert "SHADOW" not in res.notes


def test_proxy_fail_still_fails_regardless_of_good_shadow():
    # Only 1 of 14 days present → proxy ~7% → FAIL even if shadow says 100%.
    sparse = {_DAYS[0]: {"daily_pnl": 0.0}}
    with patch(
        "scripts.health_uptime.compute_uptime",
        return_value={"polls_total": 100, "polls_reachable": 100, "uptime_pct": 100.0},
    ):
        res = _eval_g6_engine_uptime(sparse, _DAYS)

    assert res.passed is False, "proxy failure must not be rescued by a good shadow"
    assert "SHADOW poll-level uptime=100.0%" in res.notes

"""
Regression — kill-switch equity-peak read-path hardening.

get_peak_balance() must exclude demo/IB-contaminated daily_pnl rows so a single
oversized row (e.g. a ~$3.97M IB demo NAV against a $10k paper book) cannot
re-inflate the equity peak and falsely trip — or, inverted, mask — the
max-drawdown kill switch. This guards the 92.61%-false-breach class fixed at
the data layer on 2026-06-02; this is the recurrence-proof read-path guard.

These tests are NEW (test_safety_layer.py is left untouched / sacred).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from risk.pnl_monitor import PnLMonitor, PnLState


def _monitor(rows, starting_balance=10000.0) -> PnLMonitor:
    db = MagicMock()
    db.get_daily_pnl.return_value = rows
    return PnLMonitor(db_manager=db, starting_balance=starting_balance)


def _row(ending_balance):
    return {"ending_balance": ending_balance}


def test_demo_contaminated_row_excluded_from_peak():
    """A demo/IB row ~400x the paper book must not become the peak."""
    rows = [_row(10000.0), _row(10500.0), _row(11000.0), _row(3_970_000.0)]
    monitor = _monitor(rows, starting_balance=10000.0)
    assert monitor.get_peak_balance() == pytest.approx(11000.0)


def test_clean_history_uses_real_max():
    """No contamination → behaviour is unchanged (true max)."""
    rows = [_row(10000.0), _row(12000.0), _row(11500.0)]
    monitor = _monitor(rows, starting_balance=10000.0)
    assert monitor.get_peak_balance() == pytest.approx(12000.0)


def test_drawdown_not_falsely_breached_by_demo_row():
    """End-to-end: the excluded demo row must not manufacture a false breach.

    Without the guard, peak=$3.97M vs current $9.8k → ~-99.8% drawdown (instant
    false halt). With it, peak=$10.2k → ~-3.9%, well inside the -10% limit.
    """
    rows = [_row(10000.0), _row(10200.0), _row(3_970_000.0)]
    monitor = _monitor(rows, starting_balance=10000.0)
    state = PnLState(current_balance=9800.0, starting_balance=10000.0, source="sqlite")
    with patch.object(monitor, "get_current_pnl_state", return_value=state):
        dd = monitor.get_drawdown_pct()
    assert dd > -0.10, f"demo row caused a false drawdown breach: {dd:.4f}"
    assert dd == pytest.approx((9800.0 - 10200.0) / 10200.0, rel=1e-3)


def test_no_anchor_preserves_legacy_max():
    """starting_balance=0 → no plausibility anchor → legacy (unclamped) max."""
    rows = [_row(10000.0), _row(50000.0)]
    monitor = _monitor(rows, starting_balance=0.0)
    assert monitor.get_peak_balance() == pytest.approx(50000.0)


def test_ceiling_boundary_inclusive():
    """A row exactly at the Nx ceiling is kept; just above it is excluded.

    Reads PLAUSIBLE_PEAK_MULTIPLE from the monitor so the boundary tracks the
    configured multiple (tightened 10x -> 5x in 340ecbb) instead of going stale.
    """
    ceiling = 10000.0 * PnLMonitor.PLAUSIBLE_PEAK_MULTIPLE
    kept = _monitor([_row(10000.0), _row(ceiling)], starting_balance=10000.0)
    assert kept.get_peak_balance() == pytest.approx(ceiling)

    excluded = _monitor([_row(10000.0), _row(ceiling + 0.01)], starting_balance=10000.0)
    assert excluded.get_peak_balance() == pytest.approx(10000.0)

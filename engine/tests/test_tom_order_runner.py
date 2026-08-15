"""Tests for backtest/tom_order_runner.py -- the default-off, dry-run-only
systematic order generator for the MES_turn_of_month strategy.

Nothing here submits an order or touches a broker/execution path; these
tests only exercise the window math and the SafetyLayer.check_order dry-run
preview (which, per test_promotion_gate_enforcement.py, shadow-approves any
tagged order today since PROMOTED_STRATEGIES is empty).
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from backtest import tom_order_runner as runner
from risk.safety_layer import OrderRequest, SafetyLayer

# A fixed, hand-picked trading-day index (plain Mon-Fri, no holidays) used to
# pin the window-boundary arithmetic without depending on real holiday-calendar
# accuracy. Spans FULL months either side so rank-from-start/rank-from-end are
# computed against a realistic month length (a partial-month fixture would
# mis-rank early/late days -- e.g. a 3-day December would wrongly look like
# "the first 3 days of December" as well as "the last day").
_FIXED_INDEX = pd.bdate_range("2025-11-01", "2026-02-28")


@pytest.fixture(autouse=True)
def _fixed_calendar(monkeypatch):
    monkeypatch.setattr(runner, "_trading_days_around", lambda as_of: _FIXED_INDEX)


@pytest.mark.parametrize(
    "as_of,expected",
    [
        (date(2025, 12, 29), False),  # 3rd-from-end of Dec -> not last day
        (date(2025, 12, 30), False),  # 2nd-from-end -> not last day
        (date(2025, 12, 31), True),  # last trading day of Dec
        (date(2026, 1, 1), True),  # 1st trading day of Jan
        (date(2026, 1, 2), True),  # 2nd trading day of Jan
        (date(2026, 1, 5), True),  # 3rd trading day of Jan
        (date(2026, 1, 6), False),  # 4th trading day of Jan -> outside window
        (date(2026, 1, 7), False),
        (date(2026, 1, 8), False),
    ],
)
def test_is_tom_window_boundaries(as_of, expected):
    assert runner.is_tom_window(as_of) is expected


def test_is_tom_window_false_for_non_trading_day():
    # Not present in the fixed index at all (weekend).
    assert runner.is_tom_window(date(2026, 1, 3)) is False


def test_build_tom_order_in_window_is_tagged_and_long():
    signal = runner.build_tom_order(date(2025, 12, 31), quantity=2)
    assert signal.in_window is True
    assert signal.order is not None
    assert signal.order.symbol == runner.TOM_SYMBOL == "MES"
    assert signal.order.strategy_id == runner.TOM_STRATEGY_ID == "MES_turn_of_month"
    assert signal.order.quantity == 2
    assert signal.order.order_type == "market"
    assert signal.order.is_futures is True


def test_build_tom_order_out_of_window_has_no_order():
    signal = runner.build_tom_order(date(2026, 1, 6))
    assert signal.in_window is False
    assert signal.order is None


def test_build_tom_order_quantity_always_positive_long_only():
    signal = runner.build_tom_order(date(2025, 12, 31), quantity=-5)
    assert signal.order.quantity == 5  # long-only: sign is not caller-controllable


def test_run_tom_dry_check_returns_none_outside_window(mock_settings):
    sl = SafetyLayer(mock_settings)
    result = runner.run_tom_dry_check(sl, date(2026, 1, 6), portfolio_equity=100_000.0)
    assert result is None


def test_run_tom_dry_check_never_calls_ib_gateway(mock_settings):
    # No ib_gateway/pnl_monitor/loss_tracker/db wired -- if this reaches a
    # submission path it would blow up; it must not. mock_settings pins
    # LIVE_TRADING_ENABLED=False (conftest's test-safe default), so the
    # honest dry-run answer here is a real rejection, not a fabricated pass --
    # this only asserts we get a genuine RiskCheckResult back, not None.
    sl = SafetyLayer(mock_settings)
    result = runner.run_tom_dry_check(sl, date(2025, 12, 31), portfolio_equity=100_000.0)
    assert result is not None
    assert result.approved is False
    assert result.rejection_reason is not None


def test_run_tom_dry_check_order_is_never_submitted_only_checked(mock_settings):
    calls = []

    class _TrackingSafetyLayer(SafetyLayer):
        def check_order(self, order, portfolio_equity):
            calls.append(order)
            return super().check_order(order, portfolio_equity)

    sl = _TrackingSafetyLayer(mock_settings)
    assert sl._ib_gateway is None
    runner.run_tom_dry_check(sl, date(2025, 12, 31), portfolio_equity=100_000.0)
    assert len(calls) == 1
    assert calls[0].strategy_id == runner.TOM_STRATEGY_ID


def test_tom_evidence_summary_matches_promotion_gate_evidence():
    evidence = runner.tom_evidence_summary()
    assert evidence["strategy_id"] == runner.TOM_STRATEGY_ID
    assert evidence["decision_mode"] == "systematic"
    # Still correctly blocked pending Amo's Tier-3 gate-policy calls (t020).
    assert evidence["paper_shadow_passed"] is False


def test_module_wired_nowhere_live():
    """Regression guard: this module must stay dry-run-only, i.e. nothing
    outside backtest/tests imports it into a live scheduling/execution path.
    """
    from pathlib import Path

    engine_root = Path(__file__).resolve().parent.parent
    live_entrypoints = [engine_root / "main.py"]
    for entry in live_entrypoints:
        if not entry.exists():
            continue
        text = entry.read_text(encoding="utf-8", errors="ignore")
        assert "tom_order_runner" not in text, f"{entry} must not import tom_order_runner yet"

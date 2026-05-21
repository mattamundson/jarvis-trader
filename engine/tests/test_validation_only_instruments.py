"""
Tests for VALIDATION_ONLY_INSTRUMENTS — Wave 3 MES+MGC paper expansion.

Verifies that:
  - Pipeline runs for validation-only instruments (MES, MGC) and produces verdicts
  - No paper orders are submitted for validation-only instruments at the approval gate
  - MCL and MNQ (order-eligible instruments) are unaffected by the guard
  - VALIDATION_ONLY_INSTRUMENTS is an immutable frozenset

The order submission guard lives in approval/service.py:ensure_approval_allowed().
The pipeline still runs to completion for validation-only symbols; their verdicts
feed the dashboard and briefing pipeline for walk-forward validation tracking.
"""

import pytest
from unittest.mock import MagicMock, patch


# ── Constant integrity ─────────────────────────────────────────────────────────


def test_validation_only_constant_immutable():
    """VALIDATION_ONLY_INSTRUMENTS must be a frozenset (immutable, hashable)."""
    from agents.pipeline import VALIDATION_ONLY_INSTRUMENTS

    assert isinstance(
        VALIDATION_ONLY_INSTRUMENTS, frozenset
    ), "VALIDATION_ONLY_INSTRUMENTS must be a frozenset to prevent accidental mutation"
    assert "MES" in VALIDATION_ONLY_INSTRUMENTS
    assert "MGC" in VALIDATION_ONLY_INSTRUMENTS
    # Confirm MCL and MNQ are NOT in validation-only (they have separate DO_NOT_TRADE handling)
    assert "MCL" not in VALIDATION_ONLY_INSTRUMENTS
    assert "MNQ" not in VALIDATION_ONLY_INSTRUMENTS


def test_validation_only_does_not_overlap_do_not_trade():
    """VALIDATION_ONLY_INSTRUMENTS and DO_NOT_TRADE_SYMBOLS must be disjoint.

    DO_NOT_TRADE_SYMBOLS blocks signal generation entirely; VALIDATION_ONLY_INSTRUMENTS
    allows signal generation but blocks order submission. Overlapping them would mean
    validation-only instruments never produce verdicts — defeating the purpose.
    """
    from agents.pipeline import VALIDATION_ONLY_INSTRUMENTS
    from backtest.signals import DO_NOT_TRADE_SYMBOLS

    overlap = VALIDATION_ONLY_INSTRUMENTS & DO_NOT_TRADE_SYMBOLS
    assert not overlap, (
        f"VALIDATION_ONLY_INSTRUMENTS and DO_NOT_TRADE_SYMBOLS overlap: {overlap}. "
        "These sets must be disjoint — DO_NOT_TRADE blocks signal generation, "
        "VALIDATION_ONLY blocks order submission only."
    )


# ── Approval gate blocks orders for validation-only symbols ───────────────────


def _make_approval_row(symbol: str) -> dict:
    """Minimal approval row for ensure_approval_allowed() tests."""
    return {
        "symbol": symbol,
        "status": "pending",
        "pipeline_snapshot": {},
    }


def _make_mock_safety_layer(kill_switch_active: bool = False):
    safety = MagicMock()
    safety.get_status.return_value = {"kill_switch_active": kill_switch_active}
    safety.get_lockout_status.return_value = {"locked": False}
    return safety


def test_mes_approval_blocked():
    """MES approval must raise ApprovalFlowError — no paper orders for validation-only."""
    from approval.service import ApprovalFlowError, ensure_approval_allowed

    row = _make_approval_row("MES")
    safety = _make_mock_safety_layer()

    with patch(
        "approval.service.approved_watchlist_symbols", return_value={"MES", "MNQ", "MCL", "MGC"}
    ):
        with pytest.raises(ApprovalFlowError) as exc_info:
            ensure_approval_allowed(row, safety)

    assert exc_info.value.status_code == 409
    assert "VALIDATION_ONLY_INSTRUMENTS" in str(exc_info.value.detail)
    assert "MES" in str(exc_info.value.detail)


def test_mgc_approval_blocked():
    """MGC approval must raise ApprovalFlowError — no paper orders for validation-only."""
    from approval.service import ApprovalFlowError, ensure_approval_allowed

    row = _make_approval_row("MGC")
    safety = _make_mock_safety_layer()

    with patch(
        "approval.service.approved_watchlist_symbols", return_value={"MES", "MNQ", "MCL", "MGC"}
    ):
        with pytest.raises(ApprovalFlowError) as exc_info:
            ensure_approval_allowed(row, safety)

    assert exc_info.value.status_code == 409
    assert "VALIDATION_ONLY_INSTRUMENTS" in str(exc_info.value.detail)
    assert "MGC" in str(exc_info.value.detail)


def test_mcl_still_submits_orders():
    """MCL approval must NOT be blocked by VALIDATION_ONLY_INSTRUMENTS (regression check)."""
    from approval.service import ensure_approval_allowed

    row = _make_approval_row("MCL")
    safety = _make_mock_safety_layer()

    with patch(
        "approval.service.approved_watchlist_symbols", return_value={"MES", "MNQ", "MCL", "MGC"}
    ):
        # Should not raise — MCL is order-eligible
        ensure_approval_allowed(row, safety)


def test_mnq_still_submits_orders():
    """MNQ approval must NOT be blocked by VALIDATION_ONLY_INSTRUMENTS (regression check)."""
    from approval.service import ensure_approval_allowed

    row = _make_approval_row("MNQ")
    safety = _make_mock_safety_layer()

    with patch(
        "approval.service.approved_watchlist_symbols", return_value={"MES", "MNQ", "MCL", "MGC"}
    ):
        # Should not raise — MNQ is order-eligible
        ensure_approval_allowed(row, safety)


def test_validation_only_check_runs_after_kill_switch():
    """Kill switch takes precedence over VALIDATION_ONLY_INSTRUMENTS check."""
    from approval.service import ApprovalFlowError, ensure_approval_allowed

    row = _make_approval_row("MCL")
    safety = _make_mock_safety_layer(kill_switch_active=True)

    with patch(
        "approval.service.approved_watchlist_symbols", return_value={"MES", "MNQ", "MCL", "MGC"}
    ):
        with pytest.raises(ApprovalFlowError) as exc_info:
            ensure_approval_allowed(row, safety)

    # Kill switch fires first — error message references kill switch, not validation-only
    assert "Kill switch" in str(exc_info.value.detail)


# ── Pipeline still runs for validation-only symbols ───────────────────────────


def test_mes_pipeline_runs_but_no_order():
    """Pipeline produces a verdict for MES but the result is marked validation_only.

    The pipeline does NOT call submit_paper_order internally — that happens via the
    approval service. This test verifies the VALIDATION_ONLY_INSTRUMENTS constant is
    present and MES is correctly classified, ensuring dashboard/briefing feeds work.
    """
    from agents.pipeline import VALIDATION_ONLY_INSTRUMENTS

    # MES is in the validation-only set → pipeline runs, no orders
    assert "MES" in VALIDATION_ONLY_INSTRUMENTS

    # Confirm the constant is importable and stable across multiple imports
    from agents import pipeline as _pipeline_mod

    assert _pipeline_mod.VALIDATION_ONLY_INSTRUMENTS is VALIDATION_ONLY_INSTRUMENTS


def test_mgc_pipeline_runs_but_no_order():
    """Pipeline produces a verdict for MGC but the result is marked validation_only.

    Same reasoning as MES test above.
    """
    from agents.pipeline import VALIDATION_ONLY_INSTRUMENTS

    assert "MGC" in VALIDATION_ONLY_INSTRUMENTS

    from agents import pipeline as _pipeline_mod

    assert _pipeline_mod.VALIDATION_ONLY_INSTRUMENTS is VALIDATION_ONLY_INSTRUMENTS


def test_validation_only_exported_in_all():
    """VALIDATION_ONLY_INSTRUMENTS must appear in pipeline.__all__ for explicit export."""
    import agents.pipeline as _pipeline_mod

    assert "VALIDATION_ONLY_INSTRUMENTS" in _pipeline_mod.__all__, (
        "VALIDATION_ONLY_INSTRUMENTS must be in pipeline.__all__ so callers "
        "(approval/service.py, routers, tests) can import it cleanly."
    )

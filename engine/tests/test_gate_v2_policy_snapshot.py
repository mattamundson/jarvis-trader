"""Gate v2 policy snapshot — load-bearing constant regression guard.

If a gate threshold or WFO window constant changes, this test fails with an
explicit message. That forces an intentional review before any threshold shift
can slip into production unnoticed.

To update: change both the constant in _gate_v2_helpers.py AND the expected
value here. Include a comment explaining why the threshold changed and link
the backtest result or compliance requirement that justified it.
"""

from __future__ import annotations

import pytest

from backtest._gate_v2_helpers import (
    COST_SWEEP_TIERS,
    COST_TIER_ORDER,
    GATE_DSR,
    GATE_DSR_ALT,
    GATE_MC_DD_ALT,
    GATE_MC_DD_CORE,
    GATE_P_EDGE,
    GATE_PF_CI_LOWER,
    MIN_OOS_TRADES_PER_WINDOW,
    N_BOOTSTRAP,
    WFO_STEP_MONTHS,
    WFO_TEST_MONTHS,
    WFO_TRAIN_MONTHS,
)

_CHANGE_NOTICE = (
    "This is a LOAD-BEARING gate threshold. If you intentionally changed it, "
    "update the expected value in test_gate_v2_policy_snapshot.py and add a "
    "comment citing the backtest result or compliance requirement that justified "
    "the change."
)


class TestGateThresholds:
    """Each test is a snapshot of one threshold constant."""

    def test_pf_ci_lower(self):
        assert GATE_PF_CI_LOWER == pytest.approx(1.10), _CHANGE_NOTICE

    def test_p_edge(self):
        assert GATE_P_EDGE == pytest.approx(0.95), _CHANGE_NOTICE

    def test_mc_dd_core(self):
        assert GATE_MC_DD_CORE == pytest.approx(0.05), _CHANGE_NOTICE

    def test_mc_dd_alt(self):
        assert GATE_MC_DD_ALT == pytest.approx(0.04), _CHANGE_NOTICE

    def test_dsr_core(self):
        assert GATE_DSR == pytest.approx(0.10), _CHANGE_NOTICE

    def test_dsr_alt(self):
        assert GATE_DSR_ALT == pytest.approx(0.30), _CHANGE_NOTICE

    def test_n_bootstrap(self):
        assert N_BOOTSTRAP == 2000, _CHANGE_NOTICE


class TestWfoWindowDefaults:
    """WFO window sizes are load-bearing — changing them invalidates all existing verdicts."""

    def test_train_months(self):
        assert WFO_TRAIN_MONTHS == 6, _CHANGE_NOTICE

    def test_test_months(self):
        assert WFO_TEST_MONTHS == 1, _CHANGE_NOTICE

    def test_step_months(self):
        assert WFO_STEP_MONTHS == 1, _CHANGE_NOTICE

    def test_min_oos_trades_per_window(self):
        assert MIN_OOS_TRADES_PER_WINDOW == 5, _CHANGE_NOTICE


class TestCostSweepTiers:
    """Cost sweep tier values; changing these re-orders which configs pass gate v2."""

    def test_tier_order(self):
        assert COST_TIER_ORDER == [
            "optimistic",
            "realistic",
            "pessimistic",
            "catastrophic",
        ], _CHANGE_NOTICE

    def test_optimistic_tier(self):
        t = COST_SWEEP_TIERS["optimistic"]
        assert t["commission"] == pytest.approx(0.31), _CHANGE_NOTICE
        assert t["slippage_ticks"] == pytest.approx(1.0), _CHANGE_NOTICE

    def test_realistic_tier(self):
        t = COST_SWEEP_TIERS["realistic"]
        assert t["commission"] == pytest.approx(0.62), _CHANGE_NOTICE
        assert t["slippage_ticks"] == pytest.approx(1.0), _CHANGE_NOTICE

    def test_pessimistic_tier(self):
        t = COST_SWEEP_TIERS["pessimistic"]
        assert t["commission"] == pytest.approx(1.24), _CHANGE_NOTICE
        assert t["slippage_ticks"] == pytest.approx(2.0), _CHANGE_NOTICE

    def test_catastrophic_tier(self):
        t = COST_SWEEP_TIERS["catastrophic"]
        assert t["commission"] == pytest.approx(2.48), _CHANGE_NOTICE
        assert t["slippage_ticks"] == pytest.approx(3.0), _CHANGE_NOTICE

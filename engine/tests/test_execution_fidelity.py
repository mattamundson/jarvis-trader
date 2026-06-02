"""
Tests for the ADVISORY execution-fidelity gate.

The execution-fidelity gate (validation_gate_config.EXECUTION_FIDELITY_GATES +
/validate/execution-fidelity endpoint) answers "does live execution match the
backtest's assumptions?" on a small sample of fills — NOT "does the strategy have
edge?" (that is proven by the gate-v2 WFO).

Critical invariant under test: the fidelity gate is ADDITIVE and gates NOTHING —
it must not alter the existing 60-trade / PF>=2.0 edge gate.
"""

from __future__ import annotations

from paper.validation_gate_config import (
    EXECUTION_FIDELITY_GATES,
    PAPER_VALIDATION_GATES,
)
from routers.proactive_validation_router import (
    _check_broker_link,
    _check_fill_sample,
    _check_kill_switch_state,
    _check_pf_floor,
)

# ---------------------------------------------------------------------------
# Invariant: fidelity gate must NOT weaken the edge gate
# ---------------------------------------------------------------------------


def test_edge_gate_unchanged_by_fidelity_gate():
    """Adding EXECUTION_FIDELITY_GATES must not alter the statistical edge gate."""
    assert PAPER_VALIDATION_GATES["min_trades"] == 60
    assert PAPER_VALIDATION_GATES["profit_factor"] == 2.0
    assert PAPER_VALIDATION_GATES["sharpe_ratio"] == 1.5
    assert PAPER_VALIDATION_GATES["win_rate_pct"] == 55.0


def test_fidelity_gates_present_and_distinct():
    """Fidelity gate has its own thresholds, far below the edge gate."""
    assert EXECUTION_FIDELITY_GATES["min_fills"] == 15
    assert EXECUTION_FIDELITY_GATES["max_avg_slippage_ticks"] == 1.5
    # The fidelity PF floor is a sign-check (1.0), NOT the 2.0 edge threshold.
    assert EXECUTION_FIDELITY_GATES["min_realized_pf_floor"] == 1.0
    assert EXECUTION_FIDELITY_GATES["min_realized_pf_floor"] < PAPER_VALIDATION_GATES["profit_factor"]
    assert EXECUTION_FIDELITY_GATES["min_fills"] < PAPER_VALIDATION_GATES["min_trades"]


# ---------------------------------------------------------------------------
# Fill-sample check
# ---------------------------------------------------------------------------


def test_fill_sample_below_minimum_is_insufficient():
    c = _check_fill_sample(5)
    assert c.status == "insufficient_data"
    assert "10 more" in c.message  # 15 - 5


def test_fill_sample_at_minimum_passes():
    c = _check_fill_sample(15)
    assert c.status == "pass"


def test_fill_sample_above_minimum_passes():
    c = _check_fill_sample(40)
    assert c.status == "pass"


# ---------------------------------------------------------------------------
# Broker-link check
# ---------------------------------------------------------------------------


def test_broker_link_both_connected_passes():
    health = {"ibkr_data": 1, "ibkr_exec": 1, "kill_switch": 0, "ts_utc": "2026-06-01T19:00:00Z"}
    assert _check_broker_link(health).status == "pass"


def test_broker_link_degraded_fails():
    health = {"ibkr_data": 1, "ibkr_exec": 0, "kill_switch": 0, "ts_utc": "2026-06-01T19:00:00Z"}
    assert _check_broker_link(health).status == "fail"


def test_broker_link_no_snapshot_is_insufficient():
    assert _check_broker_link(None).status == "insufficient_data"


# ---------------------------------------------------------------------------
# Kill-switch check
# ---------------------------------------------------------------------------


def test_kill_switch_inactive_passes():
    health = {"ibkr_data": 1, "ibkr_exec": 1, "kill_switch": 0, "ts_utc": "2026-06-01T19:00:00Z"}
    assert _check_kill_switch_state(health).status == "pass"


def test_kill_switch_active_fails():
    health = {"ibkr_data": 1, "ibkr_exec": 1, "kill_switch": 1, "ts_utc": "2026-06-01T19:00:00Z"}
    c = _check_kill_switch_state(health)
    assert c.status == "fail"
    assert c.value == "ACTIVE"


# ---------------------------------------------------------------------------
# PF-floor check (sign-check, NOT the 2.0 edge gate)
# ---------------------------------------------------------------------------


def test_pf_floor_profitable_passes():
    rows = [{"pnl": 100.0}, {"pnl": 50.0}, {"pnl": -40.0}]  # PF = 150/40 = 3.75
    assert _check_pf_floor(rows).status == "pass"


def test_pf_floor_losing_fails():
    rows = [{"pnl": 20.0}, {"pnl": -100.0}, {"pnl": -50.0}]  # PF = 20/150 = 0.13
    assert _check_pf_floor(rows).status == "fail"


def test_pf_floor_marginal_winner_above_floor_passes():
    """PF between 1.0 and 2.0 PASSES fidelity (floor=1.0) but would FAIL the edge gate (2.0)."""
    rows = [{"pnl": 120.0}, {"pnl": -100.0}]  # PF = 1.2 — above 1.0 floor, below 2.0 edge
    assert _check_pf_floor(rows).status == "pass"


def test_pf_floor_no_pnl_is_insufficient():
    assert _check_pf_floor([]).status == "insufficient_data"

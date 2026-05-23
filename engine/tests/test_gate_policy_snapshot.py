"""Gate v2 policy snapshot tests.

These tests pin the exact gate v2 threshold values that determine which
strategies are allowed into paper/live trading.  Any change to these
constants must be an intentional, reviewed decision — not an accidental
edit or a copy-paste drift.

If a threshold needs to change, update BOTH the source constant AND the
expected value in this file, then document the change in the commit message
with the reason (e.g. "tighten ALT mc_dd ceiling from 7% to 4% — see P3-9").

DO NOT suppress these failures with pytest.mark.skip or xfail to make CI
pass — fix the discrepancy or update the snapshot with a reviewed commit.
"""

from __future__ import annotations

import sys
from pathlib import Path

_engine = Path(__file__).parent.parent
if str(_engine) not in sys.path:
    sys.path.insert(0, str(_engine))

from backtest._constants import (
    COST_TIER_ORDER,
    GATE_FIXED_PARAMS_MIN_PF,
    GATE_WFO_CONSISTENCY_VALUES,
)
from backtest._gate_v2_helpers import (
    GATE_DSR,
    GATE_DSR_ALT,
    GATE_MC_DD_ALT,
    GATE_MC_DD_CORE,
    GATE_P_EDGE,
    GATE_PF_CI_LOWER,
    MIN_OOS_TRADES_PER_WINDOW,
)

# ---------------------------------------------------------------------------
# Core path thresholds — strategies must exceed ALL of these to PASS core
# ---------------------------------------------------------------------------


def test_gate_pf_ci_lower_snapshot():
    """Bootstrap CI lower bound on OOS profit factors must be >= 1.10."""
    assert GATE_PF_CI_LOWER == 1.10, (
        f"GATE_PF_CI_LOWER changed: expected 1.10, got {GATE_PF_CI_LOWER}. "
        "Update this snapshot and document the change."
    )


def test_gate_p_edge_snapshot():
    """Fraction of profitable OOS windows must be >= 0.95 (core path)."""
    assert GATE_P_EDGE == 0.95, (
        f"GATE_P_EDGE changed: expected 0.95, got {GATE_P_EDGE}. "
        "Update this snapshot and document the change."
    )


def test_gate_mc_dd_core_snapshot():
    """Monte Carlo 95th-pctile max drawdown must be <= 5.0% (core path)."""
    assert GATE_MC_DD_CORE == 0.05, (
        f"GATE_MC_DD_CORE changed: expected 0.05, got {GATE_MC_DD_CORE}. "
        "Update this snapshot and document the change."
    )


def test_gate_dsr_snapshot():
    """Deflated Sharpe ratio must be >= 0.10 (core path)."""
    assert GATE_DSR == 0.10, (
        f"GATE_DSR changed: expected 0.10, got {GATE_DSR}. "
        "Update this snapshot and document the change."
    )


# ---------------------------------------------------------------------------
# ALT path thresholds — strategies may PASS alt if core fails, subject to:
# ---------------------------------------------------------------------------


def test_gate_mc_dd_alt_snapshot():
    """Monte Carlo 95th-pctile max drawdown must be <= 4.0% (ALT path — stricter DD)."""
    assert GATE_MC_DD_ALT == 0.04, (
        f"GATE_MC_DD_ALT changed: expected 0.04, got {GATE_MC_DD_ALT}. "
        "Update this snapshot and document the change."
    )


def test_gate_dsr_alt_snapshot():
    """Deflated Sharpe ratio must be >= 0.30 (ALT path — higher bar)."""
    assert GATE_DSR_ALT == 0.30, (
        f"GATE_DSR_ALT changed: expected 0.30, got {GATE_DSR_ALT}. "
        "Update this snapshot and document the change."
    )


def test_gate_fixed_params_min_pf_snapshot():
    """Fixed-params grid min profit factor must be >= 1.20 (ALT path)."""
    assert GATE_FIXED_PARAMS_MIN_PF == 1.20, (
        f"GATE_FIXED_PARAMS_MIN_PF changed: expected 1.20, got {GATE_FIXED_PARAMS_MIN_PF}. "
        "Update this snapshot and document the change."
    )


def test_gate_wfo_consistency_values_snapshot():
    """WFO consistency must be MODERATE or STRONG (ALT path) — not WEAK."""
    assert GATE_WFO_CONSISTENCY_VALUES == ["MODERATE", "STRONG"], (
        f"GATE_WFO_CONSISTENCY_VALUES changed: expected ['MODERATE', 'STRONG'], "
        f"got {GATE_WFO_CONSISTENCY_VALUES}. Update this snapshot and document the change."
    )


# ---------------------------------------------------------------------------
# Structural / ordering constraints
# ---------------------------------------------------------------------------


def test_cost_tier_order_snapshot():
    """Cost tier ordering must be optimistic → realistic → pessimistic → catastrophic."""
    expected = ["optimistic", "realistic", "pessimistic", "catastrophic"]
    assert (
        COST_TIER_ORDER == expected
    ), f"COST_TIER_ORDER changed: expected {expected}, got {COST_TIER_ORDER}."


def test_min_oos_trades_per_window_snapshot():
    """Minimum OOS trades per WFO window must be 5 (prevents low-sample verdict noise)."""
    assert MIN_OOS_TRADES_PER_WINDOW == 5, (
        f"MIN_OOS_TRADES_PER_WINDOW changed: expected 5, got {MIN_OOS_TRADES_PER_WINDOW}. "
        "Update this snapshot and document the change."
    )


# ---------------------------------------------------------------------------
# Relational invariants — these catch changes that violate internal consistency
# ---------------------------------------------------------------------------


def test_alt_dsr_stricter_than_core_dsr():
    """ALT DSR floor must be higher than core DSR floor (ALT compensates for lower p_edge)."""
    assert GATE_DSR_ALT > GATE_DSR, (
        f"ALT DSR {GATE_DSR_ALT} must be > core DSR {GATE_DSR}. "
        "The ALT path allows lower p_edge, so it must require higher DSR to maintain safety."
    )


def test_alt_mc_dd_stricter_than_core_mc_dd():
    """ALT DD ceiling must be tighter than core DD ceiling (ALT compensates elsewhere)."""
    assert GATE_MC_DD_ALT < GATE_MC_DD_CORE, (
        f"ALT mc_dd {GATE_MC_DD_ALT} must be < core mc_dd {GATE_MC_DD_CORE}. "
        "The ALT path allows weaker p_edge, so it must require a tighter drawdown ceiling."
    )


def test_pf_ci_lower_above_breakeven():
    """Bootstrap CI lower bound must be above breakeven (> 1.0) by a meaningful margin."""
    assert GATE_PF_CI_LOWER > 1.05, (
        f"GATE_PF_CI_LOWER={GATE_PF_CI_LOWER} is dangerously close to breakeven. "
        "The lower bound on the CI means the true PF could be lower. 1.10 is the floor."
    )


def test_p_edge_is_majority():
    """p_edge threshold must be a strong majority (> 0.5) — not just 'more wins than losses'."""
    assert GATE_P_EDGE > 0.5, (
        f"GATE_P_EDGE={GATE_P_EDGE} is not a strong majority. "
        "A value <= 0.5 would allow strategies with more losing than winning OOS windows."
    )


def test_cost_tier_order_has_four_tiers():
    """Cost tier order must have exactly 4 tiers."""
    assert (
        len(COST_TIER_ORDER) == 4
    ), f"COST_TIER_ORDER has {len(COST_TIER_ORDER)} tiers, expected 4."

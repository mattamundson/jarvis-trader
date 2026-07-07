"""
Gate v2 policy snapshot test — P3-10.

PURPOSE: Catch accidental threshold drift. All 34+ WFO runners import their
gate constants from _gate_v2_helpers. A silent change there silently changes
every runner's pass/fail behaviour with no audit trail.

WHAT THIS TEST DOES:
    Assert the canonical gate v2 constants match the last reviewed values.
    If any constant changes, this test fails with a clear diff so the
    reviewer can confirm the change was intentional (not a typo or accidental
    revert).

TO UPDATE LEGITIMATELY:
    1. Make the change in _gate_v2_helpers.py (single source of truth).
    2. Run this test — it will fail.
    3. Update the SNAPSHOT dict in this file to match the new values.
    4. Add a comment explaining WHY the threshold changed (the "why" decays
       fastest from git history, so it belongs here too).
    5. Commit both files in the same commit so the audit trail is atomic.

CHANGE LOG (newest first):
    2026-05-09  GATE_MC_DD_ALT 0.07 → 0.04  (tightened: both PASS-alt strategies
                sit at 0.81% and ~1.2% DD; 7% ceiling was excessively permissive;
                aligns with de-facto observed values and raises the bar for future
                ALT approvals)

Run:  cd engine && .venv/Scripts/python backtest/test_gate_v2_policy.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

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

# ---------------------------------------------------------------------------
# Snapshot — baseline values as of 2026-05-09 review
# ---------------------------------------------------------------------------

SNAPSHOT = {
    # Core path thresholds
    "GATE_PF_CI_LOWER": 1.10,
    "GATE_P_EDGE": 0.95,
    "GATE_MC_DD_CORE": 0.05,
    "GATE_DSR": 0.10,
    # ALT path thresholds (tightened 2026-05-09)
    "GATE_MC_DD_ALT": 0.04,
    "GATE_DSR_ALT": 0.30,
    # WFO defaults
    "WFO_TRAIN_MONTHS": 6,
    "WFO_TEST_MONTHS": 1,
    "WFO_STEP_MONTHS": 1,
    "MIN_OOS_TRADES_PER_WINDOW": 5,
    # Bootstrap
    "N_BOOTSTRAP": 2000,
    # Cost tier ordering
    "COST_TIER_ORDER": ["optimistic", "realistic", "pessimistic", "catastrophic"],
    # Cost tier commission (round-trip) and slippage_ticks
    "COST_SWEEP_TIERS_optimistic_commission": 0.31,
    "COST_SWEEP_TIERS_optimistic_slippage_ticks": 1.0,
    "COST_SWEEP_TIERS_realistic_commission": 0.62,
    "COST_SWEEP_TIERS_realistic_slippage_ticks": 1.0,
    "COST_SWEEP_TIERS_pessimistic_commission": 1.24,
    "COST_SWEEP_TIERS_pessimistic_slippage_ticks": 2.0,
    "COST_SWEEP_TIERS_catastrophic_commission": 2.48,
    "COST_SWEEP_TIERS_catastrophic_slippage_ticks": 3.0,
}

# ---------------------------------------------------------------------------
# Actual values
# ---------------------------------------------------------------------------

ACTUAL = {
    "GATE_PF_CI_LOWER": GATE_PF_CI_LOWER,
    "GATE_P_EDGE": GATE_P_EDGE,
    "GATE_MC_DD_CORE": GATE_MC_DD_CORE,
    "GATE_DSR": GATE_DSR,
    "GATE_MC_DD_ALT": GATE_MC_DD_ALT,
    "GATE_DSR_ALT": GATE_DSR_ALT,
    "WFO_TRAIN_MONTHS": WFO_TRAIN_MONTHS,
    "WFO_TEST_MONTHS": WFO_TEST_MONTHS,
    "WFO_STEP_MONTHS": WFO_STEP_MONTHS,
    "MIN_OOS_TRADES_PER_WINDOW": MIN_OOS_TRADES_PER_WINDOW,
    "N_BOOTSTRAP": N_BOOTSTRAP,
    "COST_TIER_ORDER": COST_TIER_ORDER,
    "COST_SWEEP_TIERS_optimistic_commission": COST_SWEEP_TIERS["optimistic"]["commission"],
    "COST_SWEEP_TIERS_optimistic_slippage_ticks": COST_SWEEP_TIERS["optimistic"]["slippage_ticks"],
    "COST_SWEEP_TIERS_realistic_commission": COST_SWEEP_TIERS["realistic"]["commission"],
    "COST_SWEEP_TIERS_realistic_slippage_ticks": COST_SWEEP_TIERS["realistic"]["slippage_ticks"],
    "COST_SWEEP_TIERS_pessimistic_commission": COST_SWEEP_TIERS["pessimistic"]["commission"],
    "COST_SWEEP_TIERS_pessimistic_slippage_ticks": COST_SWEEP_TIERS["pessimistic"][
        "slippage_ticks"
    ],
    "COST_SWEEP_TIERS_catastrophic_commission": COST_SWEEP_TIERS["catastrophic"]["commission"],
    "COST_SWEEP_TIERS_catastrophic_slippage_ticks": COST_SWEEP_TIERS["catastrophic"][
        "slippage_ticks"
    ],
}


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------


def test_gate_v2_policy_snapshot():
    failures = []
    for key, expected in SNAPSHOT.items():
        actual = ACTUAL[key]
        if actual != expected:
            failures.append(
                f"  {key}:\n" f"    expected : {expected!r}\n" f"    actual   : {actual!r}"
            )

    if failures:
        diff = "\n".join(failures)
        raise AssertionError(
            "Gate v2 policy snapshot FAILED — threshold(s) changed:\n\n" + diff + "\n\n"
            "If this change was INTENTIONAL:\n"
            "  1. Update SNAPSHOT in test_gate_v2_policy.py to match.\n"
            "  2. Add a comment under CHANGE LOG explaining WHY.\n"
            "  3. Commit both files atomically.\n"
            "If NOT intentional, revert _gate_v2_helpers.py."
        )

    print(f"[PASS] Gate v2 policy snapshot — {len(SNAPSHOT)} constants verified.")


if __name__ == "__main__":
    try:
        test_gate_v2_policy_snapshot()
        sys.exit(0)
    except AssertionError as exc:
        print(f"[FAIL] {exc}")
        sys.exit(1)

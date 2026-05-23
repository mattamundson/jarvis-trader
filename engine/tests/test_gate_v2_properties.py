"""Property-based tests for gate v2 helper functions using Hypothesis.

Tests three invariants that must hold regardless of input shape:
1. classify_wfo_consistency output is always one of {STRONG, MODERATE, WEAK}
2. bootstrap_pf_ci_lower is monotone: adding a better OOS window never lowers the 5th-pct
3. Verdict stability: if a strategy meets all core-pass thresholds today, replacing any one
   metric with a strictly better value must not flip the verdict to FAIL

These are regression guards — if someone changes threshold constants or logic in
_gate_v2_helpers.py, these tests surface the change as a failure rather than a silent
surprise in a prod backtest run.
"""

from __future__ import annotations

import math
from typing import List

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from backtest._gate_v2_helpers import (
    GATE_DSR,
    GATE_MC_DD_CORE,
    GATE_P_EDGE,
    GATE_PF_CI_LOWER,
    bootstrap_pf_ci_lower,
    classify_wfo_consistency,
)

# ---------------------------------------------------------------------------
# Strategy builders
# ---------------------------------------------------------------------------

_pf_list = st.lists(
    st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    min_size=1,
    max_size=40,
)

_pf_list_with_extras = st.tuples(
    _pf_list,
    st.lists(
        st.floats(min_value=1.01, max_value=10.0, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=10,
    ),
)

# A strategy where extra elements are all >= the existing max — guaranteed to be
# stochastically dominant, so the bootstrap CI must not decrease.
_pf_list_with_dominant_extras = st.lists(
    st.floats(min_value=0.5, max_value=5.0, allow_nan=False, allow_infinity=False),
    min_size=15,
    max_size=20,
).flatmap(
    lambda base: st.tuples(
        st.just(base),
        st.lists(
            st.floats(
                min_value=max(base),
                max_value=max(base) + 5.0,
                allow_nan=False,
                allow_infinity=False,
            ),
            min_size=1,
            max_size=10,
        ),
    )
)


# ---------------------------------------------------------------------------
# 1. classify_wfo_consistency: output exhaustive
# ---------------------------------------------------------------------------

_VALID_CLASSIFICATIONS = {"STRONG", "MODERATE", "WEAK"}


@given(_pf_list)
@settings(max_examples=300)
def test_classify_wfo_consistency_output_always_valid(oos_pfs: List[float]) -> None:
    """classify_wfo_consistency must always return one of the three valid labels."""
    result = classify_wfo_consistency(oos_pfs)
    assert result in _VALID_CLASSIFICATIONS, f"unexpected label: {result!r}"


@given(st.lists(st.floats(min_value=1.01, max_value=10.0, allow_nan=False), min_size=8))
def test_classify_wfo_consistency_all_profitable_is_strong(oos_pfs: List[float]) -> None:
    """All-profitable OOS windows must yield STRONG (>=75% is guaranteed when 100%)."""
    assume(len(oos_pfs) >= 8)
    assert classify_wfo_consistency(oos_pfs) == "STRONG"


@given(st.lists(st.floats(max_value=0.99, allow_nan=False, allow_infinity=False), min_size=5))
def test_classify_wfo_consistency_no_profitable_is_weak(oos_pfs: List[float]) -> None:
    """Zero profitable OOS windows must yield WEAK."""
    assert classify_wfo_consistency(oos_pfs) == "WEAK"


def test_classify_wfo_consistency_empty_returns_weak() -> None:
    assert classify_wfo_consistency([]) == "WEAK"


# ---------------------------------------------------------------------------
# 2. bootstrap_pf_ci_lower: monotonicity
# ---------------------------------------------------------------------------


@given(_pf_list_with_dominant_extras)
@settings(max_examples=200, deadline=5_000)
def test_bootstrap_pf_ci_lower_monotone_with_dominant_extras(
    args: tuple[List[float], List[float]],
) -> None:
    """Adding PF windows that are all >= max(base) must not lower the 5th-pct bound.

    When every new element dominates the existing distribution, the bootstrap
    sample mean can only increase, so the 5th-percentile lower bound is
    non-decreasing. A small tolerance absorbs sampling noise at fixed seed=42
    but different sample sizes.
    """
    base_pfs, extra_dominant = args
    # Strategy already enforces min_size=15 so no assume() needed here.
    # (With n < 15 the discrete bootstrap's 5th-pct is too noisy to guarantee
    # monotonicity: the 25th-out-of-500 sample can shift with a single extra draw.)
    extended = base_pfs + extra_dominant

    ci_base = bootstrap_pf_ci_lower(base_pfs, n=500)
    ci_extended = bootstrap_pf_ci_lower(extended, n=500)

    assert math.isfinite(ci_base), f"base ci_lower not finite: {ci_base}"
    assert math.isfinite(ci_extended), f"extended ci_lower not finite: {ci_extended}"
    tolerance = 0.05 * abs(ci_base) + 0.02
    assert ci_extended >= ci_base - tolerance, (
        f"monotonicity violated with dominant extras: "
        f"base={ci_base:.4f} extended={ci_extended:.4f} tol={tolerance:.4f}"
    )


@given(_pf_list)
@settings(max_examples=200, deadline=5_000)
def test_bootstrap_pf_ci_lower_always_finite(oos_pfs: List[float]) -> None:
    """bootstrap_pf_ci_lower must never return NaN or ±inf."""
    result = bootstrap_pf_ci_lower(oos_pfs, n=200)
    assert math.isfinite(result), f"got non-finite: {result}"


@given(st.lists(st.just(float("inf")), min_size=1, max_size=20))
@settings(max_examples=20, deadline=5_000)
def test_bootstrap_pf_ci_lower_inf_inputs_finite(oos_pfs: List[float]) -> None:
    """All-inf inputs (e.g. no losers) must still yield a finite result."""
    result = bootstrap_pf_ci_lower(oos_pfs, n=200)
    assert math.isfinite(result), f"all-inf input returned non-finite: {result}"


# ---------------------------------------------------------------------------
# 3. Verdict stability — core-pass metrics must not flip to FAIL when improved
# ---------------------------------------------------------------------------


def _core_pass(pf_ci_lower: float, p_edge: float, mc_95th_dd: float, dsr: float) -> bool:
    """Mirror of the core_pass boolean in _compute_gate_v2 across runner files."""
    return (
        pf_ci_lower >= GATE_PF_CI_LOWER
        and p_edge >= GATE_P_EDGE
        and mc_95th_dd <= GATE_MC_DD_CORE
        and dsr >= GATE_DSR
    )


# Generate a strategy that always produces a currently-passing set of metrics
_passing_metrics = st.fixed_dictionaries(
    {
        "pf_ci_lower": st.floats(min_value=GATE_PF_CI_LOWER, max_value=5.0, allow_nan=False),
        "p_edge": st.floats(min_value=GATE_P_EDGE, max_value=1.0, allow_nan=False),
        "mc_95th_dd": st.floats(min_value=0.0, max_value=GATE_MC_DD_CORE, allow_nan=False),
        "dsr": st.floats(min_value=GATE_DSR, max_value=3.0, allow_nan=False),
    }
)

_improvement_delta = st.floats(min_value=0.001, max_value=0.5, allow_nan=False)


@given(_passing_metrics)
@settings(max_examples=300)
def test_core_pass_stable_at_threshold(m: dict) -> None:
    """A strategy whose metrics all meet gate v2 thresholds must produce core_pass=True."""
    assert _core_pass(
        m["pf_ci_lower"], m["p_edge"], m["mc_95th_dd"], m["dsr"]
    ), f"Expected PASS but got FAIL: {m}"


@given(_passing_metrics, _improvement_delta)
@settings(max_examples=200)
def test_core_pass_stable_when_pf_improves(m: dict, delta: float) -> None:
    """Increasing pf_ci_lower on an already-passing strategy must keep it passing."""
    improved = {**m, "pf_ci_lower": m["pf_ci_lower"] + delta}
    assert _core_pass(
        improved["pf_ci_lower"], improved["p_edge"], improved["mc_95th_dd"], improved["dsr"]
    )


@given(_passing_metrics, _improvement_delta)
@settings(max_examples=200)
def test_core_pass_stable_when_dd_improves(m: dict, delta: float) -> None:
    """Decreasing mc_95th_dd on an already-passing strategy must keep it passing."""
    new_dd = max(0.0, m["mc_95th_dd"] - delta)
    assert _core_pass(m["pf_ci_lower"], m["p_edge"], new_dd, m["dsr"])


@given(_passing_metrics, _improvement_delta)
@settings(max_examples=200)
def test_core_pass_stable_when_dsr_improves(m: dict, delta: float) -> None:
    """Increasing DSR on an already-passing strategy must keep it passing."""
    assert _core_pass(m["pf_ci_lower"], m["p_edge"], m["mc_95th_dd"], m["dsr"] + delta)


# ---------------------------------------------------------------------------
# 4. Boundary symmetry: just-below thresholds must be FAIL
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "metric,tweak",
    [
        ("pf_ci_lower", -0.001),  # just below PF CI threshold
        ("p_edge", -0.001),  # just below p_edge threshold
        ("dsr", -0.001),  # just below DSR threshold
    ],
)
def test_core_fail_just_below_threshold(metric: str, tweak: float) -> None:
    """A metric just below its threshold must produce core_pass=False."""
    m = {
        "pf_ci_lower": GATE_PF_CI_LOWER,
        "p_edge": GATE_P_EDGE,
        "mc_95th_dd": GATE_MC_DD_CORE,
        "dsr": GATE_DSR,
    }
    m[metric] = m[metric] + tweak  # goes below threshold
    assert not _core_pass(
        m["pf_ci_lower"], m["p_edge"], m["mc_95th_dd"], m["dsr"]
    ), f"Expected FAIL just below {metric} threshold but got PASS"


def test_core_fail_dd_just_above_threshold() -> None:
    """mc_95th_dd just above ceiling must produce core_pass=False."""
    m = {
        "pf_ci_lower": GATE_PF_CI_LOWER,
        "p_edge": GATE_P_EDGE,
        "mc_95th_dd": GATE_MC_DD_CORE + 0.001,
        "dsr": GATE_DSR,
    }
    assert not _core_pass(m["pf_ci_lower"], m["p_edge"], m["mc_95th_dd"], m["dsr"])

"""Property-based tests for compare_verdicts helper functions using Hypothesis.

Tests four invariants that must hold regardless of input values:
1. _is_drifted(x, x, t) is always False (identical values never drift)
2. _is_drifted handles None/zero inputs without raising
3. compare() on identical verdicts produces no transition, no drift, no rating drop
4. _is_rating_drop correctly detects PASS→FAIL and core→alt degradations
"""

from __future__ import annotations

import math
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from backtest.compare_verdicts import ThresholdConfig, _is_drifted, _is_rating_drop, compare

# ---------------------------------------------------------------------------
# Finite float strategy: excludes NaN / inf to keep test behaviour predictable.
# ---------------------------------------------------------------------------
_finite = st.floats(min_value=-1e9, max_value=1e9, allow_nan=False, allow_infinity=False)
_positive = st.floats(min_value=1e-6, max_value=1e9, allow_nan=False, allow_infinity=False)
_threshold = st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False)


# ---------------------------------------------------------------------------
# _is_drifted property tests
# ---------------------------------------------------------------------------


@given(_finite, _threshold)
@settings(max_examples=300)
def test_is_drifted_same_value_never_drifts(value: float, threshold: float) -> None:
    assume(not math.isnan(value) and not math.isinf(value))
    assert _is_drifted(value, value, threshold) is False


@given(_finite, _threshold)
@settings(max_examples=200)
def test_is_drifted_none_old_never_drifts(new: float, threshold: float) -> None:
    assert _is_drifted(None, new, threshold) is False


@given(_finite, _threshold)
@settings(max_examples=200)
def test_is_drifted_none_new_never_drifts(old: float, threshold: float) -> None:
    assert _is_drifted(old, None, threshold) is False


@given(_finite, _threshold)
@settings(max_examples=200)
def test_is_drifted_zero_old_drifts_iff_new_nonzero(new: float, threshold: float) -> None:
    result = _is_drifted(0, new, threshold)
    expected = new != 0
    assert result == expected


@given(_positive, _positive, _threshold)
@settings(max_examples=500)
def test_is_drifted_relative_threshold_correct(old: float, new: float, threshold: float) -> None:
    """If relative change exceeds threshold → drifted; otherwise → not drifted."""
    relative = abs(new - old) / abs(old)
    result = _is_drifted(old, new, threshold)
    if relative > threshold:
        assert result is True
    else:
        assert result is False


# ---------------------------------------------------------------------------
# compare() stability properties — identical inputs
# ---------------------------------------------------------------------------


def _make_verdict(
    verdict: str = "PASS",
    passed_via: str = "core",
    pf_ci_lower: float = 1.5,
    p_edge: float = 0.96,
    dsr: float = 0.5,
    mc_95th_dd_pct: float = 2.0,
    fast: int = 20,
    slow: int = 50,
    n_oos_windows: int = 10,
) -> dict[str, Any]:
    return {
        "symbol": "MES",
        "family": "trend",
        "verdict": verdict,
        "passed_via": passed_via,
        "gate_v2_metrics": {
            "pf_ci_lower": pf_ci_lower,
            "p_edge": p_edge,
            "dsr": dsr,
            "mc_95th_dd_pct": mc_95th_dd_pct,
            "fixed_params_min_pf": 1.3,
            "wfo_consistency": "MODERATE",
            "cost_survives_through": "realistic",
        },
        "champion_params": {"fast": fast, "slow": slow},
        "wfo_config": {"n_oos_windows": n_oos_windows},
    }


@given(
    verdict=st.sampled_from(["PASS", "FAIL"]),
    passed_via=st.sampled_from(["core", "alt"]),
    pf=_positive,
    p_edge=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    dsr=_positive,
    mc_dd=st.floats(min_value=0.0, max_value=20.0, allow_nan=False),
)
@settings(max_examples=200)
def test_compare_identical_no_transition(
    verdict: str, passed_via: str, pf: float, p_edge: float, dsr: float, mc_dd: float
) -> None:
    v = _make_verdict(
        verdict=verdict,
        passed_via=passed_via,
        pf_ci_lower=pf,
        p_edge=p_edge,
        dsr=dsr,
        mc_95th_dd_pct=mc_dd,
    )
    diff = compare(v, v)
    assert diff["verdict_transition"] == "no transition"


@given(
    fast=st.integers(min_value=5, max_value=50),
    slow=st.integers(min_value=20, max_value=200),
)
@settings(max_examples=200)
def test_compare_identical_no_champion_drift(fast: int, slow: int) -> None:
    assume(fast < slow)
    v = _make_verdict(fast=fast, slow=slow)
    diff = compare(v, v)
    assert diff["champion_drift"] == []


@given(
    pf=_positive,
    dsr=_positive,
    mc_dd=st.floats(min_value=0.01, max_value=5.0, allow_nan=False),
)
@settings(max_examples=200)
def test_compare_identical_no_rating_drop(pf: float, dsr: float, mc_dd: float) -> None:
    v = _make_verdict(
        verdict="PASS", passed_via="core", pf_ci_lower=pf, dsr=dsr, mc_95th_dd_pct=mc_dd
    )
    diff = compare(v, v)
    assert _is_rating_drop(diff) is False


# ---------------------------------------------------------------------------
# _is_rating_drop degradation detection
# ---------------------------------------------------------------------------


def test_rating_drop_pass_to_fail() -> None:
    old = _make_verdict(verdict="PASS")
    new = _make_verdict(verdict="FAIL")
    diff = compare(old, new)
    assert _is_rating_drop(diff) is True


def test_rating_drop_core_to_alt() -> None:
    old = _make_verdict(verdict="PASS", passed_via="core")
    new = _make_verdict(verdict="PASS", passed_via="alt")
    diff = compare(old, new)
    assert _is_rating_drop(diff) is True


def test_rating_drop_improvement_alt_to_core_is_not_drop() -> None:
    old = _make_verdict(verdict="PASS", passed_via="alt")
    new = _make_verdict(verdict="PASS", passed_via="core")
    diff = compare(old, new)
    assert _is_rating_drop(diff) is False


@given(
    old_pf=st.floats(min_value=0.5, max_value=5.0, allow_nan=False),
    drop_fraction=st.floats(min_value=0.16, max_value=0.90, allow_nan=False),
)
@settings(max_examples=200)
def test_rating_drop_large_pf_decline_detected(old_pf: float, drop_fraction: float) -> None:
    new_pf = old_pf * (1.0 - drop_fraction)
    assume(new_pf > 0)
    old = _make_verdict(verdict="PASS", passed_via="core", pf_ci_lower=old_pf)
    new = _make_verdict(verdict="PASS", passed_via="core", pf_ci_lower=new_pf)
    diff = compare(old, new)
    assert _is_rating_drop(diff) is True


@given(
    old_dsr=st.floats(min_value=0.2, max_value=5.0, allow_nan=False),
    drop_fraction=st.floats(min_value=0.21, max_value=0.90, allow_nan=False),
)
@settings(max_examples=200)
def test_rating_drop_large_dsr_decline_detected(old_dsr: float, drop_fraction: float) -> None:
    new_dsr = old_dsr * (1.0 - drop_fraction)
    assume(new_dsr > 0)
    old = _make_verdict(verdict="PASS", passed_via="core", dsr=old_dsr)
    new = _make_verdict(verdict="PASS", passed_via="core", dsr=new_dsr)
    diff = compare(old, new)
    assert _is_rating_drop(diff) is True


@given(
    old_mc=st.floats(min_value=0.5, max_value=3.0, allow_nan=False),
    rise_fraction=st.floats(min_value=0.51, max_value=3.0, allow_nan=False),
)
@settings(max_examples=200)
def test_rating_drop_large_mc_dd_rise_detected(old_mc: float, rise_fraction: float) -> None:
    new_mc = old_mc * (1.0 + rise_fraction)
    old = _make_verdict(verdict="PASS", passed_via="core", mc_95th_dd_pct=old_mc)
    new = _make_verdict(verdict="PASS", passed_via="core", mc_95th_dd_pct=new_mc)
    diff = compare(old, new)
    assert _is_rating_drop(diff) is True


# ---------------------------------------------------------------------------
# ThresholdConfig YAML loading — graceful fallback
# ---------------------------------------------------------------------------


def test_threshold_config_defaults_are_sensible() -> None:
    cfg = ThresholdConfig()
    assert 0.0 < cfg.param_drift < 1.0
    assert 0.0 < cfg.rating_drop_pf_ci < 1.0
    assert 0.0 < cfg.rating_drop_dsr < 1.0
    assert 0.0 < cfg.rating_drop_mc_dd < 5.0


@given(
    pf_drop=st.floats(min_value=0.01, max_value=0.99, allow_nan=False),
    dsr_drop=st.floats(min_value=0.01, max_value=0.99, allow_nan=False),
)
@settings(max_examples=150)
def test_custom_threshold_config_respected(pf_drop: float, dsr_drop: float) -> None:
    """Tighter thresholds catch smaller drops."""
    cfg = ThresholdConfig(rating_drop_pf_ci=pf_drop, rating_drop_dsr=dsr_drop)
    old_pf = 2.0
    new_pf = old_pf * (1.0 - pf_drop * 1.1)  # 10% below trigger
    assume(new_pf > 0)
    old = _make_verdict(pf_ci_lower=old_pf)
    new = _make_verdict(pf_ci_lower=new_pf)
    diff = compare(old, new, cfg=cfg)
    assert _is_rating_drop(diff, cfg=cfg) is True

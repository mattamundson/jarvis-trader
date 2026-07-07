"""Tests for the two gate-v2 policy layers in validate_strategy._evaluate_gate_v2:

  #3 H1/H2 stationarity ENFORCEMENT — overrides a PASS to FAIL on positive
     non-stationarity evidence (adequate sample AND a losing half). Absence of
     evidence (sparse / no stationarity) must NOT block.
  #4 Beta-harvest p_edge RELAXATION — rescues a CORE failure whose sole failing
     criterion is p_edge, when tagged beta_harvest + H1/H2 consistent + p_edge>=0.60.

Both must be behavior-neutral when their inputs are absent (legacy callers).

Run:  cd engine && .venv/Scripts/python scripts/test_gate_stationarity_betaharvest.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ENGINE = Path(__file__).resolve().parent.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from scripts.validate_strategy import (  # noqa: E402
    _CORE_P_EDGE_IDX,
    _evaluate_gate_v2,
    _score_core_gate,
)


def _report(pf_ci=1.50, p_edge=0.99, mc=3.0, dsr=0.50):
    """Minimal report with the four keys _score_core_gate reads. Defaults all
    PASS core; override one to engineer a specific failure pattern."""
    return {
        "bootstrap_block": {"pf_ci_95_low": pf_ci},
        "bootstrap_iid": {"p_positive_edge": p_edge},
        "drawdown_mc": {"mc_95th": mc},
        "deflated_sharpe": {"dsr": dsr},
    }


def _stat(adequate=True, both=True, h1=1.5, h2=1.5, h1n=12, h2n=12):
    return {
        "consistent": bool(adequate and both),
        "sample_adequate": adequate,
        "both_profitable": both,
        "h1_pf": h1,
        "h2_pf": h2,
        "h1_n": h1n,
        "h2_n": h2n,
    }


_NONSTAT = _stat(both=False, h1=0.9, h2=5.0)  # adequate, a losing half
_CONSISTENT = _stat(both=True)
_SPARSE = _stat(adequate=False, both=False, h1n=3, h2n=3)


# ---------------------------------------------------------------- p_edge index
def test_core_pedge_index_contract():
    """A report failing ONLY p_edge must show core_passes[_CORE_P_EDGE_IDX] False
    and every other criterion True — pins the index the rescue targets."""
    passes, _ = _score_core_gate(_report(p_edge=0.70))
    assert passes[_CORE_P_EDGE_IDX] is False
    assert sum(1 for p in passes if not p) == 1
    print("[PASS] _CORE_P_EDGE_IDX targets the p_edge criterion")


# ---------------------------------------------------------------- #3 enforcement
def test_enforce_blocks_nonstationary_pass():
    g = _evaluate_gate_v2(_report(), stationarity=_NONSTAT, enforce_h1h2=True)
    assert g["verdict"] == "FAIL"
    assert g["stationarity_block"] is True
    assert g["stationarity_verdict"] == "NON_STATIONARY"
    assert g["passed_via"] is None
    print("[PASS] enforce overrides a non-stationary PASS to FAIL")


def test_record_only_when_disabled():
    g = _evaluate_gate_v2(_report(), stationarity=_NONSTAT, enforce_h1h2=False)
    assert g["verdict"] == "PASS"
    assert g["stationarity_block"] is False
    assert g["stationarity_verdict"] == "NON_STATIONARY"  # still recorded
    print("[PASS] enforce OFF -> non-stationarity recorded but not blocking")


def test_insufficient_sample_not_blocked():
    g = _evaluate_gate_v2(_report(), stationarity=_SPARSE, enforce_h1h2=True)
    assert g["verdict"] == "PASS"
    assert g["stationarity_block"] is False
    assert g["stationarity_verdict"] == "INSUFFICIENT_SAMPLE"
    print("[PASS] sparse sample is not blocked (absence of evidence)")


def test_consistent_not_blocked():
    g = _evaluate_gate_v2(_report(), stationarity=_CONSISTENT, enforce_h1h2=True)
    assert g["verdict"] == "PASS"
    assert g["stationarity_block"] is False
    assert g["stationarity_verdict"] == "CONSISTENT"
    print("[PASS] consistent split passes enforcement")


def test_none_stationarity_is_backward_compatible():
    g1 = _evaluate_gate_v2(_report())  # legacy call, no stationarity
    g2 = _evaluate_gate_v2(_report(), stationarity=None, enforce_h1h2=True)
    assert g1["verdict"] == g2["verdict"] == "PASS"
    assert g2["stationarity_verdict"] == "UNSCORED"
    assert g2["stationarity_block"] is False
    print("[PASS] stationarity=None preserves legacy behavior")


# ---------------------------------------------------------------- #4 beta-harvest
def test_beta_harvest_rescues_sole_pedge_fail():
    g = _evaluate_gate_v2(
        _report(p_edge=0.70),  # fails ONLY p_edge (0.70 in [0.60, 0.95))
        stationarity=_CONSISTENT,
        strategy_class="beta_harvest",
        beta_harvest_enforce=True,
        enforce_h1h2=True,
    )
    assert g["beta_harvest_applied"] is True
    assert g["core_verdict"] == "PASS"
    assert g["verdict"] == "PASS"
    assert g["passed_via"] == "core(beta_harvest)"
    print("[PASS] beta-harvest rescues a sole-p_edge core failure")


def test_beta_harvest_off_no_rescue():
    g = _evaluate_gate_v2(
        _report(p_edge=0.70),
        stationarity=_CONSISTENT,
        strategy_class="beta_harvest",
        beta_harvest_enforce=False,
        enforce_h1h2=False,
    )
    assert g["beta_harvest_applied"] is False
    assert g["core_verdict"] == "FAIL"
    print("[PASS] beta-harvest flag OFF -> no rescue")


def test_beta_harvest_requires_class_tag():
    g = _evaluate_gate_v2(
        _report(p_edge=0.70),
        stationarity=_CONSISTENT,
        strategy_class="",  # untagged
        beta_harvest_enforce=True,
        enforce_h1h2=False,
    )
    assert g["beta_harvest_applied"] is False
    assert g["core_verdict"] == "FAIL"
    print("[PASS] rescue requires strategy_class == beta_harvest")


def test_beta_harvest_not_sole_failure():
    g = _evaluate_gate_v2(
        _report(p_edge=0.70, dsr=0.05),  # fails p_edge AND dsr
        stationarity=_CONSISTENT,
        strategy_class="beta_harvest",
        beta_harvest_enforce=True,
        enforce_h1h2=False,
    )
    assert g["beta_harvest_applied"] is False
    assert g["core_verdict"] == "FAIL"
    print("[PASS] no rescue when p_edge is not the sole failure")


def test_beta_harvest_pedge_below_floor():
    g = _evaluate_gate_v2(
        _report(p_edge=0.50),  # below the 0.60 relaxed floor
        stationarity=_CONSISTENT,
        strategy_class="beta_harvest",
        beta_harvest_enforce=True,
        enforce_h1h2=False,
    )
    assert g["beta_harvest_applied"] is False
    print("[PASS] no rescue when p_edge < relaxed floor 0.60")


def test_beta_harvest_requires_consistent_h1h2():
    g = _evaluate_gate_v2(
        _report(p_edge=0.70),
        stationarity=_NONSTAT,  # not consistent
        strategy_class="beta_harvest",
        beta_harvest_enforce=True,
        enforce_h1h2=False,  # isolate the rescue path
    )
    assert g["beta_harvest_applied"] is False
    print("[PASS] no rescue when H1/H2 is not consistent")


def main():
    tests = [
        test_core_pedge_index_contract,
        test_enforce_blocks_nonstationary_pass,
        test_record_only_when_disabled,
        test_insufficient_sample_not_blocked,
        test_consistent_not_blocked,
        test_none_stationarity_is_backward_compatible,
        test_beta_harvest_rescues_sole_pedge_fail,
        test_beta_harvest_off_no_rescue,
        test_beta_harvest_requires_class_tag,
        test_beta_harvest_not_sole_failure,
        test_beta_harvest_pedge_below_floor,
        test_beta_harvest_requires_consistent_h1h2,
    ]
    failures = []
    for t in tests:
        try:
            t()
        except Exception as exc:
            print(f"[FAIL] {t.__name__}: {exc}")
            failures.append(t.__name__)
    print(f"\n{'=' * 60}")
    if failures:
        print(f"FAILED {len(failures)}/{len(tests)} tests: {', '.join(failures)}")
        sys.exit(1)
    print(f"ALL {len(tests)} gate stationarity/beta-harvest tests PASSED.")
    sys.exit(0)


if __name__ == "__main__":
    main()

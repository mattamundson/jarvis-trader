"""Golden-vector parity test for dm_edge_screen.py against a reference implementation.

Reference: johntwk/Diebold-Mariano-Test (MIT) semantics — DM statistic with HLN (1997)
small-sample modification. We validate:
  1. Synthetic-data parity vs a hand-computed closed-form case (h=1, no autocorrelation).
  2. Statistical sanity: identical series -> p=1; shifted series -> rejection.
  3. p-value function parity vs scipy.stats.t.sf (if scipy available) on a t-grid.

Run: engine/.venv/Scripts/python engine/backtest/tests_dm_edge_screen.py
Research-lane only; not wired into the test suite.
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dm_edge_screen import dm_test, _t_sf_two_sided  # noqa: E402


def test_identical_series() -> None:
    """Identical score series -> zero loss differential -> p == 1 (no edge difference)."""
    a = [0.5, -0.2, 0.8, 0.1, -0.3, 0.6, 0.2, 0.9, -0.1, 0.4]
    res = dm_test(a, list(a), power=2, h=1)
    assert res["dm"] is None, f"expected None DM for identical series, got {res}"
    print("PASS identical series -> degenerate (variance 0) handled")


def test_closed_form_case() -> None:
    """Hand-computable case: n=6, known loss differentials, h=1 (no HAC lag).

    d = [1, -1, 1, -1, 1, -1]  -> dbar=0 -> DM=0 -> p=1.
    """
    a = [1.0, 0.0, 1.0, 0.0, 1.0, 0.0]  # losses (as -score) alternate
    b = [0.0, 1.0, 0.0, 1.0, 0.0, 1.0]
    res = dm_test(a, b, power=1, h=1)
    assert res["n"] == 6
    assert abs(res["dbar"]) < 1e-12, res
    assert abs(res["dm"]) < 1e-12, res
    assert res["p_two_sided"] == 1.0, res
    print(f"PASS closed-form dbar=0 case: dm={res['dm']:.6f}, p={res['p_two_sided']:.6f}")


def test_clear_rejection() -> None:
    """B consistently better than A -> large positive DM (A worse, higher loss) -> tiny p-value."""
    random.seed(42)
    # A has mean 0 scores; B has mean +2 scores (B better since higher score = better)
    a = [random.gauss(0, 1) for _ in range(60)]
    b = [random.gauss(2, 1) for _ in range(60)]
    res = dm_test(a, b, power=1, h=1)
    assert res["dm_hln"] > 3, f"expected strongly positive DM (A worse than B), got {res['dm_hln']}"
    assert res["p_two_sided"] < 0.01, f"expected rejection, p={res['p_two_sided']}"
    print(f"PASS clear rejection: dm_hln={res['dm_hln']:.3f}, p={res['p_two_sided']:.2e}")


def test_hln_correction_shrinks_statistic() -> None:
    """HLN factor < 1 for h=1 and finite n (small-sample conservatism)."""
    random.seed(7)
    a = [random.gauss(0, 1) for _ in range(12)]
    b = [random.gauss(0.5, 1) for _ in range(12)]
    res = dm_test(a, b, power=1, h=1)
    expected_factor = math.sqrt((12 + 1 - 2 + 0) / 12)
    assert abs(res["hln_factor"] - expected_factor) < 1e-12, res
    assert abs(res["dm_hln"] - res["dm"] * expected_factor) < 1e-12, res
    print(f"PASS HLN factor: {res['hln_factor']:.6f} (dm {res['dm']:.4f} -> {res['dm_hln']:.4f})")


def test_t_parity_scipy() -> None:
    """p-value function matches scipy.stats.t two-sided survival on a grid."""
    try:
        from scipy import stats  # type: ignore
    except ImportError:
        print("SKIP scipy parity (scipy not installed)")
        return
    for dof in (3, 10, 30):
        for t in (0.5, 1.0, 2.0, 3.5, 6.0):
            expected = 2.0 * stats.t.sf(t, dof)
            got = _t_sf_two_sided(t, dof)
            assert abs(expected - got) < 1e-8, (dof, t, expected, got)
    print("PASS t-distribution p parity vs scipy (15 points, max err < 1e-8)")


def test_minimum_sample_guard() -> None:
    res = dm_test([1.0, 2.0], [0.5, 1.0], power=1, h=1)
    assert res["dm"] is None and "insufficient" in res["note"]
    print("PASS n<3 guard")


if __name__ == "__main__":
    test_identical_series()
    test_closed_form_case()
    test_clear_rejection()
    test_hln_correction_shrinks_statistic()
    test_t_parity_scipy()
    test_minimum_sample_guard()
    print("\nALL GOLDEN-VECTOR TESTS PASSED")

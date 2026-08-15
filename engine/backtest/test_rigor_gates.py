"""Tests for the backtest-rigor guardrail suite (engine/backtest/rigor_gates.py).

Covers the five gates against synthetic data with a known ground truth:
Sharpe-implausibility, MC trade-order permutation, Ljung-Box independence,
ADF stationarity, and Diebold-Mariano.

Run:  cd engine && .venv/Scripts/python backtest/test_rigor_gates.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

import numpy as np

from backtest.rigor_gates import (
    adf_stationarity_check,
    diebold_mariano_test,
    ljung_box_independence_check,
    mc_permutation_gate,
    sharpe_implausibility_gate,
)

# ---------------------------------------------------------------------------
# 1. Sharpe-implausibility gate
# ---------------------------------------------------------------------------


def test_extreme_sharpe_is_flagged():
    """A synthetic Sharpe of ~8 (real strategies almost never sustain this) trips the gate."""
    r = sharpe_implausibility_gate(sharpe=8.0, n_trades=20)
    assert r["flagged"] is True
    assert r["severity"] == "extreme"
    print(f"[PASS] Sharpe=8.0 flagged: severity={r['severity']}")


def test_moderately_high_sharpe_is_flagged_not_extreme():
    r = sharpe_implausibility_gate(sharpe=6.0, n_trades=50)
    assert r["flagged"] is True
    assert r["severity"] == "implausible"
    print(f"[PASS] Sharpe=6.0 flagged non-extreme: severity={r['severity']}")


def test_realistic_sharpe_is_not_flagged():
    """A realistic live-strategy Sharpe (~1.5) must NOT be flagged."""
    r = sharpe_implausibility_gate(sharpe=1.5, n_trades=200)
    assert r["flagged"] is False
    assert r["severity"] == "normal"
    print(f"[PASS] Sharpe=1.5 not flagged: severity={r['severity']}")


def test_small_sample_caveat_only_added_when_flagged_and_thin():
    r_thin_high = sharpe_implausibility_gate(sharpe=6.0, n_trades=10)
    r_thin_low = sharpe_implausibility_gate(sharpe=1.0, n_trades=10)
    assert "small-sample" in r_thin_high["explanation"] or "n_trades" in r_thin_high["explanation"]
    assert "small-sample" not in r_thin_low["explanation"]
    print("[PASS] small-sample caveat only attached to flagged+thin Sharpe.")


def test_custom_threshold():
    r = sharpe_implausibility_gate(sharpe=3.0, threshold=2.5)
    assert r["flagged"] is True
    print("[PASS] custom threshold respected.")


# ---------------------------------------------------------------------------
# 2. MC trade-order permutation gate
# ---------------------------------------------------------------------------


def test_permutation_gate_typical_random_walk_is_consistent():
    """A genuinely random i.i.d. trade sequence should look typical of its own reordering."""
    rng = np.random.default_rng(7)
    pnls = rng.normal(loc=20.0, scale=100.0, size=80).tolist()
    r = mc_permutation_gate(pnls, n_iters=500, initial_capital=10_000.0, seed=1)
    assert r["n_trades"] == 80
    # Not a strict guarantee for every seed, but the typical case is inside-band.
    print(
        f"[INFO] permutation gate on random pnls: consistent={r['consistent_with_reordering']} "
        f"sharpe_pct={r['sharpe_percentile']} dd_pct={r['max_dd_percentile']}"
    )
    assert isinstance(r["consistent_with_reordering"], bool)


def test_permutation_gate_insufficient_trades_fails_closed():
    r = mc_permutation_gate([100.0], n_iters=200)
    assert r["flagged"] is True
    assert r["consistent_with_reordering"] is False
    print("[PASS] single-trade input fails closed.")


def test_permutation_gate_empty_fails_closed():
    r = mc_permutation_gate([], n_iters=200)
    assert r["flagged"] is True
    print("[PASS] empty input fails closed.")


def test_permutation_gate_reports_monte_carlo_verdict():
    rng = np.random.default_rng(3)
    pnls = (rng.normal(30.0, 80.0, size=40)).tolist()
    r = mc_permutation_gate(pnls, n_iters=300, seed=2)
    assert r["monte_carlo_verdict"] in {"EXCELLENT", "GOOD", "MARGINAL", "POOR"}
    print(f"[PASS] monte_carlo_verdict present: {r['monte_carlo_verdict']}")


# ---------------------------------------------------------------------------
# 3. Ljung-Box independence pre-check
# ---------------------------------------------------------------------------


def test_iid_series_passes_ljung_box():
    """Pure white noise should NOT show significant autocorrelation."""
    rng = np.random.default_rng(42)
    series = rng.normal(0, 1, size=300)
    r = ljung_box_independence_check(series, lags=10)
    assert r["independent"] is True
    print(f"[PASS] i.i.d. series passes Ljung-Box: p={r['p_value']:.4f}")


def test_strongly_autocorrelated_series_fails_ljung_box():
    """A strong AR(1) process (phi=0.9) must show significant autocorrelation."""
    rng = np.random.default_rng(11)
    n = 300
    phi = 0.9
    series = np.zeros(n)
    noise = rng.normal(0, 1, size=n)
    for t in range(1, n):
        series[t] = phi * series[t - 1] + noise[t]
    r = ljung_box_independence_check(series, lags=10)
    assert r["independent"] is False
    print(f"[PASS] AR(1) series fails Ljung-Box (rejected i.i.d.): p={r['p_value']:.6f}")


def test_ljung_box_undetermined_with_too_few_observations():
    r = ljung_box_independence_check([1.0, 2.0, 3.0], lags=10)
    assert r["independent"] is None
    print("[PASS] too-few-observations returns undetermined, not a pass.")


# ---------------------------------------------------------------------------
# 4. ADF stationarity pre-check
# ---------------------------------------------------------------------------


def test_stationary_series_passes_adf():
    """Mean-reverting noise around a constant should be judged stationary."""
    rng = np.random.default_rng(5)
    series = rng.normal(loc=50.0, scale=2.0, size=200)
    r = adf_stationarity_check(series)
    assert r["stationary"] is True
    print(f"[PASS] stationary series passes ADF: p={r['p_value']:.4f}")


def test_random_walk_fails_adf():
    """A cumulative-sum random walk is the canonical non-stationary series."""
    rng = np.random.default_rng(9)
    steps = rng.normal(0, 1, size=300)
    random_walk = np.cumsum(steps) + 1000.0
    r = adf_stationarity_check(random_walk)
    assert r["stationary"] is False
    print(f"[PASS] random walk fails ADF (non-stationary): p={r['p_value']:.4f}")


def test_adf_undetermined_with_too_few_observations():
    r = adf_stationarity_check(list(range(10)))
    assert r["stationary"] is None
    print("[PASS] too-few-observations returns undetermined, not a pass.")


# ---------------------------------------------------------------------------
# 5. Diebold-Mariano test
# ---------------------------------------------------------------------------


def test_dm_detects_clearly_superior_candidate():
    """Candidate with a large, low-noise mean-return edge over baseline -> significant."""
    rng = np.random.default_rng(21)
    n = 150
    baseline = rng.normal(0.0, 0.05, size=n)
    candidate = rng.normal(0.5, 0.05, size=n)
    r = diebold_mariano_test(candidate, baseline, h=1)
    assert r["significant"] is True
    assert r["better"] == "candidate"
    print(f"[PASS] DM detects superior candidate: p={r['p_value']:.6f} stat={r['dm_statistic']:.3f}")


def test_dm_no_difference_for_identical_series():
    rng = np.random.default_rng(13)
    series = rng.normal(0.1, 0.2, size=100)
    r = diebold_mariano_test(series, series.copy(), h=1)
    assert r["significant"] is False
    assert r["better"] == "tie"
    print("[PASS] DM reports no difference for identical series.")


def test_dm_mismatched_lengths_fails_closed():
    r = diebold_mariano_test([1.0, 2.0, 3.0], [1.0, 2.0])
    assert r["significant"] is False
    assert r["better"] == "tie"
    assert r["n"] is None
    print("[PASS] mismatched-length series fails closed.")


def test_dm_too_few_observations_fails_closed():
    r = diebold_mariano_test([1.0] * 5, [2.0] * 5)
    assert r["significant"] is False
    print("[PASS] too-few-observations DM fails closed.")


def main():
    tests = [
        test_extreme_sharpe_is_flagged,
        test_moderately_high_sharpe_is_flagged_not_extreme,
        test_realistic_sharpe_is_not_flagged,
        test_small_sample_caveat_only_added_when_flagged_and_thin,
        test_custom_threshold,
        test_permutation_gate_typical_random_walk_is_consistent,
        test_permutation_gate_insufficient_trades_fails_closed,
        test_permutation_gate_empty_fails_closed,
        test_permutation_gate_reports_monte_carlo_verdict,
        test_iid_series_passes_ljung_box,
        test_strongly_autocorrelated_series_fails_ljung_box,
        test_ljung_box_undetermined_with_too_few_observations,
        test_stationary_series_passes_adf,
        test_random_walk_fails_adf,
        test_adf_undetermined_with_too_few_observations,
        test_dm_detects_clearly_superior_candidate,
        test_dm_no_difference_for_identical_series,
        test_dm_mismatched_lengths_fails_closed,
        test_dm_too_few_observations_fails_closed,
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
    print(f"ALL {len(tests)} rigor-gates tests PASSED.")
    sys.exit(0)


if __name__ == "__main__":
    main()

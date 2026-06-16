"""Tests for family-wide BH-FDR over the gate-v2 campaign (backtest/family_fdr.py)."""

from __future__ import annotations

import math

from backtest import family_fdr as ff

# --- bh_fdr core -----------------------------------------------------------

def test_bh_fdr_empty():
    assert ff.bh_fdr([], 0.10) == []


def test_bh_fdr_all_tiny_pass():
    # All p-values far below any BH line -> all discoveries.
    flags = ff.bh_fdr([0.0, 1e-6, 1e-5], 0.10)
    assert flags == [True, True, True]


def test_bh_fdr_all_large_fail():
    flags = ff.bh_fdr([0.6, 0.7, 0.9, 0.99], 0.10)
    assert flags == [False, False, False, False]


def test_bh_fdr_known_vector():
    # Classic BH worked example. n=4, q=0.10 -> only p=0.001 survives.
    pvals = [0.001, 0.20, 0.40, 0.80]
    flags = ff.bh_fdr(pvals, 0.10)
    assert flags == [True, False, False, False]


def test_bh_fdr_step_up_includes_lower_ranks():
    # BH is step-up: if a higher rank passes, all lower-p entries pass too even
    # if an individual lower rank sat just above its own line.
    # p=[0.01,0.02,0.03,0.04,0.05], n=5, q=0.10 lines=[.02,.04,.06,.08,.10]
    # largest k meeting p<=line: rank5 (0.05<=0.10) -> cutoff 0.05 -> all pass.
    flags = ff.bh_fdr([0.01, 0.02, 0.03, 0.04, 0.05], 0.10)
    assert flags == [True, True, True, True, True]


def test_bh_fdr_preserves_input_order():
    # Unsorted input: flags must map back to original positions.
    pvals = [0.80, 0.001, 0.40]
    flags = ff.bh_fdr(pvals, 0.10)
    assert flags == [False, True, False]


# --- binomial OOS sign-test -----------------------------------------------

def test_binomial_perfect_small():
    # 7/7 profitable windows -> P(X>=7 | Bin(7,0.5)) = 1/128.
    assert math.isclose(ff.binomial_oos_pvalue(1.0, 7), 1 / 128, rel_tol=1e-9)


def test_binomial_coin_flip():
    # 3/5 profitable -> P(X>=3 | Bin(5,0.5)) = (10+5+1)/32 = 0.5.
    assert math.isclose(ff.binomial_oos_pvalue(0.6, 5), 0.5, rel_tol=1e-9)


def test_binomial_zero_windows_is_one():
    assert ff.binomial_oos_pvalue(0.9, 0) == 1.0


def test_binomial_monotonic_in_k():
    # More profitable windows -> smaller (more significant) p-value.
    p_low = ff.binomial_oos_pvalue(0.4, 10)
    p_high = ff.binomial_oos_pvalue(0.9, 10)
    assert p_high < p_low


# --- conservative / shrink-only properties ---------------------------------

def _synthetic_verdicts():
    """Two strong + two weak strategies, plus one with no OOS data."""
    def mk(_id, verdict, p_edge, n, dsr, pf):
        return {
            "_id": _id,
            "symbol": _id.split("_")[0],
            "family": "trend",
            "verdict": verdict,
            "gate_v2_metrics": {
                "pf_ci_lower": pf,
                "p_edge": p_edge,
                "dsr": dsr,
            },
            "wfo_config": {"n_oos_windows": n},
        }

    return [
        mk("AAA_trend#1", "PASS", 1.0, 7, 1.0, 3.0),
        mk("BBB_trend#1", "PASS", 0.68, 19, 1.0, 2.5),
        mk("CCC_gap#1", "FAIL", 0.4, 5, 0.0, 0.5),
        mk("DDD_ib#1", "FAIL", 0.0, 5, 0.0, 0.4),
        # no OOS windows -> excluded
        {
            "_id": "EEE_meanrev#1",
            "symbol": "EEE",
            "family": "meanrev",
            "verdict": "FAIL",
            "gate_v2_metrics": {"p_edge": None, "dsr": None},
            "wfo_config": {"n_oos_windows": 0},
        },
    ]


def test_build_family_excludes_no_oos():
    family, excluded = ff.build_family(_synthetic_verdicts())
    ids = {r["id"] for r in family}
    assert "EEE_meanrev#1" not in ids
    assert len(excluded) == 1
    assert excluded[0]["id"] == "EEE_meanrev#1"


def test_robust_edge_is_subset_of_gate_pass(monkeypatch):
    monkeypatch.setattr(ff, "load_verdicts", lambda *a, **k: _synthetic_verdicts())
    report = ff.run(q=0.10)
    robust = set(report["robust_edge_ids"])
    gate_pass = set(report["gate_pass_ids"])
    # FDR can only shrink: every robust edge must be a gate-v2 PASS.
    assert robust.issubset(gate_pass)


def test_run_counts_consistent(monkeypatch):
    monkeypatch.setattr(ff, "load_verdicts", lambda *a, **k: _synthetic_verdicts())
    report = ff.run(q=0.10)
    assert report["n_verdicts_total"] == 5
    assert report["n_family"] == 4
    assert report["n_excluded"] == 1
    assert report["n_robust_edge"] <= report["n_gate_pass"]


def test_run_on_real_verdicts_smoke():
    # Runs against the live verdict dir; must not crash and must shrink-only.
    # The verdict dir is runtime-generated (empty in a fresh checkout / CI), so
    # assert robustness + the shrink-only invariant, not a minimum count.
    report = ff.run(q=0.10)
    assert report["n_verdicts_total"] >= 0
    assert report["n_robust_edge"] <= report["n_gate_pass"]
    assert set(report["robust_edge_ids"]).issubset(set(report["gate_pass_ids"]))

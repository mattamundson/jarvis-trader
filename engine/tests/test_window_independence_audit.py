"""Tests for the OOS-window independence/overlap audit (backtest/window_independence_audit.py).

Pure-function regression cover for the statistical helpers that decide whether the
family-FDR binomial test is fed *independent* windows (AC1, AR(1) effective-N,
binomial p) plus an end-to-end audit_candidate() over a synthetic verdict JSON.
Read-only analysis module; no trading path. Math is hand-verified in comments.
"""

from __future__ import annotations

import json
import math

from backtest import window_independence_audit as wia

# --- _parse_ym / _oos_bounds ----------------------------------------------


def test_parse_ym_ordinal_month():
    # 2025*12 + 3
    assert wia._parse_ym("2025-03") == 24303
    assert wia._parse_ym(" 2024-01 ") == 24289


def test_oos_bounds_splits_on_arrow_and_strips():
    assert wia._oos_bounds("2025-01 -> 2025-03") == (24301, 24303)
    # span is end - start = 2 ordinal months
    s, e = wia._oos_bounds("2024-01 -> 2024-04")
    assert e - s == 3


# --- _lag1_autocorr --------------------------------------------------------


def test_lag1_autocorr_too_few_points_is_nan():
    assert math.isnan(wia._lag1_autocorr([1.0, 2.0]))


def test_lag1_autocorr_zero_variance_is_nan():
    assert math.isnan(wia._lag1_autocorr([3.0, 3.0, 3.0, 3.0]))


def test_lag1_autocorr_nonfinite_is_nan():
    assert math.isnan(wia._lag1_autocorr([1.0, float("inf"), 2.0]))
    assert math.isnan(wia._lag1_autocorr([1.0, float("nan"), 2.0]))


def test_lag1_autocorr_symmetric_series_is_zero():
    # [1,2,3]: mu=2, denom=2, num=(-1*0)+(0*1)=0 -> 0.0
    assert wia._lag1_autocorr([1.0, 2.0, 3.0]) == 0.0


def test_lag1_autocorr_known_positive_value():
    # [1,2,3,4]: mu=2.5, denom=5.0, num=0.75-0.25+0.75=1.25 -> 0.25
    assert wia._lag1_autocorr([1.0, 2.0, 3.0, 4.0]) == 0.25


# --- _neff_ar1 -------------------------------------------------------------


def test_neff_ar1_nan_returns_nominal_n():
    assert wia._neff_ar1(7, float("nan")) == 7.0


def test_neff_ar1_zero_corr_returns_nominal_n():
    assert wia._neff_ar1(10, 0.0) == 10.0


def test_neff_ar1_half_corr_thirds_the_n():
    # n*(1-0.5)/(1+0.5) = n/3
    assert wia._neff_ar1(9, 0.5) == 3.0


def test_neff_ar1_negative_corr_clamped_to_zero():
    # r<0 -> max(0,r)=0 -> returns n
    assert wia._neff_ar1(8, -0.5) == 8.0


def test_neff_ar1_corr_above_one_clamped_below_one():
    # r=2.0 clamps to 0.999; result must be tiny and strictly positive, never <=0
    val = wia._neff_ar1(8, 2.0)
    assert 0.0 < val < 0.01


# --- _binom_p_at_least -----------------------------------------------------


def test_binom_p_all_wins_is_half_to_the_n():
    assert wia._binom_p_at_least(7, 7) == 0.5**7
    assert wia._binom_p_at_least(4, 4) == 0.0625


def test_binom_p_at_least_zero_is_one():
    assert wia._binom_p_at_least(0, 5) == 1.0


def test_binom_p_at_least_two_of_three():
    # C(3,2)*.125 + C(3,3)*.125 = 0.375 + 0.125 = 0.5
    assert math.isclose(wia._binom_p_at_least(2, 3), 0.5, rel_tol=1e-12)


# --- audit_candidate (end-to-end over a synthetic verdict) -----------------


def _write_verdict(tmp_path, name, cfg, windows):
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps({"wfo_config": cfg, "windows": windows}))
    return tmp_path


def test_audit_candidate_independent_nonoverlap(tmp_path):
    # step==test=3 -> adjacent OOS windows do not overlap.
    vdir = _write_verdict(
        tmp_path,
        "CLEAN",
        {"test_months": 3, "step_months": 3},
        [
            {"oos_pf": 1.5, "oos_trades": 60, "oos_period": "2024-01 -> 2024-03"},
            {"oos_pf": 0.8, "oos_trades": 55, "oos_period": "2024-04 -> 2024-06"},
            {"oos_pf": 1.2, "oos_trades": 64, "oos_period": "2024-07 -> 2024-09"},
        ],
    )
    r = wia.audit_candidate("CLEAN", vdir)
    assert r["n"] == 3
    assert r["wins"] == 2  # 1.5 and 1.2 are > 1.0
    assert r["overlap_pct"] == 0.0
    assert r["thin"] == 0
    assert r["degenerate"] is False
    assert r["median_trades"] == 60
    assert r["neff_block"] == 3.0  # block = test/step = 1.0
    assert r["pf"] == [1.5, 0.8, 1.2]


def test_audit_candidate_detects_50pct_overlap(tmp_path):
    # step=1, test=2 -> adjacent OOS windows share half their span.
    vdir = _write_verdict(
        tmp_path,
        "OVERLAP",
        {"test_months": 2, "step_months": 1},
        [
            {"oos_pf": 1.1, "oos_trades": 30, "oos_period": "2024-01 -> 2024-03"},
            {"oos_pf": 1.2, "oos_trades": 30, "oos_period": "2024-02 -> 2024-04"},
            {"oos_pf": 1.3, "oos_trades": 30, "oos_period": "2024-03 -> 2024-05"},
        ],
    )
    r = wia.audit_candidate("OVERLAP", vdir)
    assert math.isclose(r["overlap_pct"], 50.0, rel_tol=1e-9)
    assert r["neff_block"] == 1.5  # n / (test/step) = 3 / 2


def test_audit_candidate_flags_degenerate_thin_windows(tmp_path):
    # A non-finite PF (Infinity) and trade counts below MIN_OOS_TRADES_PER_WINDOW.
    vdir = _write_verdict(
        tmp_path,
        "DEGEN",
        {"test_months": 3, "step_months": 3},
        [
            {"oos_pf": float("inf"), "oos_trades": 2, "oos_period": "2024-01 -> 2024-03"},
            {"oos_pf": 0.5, "oos_trades": 3, "oos_period": "2024-04 -> 2024-06"},
            {"oos_pf": 1.4, "oos_trades": 60, "oos_period": "2024-07 -> 2024-09"},
        ],
    )
    r = wia.audit_candidate("DEGEN", vdir)
    assert r["degenerate"] is True
    # two windows have trades < 5 (the wia.MIN_OOS_TRADES_PER_WINDOW floor)
    assert r["thin"] == 2
    assert wia.MIN_OOS_TRADES_PER_WINDOW == 5


def test_audit_candidate_skips_none_pf_but_counts_trades(tmp_path):
    # oos_pf None is excluded from the pf series but the window still counts for n/trades.
    vdir = _write_verdict(
        tmp_path,
        "NULLPF",
        {"test_months": 3, "step_months": 3},
        [
            {"oos_pf": None, "oos_trades": 40, "oos_period": "2024-01 -> 2024-03"},
            {"oos_pf": 1.6, "oos_trades": 50, "oos_period": "2024-04 -> 2024-06"},
        ],
    )
    r = wia.audit_candidate("NULLPF", vdir)
    assert r["n"] == 2
    assert r["pf"] == [1.6]
    assert r["wins"] == 1
    assert r["trades"] == [40, 50]

"""P2-honesty: the proactive validation suite must not report confident
pass/fail on degenerate small-sample statistics.

Two live anomalies motivated this:
  - WFE reported a profit_factor of 3173 as "healthy (pass)" and 0.000 as
    "critically low — overfitting (fail)". Both are artifacts of a WFE snapshot
    resting on a handful of trades (near-zero gross loss / gross win), not real
    signal about the strategy.
  - MC Edge reported "p=1.000 | verdict=EXCELLENT | 100.0% paths profitable" —
    a self-contradiction: the permutation p-value says the sequence is trivially
    beatable (no edge) while the MC's own verdict says EXCELLENT. With every
    bootstrap path profitable there is no dispersion to estimate significance.

These tests pin the two pure decision helpers that gate such cases to
`insufficient_data`. They use the real helpers (no mocks) — the I/O wrappers
_check_wfe / _check_mc_edge delegate to them.
"""
from routers.proactive_validation_router import (
    _MC_MIN_TRADES,
    _WFE_MIN_TRADES,
    _check_validation_gates,
    _mc_honesty_status,
    _wfe_honesty_status,
)


# --------------------------------------------------------------------------- #
# WFE degeneracy guard
# --------------------------------------------------------------------------- #
def test_wfe_small_sample_is_insufficient_not_pass():
    # PF 3173 only happens because gross loss ~ 0 over a tiny trade count.
    status, _msg = _wfe_honesty_status(pf=3173.0, trades=3)
    assert status == "insufficient_data"


def test_wfe_zero_pf_small_sample_is_insufficient_not_fail():
    # PF 0.000 over a tiny sample is "no evidence", not proof of overfitting.
    status, _msg = _wfe_honesty_status(pf=0.0, trades=2)
    assert status == "insufficient_data"


def test_wfe_missing_trade_count_is_insufficient():
    # Legacy snapshot with no trade count recorded — cannot trust the PF.
    status, _msg = _wfe_honesty_status(pf=1.4, trades=None)
    assert status == "insufficient_data"


def test_wfe_degenerate_pf_even_with_enough_trades_is_insufficient():
    # A PF this extreme means near-zero gross loss regardless of count.
    status, _msg = _wfe_honesty_status(pf=3173.0, trades=50)
    assert status == "insufficient_data"


def test_wfe_healthy_pf_with_enough_trades_is_not_gated():
    # A normal PF on an adequate sample must pass through (helper returns None,
    # caller applies the usual pass/warn/fail).
    assert _wfe_honesty_status(pf=1.35, trades=_WFE_MIN_TRADES) is None


# --------------------------------------------------------------------------- #
# MC edge degeneracy / contradiction guard
# --------------------------------------------------------------------------- #
def test_mc_all_paths_profitable_is_insufficient():
    # 100% of bootstrap paths profitable => no dispersion => untrustworthy.
    status, _msg = _mc_honesty_status(p_value=1.0, verdict="EXCELLENT", prob_profitable=100.0)
    assert status == "insufficient_data"


def test_mc_no_paths_profitable_is_insufficient():
    status, _msg = _mc_honesty_status(p_value=0.0, verdict="POOR", prob_profitable=0.0)
    assert status == "insufficient_data"


def test_mc_good_verdict_but_insignificant_p_is_contradiction():
    # verdict says EXCELLENT but permutation test says no significance (p>0.10).
    status, _msg = _mc_honesty_status(p_value=0.62, verdict="EXCELLENT", prob_profitable=72.0)
    assert status == "insufficient_data"


def test_mc_significant_p_but_poor_verdict_is_contradiction():
    status, _msg = _mc_honesty_status(p_value=0.03, verdict="POOR", prob_profitable=58.0)
    assert status == "insufficient_data"


def test_mc_coherent_significant_result_is_not_gated():
    # Significant p AND good verdict, with real dispersion — must pass through.
    assert _mc_honesty_status(p_value=0.03, verdict="GOOD", prob_profitable=71.0) is None


def test_mc_coherent_failure_is_not_gated():
    # Not significant AND not a good verdict — signals agree on "no edge yet".
    assert _mc_honesty_status(p_value=0.40, verdict="MARGINAL", prob_profitable=55.0) is None


def test_min_trade_floors_exist():
    # The count floors the guards lean on must be defined and sane.
    assert _WFE_MIN_TRADES >= 10
    assert _MC_MIN_TRADES >= 10


# --------------------------------------------------------------------------- #
# Validation Gates truthy-dict regression (live-confirmed 2026-07-10: MES
# reported "6/6 passing" with an actual 23.0% max drawdown against a 15.0%
# ceiling, because `if v` on a non-empty {"value":..,"passes":False} dict is
# always truthy). pf.values() must be checked via the nested "passes" flag.
# --------------------------------------------------------------------------- #
def _pf_entry(value, threshold, passes):
    return {"value": value, "threshold": threshold, "passes": passes}


def test_validation_gates_hard_metric_fail_is_reported_as_fail():
    # Mirrors the live MES anomaly: every gate passes except max_drawdown_pct
    # (23.0% actual vs 15.0% ceiling). Must surface as a real FAIL, not "6/6
    # passing", and the failed-gates list must be non-empty.
    pf = {
        "profit_factor": _pf_entry(2.4, 2.0, True),
        "sharpe_ratio": _pf_entry(1.8, 1.5, True),
        "win_rate_pct": _pf_entry(58.0, 55.0, True),
        "total_trades": _pf_entry(65, 60, True),
        "days_active": _pf_entry(35, 30, True),
        "max_drawdown_pct": _pf_entry(23.0, 15.0, False),
    }
    progress = {
        "status": "in_progress",
        "pass_fail": pf,
        "profit_factor": 2.4,
        "sharpe_ratio": 1.8,
        "win_rate_pct": 58.0,
        "max_drawdown_pct": 23.0,
    }
    check = _check_validation_gates(progress)
    assert check.status == "fail"
    assert "5/6" in check.value


def test_validation_gates_count_and_days_shortfall_only_is_warn_not_fail():
    # Trade-count / days-elapsed shortfalls get their own dedicated checks
    # (Trade Count, Time Elapsed) — the rollup Validation Gates check should
    # warn, not hard-fail, when those are the only gates still short.
    pf = {
        "profit_factor": _pf_entry(2.4, 2.0, True),
        "sharpe_ratio": _pf_entry(1.8, 1.5, True),
        "win_rate_pct": _pf_entry(58.0, 55.0, True),
        "total_trades": _pf_entry(40, 60, False),
        "days_active": _pf_entry(20, 30, False),
        "max_drawdown_pct": _pf_entry(8.0, 15.0, True),
    }
    progress = {
        "status": "in_progress",
        "pass_fail": pf,
        "profit_factor": 2.4,
        "sharpe_ratio": 1.8,
        "win_rate_pct": 58.0,
        "max_drawdown_pct": 8.0,
    }
    check = _check_validation_gates(progress)
    assert check.status == "warn"

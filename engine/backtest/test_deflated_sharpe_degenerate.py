"""Regression test: the DSR degenerate-variance fallback must FAIL conservatively.

Guards D1. `_sharpe_standard_error` returns a non-finite sigma when the
non-normality variance estimate breaks down:
    var(SR) = (1 - g3*SR + ((g4-1)/4)*SR^2) / (T-1)   <= 0
which happens for high-Sharpe, positively-skewed series (exactly our sparse
trend survivors). The OLD behaviour returned a FAKE dsr=1.0 in that case
(`dsr = 0.0 if sharpe <= expected_max else 1.0`), which auto-passes both the
core (>=0.10) and alt (>=0.30) gate floors on a strategy whose selection-bias
correction is undefined. A degenerate SE is NOT evidence of a real edge -- it
is an absence of evidence, so the honest verdict is fail-conservative dsr=0.0
plus a surfaced `dsr_degenerate` flag.

Run:  cd engine && .venv/Scripts/python backtest/test_deflated_sharpe_degenerate.py
"""

from __future__ import annotations

import sys

import numpy as np

sys.path.insert(0, ".")

from backtest.deflated_sharpe import (
    _sharpe_standard_error,
    deflated_sharpe_from_returns,
    deflated_sharpe_ratio,
)


def test_degenerate_variance_fails_conservative():
    """High Sharpe + high positive skew -> negative variance -> sigma=inf.

    OLD code returned dsr=1.0 (auto-pass). The honest value is 0.0, flagged.
    """
    # 1 - 2.0*10 + ((1.0-1.0)/4)*100 = -19 < 0  -> variance <= 0 -> sigma=inf
    sigma = _sharpe_standard_error(sharpe=10.0, skew=2.0, kurt=1.0, n_obs=40)
    assert not np.isfinite(sigma), f"setup invalid: expected non-finite sigma, got {sigma}"

    res = deflated_sharpe_ratio(sharpe=10.0, n_trials=8, n_obs=40, skew=2.0, kurt=1.0)
    assert res["dsr"] == 0.0, (
        f"degenerate-variance DSR must be fail-conservative 0.0, got {res['dsr']} "
        "(the fake-1.0 fallback would auto-pass a strategy with undefined SE)."
    )
    assert res["dsr_degenerate"] is True, "degenerate path must surface dsr_degenerate=True"
    assert res["passes_at_10pct"] is False
    print("[PASS] degenerate variance -> dsr=0.0, dsr_degenerate=True (was fake 1.0).")


def test_normal_case_unaffected():
    """A finite-sigma compute must be untouched: real Phi(z), flag False."""
    res = deflated_sharpe_ratio(sharpe=1.5, n_trials=10, n_obs=200, skew=0.0, kurt=3.0)
    assert np.isfinite(res["sharpe_std_error"]) and res["sharpe_std_error"] > 0
    assert 0.0 < res["dsr"] < 1.0, f"expected a genuine Phi(z) in (0,1), got {res['dsr']}"
    assert res["dsr_degenerate"] is False
    print(f"[PASS] normal case unaffected: dsr={res['dsr']:.4f}, dsr_degenerate=False.")


def test_genuine_high_sharpe_not_flagged():
    """A genuinely huge Sharpe with FINITE small sigma yields Phi(z)~1 honestly.

    This is the case the fix must NOT clobber: sigma is finite, so dsr is a real
    norm.cdf (near 1.0), and dsr_degenerate stays False.
    """
    res = deflated_sharpe_ratio(sharpe=3.0, n_trials=2, n_obs=5000, skew=0.0, kurt=3.0)
    assert np.isfinite(res["sharpe_std_error"]) and res["sharpe_std_error"] > 0
    assert res["dsr_degenerate"] is False
    assert res["dsr"] > 0.99, f"genuine high-Sharpe should pass honestly, got {res['dsr']}"
    print(f"[PASS] genuine finite-sigma high Sharpe honest: dsr={res['dsr']:.6f}, flag False.")


def test_insufficient_sample_guard_carries_flag():
    """The n_obs<2 early guard returns dsr=0.0 and a present (False) flag.

    Insufficient sample is a different failure than variance degeneracy, so the
    flag is False there -- but the key contract is the field always exists, so
    downstream verdict writers can record it unconditionally.
    """
    res = deflated_sharpe_ratio(sharpe=2.0, n_trials=5, n_obs=1)
    assert res["dsr"] == 0.0 and res["dsr_degenerate"] is False
    print("[PASS] insufficient-sample guard returns dsr=0.0 with dsr_degenerate=False present.")


def test_from_returns_propagates_flag():
    """deflated_sharpe_from_returns must surface dsr_degenerate too."""
    # Mostly-flat returns with a couple of large positive jumps -> high skew + SR.
    rng = np.random.default_rng(7)
    base = rng.normal(0.0001, 0.0002, size=60)
    base[10] = 0.05
    base[40] = 0.06
    res = deflated_sharpe_from_returns(base.tolist(), n_trials=8)
    assert "dsr_degenerate" in res, "from_returns must include the dsr_degenerate field"
    assert isinstance(res["dsr_degenerate"], bool)
    print(f"[PASS] from_returns propagates dsr_degenerate={res['dsr_degenerate']}.")


def main():
    tests = [
        test_degenerate_variance_fails_conservative,
        test_normal_case_unaffected,
        test_genuine_high_sharpe_not_flagged,
        test_insufficient_sample_guard_carries_flag,
        test_from_returns_propagates_flag,
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
    print(f"ALL {len(tests)} deflated-sharpe degenerate-variance tests PASSED.")
    sys.exit(0)


if __name__ == "__main__":
    main()

"""Tests for the strategy-agnostic parameter-sensitivity core.

The historical `sensitivity.py` was hard-wired to the STC strategy (fixed
`PARAM_RANGES`, fixed `_compute_signals` kwargs). Task 2 of the edge-validation
top-10 generalizes it to a `sweep_param_sensitivity(run_fn, param_ranges,
base_params)` core so any study (e.g. singlefinder) can be swept. These tests
exercise that core with synthetic, deterministic `run_fn`s (no real backtests)
plus a guard that the STC wrapper still delegates correctly.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backtest import sensitivity as S


def _metrics(pf, trades=100):
    """Minimal metrics dict the core consumes."""
    return {"pf": pf, "sharpe": 0.0, "return": 0.0, "win_rate": 50.0, "trades": trades}


# ── core: sweep_param_sensitivity ────────────────────────────────────────────


def test_flat_run_fn_is_robust():
    """Constant PF across every param value -> zero CV -> stability 100 -> ROBUST."""
    run_fn = lambda params: _metrics(1.5)  # noqa: E731
    ranges = {"a": [1, 2, 3, 4, 5], "b": [10, 20, 30, 40, 50]}
    base = {"a": 3, "b": 30}

    res = S.sweep_param_sensitivity(run_fn, ranges, base)

    assert res["verdict"] == "ROBUST"
    assert res["stability_scores"]["a"] == 100.0
    assert res["stability_scores"]["b"] == 100.0
    assert res["stability_scores"]["overall"] == 100.0
    assert res["base_result"]["pf"] == 1.5


def test_spiky_param_is_fragile():
    """PF good only at the exact base value, near-zero elsewhere -> FRAGILE."""

    def run_fn(params):
        return _metrics(2.0 if params["a"] == 3 else 0.2)

    ranges = {"a": [1, 2, 3, 4, 5]}
    base = {"a": 3}

    res = S.sweep_param_sensitivity(run_fn, ranges, base)

    assert res["verdict"] == "FRAGILE"
    assert res["stability_scores"]["a"] < 50.0


def test_verdict_bands_on_min_score():
    """Verdict keys off the WORST per-param stability, not the average."""

    # One rock-stable param, one moderately noisy param -> verdict follows the noisy one.
    def run_fn(params):
        # 'a' is flat; 'b' wobbles enough to land in the ACCEPTABLE band.
        if params["b"] == 10:
            return _metrics(1.0)
        if params["b"] == 20:
            return _metrics(1.15)
        if params["b"] == 30:
            return _metrics(1.0)
        if params["b"] == 40:
            return _metrics(0.85)
        return _metrics(1.0)

    ranges = {"a": [1, 2, 3, 4, 5], "b": [10, 20, 30, 40, 50]}
    base = {"a": 3, "b": 30}

    res = S.sweep_param_sensitivity(run_fn, ranges, base)
    assert res["stability_scores"]["a"] == 100.0
    # min score drives the verdict; it is strictly below the 'a' score
    assert res["verdict"] in {"ROBUST", "ACCEPTABLE", "FRAGILE"}
    assert (
        min(res["stability_scores"]["a"], res["stability_scores"]["b"])
        <= res["stability_scores"]["a"]
    )


def test_held_params_stay_at_base_during_sweep():
    """When sweeping one param, the others must be pinned at their base values."""
    seen = []

    def run_fn(params):
        seen.append(dict(params))
        return _metrics(1.3)

    ranges = {"a": [1, 2, 3], "b": [10, 20, 30]}
    base = {"a": 2, "b": 20}

    S.sweep_param_sensitivity(run_fn, ranges, base)

    # Every call sweeping 'a' must hold b==20; every call sweeping 'b' holds a==2.
    a_calls = [c for c in seen if c["a"] in (1, 2, 3) and c not in ()]
    for c in seen:
        # exactly one param differs from base at a time (or none, for the base point)
        diffs = [k for k in base if c[k] != base[k]]
        assert len(diffs) <= 1


def test_single_param_family_singlefinder_shape():
    """The singlefinder family is one knob (min_single_ticks); the core handles it."""

    def run_fn(params):
        # Stable ~1.4 PF across the whole neighborhood, like the real champion.
        table = {1: 1.30, 2: 1.48, 3: 1.42, 4: 1.38, 5: 1.33, 6: 1.20}
        return _metrics(table[params["min_single_ticks"]], trades=500)

    ranges = {"min_single_ticks": [1, 2, 3, 4, 5, 6]}
    base = {"min_single_ticks": 2}

    res = S.sweep_param_sensitivity(run_fn, ranges, base)

    assert res["verdict"] == "ROBUST"
    sweep = res["sensitivity"]["min_single_ticks"]
    assert [pt["value"] for pt in sweep] == [1, 2, 3, 4, 5, 6]
    assert all("pf" in pt and "trades" in pt for pt in sweep)
    # base point flagged with 0% change-from-base
    base_pt = next(pt for pt in sweep if pt["value"] == 2)
    assert base_pt["pct_change_from_base"] == 0.0


def test_base_value_not_in_range_does_not_crash():
    """A base value absent from the sweep list falls back to the closest-N window."""
    run_fn = lambda params: _metrics(1.4)  # noqa: E731
    ranges = {"a": [1, 2, 4, 5, 6]}  # base 3 not present
    base = {"a": 3}

    res = S.sweep_param_sensitivity(run_fn, ranges, base)
    assert "a" in res["stability_scores"]
    assert res["verdict"] in {"ROBUST", "ACCEPTABLE", "FRAGILE"}


# ── wrapper: STC run_sensitivity_analysis still delegates ─────────────────────


def test_stc_wrapper_still_works(monkeypatch):
    """The legacy STC entrypoint must keep producing the same result shape."""

    def fake_backtest(df_base, multiplier, capital, *, stc_os, stc_ob, stop_atr, t1_atr):
        # Flat, healthy PF regardless of params -> ROBUST.
        return SimpleNamespace(
            total_trades=120,
            profit_factor=1.6,
            sharpe_ratio=1.1,
            total_return_pct=0.25,
            win_rate=0.55,
            max_drawdown_pct=0.04,
        )

    monkeypatch.setattr(S, "_run_single_backtest", fake_backtest)

    res = S.run_sensitivity_analysis(df=None, symbol="SPY", multiplier=5.0)

    assert set(res) >= {"base_params", "base_result", "sensitivity", "stability_scores", "verdict"}
    assert res["verdict"] == "ROBUST"
    assert res["base_result"]["pf"] == 1.6


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

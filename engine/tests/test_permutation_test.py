"""Tests for bar-permutation MCPT (backtest.bar_permute + analytics.permutation_test).

Two concerns:
  1. The permutation preserves the right invariants (component multisets, endpoints,
     return moments on gap-free series) and destroys order.
  2. The MCPT harness correctly PASSES an order-dependent edge and REJECTS an
     order-invariant / memorized "edge" (the data-mining-bias case the test exists for).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analytics.permutation_test import (
    INSAMPLE_ALPHA,
    bootstrap_metric_ci,
    permute_and_score,
    run_insample_mcpt,
    run_walkforward_mcpt,
    validate_strategy,
)
from backtest.bar_permute import get_block_permutation, get_permutation

# ── synthetic data ──────────────────────────────────────────────────────────────

def _synth(n: int = 300, drift: float = 0.0, vol: float = 0.01, seed: int = 1,
           gap_free: bool = False) -> pd.DataFrame:
    """A synthetic OHLC frame. gap_free sets open == prior close (gaps collapse to 0),
    which makes close-to-close returns an exact permutation of the original."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, n)
    close = 100.0 * np.exp(np.cumsum(rets))
    open_ = np.empty(n)
    open_[0] = 100.0
    if gap_free:
        open_[1:] = close[:-1]
    else:
        open_[1:] = close[:-1] * np.exp(rng.normal(0, vol / 2, n - 1))
    hi_pad = np.abs(rng.normal(0, vol, n))
    lo_pad = np.abs(rng.normal(0, vol, n))
    high = np.maximum(open_, close) * np.exp(hi_pad)
    low = np.minimum(open_, close) * np.exp(-lo_pad)
    idx = pd.date_range("2025-01-01", periods=n, freq="h")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)


def _ar1(n: int = 300, phi: float = 0.6, vol: float = 0.008, seed: int = 1) -> pd.DataFrame:
    """Gap-free series whose log returns are positively autocorrelated (AR(1)).

    The edge lives in *ordering*: a momentum rule profits from the serial correlation,
    and a bar permutation destroys it while leaving the return multiset (and therefore
    any order-invariant statistic) untouched. This is the case MCPT must reward."""
    rng = np.random.default_rng(seed)
    r = np.empty(n)
    r[0] = rng.normal(0, vol)
    for t in range(1, n):
        r[t] = phi * r[t - 1] + rng.normal(0, vol)
    close = 100.0 * np.exp(np.cumsum(r))
    open_ = np.empty(n)
    open_[0] = 100.0
    open_[1:] = close[:-1]  # gap-free
    high = np.maximum(open_, close) * 1.001
    low = np.minimum(open_, close) * 0.999
    idx = pd.date_range("2025-01-01", periods=n, freq="h")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)


# ── optimize_fn fixtures (caller contract: df -> (params, pf)) ───────────────────

def _momentum_pf(df: pd.DataFrame) -> tuple[int, float]:
    """ORDER-DEPENDENT optimizer: grid over a momentum lookback and return the best
    profit factor of 'go long when recent mean return > 0'. Decisions use only returns
    up to t-1 (shift(1)) — no look-ahead. Profitable iff returns are autocorrelated."""
    r = np.diff(np.log(df["close"].to_numpy()))
    best_pf, best_lb = 0.0, None
    for lb in range(1, 6):
        sig = pd.Series(r).rolling(lb).mean().shift(1).to_numpy()
        pos = np.where(sig > 0, 1.0, 0.0)
        pnl = pos * r
        gp = pnl[pnl > 0].sum()
        gl = abs(pnl[pnl < 0].sum())
        pf = gp / gl if gl > 0 else (gp if gp > 0 else 0.0)
        if pf > best_pf:
            best_pf, best_lb = pf, lb
    return best_lb, float(best_pf)


def _buy_hold_pf(df: pd.DataFrame) -> tuple[None, float]:
    """ORDER-INVARIANT score: gross up moves / gross down moves. On a gap-free series
    this is identical for every permutation, so MCPT must flag it as no-edge."""
    diffs = np.diff(df["close"].to_numpy())
    gp = diffs[diffs > 0].sum()
    gl = abs(diffs[diffs < 0].sum())
    return None, float(gp / gl) if gl > 0 else (float(gp) if gp > 0 else 0.0)


# ── invariants ───────────────────────────────────────────────────────────────────

def test_component_multisets_preserved():
    df = _synth(seed=2)
    perm = get_permutation(df, seed=7)
    lb = np.log(df[["open", "high", "low", "close"]].to_numpy())
    lp = np.log(perm[["open", "high", "low", "close"]].to_numpy())
    # intra-bar components (high-open, low-open, close-open), bars after the anchor
    for col in (1, 2, 3):
        orig = np.sort((lb[1:, col] - lb[1:, 0]))
        pm = np.sort((lp[1:, col] - lp[1:, 0]))
        np.testing.assert_allclose(orig, pm, atol=1e-9)
    # gap component (open - prev_close)
    orig_gap = np.sort(lb[1:, 0] - lb[:-1, 3])
    perm_gap = np.sort(lp[1:, 0] - lp[:-1, 3])
    np.testing.assert_allclose(orig_gap, perm_gap, atol=1e-9)


def test_endpoints_preserved_even_with_gaps():
    df = _synth(seed=3)  # real gaps present
    perm = get_permutation(df, seed=11)
    # first bar is the verbatim anchor
    np.testing.assert_allclose(df.iloc[0].to_numpy(), perm.iloc[0].to_numpy(), atol=1e-9)
    # last close is invariant: sum(gap)+sum(rel_close) is permutation-invariant
    assert perm["close"].iloc[-1] == pytest.approx(df["close"].iloc[-1], rel=1e-9)


def test_moments_preserved_on_gap_free_series():
    """Replicates the article's verification: gap-free series -> mean/std/skew/kurt of
    log returns identical to ~6 decimals between real and one permutation."""
    df = _synth(seed=4, gap_free=True)
    perm = get_permutation(df, seed=99)
    real_r = np.log(df["close"]).diff().dropna()
    perm_r = np.log(perm["close"]).diff().dropna()
    assert real_r.mean() == pytest.approx(perm_r.mean(), abs=1e-6)
    assert real_r.std() == pytest.approx(perm_r.std(), abs=1e-6)
    assert real_r.skew() == pytest.approx(perm_r.skew(), abs=1e-6)
    assert real_r.kurt() == pytest.approx(perm_r.kurt(), abs=1e-6)


def test_anchor_segment_held_fixed():
    df = _synth(seed=5)
    perm = get_permutation(df, start_index=50, seed=5)
    np.testing.assert_allclose(
        df.iloc[:51].to_numpy(), perm.iloc[:51].to_numpy(), atol=1e-9
    )


def test_prices_positive_and_deterministic():
    df = _synth(seed=6)
    p1 = get_permutation(df, seed=42)
    p2 = get_permutation(df, seed=42)
    assert (p1[["open", "high", "low", "close"]].to_numpy() > 0).all()
    pd.testing.assert_frame_equal(p1, p2)


def test_extra_columns_carried_through():
    df = _synth(seed=8)
    df["volume"] = np.arange(len(df), dtype=float)
    perm = get_permutation(df, seed=8)
    assert "volume" in perm.columns
    np.testing.assert_array_equal(perm["volume"].to_numpy(), df["volume"].to_numpy())


def test_ohlc_validity_high_is_max_low_is_min():
    df = _synth(seed=9)
    perm = get_permutation(df, seed=9)
    o, h, lo, c = (perm[k].to_numpy() for k in ("open", "high", "low", "close"))
    assert (h >= np.maximum(o, c) - 1e-9).all()
    assert (lo <= np.minimum(o, c) + 1e-9).all()


def test_block_permutation_runs_and_preserves_endpoints():
    df = _synth(seed=10)
    perm = get_block_permutation(df, block_size=5, seed=10)
    np.testing.assert_allclose(df.iloc[0].to_numpy(), perm.iloc[0].to_numpy(), atol=1e-9)
    assert (perm["close"].to_numpy() > 0).all()


def test_too_few_bars_raises():
    df = _synth(n=10, seed=1)
    with pytest.raises(ValueError):
        get_permutation(df, start_index=9)


# ── MCPT harness behavior ────────────────────────────────────────────────────────

def test_insample_mcpt_passes_order_dependent_edge():
    """A genuine order-dependent edge sits in the right tail of the null -> low p."""
    df = _ar1(n=300, phi=0.6, seed=1)
    res = run_insample_mcpt(df, _momentum_pf, n_permutations=200, seed=0)
    assert res["real_pf"] > res["perm_pf_mean"]
    assert res["p_value"] < INSAMPLE_ALPHA
    assert res["passes"] is True


def test_insample_mcpt_rejects_order_invariant_edge():
    """An order-invariant 'edge' is matched by every permutation -> high p, REJECT."""
    df = _synth(n=200, drift=0.002, seed=4, gap_free=True)
    res = run_insample_mcpt(df, _buy_hold_pf, n_permutations=100, seed=0)
    assert res["p_value"] > INSAMPLE_ALPHA
    assert res["passes"] is False


def test_insample_mcpt_rejects_constant_optimizer():
    """A memorizing optimizer that reports the same PF on noise has no real edge."""
    df = _synth(n=150, seed=12)
    res = run_insample_mcpt(df, lambda d: ("fixed", 2.5), n_permutations=50, seed=0)
    assert res["p_value"] == pytest.approx(1.0, abs=1e-9)
    assert res["passes"] is False


def test_walkforward_mcpt_runs_and_reports():
    df = _synth(n=300, seed=13)

    def wf(d, train_window):  # toy order-invariant walk-forward
        return _buy_hold_pf(d.iloc[train_window:])[1]

    res = run_walkforward_mcpt(df, wf, train_window=133, n_permutations=40, seed=0)
    assert res["test"] == "walkforward_mcpt"
    assert 0.0 < res["p_value"] <= 1.0
    assert res["n_permutations"] == 40


def test_validate_strategy_passes_real_edge():
    df = _ar1(n=300, phi=0.6, seed=1)

    def wf(d, train_window):
        return _momentum_pf(d.iloc[train_window:])[1]

    out = validate_strategy(
        df, _momentum_pf, wf, train_window=150, n_insample_perms=200, n_wf_perms=100, seed=0
    )
    assert out["verdict"] == "PASS"


def test_validate_strategy_rejects_at_gate2():
    df = _synth(n=200, drift=0.002, seed=4, gap_free=True)
    out = validate_strategy(
        df, _buy_hold_pf, lambda d, tw: 2.0, train_window=100,
        n_insample_perms=50, n_wf_perms=20, seed=0,
    )
    assert out["verdict"] == "REJECT (in-sample MCPT)"


# ── trade-sign permutation test (Aronson) ────────────────────────────────────────

def test_trade_shuffle_rejects_no_edge():
    """Symmetric P&L around zero -> the real result is ordinary under the null."""
    rng = np.random.default_rng(3)
    pnls = rng.normal(0.0, 1.0, 80).tolist()  # mean ~ 0, no directional edge
    res = permute_and_score(pnls, n_iters=500, metric="mean", seed=0)
    assert res["p_value"] > res["alpha"]
    assert res["passes"] is False
    assert res["n_trades"] == 80


def test_trade_shuffle_passes_real_edge():
    """A win-heavy P&L list sits in the right tail of the sign-flip null."""
    pnls = [1.0] * 45 + [-1.0] * 8  # strongly positive mean
    res = permute_and_score(pnls, n_iters=500, metric="mean", seed=0)
    assert res["real_score"] > res["perm_score_mean"]
    assert res["p_value"] < res["alpha"]
    assert res["passes"] is True


def test_trade_shuffle_profit_factor_metric():
    pnls = [2.0, 3.0, 1.5, 2.5, -0.5, -0.4]  # PF well above 1
    res = permute_and_score(pnls, n_iters=300, metric="profit_factor", seed=1)
    assert res["metric"] == "profit_factor"
    assert 0.0 < res["p_value"] <= 1.0


def test_trade_shuffle_accepts_dicts_and_objects():
    class _T:
        def __init__(self, pnl):
            self.pnl = pnl

    as_dicts = [{"pnl": 1.0}, {"pnl": -1.0}, {"pnl": 1.0}]
    as_objs = [_T(1.0), _T(-1.0), _T(1.0)]
    r1 = permute_and_score(as_dicts, n_iters=50, seed=0)
    r2 = permute_and_score(as_objs, n_iters=50, seed=0)
    assert r1["n_trades"] == r2["n_trades"] == 3


def test_trade_shuffle_too_few_trades_fails_closed():
    res = permute_and_score([1.0], n_iters=100, seed=0)
    assert res["n_trades"] == 1
    assert res["p_value"] == 1.0
    assert res["passes"] is False



# -- bootstrap CI on the trade metric (complements the sign-flip p-value) --


def test_bootstrap_ci_brackets_observed_and_orders():
    pnls = [5.0, 7.0, 6.0, -2.0, 8.0, 4.0, -1.0, 6.0, 5.0, 7.0]
    res = bootstrap_metric_ci(pnls, n_iters=2000, metric="mean", seed=0)
    assert res["ci_lower"] <= res["real_score"] <= res["ci_upper"]
    assert res["metric"] == "mean"
    assert res["n_trades"] == 10


def test_bootstrap_strong_edge_low_null_probability():
    # Strongly positive mean -> bootstrap almost never lands at/below the no-edge value.
    pnls = [5.0, 7.0, 6.0, 8.0, 4.0, 9.0, 6.0, 5.0, 7.0, 6.0]
    res = bootstrap_metric_ci(pnls, n_iters=2000, metric="mean", seed=0)
    assert res["p_null"] < 0.05
    assert res["ci_lower"] > 0.0


def test_bootstrap_profit_factor_handles_no_loss_resample():
    # A resample with no losers makes PF = inf; nearest-rank percentile must keep the
    # bound a real number (finite or a clean inf), never NaN.
    pnls = [5.0, 7.0, 6.0, 8.0, 4.0, 9.0, -1.0, 6.0, 5.0, 7.0]
    res = bootstrap_metric_ci(pnls, n_iters=2000, metric="profit_factor", seed=0)
    assert not np.isnan(res["ci_lower"])
    assert not np.isnan(res["ci_upper"])
    assert res["ci_lower"] <= res["ci_upper"]


def test_bootstrap_reproducible_with_seed():
    pnls = [3.0, -1.0, 4.0, -2.0, 5.0, 1.0]
    a = bootstrap_metric_ci(pnls, n_iters=800, metric="mean", seed=11)
    b = bootstrap_metric_ci(pnls, n_iters=800, metric="mean", seed=11)
    assert a == b


def test_bootstrap_too_few_trades_fails_closed():
    res = bootstrap_metric_ci([1.0], n_iters=100, metric="mean", seed=0)
    assert res["n_trades"] == 1
    assert res["p_null"] == 1.0

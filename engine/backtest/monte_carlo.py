"""
JARVIS TRADER — Monte Carlo Simulation
Validates backtest robustness by randomizing trade order N times.
If the strategy is truly profitable, the original equity curve should
sit in the upper portion of the shuffled distribution.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

import numpy as np

from backtest.backtester import BacktestResult, Trade
from backtest.contract_specs import CONTRACT_SPECS

# ---------------------------------------------------------------------------
# Core simulation
# ---------------------------------------------------------------------------


def _get_tick_value(symbol: str) -> float:
    """Dollar value of one tick for *symbol* — delegates to CONTRACT_SPECS."""
    spec = CONTRACT_SPECS.get(symbol.upper())
    return spec.tick_value if spec is not None else 0.01


def _compute_sharpe(equity: np.ndarray, ann_factor: float = 252.0) -> float:
    """Annualised Sharpe from an equity curve (trade-by-trade steps)."""
    if len(equity) < 2:
        return 0.0
    returns = np.diff(equity) / equity[:-1]
    std = returns.std()
    if std == 0:
        return 0.0
    return float(returns.mean() / std * np.sqrt(ann_factor))


def _compute_max_dd(equity: np.ndarray) -> float:
    """Max drawdown as a positive percentage (0-100 scale)."""
    if len(equity) < 2:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    return float(abs(dd.min()) * 100.0)


def run_monte_carlo(
    result: BacktestResult,
    n_simulations: int = 10_000,
    initial_capital: float = 10_000.0,
    max_slippage_ticks: float = 0.0,
    symbol: str = "MES",
    seed: int = 42,
) -> dict:
    """Run Monte Carlo simulation on a BacktestResult.

    Shuffles the trade P&L sequence *n_simulations* times and collects
    distributions of final capital, max drawdown, and Sharpe ratio.

    Args:
        result: BacktestResult object with trades
        n_simulations: Number of Monte Carlo runs (default 1000)
        initial_capital: Starting capital (default 10000)
        max_slippage_ticks: Max random slippage per trade in ticks (default 0)
        symbol: Instrument symbol for tick value lookup (default MES)
        seed: Random seed for reproducibility (default 42)

    Returns:
        Dictionary with percentile statistics, confidence metrics, and verdict
    """
    pnls = np.array([t.pnl for t in result.trades], dtype=np.float64)

    # Get tick value for slippage conversion
    tick_value = _get_tick_value(symbol)
    n_trades = len(pnls)

    if n_trades == 0:
        return {
            "n_simulations": n_simulations,
            "n_trades": 0,
            "original": {},
            "distribution": {},
            "confidence": {},
            "verdict": "POOR",
        }

    # --- Original strategy metrics ---
    orig_equity = initial_capital + np.cumsum(pnls)
    orig_equity = np.concatenate([[initial_capital], orig_equity])
    orig_final = float(orig_equity[-1])
    orig_return_pct = (orig_final - initial_capital) / initial_capital * 100.0
    orig_max_dd = _compute_max_dd(orig_equity)
    orig_sharpe = _compute_sharpe(orig_equity)

    gross_profit = float(pnls[pnls > 0].sum()) if (pnls > 0).any() else 0.0
    gross_loss = float(abs(pnls[pnls <= 0].sum())) if (pnls <= 0).any() else 0.0
    orig_pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # --- Monte Carlo simulations (vectorised) ---
    rng = np.random.default_rng(seed)

    # Build matrix of shuffled indices: (n_simulations, n_trades)
    # Each row is a permutation of trade indices
    idx_matrix = np.tile(np.arange(n_trades), (n_simulations, 1))
    # Shuffle each row independently using the RNG
    for i in range(n_simulations):
        rng.shuffle(idx_matrix[i])

    # Gather shuffled P&Ls and compute cumulative equity curves
    shuffled_pnls = pnls[idx_matrix]  # (n_simulations, n_trades)

    # Apply random slippage if specified
    if max_slippage_ticks > 0:
        # Generate random slippage in ticks: uniform between 0 and max_slippage_ticks
        # Shape: (n_simulations, n_trades)
        slippage_ticks = rng.uniform(0, max_slippage_ticks, size=(n_simulations, n_trades))
        # Convert ticks to dollars and subtract from P&Ls (slippage reduces profit/increases loss)
        slippage_dollars = slippage_ticks * tick_value
        shuffled_pnls = shuffled_pnls - slippage_dollars

    cum_pnls = np.cumsum(shuffled_pnls, axis=1)  # (n_simulations, n_trades)

    # Prepend initial capital column
    init_col = np.full((n_simulations, 1), initial_capital)
    equities = np.hstack([init_col, initial_capital + cum_pnls])  # (n_sims, n_trades+1)

    # Final capitals
    final_capitals = equities[:, -1]

    # Max drawdowns per simulation
    peaks = np.maximum.accumulate(equities, axis=1)
    dd = (equities - peaks) / peaks
    max_dds = np.abs(dd.min(axis=1)) * 100.0  # positive percentages

    # Sharpe ratios per simulation
    returns = np.diff(equities, axis=1) / equities[:, :-1]
    means = returns.mean(axis=1)
    stds = returns.std(axis=1)
    # Avoid division by zero
    safe_stds = np.where(stds == 0, 1.0, stds)
    sharpes = means / safe_stds * np.sqrt(252.0)
    sharpes = np.where(stds == 0, 0.0, sharpes)

    # --- Distribution stats helper ---
    def _dist_stats(arr: np.ndarray) -> dict:
        return {
            "p5": float(np.percentile(arr, 5)),
            "p25": float(np.percentile(arr, 25)),
            "median": float(np.median(arr)),
            "p75": float(np.percentile(arr, 75)),
            "p95": float(np.percentile(arr, 95)),
            "mean": float(arr.mean()),
            "std": float(arr.std()),
        }

    dist_final = _dist_stats(final_capitals)
    dist_dd = _dist_stats(max_dds)
    dist_sharpe = _dist_stats(sharpes)

    # --- Confidence metrics ---
    prob_profitable = float((final_capitals > initial_capital).mean() * 100.0)
    prob_better = float((final_capitals >= orig_final).mean() * 100.0)
    prob_2x = float((final_capitals >= initial_capital * 2.0).mean() * 100.0)
    # Fraction of PERMUTED paths (reorderings of the same trade multiset) whose
    # FINAL capital ends below starting capital (any net loss) -- NOT a
    # drawdown-threshold breach. Distinct from `probability_of_ruin()` below,
    # which is an IID bootstrap over MINIMUM equity vs. a ruin threshold.
    prob_any_loss_permuted = float((final_capitals < initial_capital).mean() * 100.0)
    var_5 = float(np.percentile(final_capitals, 5))
    bottom_5_mask = final_capitals <= np.percentile(final_capitals, 5)
    expected_shortfall = (
        float(final_capitals[bottom_5_mask].mean()) if bottom_5_mask.any() else var_5
    )

    # --- Verdict ---
    original_above_p75 = orig_final >= dist_final["p75"]
    original_above_median = orig_final >= dist_final["median"]

    if prob_profitable > 80.0 and original_above_p75:
        verdict = "EXCELLENT"
    elif prob_profitable > 65.0 and original_above_median:
        verdict = "GOOD"
    elif prob_profitable > 50.0:
        verdict = "MARGINAL"
    else:
        verdict = "POOR"

    return {
        "n_simulations": n_simulations,
        "n_trades": n_trades,
        "original": {
            "final_capital": round(orig_final, 2),
            "total_return_pct": round(orig_return_pct, 2),
            "max_drawdown_pct": round(orig_max_dd, 2),
            "sharpe_ratio": round(orig_sharpe, 4),
            "profit_factor": round(orig_pf, 3),
        },
        "distribution": {
            "final_capital": {k: round(v, 2) for k, v in dist_final.items()},
            "max_drawdown_pct": {k: round(v, 2) for k, v in dist_dd.items()},
            "sharpe_ratio": {k: round(v, 4) for k, v in dist_sharpe.items()},
        },
        "confidence": {
            "prob_profitable": round(prob_profitable, 2),
            "prob_better_than_original": round(prob_better, 2),
            "prob_achieving_2x_return": round(prob_2x, 2),
            "prob_any_loss_permuted": round(prob_any_loss_permuted, 2),
            "value_at_risk_5pct": round(var_5, 2),
            "expected_shortfall": round(expected_shortfall, 2),
            "worst_case_max_drawdown": round(float(np.percentile(max_dds, 5)), 2),
        },
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Bootstrap primitives (Tier A statistical hardening)
# ---------------------------------------------------------------------------
#
# `run_monte_carlo` answers "given the observed multiset of PnLs, what
# drawdown path could we have seen under a different trade order?"
# The bootstrap functions below answer a different question:
#   "if the trade-generating process produced a new sample of size N, what
#    PF / Sharpe / max-DD would we see?"
#
# Permutation (shuffle without replacement) preserves the exact multiset.
# Bootstrap (resample with replacement) approximates the sampling
# distribution of the statistic. Both belong in this module under distinct
# names so downstream callers can pick the question that matches their need.
#
# Moving-block bootstrap is added for strategies where trade PnLs are
# serially correlated (mean-reversion in particular). Default block length
# is sqrt(N) — a standard finite-sample rule of thumb from Politis-Romano.


def _pf_from_pnls(pnls: np.ndarray) -> float:
    """Profit factor from a pnl array. Returns inf if no losses, 0 if no wins."""
    wins = pnls[pnls > 0].sum()
    losses = -pnls[pnls < 0].sum()  # absolute value
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return float(wins / losses)


def bootstrap_pf(
    pnls: list[float] | np.ndarray,
    n_resamples: int = 10_000,
    seed: int = 42,
) -> dict:
    """Bootstrap a 95% confidence interval on profit factor.

    Resamples the pnl list WITH REPLACEMENT n_resamples times and recomputes
    PF on each resample. The resulting distribution approximates the sampling
    distribution of PF given the observed trade-generating process.

    Args:
        pnls: per-trade PnL values (USD)
        n_resamples: bootstrap iterations
        seed: RNG seed for reproducibility

    Returns:
        {median_pf, pf_ci_95_low, pf_ci_95_high, p_positive_edge, n_trades}
        p_positive_edge = fraction of bootstrap resamples with PF > 1.0
    """
    pnls_arr = np.asarray(pnls, dtype=float)
    n = len(pnls_arr)
    if n == 0:
        return {
            "median_pf": 0.0,
            "pf_ci_95_low": 0.0,
            "pf_ci_95_high": 0.0,
            "p_positive_edge": 0.0,
            "n_trades": 0,
        }

    rng = np.random.default_rng(seed)
    pfs = np.empty(n_resamples, dtype=float)
    for i in range(n_resamples):
        sample = pnls_arr[rng.integers(0, n, size=n)]
        pfs[i] = _pf_from_pnls(sample)

    # Replace inf (no-losses resamples) with a large finite sentinel so
    # percentiles remain meaningful. np.percentile handles inf poorly.
    finite = pfs[np.isfinite(pfs)]
    if len(finite) == 0:
        median_pf = float("inf")
        ci_low = float("inf")
        ci_high = float("inf")
    else:
        median_pf = float(np.median(finite))
        ci_low = float(np.percentile(finite, 2.5))
        ci_high = float(np.percentile(finite, 97.5))

    p_positive_edge = float(np.mean(pfs > 1.0))

    return {
        "median_pf": round(median_pf, 4),
        "pf_ci_95_low": round(ci_low, 4),
        "pf_ci_95_high": round(ci_high, 4),
        "p_positive_edge": round(p_positive_edge, 4),
        "n_trades": n,
    }


def moving_block_bootstrap(
    pnls: list[float] | np.ndarray,
    n_resamples: int = 10_000,
    block_size: int | None = None,
    seed: int = 42,
) -> dict:
    """Moving-block bootstrap preserving short-run serial correlation.

    Instead of resampling individual trades (IID assumption), sample blocks of
    contiguous trades with replacement. This preserves serial-correlation
    structure important for mean-reversion strategies, where sequential
    trades are NOT independent.

    Args:
        pnls: per-trade PnL values
        n_resamples: bootstrap iterations
        block_size: contiguous-block length. Defaults to ceil(sqrt(N)).
        seed: RNG seed

    Returns:
        {median_pf, pf_ci_95_low, pf_ci_95_high, p_positive_edge, block_size, n_trades}
    """
    pnls_arr = np.asarray(pnls, dtype=float)
    n = len(pnls_arr)
    if n == 0:
        return {
            "median_pf": 0.0,
            "pf_ci_95_low": 0.0,
            "pf_ci_95_high": 0.0,
            "p_positive_edge": 0.0,
            "block_size": 0,
            "n_trades": 0,
        }

    if block_size is None:
        block_size = max(1, int(np.ceil(np.sqrt(n))))
    block_size = min(block_size, n)

    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block_size))
    max_start = n - block_size + 1

    pfs = np.empty(n_resamples, dtype=float)
    for i in range(n_resamples):
        starts = rng.integers(0, max_start, size=n_blocks)
        sample = np.concatenate([pnls_arr[s : s + block_size] for s in starts])[:n]
        pfs[i] = _pf_from_pnls(sample)

    finite = pfs[np.isfinite(pfs)]
    if len(finite) == 0:
        median_pf, ci_low, ci_high = float("inf"), float("inf"), float("inf")
    else:
        median_pf = float(np.median(finite))
        ci_low = float(np.percentile(finite, 2.5))
        ci_high = float(np.percentile(finite, 97.5))
    p_positive_edge = float(np.mean(pfs > 1.0))

    return {
        "median_pf": round(median_pf, 4),
        "pf_ci_95_low": round(ci_low, 4),
        "pf_ci_95_high": round(ci_high, 4),
        "p_positive_edge": round(p_positive_edge, 4),
        "block_size": block_size,
        "n_trades": n,
    }


def bootstrap_sharpe(
    pnls: list[float] | np.ndarray,
    initial_capital: float = 10_000.0,
    n_resamples: int = 10_000,
    seed: int = 42,
    ann_factor: float = 252.0,
) -> dict:
    """Bootstrap a 95% confidence interval on Sharpe ratio.

    Sharpe is computed from the equity curve that results from applying the
    resampled PnL sequence, matching `_compute_sharpe` convention in this
    module.

    Args:
        pnls: per-trade PnL values (USD)
        initial_capital: starting equity for Sharpe normalization
        n_resamples: bootstrap iterations
        seed: RNG seed
        ann_factor: annualization factor (252 trading days is the convention)

    Returns:
        {median_sharpe, sharpe_ci_95_low, sharpe_ci_95_high, p_positive_sharpe, n_trades}
    """
    pnls_arr = np.asarray(pnls, dtype=float)
    n = len(pnls_arr)
    if n < 2:
        return {
            "median_sharpe": 0.0,
            "sharpe_ci_95_low": 0.0,
            "sharpe_ci_95_high": 0.0,
            "p_positive_sharpe": 0.0,
            "n_trades": n,
        }

    rng = np.random.default_rng(seed)
    sharpes = np.empty(n_resamples, dtype=float)
    for i in range(n_resamples):
        sample = pnls_arr[rng.integers(0, n, size=n)]
        equity = np.concatenate([[initial_capital], initial_capital + np.cumsum(sample)])
        sharpes[i] = _compute_sharpe(equity, ann_factor=ann_factor)

    return {
        "median_sharpe": round(float(np.median(sharpes)), 4),
        "sharpe_ci_95_low": round(float(np.percentile(sharpes, 2.5)), 4),
        "sharpe_ci_95_high": round(float(np.percentile(sharpes, 97.5)), 4),
        "p_positive_sharpe": round(float(np.mean(sharpes > 0)), 4),
        "n_trades": n,
    }


def bootstrap_win_rate(
    pnls: list[float] | np.ndarray,
    n_resamples: int = 10_000,
    seed: int = 42,
) -> dict:
    """Bootstrap a 95% confidence interval on win rate (fraction of trades with PnL > 0).

    Complement to the Deflated Sharpe: DSR is a risk-adjusted-RETURN statistic, so
    a strategy carried by a few large outlier wins can still pass it. The win-rate
    CI lower bound binds exactly there — it measures how *reliably* the strategy
    wins, independent of win size. Resamples the per-trade win/loss outcomes WITH
    REPLACEMENT and reports the 2.5th percentile as the lower bound.

    Args:
        pnls: per-trade PnL values (USD); a "win" is pnl > 0 (breakeven is not a win)
        n_resamples: bootstrap iterations
        seed: RNG seed

    Returns:
        {win_rate, win_rate_ci_95_low, win_rate_ci_95_high, n_trades}
        Fail-safe (all 0.0) when fewer than 2 trades exist.
    """
    pnls_arr = np.asarray(pnls, dtype=float)
    n = len(pnls_arr)
    if n < 2:
        return {
            "win_rate": 0.0,
            "win_rate_ci_95_low": 0.0,
            "win_rate_ci_95_high": 0.0,
            "n_trades": n,
        }

    wins = (pnls_arr > 0.0).astype(float)
    rng = np.random.default_rng(seed)
    rates = np.empty(n_resamples, dtype=float)
    for i in range(n_resamples):
        rates[i] = float(np.mean(wins[rng.integers(0, n, size=n)]))

    return {
        "win_rate": round(float(np.mean(wins)), 4),
        "win_rate_ci_95_low": round(float(np.percentile(rates, 2.5)), 4),
        "win_rate_ci_95_high": round(float(np.percentile(rates, 97.5)), 4),
        "n_trades": n,
    }


def bootstrap_max_dd(
    pnls: list[float] | np.ndarray,
    initial_capital: float = 10_000.0,
    n_resamples: int = 10_000,
    seed: int = 42,
) -> dict:
    """Permutation distribution of max drawdown.

    Max drawdown is path-dependent, so the meaningful question is "under
    alternative trade orders, what's the worst DD we could have seen?"
    This is the same question `run_monte_carlo` answers but exposed as a
    primitive that works on a bare pnl list — no BacktestResult needed.

    Args:
        pnls: per-trade PnL values (USD)
        initial_capital: starting equity for DD scaling
        n_resamples: permutation iterations
        seed: RNG seed

    Returns:
        {observed_max_dd_pct, mc_50th, mc_95th, mc_99th, n_trades}
    """
    pnls_arr = np.asarray(pnls, dtype=float)
    n = len(pnls_arr)
    if n < 2:
        return {
            "observed_max_dd_pct": 0.0,
            "mc_50th": 0.0,
            "mc_95th": 0.0,
            "mc_99th": 0.0,
            "n_trades": n,
        }

    observed_equity = np.concatenate([[initial_capital], initial_capital + np.cumsum(pnls_arr)])
    observed_dd = _compute_max_dd(observed_equity)

    rng = np.random.default_rng(seed)
    dds = np.empty(n_resamples, dtype=float)
    for i in range(n_resamples):
        shuffled = rng.permutation(pnls_arr)
        equity = np.concatenate([[initial_capital], initial_capital + np.cumsum(shuffled)])
        dds[i] = _compute_max_dd(equity)

    return {
        "observed_max_dd_pct": round(observed_dd, 4),
        "mc_50th": round(float(np.percentile(dds, 50)), 4),
        "mc_95th": round(float(np.percentile(dds, 95)), 4),
        "mc_99th": round(float(np.percentile(dds, 99)), 4),
        "n_trades": n,
    }


def compute_var(
    pnls: list[float] | np.ndarray,
    confidence: float = 0.95,
    n_resamples: int = 10_000,
    seed: int = 42,
) -> dict:
    """Bootstrap-resampled historical-simulation VaR on the trade-P&L distribution.

    VaR is the (1-confidence) percentile of the per-trade PnL distribution — e.g.
    at confidence=0.95 this is the 5th percentile, the loss level exceeded only
    5% of the time. Resamples pnls WITH REPLACEMENT n_resamples times, takes the
    (1-confidence) percentile of EACH resample to build the sampling distribution
    of the VaR estimate, and reports the point estimate from the *observed* sample
    (not the bootstrap mean) alongside the median and 95% CI across resamples.

    SIGN / UNITS CONVENTION: same units as the input `pnls` (USD dollars, per the
    convention shared by `bootstrap_pf`/`bootstrap_max_dd` in this module) and the
    same SIGN convention as `metrics.py`'s `var_95`/`cvar_95` fields — negative
    for a loss level, not a positive magnitude. A strategy with no meaningful tail
    risk can have a VaR at or above 0.0.

    Args:
        pnls: per-trade PnL values (USD)
        confidence: VaR confidence level (default 0.95 -> 5th percentile)
        n_resamples: bootstrap iterations
        seed: RNG seed for reproducibility

    Returns:
        {var_pct, median_var, var_ci_95_low, var_ci_95_high, confidence, n_trades}
        Fail-safe (all 0.0) when fewer than 2 trades exist.
    """
    pnls_arr = np.asarray(pnls, dtype=float)
    n = len(pnls_arr)
    if n < 2:
        return {
            "var_pct": 0.0,
            "median_var": 0.0,
            "var_ci_95_low": 0.0,
            "var_ci_95_high": 0.0,
            "confidence": confidence,
            "n_trades": n,
        }

    percentile = (1.0 - confidence) * 100.0
    point_estimate = float(np.percentile(pnls_arr, percentile))

    rng = np.random.default_rng(seed)
    resampled_vars = np.empty(n_resamples, dtype=float)
    for i in range(n_resamples):
        sample = pnls_arr[rng.integers(0, n, size=n)]
        resampled_vars[i] = np.percentile(sample, percentile)

    return {
        "var_pct": round(point_estimate, 4),
        "median_var": round(float(np.median(resampled_vars)), 4),
        "var_ci_95_low": round(float(np.percentile(resampled_vars, 2.5)), 4),
        "var_ci_95_high": round(float(np.percentile(resampled_vars, 97.5)), 4),
        "confidence": confidence,
        "n_trades": n,
    }


def compute_cvar(
    pnls: list[float] | np.ndarray,
    confidence: float = 0.95,
    n_resamples: int = 10_000,
    seed: int = 42,
) -> dict:
    """Bootstrap-resampled CVaR / Expected Shortfall: mean loss beyond VaR.

    CVaR (also called Expected Shortfall) is the mean of the tail of the PnL
    distribution at or beyond the VaR threshold — it answers "given that we're
    in the bad (1-confidence) scenario, how bad on average?" Resamples pnls WITH
    REPLACEMENT n_resamples times; on each resample, recomputes the VaR threshold
    and averages the resample's own tail beyond it, matching the observed-sample
    computation in `metrics.py::calculate_metrics` (`cvar_95`/`cvar_99`).

    SIGN / UNITS CONVENTION: same as `compute_var` — USD dollars (module
    convention), negative for a loss (matches `metrics.py`'s `cvar_95`/`cvar_99`
    sign convention, just in dollars rather than fraction-of-capital).

    Args:
        pnls: per-trade PnL values (USD)
        confidence: CVaR confidence level (default 0.95 -> beyond 5th percentile)
        n_resamples: bootstrap iterations
        seed: RNG seed for reproducibility

    Returns:
        {cvar, median_cvar, cvar_ci_95_low, cvar_ci_95_high, confidence, n_trades}
        Fail-safe (all 0.0) when fewer than 2 trades exist.
    """
    pnls_arr = np.asarray(pnls, dtype=float)
    n = len(pnls_arr)
    if n < 2:
        return {
            "cvar": 0.0,
            "median_cvar": 0.0,
            "cvar_ci_95_low": 0.0,
            "cvar_ci_95_high": 0.0,
            "confidence": confidence,
            "n_trades": n,
        }

    percentile = (1.0 - confidence) * 100.0

    def _cvar_of(sample: np.ndarray) -> float:
        var_point = np.percentile(sample, percentile)
        tail = sample[sample <= var_point]
        return float(tail.mean()) if len(tail) > 0 else float(var_point)

    point_estimate = _cvar_of(pnls_arr)

    rng = np.random.default_rng(seed)
    resampled_cvars = np.empty(n_resamples, dtype=float)
    for i in range(n_resamples):
        sample = pnls_arr[rng.integers(0, n, size=n)]
        resampled_cvars[i] = _cvar_of(sample)

    return {
        "cvar": round(point_estimate, 4),
        "median_cvar": round(float(np.median(resampled_cvars)), 4),
        "cvar_ci_95_low": round(float(np.percentile(resampled_cvars, 2.5)), 4),
        "cvar_ci_95_high": round(float(np.percentile(resampled_cvars, 97.5)), 4),
        "confidence": confidence,
        "n_trades": n,
    }


def probability_of_ruin(
    pnls: list[float] | np.ndarray,
    initial_capital: float = 10_000.0,
    ruin_threshold_pct: float = 0.5,
    n_resamples: int = 10_000,
    seed: int = 42,
) -> dict:
    """Fraction of bootstrap equity paths whose MINIMUM value breaches a ruin floor.

    Distinct from `run_monte_carlo`'s `prob_any_loss_permuted` field in two ways:
    (1) it checks the MINIMUM value along the path, not the final value — a path
    that dips below the ruin floor mid-sequence and recovers still counts as ruin;
    (2) it resamples pnls WITH REPLACEMENT (IID bootstrap, same as
    `bootstrap_pf`/`bootstrap_sharpe`) rather than permuting the exact same trade
    multiset, since ruin risk should reflect the sampling distribution of a
    plausible new trade sequence, not just reorderings of the observed one.

    Args:
        pnls: per-trade PnL values (USD)
        initial_capital: starting equity
        ruin_threshold_pct: fraction of initial_capital defining the ruin floor
            (default 0.5 -> ruin if equity ever drops to 50% of starting capital)
        n_resamples: bootstrap iterations
        seed: RNG seed for reproducibility

    Returns:
        {probability_of_ruin, ruin_threshold_pct, ruin_equity_level, n_resamples, n_trades}
        Fail-safe: returns 0.0 (not 1.0) for < 2 trades -- too little data to
        simulate a path, must not silently over-flag as risky.
    """
    pnls_arr = np.asarray(pnls, dtype=float)
    n = len(pnls_arr)
    ruin_level = initial_capital * ruin_threshold_pct

    if n < 2:
        return {
            "probability_of_ruin": 0.0,
            "ruin_threshold_pct": ruin_threshold_pct,
            "ruin_equity_level": round(float(ruin_level), 2),
            "n_resamples": n_resamples,
            "n_trades": n,
        }

    rng = np.random.default_rng(seed)
    breaches = 0
    for i in range(n_resamples):
        sample = pnls_arr[rng.integers(0, n, size=n)]
        equity = np.concatenate([[initial_capital], initial_capital + np.cumsum(sample)])
        if equity.min() <= ruin_level:
            breaches += 1

    return {
        "probability_of_ruin": round(breaches / n_resamples, 4),
        "ruin_threshold_pct": ruin_threshold_pct,
        "ruin_equity_level": round(float(ruin_level), 2),
        "n_resamples": n_resamples,
        "n_trades": n,
    }


# ---------------------------------------------------------------------------
# Slippage stress test
# ---------------------------------------------------------------------------


def run_slippage_stress(
    result: BacktestResult,
    symbol: str = "MES",
    extra_tick_scenarios: tuple[int, ...] = (0, 1, 2, 3, 4, 6, 8),
) -> dict:
    """Measure how PF degrades as execution slippage increases.

    For each extra-ticks scenario, adds (extra_ticks × tick_value) as a
    fixed cost to every trade and recomputes PF. Identifies the breakeven
    slippage — the number of extra ticks that drives PF to exactly 1.0.

    Args:
        result: BacktestResult with trades
        symbol: instrument symbol for tick value lookup
        extra_tick_scenarios: additional ticks per trade to stress-test

    Returns:
        {scenarios, breakeven_extra_ticks, breakeven_pf_at_1_tick, verdict}
    """
    tick_value = _get_tick_value(symbol)
    pnls = np.array([t.pnl for t in result.trades], dtype=np.float64)
    n = len(pnls)
    if n == 0:
        return {"scenarios": [], "breakeven_extra_ticks": None, "verdict": "NO_TRADES"}

    scenarios = []
    prev_pf = None
    breakeven_ticks = None

    for extra_ticks in extra_tick_scenarios:
        added_cost = extra_ticks * tick_value  # $/contract/trade (one round-turn leg)
        adjusted = pnls - added_cost
        wins = adjusted[adjusted > 0]
        losses = adjusted[adjusted <= 0]
        gp = float(wins.sum()) if len(wins) else 0.0
        gl = float(abs(losses.sum())) if len(losses) else 0.0
        pf = gp / gl if gl > 0 else float("inf")
        profitable = pf > 1.0
        scenarios.append(
            {
                "extra_ticks": extra_ticks,
                "added_cost_per_trade": round(added_cost, 2),
                "pf": round(pf, 3),
                "profitable": profitable,
            }
        )
        # Linear interpolation for breakeven (where PF crosses 1.0)
        if prev_pf is not None and prev_pf > 1.0 and pf <= 1.0 and breakeven_ticks is None:
            frac = (prev_pf - 1.0) / (prev_pf - pf)
            prev_ticks = scenarios[-2]["extra_ticks"]
            breakeven_ticks = prev_ticks + frac * (extra_ticks - prev_ticks)
        prev_pf = pf

    # Verdict: how many extra ticks can this strategy absorb?
    if breakeven_ticks is None:
        verdict = "ROBUST"  # PF > 1.0 even at max stress scenario
    elif breakeven_ticks >= 4:
        verdict = "ADEQUATE"  # survives realistic spread widening
    elif breakeven_ticks >= 2:
        verdict = "MARGINAL"  # thin edge
    else:
        verdict = "FRAGILE"  # even normal execution variability kills it

    return {
        "symbol": symbol,
        "tick_value": tick_value,
        "n_trades": n,
        "scenarios": scenarios,
        "breakeven_extra_ticks": round(breakeven_ticks, 2) if breakeven_ticks is not None else None,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Report formatter
# ---------------------------------------------------------------------------


def format_report(mc: dict) -> str:
    """Return a human-readable Monte Carlo report string."""
    if mc["n_trades"] == 0:
        return "=== MONTE CARLO ANALYSIS ===\nNo trades to simulate.\n"

    o = mc["original"]
    d = mc["distribution"]
    c = mc["confidence"]

    lines = [
        f"=== MONTE CARLO ANALYSIS ({mc['n_simulations']:,} simulations) ===",
        f"Original Strategy: Return={o['total_return_pct']:+.1f}%  "
        f"MaxDD={o['max_drawdown_pct']:.1f}%  "
        f"Sharpe={o['sharpe_ratio']:.2f}  "
        f"PF={o['profit_factor']:.2f}",
        "",
        "DISTRIBUTION OF OUTCOMES:",
        f"{'':14s} {'P5%':>10s} {'P25%':>10s} {'Median':>10s} {'P75%':>10s} {'P95%':>10s}",
        f"{'Final Cap:':14s} "
        f"${d['final_capital']['p5']:>9,.0f} "
        f"${d['final_capital']['p25']:>9,.0f} "
        f"${d['final_capital']['median']:>9,.0f} "
        f"${d['final_capital']['p75']:>9,.0f} "
        f"${d['final_capital']['p95']:>9,.0f}",
        f"{'Max DD:':14s} "
        f"{d['max_drawdown_pct']['p5']:>9.1f}% "
        f"{d['max_drawdown_pct']['p25']:>9.1f}% "
        f"{d['max_drawdown_pct']['median']:>9.1f}% "
        f"{d['max_drawdown_pct']['p75']:>9.1f}% "
        f"{d['max_drawdown_pct']['p95']:>9.1f}%",
        f"{'Sharpe:':14s} "
        f"{d['sharpe_ratio']['p5']:>10.2f} "
        f"{d['sharpe_ratio']['p25']:>10.2f} "
        f"{d['sharpe_ratio']['median']:>10.2f} "
        f"{d['sharpe_ratio']['p75']:>10.2f} "
        f"{d['sharpe_ratio']['p95']:>10.2f}",
        "",
        "CONFIDENCE ANALYSIS:",
        f"  Probability of Profit:       {c['prob_profitable']:.1f}%",
        f"  Prob Any Loss (permuted):    {c['prob_any_loss_permuted']:.1f}%",
        f"  Probability 2x Return:       {c['prob_achieving_2x_return']:.1f}%",
        f"  Original beats X% of sims:   {100.0 - c['prob_better_than_original']:.1f}%",
        f"  5% Value at Risk:            ${c['value_at_risk_5pct']:,.0f}",
        f"  Expected Shortfall (CVaR):   ${c['expected_shortfall']:,.0f}",
        f"  Worst-case Max DD (p5):      {c['worst_case_max_drawdown']:.1f}%",
        "",
        f"VERDICT: {mc['verdict']}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def _load_result_from_json(path: str) -> BacktestResult:
    """Load a backtest JSON file and reconstruct a BacktestResult object."""
    with open(path, "r") as f:
        data = json.load(f)

    # Support two JSON formats:
    #  1. Full BacktestResult.to_dict() output (has 'trades' key with full trade dicts)
    #  2. Simplified format from run_backtest.py (has 'trades_list' with {entry_date, exit_date, pnl})

    trades: List[Trade] = []

    if "trades" in data and data["trades"]:
        # Full format
        for td in data["trades"]:
            from datetime import datetime

            entry_dt = (
                datetime.fromisoformat(td["entry_date"]) if td.get("entry_date") else datetime.now()
            )
            exit_dt = datetime.fromisoformat(td["exit_date"]) if td.get("exit_date") else None
            trades.append(
                Trade(
                    entry_date=entry_dt,
                    symbol=td.get("symbol", data.get("symbol", "UNK")),
                    direction=td.get("direction", "long"),
                    entry_price=td.get("entry_price", 0.0),
                    stop_price=td.get("stop_price", 0.0),
                    target_1=td.get("target_1", 0.0),
                    target_2=td.get("target_2", 0.0),
                    contracts=td.get("contracts", 1),
                    multiplier=td.get("multiplier", 1.0),
                    exit_date=exit_dt,
                    exit_price=td.get("exit_price"),
                    pnl=td.get("pnl", 0.0),
                    pnl_pct=td.get("pnl_pct", 0.0),
                    exit_reason=td.get("exit_reason", ""),
                    holding_bars=td.get("holding_bars", 0),
                    regime=td.get("regime", ""),
                    bias=td.get("bias", ""),
                )
            )
    elif "trades_list" in data and data["trades_list"]:
        # Simplified format
        from datetime import datetime

        symbol = data.get("symbol", "UNK")
        for td in data["trades_list"]:
            entry_dt = (
                datetime.fromisoformat(td["entry_date"]) if td.get("entry_date") else datetime.now()
            )
            exit_dt = datetime.fromisoformat(td["exit_date"]) if td.get("exit_date") else None
            trades.append(
                Trade(
                    entry_date=entry_dt,
                    symbol=symbol,
                    direction="long",
                    entry_price=0.0,
                    stop_price=0.0,
                    target_1=0.0,
                    target_2=0.0,
                    contracts=1,
                    multiplier=1.0,
                    exit_date=exit_dt,
                    pnl=td.get("pnl", 0.0),
                )
            )

    initial_capital = data.get("initial_capital", 10_000.0)
    total_pnl = sum(t.pnl for t in trades)

    result = BacktestResult(
        symbol=data.get("symbol", "UNK"),
        start_date=data.get("start_date", data.get("start", "")),
        end_date=data.get("end_date", data.get("end", "")),
        initial_capital=initial_capital,
        final_capital=data.get("final_capital", initial_capital + total_pnl),
        trades=trades,
        total_trades=len(trades),
        total_pnl=total_pnl,
        total_return_pct=data.get("total_return_pct", data.get("total_return", 0.0)),
        sharpe_ratio=data.get("sharpe_ratio", data.get("sharpe", 0.0)),
        profit_factor=data.get("profit_factor", data.get("profit_factor", 0.0)),
        win_rate=data.get("win_rate", 0.0),
    )

    return result


def main():
    parser = argparse.ArgumentParser(description="Monte Carlo simulation on backtest results")
    parser.add_argument("--result", required=True, help="Path to backtest result JSON file")
    parser.add_argument(
        "--n-sims", type=int, default=1_000, help="Number of simulations (default: 1000)"
    )
    parser.add_argument(
        "--capital", type=float, default=10_000.0, help="Initial capital (default: 10000)"
    )
    parser.add_argument(
        "--max-slippage",
        type=float,
        default=0.0,
        help="Max random slippage per trade in ticks (default: 0)",
    )
    parser.add_argument(
        "--symbol", default="MES", help="Instrument symbol for tick value (default: MES)"
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    args = parser.parse_args()

    # Load result
    result_path = Path(args.result)
    if not result_path.exists():
        print(f"ERROR: File not found: {result_path}")
        sys.exit(1)

    print(f"Loading backtest results from {result_path} ...")
    bt_result = _load_result_from_json(str(result_path))
    print(f"  {len(bt_result.trades)} trades loaded for {bt_result.symbol}")

    # Run simulation
    print(f"Running {args.n_sims:,} Monte Carlo simulations...")
    if args.max_slippage > 0:
        print(f"  Slippage: uniform 0-{args.max_slippage} ticks ({args.symbol})")
    mc = run_monte_carlo(
        bt_result,
        n_simulations=args.n_sims,
        initial_capital=args.capital,
        max_slippage_ticks=args.max_slippage,
        symbol=args.symbol,
        seed=args.seed,
    )

    # Print report
    print()
    print(format_report(mc))

    # Save JSON output
    symbol = bt_result.symbol
    # Derive interval from filename if possible
    interval = "1h"
    stem = result_path.stem
    for itv in ("1h", "1d", "5m", "15m", "30m", "4h"):
        if itv in stem:
            interval = itv
            break

    out_path = result_path.parent / f"{symbol}_{interval}_monte_carlo.json"
    with open(out_path, "w") as f:
        json.dump(mc, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()

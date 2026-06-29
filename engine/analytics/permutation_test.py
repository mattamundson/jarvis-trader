"""Monte Carlo permutation tests (MCPT) for strategy validation.

This is the price-permutation companion to ``backtest/monte_carlo.py``. Where the latter
shuffles a realized trade sequence, this module shuffles the *price bars* (via
``backtest.bar_permute``) and re-runs the strategy's own optimizer on each permutation,
building a null distribution for the optimized profit factor. It answers the question a
single backtest cannot: *would my optimization process have produced a result this good
on data with no real pattern?* (Masters, *Permutation and Randomization Tests for Trading
System Development*, 2020.)

Two tests and one harness:

* ``run_insample_mcpt`` — re-optimize on each permutation. Catches data-mining bias: an
  optimizer that finds "edge" in noise just as easily as in real data has none.
* ``run_walkforward_mcpt`` — permute only the data *after* the first training fold and
  run the full walk-forward, so the strategy decides on permuted bars using parameters
  learned from real ones (production-faithful). Catches lucky single-path alignment.
* ``validate_strategy`` — the four-gate pipeline (in-sample excellence -> in-sample MCPT
  -> walk-forward -> walk-forward MCPT) with fail-closed verdicts.

Caller contract (decoupled from any specific runner so this stays additive):

* ``optimize_fn(df) -> (params, profit_factor)`` — run the parameter search on ``df`` and
  return the chosen params plus the in-sample profit factor of the winner.
* ``walkforward_fn(df, train_window) -> profit_factor`` — run the rolling walk-forward
  over ``df`` with the given training window and return the aggregate OOS profit factor.

p-values use the Phipson & Smyth (2010) convention ``p = (1 + #{perm >= real}) / (1 + n)``
so a permutation test never reports exactly zero (a single sample is never infinitely
significant).

Discipline (non-negotiable, see ``.claude/rules/ml-pitfalls-defense.md``): lock the
strategy specification *before* running MCPT. If it fails a gate, discard the strategy —
do not tweak-and-rerun. Iterating against the test turns the test into a target and
data-mines the p-value itself.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import numpy as np
import pandas as pd

from backtest.bar_permute import get_permutation

logger = logging.getLogger(__name__)

OptimizeFn = Callable[[pd.DataFrame], "tuple[Any, float]"]
WalkforwardFn = Callable[[pd.DataFrame, int], float]
PermuteFn = Callable[..., pd.DataFrame]

# ---------------------------------------------------------------------------
# Thresholds — canonical; mirror the addendum in ml-pitfalls-defense.md
# ---------------------------------------------------------------------------

#: In-sample MCPT p-value ceiling. Masters recommends a strict bar here because the
#: in-sample test is cheap and is the first thing to throw a bad idea away.
INSAMPLE_ALPHA: float = 0.01

#: Walk-forward MCPT p-value ceiling for < ~2 years of OOS data.
WF_ALPHA: float = 0.05

#: Walk-forward MCPT p-value ceiling for >= ~2 years of OOS data (more samples ->
#: demand more significance).
WF_ALPHA_LONG: float = 0.01

DEFAULT_INSAMPLE_PERMS: int = 1000
DEFAULT_WF_PERMS: int = 200


def _perm_pvalue(real: float, permuted: list[float]) -> float:
    """Phipson & Smyth permutation p-value: (1 + #{perm >= real}) / (1 + n)."""
    n = len(permuted)
    better = sum(1 for p in permuted if p >= real)
    return (1 + better) / (1 + n)


def run_insample_mcpt(
    df: pd.DataFrame,
    optimize_fn: OptimizeFn,
    n_permutations: int = DEFAULT_INSAMPLE_PERMS,
    seed: int = 0,
    permute_fn: PermuteFn = get_permutation,
) -> dict[str, Any]:
    """In-sample MCPT: re-optimize on each price permutation, return the p-value.

    A high p-value means the optimizer extracts "edge" from noise as readily as from
    the real series -> the in-sample result is data-mining bias, not alpha.
    """
    real_params, real_pf = optimize_fn(df)
    permuted_pfs: list[float] = []
    for i in range(1, n_permutations + 1):
        perm = permute_fn(df, start_index=0, seed=seed + i)
        try:
            _, perm_pf = optimize_fn(perm)
        except Exception:  # pragma: no cover - a degenerate permutation must not abort the run
            logger.warning("optimize_fn failed on permutation %d; counting as PF=0", i)
            perm_pf = 0.0
        permuted_pfs.append(float(perm_pf))

    p_value = _perm_pvalue(real_pf, permuted_pfs)
    return {
        "test": "insample_mcpt",
        "real_pf": round(float(real_pf), 4),
        "real_params": real_params,
        "p_value": round(p_value, 4),
        "n_permutations": n_permutations,
        "perm_pf_mean": round(float(np.mean(permuted_pfs)), 4) if permuted_pfs else 0.0,
        "perm_better_count": sum(1 for p in permuted_pfs if p >= real_pf),
        "permuted_pfs": permuted_pfs,
        "passes": p_value < INSAMPLE_ALPHA,
        "alpha": INSAMPLE_ALPHA,
    }


def run_walkforward_mcpt(
    df: pd.DataFrame,
    walkforward_fn: WalkforwardFn,
    train_window: int,
    n_permutations: int = DEFAULT_WF_PERMS,
    seed: int = 0,
    permute_fn: PermuteFn = get_permutation,
    long_history: bool = False,
) -> dict[str, Any]:
    """Walk-forward MCPT: permute only post-train bars, re-run the full walk-forward.

    ``long_history`` selects the stricter alpha (WF_ALPHA_LONG) for >= ~2yr OOS data.
    """
    real_wf_pf = walkforward_fn(df, train_window)
    permuted_pfs: list[float] = []
    for i in range(1, n_permutations + 1):
        perm = permute_fn(df, start_index=train_window, seed=seed + i)
        try:
            perm_pf = walkforward_fn(perm, train_window)
        except Exception:  # pragma: no cover
            logger.warning("walkforward_fn failed on permutation %d; counting as PF=0", i)
            perm_pf = 0.0
        permuted_pfs.append(float(perm_pf))

    alpha = WF_ALPHA_LONG if long_history else WF_ALPHA
    p_value = _perm_pvalue(real_wf_pf, permuted_pfs)
    return {
        "test": "walkforward_mcpt",
        "real_wf_pf": round(float(real_wf_pf), 4),
        "p_value": round(p_value, 4),
        "n_permutations": n_permutations,
        "perm_pf_mean": round(float(np.mean(permuted_pfs)), 4) if permuted_pfs else 0.0,
        "perm_better_count": sum(1 for p in permuted_pfs if p >= real_wf_pf),
        "permuted_pfs": permuted_pfs,
        "passes": p_value < alpha,
        "alpha": alpha,
    }


def validate_strategy(
    df: pd.DataFrame,
    optimize_fn: OptimizeFn,
    walkforward_fn: WalkforwardFn,
    train_window: int,
    n_insample_perms: int = DEFAULT_INSAMPLE_PERMS,
    n_wf_perms: int = DEFAULT_WF_PERMS,
    seed: int = 0,
    permute_fn: PermuteFn = get_permutation,
    long_history: bool = False,
) -> dict[str, Any]:
    """Four-gate fail-closed validation pipeline.

    Gate 1 (in-sample excellence): optimized PF > 1 (a losing in-sample strategy is not
        worth permuting). Gate 2 (in-sample MCPT): p < INSAMPLE_ALPHA. Gate 3
        (walk-forward): aggregate OOS PF > 1. Gate 4 (walk-forward MCPT): p < alpha.

    Returns a dict with ``verdict`` in {PASS, REJECT (in-sample excellence),
    REJECT (in-sample MCPT), REJECT (walk-forward), REJECT (walk-forward MCPT)} plus the
    stats computed up to the first failing gate (fail-closed: later gates are not run).
    """
    _, real_is_pf = optimize_fn(df.iloc[: train_window + 1])
    if not real_is_pf > 1.0:
        return {"verdict": "REJECT (in-sample excellence)", "is_pf": round(float(real_is_pf), 4)}

    is_res = run_insample_mcpt(
        df.iloc[: train_window + 1], optimize_fn, n_insample_perms, seed, permute_fn
    )
    if not is_res["passes"]:
        return {
            "verdict": "REJECT (in-sample MCPT)",
            "is_pf": is_res["real_pf"],
            "is_pval": is_res["p_value"],
        }

    wf_res = run_walkforward_mcpt(
        df, walkforward_fn, train_window, n_wf_perms, seed, permute_fn, long_history
    )
    real_wf_pf = wf_res["real_wf_pf"]
    if not real_wf_pf > 1.0:
        return {
            "verdict": "REJECT (walk-forward)",
            "is_pf": is_res["real_pf"],
            "is_pval": is_res["p_value"],
            "wf_pf": real_wf_pf,
        }
    if not wf_res["passes"]:
        return {
            "verdict": "REJECT (walk-forward MCPT)",
            "is_pf": is_res["real_pf"],
            "is_pval": is_res["p_value"],
            "wf_pf": real_wf_pf,
            "wf_pval": wf_res["p_value"],
        }

    return {
        "verdict": "PASS",
        "is_pf": is_res["real_pf"],
        "is_pval": is_res["p_value"],
        "wf_pf": real_wf_pf,
        "wf_pval": wf_res["p_value"],
        "params": is_res["real_params"],
    }


# ---------------------------------------------------------------------------
# Trade-sign permutation test (Aronson EBTA ch. 6) — the OTHER null
# ---------------------------------------------------------------------------
#
# The MCPT above permutes *price* and re-optimizes; it is the right null for a
# mechanical optimizer. This test takes an already-realized *trade list* and asks a
# narrower question: given these trade outcomes, is the aggregate result better than a
# strategy with no directional edge would produce by chance? Under H0 (no edge) each
# trade is as likely to have made money as to have lost the same magnitude, so the null
# is built by randomly flipping the sign of each trade's P&L and rescoring.
#
# This is the correct null for ``forward_test.py`` graduation (the live entry path is
# LLM-driven, not a mechanical optimizer, so there is no optimizer to permute). It is
# provided here as a DIAGNOSTIC; wiring it into the graduation rule changes trade
# authorization and is deferred to a [safety-review] PR.

#: Trade-sign permutation p-value ceiling.
TRADE_SHUFFLE_ALPHA: float = 0.05


def _extract_pnls(trades: Any) -> np.ndarray:
    """Coerce a trade list into a float P&L array. Accepts floats, dicts with a 'pnl'
    key, or objects with a ``.pnl`` attribute."""
    out: list[float] = []
    for t in trades:
        if isinstance(t, (int, float)):
            out.append(float(t))
        elif isinstance(t, dict):
            out.append(float(t.get("pnl", 0.0)))
        else:
            out.append(float(getattr(t, "pnl", 0.0)))
    return np.array(out, dtype=np.float64)


def _trade_metric(pnls: np.ndarray, metric: str) -> float:
    """Score a P&L array. 'mean'/'total' test return edge; 'sharpe' tests risk-adjusted
    edge; 'profit_factor' tests the win/loss money ratio."""
    if metric == "mean":
        return float(pnls.mean())
    if metric == "total":
        return float(pnls.sum())
    if metric == "sharpe":
        std = pnls.std()
        return float(pnls.mean() / std) if std > 0 else 0.0
    if metric == "profit_factor":
        gp = float(pnls[pnls > 0].sum())
        gl = float(abs(pnls[pnls < 0].sum()))
        return gp / gl if gl > 0 else (gp if gp > 0 else 0.0)
    raise ValueError(f"unknown metric: {metric!r}")


def permute_and_score(
    trades: Any,
    n_iters: int = 500,
    metric: str = "mean",
    seed: int = 0,
) -> dict[str, Any]:
    """Sign-flip permutation test over a realized trade list (Aronson EBTA ch. 6).

    Builds a no-edge null by randomly negating each trade's P&L ``n_iters`` times and
    rescoring, then reports where the real score falls. A high p-value means the realized
    result is within what a no-edge strategy produces by luck.

    Args:
        trades: sequence of P&L floats, dicts with ``pnl``, or objects with ``.pnl``.
        n_iters: number of sign-flip permutations (Aronson recommends >= 500).
        metric: one of ``mean`` / ``total`` / ``sharpe`` / ``profit_factor``.
        seed: RNG seed.

    Returns:
        dict with ``real_score``, ``p_value``, ``passes`` (p < TRADE_SHUFFLE_ALPHA),
        ``n_trades`` and the null mean. With < 2 trades the test is undefined and
        returns ``p_value = 1.0`` (fail-closed: too little evidence is no evidence).
    """
    pnls = _extract_pnls(trades)
    n = len(pnls)
    if n < 2:
        return {
            "test": "trade_sign_permutation",
            "metric": metric,
            "real_score": float(pnls.sum()) if n else 0.0,
            "p_value": 1.0,
            "n_iters": n_iters,
            "n_trades": n,
            "perm_score_mean": 0.0,
            "passes": False,
            "alpha": TRADE_SHUFFLE_ALPHA,
        }

    real = _trade_metric(pnls, metric)
    rng = np.random.default_rng(seed)
    perm_scores = [
        _trade_metric(pnls * rng.choice((-1.0, 1.0), size=n), metric) for _ in range(n_iters)
    ]
    p_value = _perm_pvalue(real, perm_scores)
    return {
        "test": "trade_sign_permutation",
        "metric": metric,
        "real_score": round(real, 6),
        "p_value": round(p_value, 4),
        "n_iters": n_iters,
        "n_trades": n,
        "perm_score_mean": round(float(np.mean(perm_scores)), 6),
        "passes": p_value < TRADE_SHUFFLE_ALPHA,
        "alpha": TRADE_SHUFFLE_ALPHA,
    }


#: No-edge reference value per metric — the bootstrap reports the probability the metric
#: lands at or below it. Return metrics break even at 0; profit factor breaks even at 1.
_METRIC_BREAKEVEN: dict[str, float] = {
    "mean": 0.0,
    "total": 0.0,
    "sharpe": 0.0,
    "profit_factor": 1.0,
}


def bootstrap_metric_ci(
    trades: Any,
    n_iters: int = 2000,
    metric: str = "mean",
    seed: int = 0,
    ci: float = 0.95,
) -> dict[str, Any]:
    """Bootstrap confidence interval on a realized trade metric.

    The companion to :func:`permute_and_score`: where the sign-flip test gives a
    significance p-value under a no-edge null, this resamples the trade list *with
    replacement* to build the metric's sampling distribution, so the caller can see how
    *wide* the estimate is — the dimension a single p-value hides, and the one that
    matters most on the small trade counts JARVIS forward-tests on. ``p_null`` is the
    bootstrap probability the metric is no better than its no-edge value
    (:data:`_METRIC_BREAKEVEN`).

    Profit factor is +inf for a no-loss resample; the CI bounds use nearest-rank
    percentiles so a bound is always a real datum (finite or a clean inf), never NaN
    (linear interpolation between two infs yields NaN).

    With < 2 trades the interval is undefined and the function fails closed
    (``p_null = 1.0``).
    """
    pnls = _extract_pnls(trades)
    n = len(pnls)
    breakeven = _METRIC_BREAKEVEN.get(metric)
    if breakeven is None:
        raise ValueError(f"unknown metric: {metric!r}")

    if n < 2:
        score = _trade_metric(pnls, metric) if n else 0.0
        return {
            "test": "trade_bootstrap_ci",
            "metric": metric,
            "real_score": round(float(score), 6),
            "ci_lower": float(score),
            "ci_upper": float(score),
            "ci": ci,
            "p_null": 1.0,
            "n_iters": n_iters,
            "n_trades": n,
        }

    real = _trade_metric(pnls, metric)
    rng = np.random.default_rng(seed)
    boot = np.array(
        [_trade_metric(pnls[rng.integers(0, n, size=n)], metric) for _ in range(n_iters)],
        dtype=float,
    )
    lo_pct = 100.0 * (1.0 - ci) / 2.0
    hi_pct = 100.0 * (1.0 - (1.0 - ci) / 2.0)
    return {
        "test": "trade_bootstrap_ci",
        "metric": metric,
        "real_score": round(real, 6),
        "ci_lower": float(np.percentile(boot, lo_pct, method="nearest")),
        "ci_upper": float(np.percentile(boot, hi_pct, method="nearest")),
        "ci": ci,
        "p_null": round(float(np.mean(boot <= breakeven)), 4),
        "n_iters": n_iters,
        "n_trades": n,
    }

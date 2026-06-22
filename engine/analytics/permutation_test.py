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

"""Trade-sign permutation significance test — is the edge real, or luck?

Implements the Monte Carlo permutation test from Aronson, *Evidence-Based
Technical Analysis* (Wiley 2006), ch. 6, applied at the trade level.

The null hypothesis: the strategy has **no directional skill**. Under that
null, the sign of each realized trade P&L is a coin flip — a skill-less
strategy would have been equally likely to take the opposite side and earn
the opposite result. We therefore build the null distribution of the edge
statistic (mean trade P&L) by randomly flipping the sign of each trade's
P&L `n_iters` times, and compute a one-sided p-value:

    p = P(null statistic >= observed statistic)

A small p-value means the observed positive mean is hard to reproduce by
chance under the no-skill null, i.e. the directional edge is statistically
distinguishable from luck.

This complements — it does NOT duplicate — the two existing permutation
tools in the backtest package:

  * `deflated_sharpe.py` corrects a Sharpe for *multiple testing* across N
    grid-search trials (selection bias).
  * `monte_carlo.py` shuffles trade *order* to get a drawdown distribution
    (`mc_95th_dd`); order-shuffling leaves the mean/sum invariant, so it
    cannot test directional edge.

This module shuffles trade *signs*, which is the missing test for "is the
directional edge significant" called out in
`.claude/rules/ml-pitfalls-defense.md` (pitfall #9). Pure NumPy, no new
dependency.

Usage as a paper-promotion gate (shadow today; enforce when authorized):
    p < 0.05  ->  edge is statistically significant
"""
from __future__ import annotations

from typing import Sequence, Union

import numpy as np

TradeLike = Union[float, int, dict]


def _extract_pnls(trades: Sequence[TradeLike]) -> np.ndarray:
    """Coerce a sequence of floats or trade dicts into a 1-D P&L array.

    Dicts are probed for the first present of: pnl, profit, realized_pnl,
    pnl_dollars, net_pnl. Entries that resolve to None are dropped.
    """
    pnls: list[float] = []
    for t in trades:
        if isinstance(t, dict):
            val = None
            for key in ("pnl", "profit", "realized_pnl", "pnl_dollars", "net_pnl"):
                if t.get(key) is not None:
                    val = t[key]
                    break
            if val is None:
                continue
            pnls.append(float(val))
        elif t is not None:
            pnls.append(float(t))
    return np.asarray(pnls, dtype=float)


def permutation_test(
    trades: Sequence[TradeLike],
    n_iters: int = 1000,
    seed: int = 42,
) -> dict:
    """Sign-shuffle permutation test for directional edge significance.

    Args:
        trades: realized per-trade P&Ls (floats) or trade dicts with a
            'pnl'-like field. Order is irrelevant.
        n_iters: number of sign-flip permutations (Aronson recommends >= 500;
            default 1000 for a stable p-value).
        seed: RNG seed for reproducibility (matches monte_carlo.py default 42).

    Returns:
        {
            "observed": float,        # observed mean trade P&L
            "p_value": float,         # one-sided P(null mean >= observed)
            "passes_at_5pct": bool,   # p_value < 0.05
            "null_mean": float,       # mean of the null statistic distribution
            "null_std": float,        # std of the null statistic distribution
            "n_iters": int,
            "n_trades": int,
        }

    Degenerate inputs (0 or 1 trade) return p_value = 1.0 — no detectable
    edge — rather than a false positive.
    """
    pnls = _extract_pnls(trades)
    n = len(pnls)

    if n < 2:
        return {
            "observed": float(pnls[0]) if n == 1 else 0.0,
            "p_value": 1.0,
            "passes_at_5pct": False,
            "null_mean": 0.0,
            "null_std": 0.0,
            "n_iters": int(n_iters),
            "n_trades": int(n),
        }

    observed = float(pnls.mean())

    rng = np.random.default_rng(seed)
    # Each row: an independent set of +/-1 sign flips applied to the P&Ls.
    signs = rng.choice(np.array([-1.0, 1.0]), size=(n_iters, n))
    null_means = (signs * pnls).mean(axis=1)

    # One-sided test for a POSITIVE edge. The +1 / +1 correction (Davison &
    # Hinkley 1997) keeps the p-value strictly positive and unbiased: the
    # observed arrangement is itself one valid permutation.
    count_ge = int(np.sum(null_means >= observed))
    p_value = (count_ge + 1) / (n_iters + 1)

    return {
        "observed": round(observed, 6),
        "p_value": round(float(p_value), 6),
        "passes_at_5pct": bool(p_value < 0.05),
        "null_mean": round(float(null_means.mean()), 6),
        "null_std": round(float(null_means.std(ddof=1)), 6),
        "n_iters": int(n_iters),
        "n_trades": int(n),
    }


def permute_and_score(
    trades: Sequence[TradeLike],
    n_iters: int = 500,
    seed: int = 42,
) -> float:
    """Thin wrapper named in ml-pitfalls-defense.md — returns just the p-value.

    `permute_and_score(trades, n_iters=500) -> p_value`
    """
    return permutation_test(trades, n_iters=n_iters, seed=seed)["p_value"]

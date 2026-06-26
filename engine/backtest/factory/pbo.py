"""Probability of Backtest Overfitting (PBO) via CSCV.

Combinatorially-Symmetric Cross-Validation, per Bailey, Borwein, Lopez de Prado
& Zhu (2017), "The Probability of Backtest Overfitting". Given a matrix of
per-period performance for N candidate strategies, PBO estimates the probability
that the strategy selected as best in-sample underperforms the median strategy
out-of-sample -- i.e. that the selection is overfit noise rather than edge.

PBO ~ 0.5 means selection is no better than chance (pure overfitting). PBO near
0 means the in-sample winner reliably generalises. A common rejection bar is
PBO > 0.5; conservative discovery uses PBO < 0.25 for a survivor.

This complements the Deflated Sharpe ratio: DSR corrects a single strategy's
Sharpe for the number of trials; PBO measures whether the *selection procedure*
across the trial set generalises out-of-sample.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations

import numpy as np


def sharpe_perf(block: np.ndarray) -> np.ndarray:
    """Per-strategy Sharpe of a (rows x N) block. Zero-variance cols -> mean sign."""
    mean = block.mean(axis=0)
    std = block.std(axis=0, ddof=1) if block.shape[0] > 1 else np.zeros(block.shape[1])
    with np.errstate(divide="ignore", invalid="ignore"):
        sr = np.where(std > 0, mean / std, 0.0)
    return sr


@dataclass
class PBOResult:
    pbo: float
    n_splits: int
    n_strategies: int
    lambdas: list[float]
    median_logit: float


def probability_of_backtest_overfitting(
    perf_matrix: np.ndarray,
    n_partitions: int = 16,
    perf_fn=sharpe_perf,
) -> PBOResult:
    """Estimate PBO via CSCV.

    Args:
        perf_matrix: (T observations x N strategies) array of per-period returns
            (or any per-period performance contribution).
        n_partitions: S, number of disjoint row submatrices (must be even). The
            number of IS/OOS splits evaluated is C(S, S/2).
        perf_fn: maps a (rows x N) block to a length-N performance vector.

    Returns:
        PBOResult with pbo in [0, 1] and the per-split relative-rank logits.
    """
    M = np.asarray(perf_matrix, dtype=float)
    if M.ndim != 2:
        raise ValueError("perf_matrix must be 2-D (T x N)")
    T, N = M.shape
    if N < 2:
        raise ValueError("PBO needs at least 2 candidate strategies")
    if n_partitions % 2 != 0:
        raise ValueError("n_partitions (S) must be even")
    if n_partitions < 2 or n_partitions > T:
        raise ValueError(f"n_partitions must be in [2, T={T}]")

    # Disjoint, contiguous, equal-size row partitions (trim the remainder so all
    # partitions have identical length -- required for symmetric recombination).
    part_size = T // n_partitions
    usable = part_size * n_partitions
    parts = [np.arange(i * part_size, (i + 1) * part_size) for i in range(n_partitions)]
    _ = usable  # rows beyond `usable` are intentionally dropped

    half = n_partitions // 2
    lambdas: list[float] = []
    for is_combo in combinations(range(n_partitions), half):
        is_set = set(is_combo)
        is_rows = np.concatenate([parts[i] for i in is_combo])
        oos_rows = np.concatenate([parts[i] for i in range(n_partitions) if i not in is_set])

        r_is = perf_fn(M[is_rows])
        r_oos = perf_fn(M[oos_rows])

        n_star = int(np.argmax(r_is))  # best strategy in-sample

        # Relative rank of the IS-best strategy's OOS performance, in (0, 1).
        # rank = 1 (worst) .. N (best); average ranks for ties.
        order = np.argsort(r_oos, kind="mergesort")
        ranks = np.empty(N, dtype=float)
        ranks[order] = np.arange(1, N + 1, dtype=float)
        # average tied ranks so a degenerate all-equal OOS gives omega ~ 0.5
        for val in np.unique(r_oos):
            mask = r_oos == val
            if mask.sum() > 1:
                ranks[mask] = ranks[mask].mean()
        omega = ranks[n_star] / (N + 1)
        omega = min(max(omega, 1e-12), 1 - 1e-12)
        lambdas.append(math.log(omega / (1 - omega)))

    arr = np.asarray(lambdas)
    pbo = float(np.mean(arr <= 0.0))
    return PBOResult(
        pbo=pbo,
        n_splits=len(lambdas),
        n_strategies=N,
        lambdas=lambdas,
        median_logit=float(np.median(arr)),
    )

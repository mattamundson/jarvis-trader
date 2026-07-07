"""
MCPT Small-Sample Power Analysis
================================
Prerequisite for wiring the trade-sign permutation test (Aronson EBTA ch. 6,
``permute_and_score``) into the gate-v2 promotion path as a BLOCKING gate.

``ml-pitfalls-defense.md`` (pitfall #9) defers that wiring to a [safety-review]
PR precisely because "small-sample power on the 16-trade (MES) / 67-trade (MGC)
series must be observed before either blocks." A permutation test with too few
trades has almost no power: it will fail to reject the no-edge null even for a
genuine edge, so gating on it would reject good strategies (a false-negative
machine), not filter noise. This module MEASURES that power so the wiring
decision is evidence-based.

Method: for a given per-trade effect size (mean / std of trade PnL) and sample
size N, simulate many trade series with that true edge, run ``permute_and_score``
on each, and report the fraction that reject at alpha = power. Reuses the
production permutation test — does not reimplement the null.

Diagnostic only; changes no trade authorization.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from analytics.permutation_test import permute_and_score

logger = logging.getLogger(__name__)

# Live sample sizes from CLAUDE.md: MES ~16 OOS trades, MGC ~67.
LIVE_SAMPLE_SIZES = (16, 67, 120, 250)
# Per-trade effect sizes (mean/std). Real trend systems sit around 0.05-0.30.
EFFECT_SIZES = (0.05, 0.10, 0.20, 0.30, 0.50)


@dataclass(frozen=True)
class PowerResult:
    n_trades: int
    effect_size: float
    metric: str
    alpha: float
    power: float          # P(reject no-edge null | true edge present)
    n_sims: int


def estimate_power(
    n_trades: int,
    effect_size: float,
    *,
    metric: str = "mean",
    n_sims: int = 400,
    n_perm: int = 500,
    seed: int = 0,
) -> PowerResult:
    """Monte Carlo power of the trade-sign permutation test.

    Each sim draws ``n_trades`` PnLs from Normal(effect_size, 1.0) — so
    ``effect_size`` is the per-trade Sharpe — and counts a rejection when the
    permutation p-value < alpha.
    """
    rng = np.random.default_rng(seed)
    alpha = 0.05
    rejects = 0
    for i in range(n_sims):
        pnls = rng.normal(effect_size, 1.0, size=n_trades)
        res = permute_and_score(pnls.tolist(), n_iters=n_perm, metric=metric, seed=i)
        alpha = res["alpha"]
        if res["p_value"] < alpha:
            rejects += 1
    return PowerResult(
        n_trades=n_trades,
        effect_size=effect_size,
        metric=metric,
        alpha=alpha,
        power=rejects / n_sims,
        n_sims=n_sims,
    )


def power_grid(
    sample_sizes=LIVE_SAMPLE_SIZES,
    effect_sizes=EFFECT_SIZES,
    *,
    metric: str = "mean",
    n_sims: int = 400,
) -> list[PowerResult]:
    """Full (N x effect) power grid."""
    return [
        estimate_power(n, e, metric=metric, n_sims=n_sims)
        for n in sample_sizes
        for e in effect_sizes
    ]


def format_grid(results: list[PowerResult]) -> str:
    header = f"{'N trades':>9s} {'effect':>7s} {'power':>7s}"
    lines = [header, "-" * len(header)]
    for r in results:
        flag = "  <-- underpowered" if r.power < 0.80 else ""
        lines.append(f"{r.n_trades:9d} {r.effect_size:7.2f} {r.power:7.1%}{flag}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(format_grid(power_grid()))

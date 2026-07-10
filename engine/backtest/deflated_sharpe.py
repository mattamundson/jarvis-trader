"""Deflated Sharpe Ratio — multiple-testing correction for backtest Sharpe.

Implements the DSR from Bailey, Borwein, López de Prado, Zhu (2014, 2015):
"The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest
Overfitting, and Non-Normality."

The motivation: if we grid-search N parameter combinations and report the
best Sharpe, the naive p-value is useless — the "best" statistic is biased
upward by the maximum operator. DSR corrects by computing the expected
maximum Sharpe under the null (zero-skill random strategies) and asking how
many standard errors above that maximum our observed Sharpe sits.

Key formula:
    DSR = Φ((SR_observed - E[max SR | N, null]) / σ_SR)

where:
    E[max SR | N, null] ≈ ((1-γ)·Φ⁻¹(1 - 1/N) + γ·Φ⁻¹(1 - 1/(N·e))) · σ_null
    σ_null = 1 (assuming unit-variance sharpes under the null)
    σ_SR   = sqrt((1 - γ₃·SR + ((γ₄-1)/4)·SR²) / (T-1))
    γ      = Euler-Mascheroni constant ≈ 0.5772156649
    γ₃     = skew of returns
    γ₄     = kurtosis of returns (not excess kurtosis — full kurtosis)
    T      = sample size (number of trades or bars)
    N      = number of independent trials (grid combinations explored)
    Φ      = standard normal CDF

Interpretation:
    dsr < 0.05 → failed multiple-testing correction (SR indistinguishable
                 from "luck" given N trials)
    dsr < 0.10 → marginal
    dsr ≥ 0.10 → passes. Genuine edge survives the selection-bias penalty.

Rejected dependency: the `arch` library has a canonical implementation but
pulls in ~50MB of GARCH/volatility tooling we don't need. DSR is closed-form
and ~80 LOC, so we implement it directly.
"""

from __future__ import annotations

from math import e as EULER_E
from typing import Sequence

import numpy as np
from scipy import stats

EULER_MASCHERONI = 0.5772156649015329


def _expected_max_sharpe(n_trials: int) -> float:
    """Expected maximum Sharpe ratio over N zero-skill strategies.

    Uses the Gumbel-distribution approximation from Bailey & López de Prado.
    Assumes each trial's Sharpe is N(0, 1) under the null.
    """
    if n_trials < 2:
        return 0.0
    # Two quantile terms with Euler-Mascheroni weighting
    q1 = stats.norm.ppf(1.0 - 1.0 / n_trials)
    q2 = stats.norm.ppf(1.0 - 1.0 / (n_trials * EULER_E))
    return float((1.0 - EULER_MASCHERONI) * q1 + EULER_MASCHERONI * q2)


def _sharpe_standard_error(sharpe: float, skew: float, kurt: float, n_obs: int) -> float:
    """Standard error of Sharpe under non-normal returns.

    Mertens (2002) / Lo (2002) / Bailey-López de Prado (2014) formula:
        var(SR) = (1 - γ₃·SR + ((γ₄-1)/4)·SR²) / (T-1)

    `kurt` is raw kurtosis (Gaussian = 3), not excess kurtosis. If the caller
    passes scipy-default excess kurtosis, they must add 3 first.
    """
    if n_obs < 2:
        return float("inf")
    variance = (1.0 - skew * sharpe + ((kurt - 1.0) / 4.0) * sharpe**2) / (n_obs - 1)
    # Guard against numerical negatives on degenerate samples
    if variance <= 0:
        return float("inf")
    return float(np.sqrt(variance))


def deflated_sharpe_ratio(
    sharpe: float,
    n_trials: int,
    n_obs: int,
    skew: float = 0.0,
    kurt: float = 3.0,
) -> dict:
    """Compute the Deflated Sharpe Ratio p-value.

    Args:
        sharpe: observed Sharpe ratio of the winning strategy
        n_trials: N independent trials (e.g., grid-search combinations tested)
        n_obs: T sample size (trades or bars used to compute the Sharpe)
        skew: skew of returns (default 0 = Gaussian)
        kurt: raw kurtosis of returns (default 3 = Gaussian). Pass 3 + excess_kurtosis
              if you computed scipy's default (which returns excess kurtosis).

    Returns:
        {
            "raw_sharpe": float,
            "expected_max_sharpe": float,      # E[max SR | N, null]
            "sharpe_std_error": float,         # σ_SR
            "dsr": float,                      # deflated Sharpe p-value (0..1)
            "passes_at_10pct": bool,           # dsr ≥ 0.10
            "n_trials": int,
            "n_obs": int,
        }

    The p-value is Φ((SR - E[maxSR]) / σ_SR). Values near 1 indicate a strong
    pass (SR is far above the selection-bias threshold). Values near 0
    indicate failure — the observed SR is indistinguishable from noise across
    N trials.
    """
    if n_obs < 2 or n_trials < 1:
        return {
            "raw_sharpe": float(sharpe),
            "expected_max_sharpe": 0.0,
            "sharpe_std_error": float("inf"),
            "dsr": 0.0,
            "passes_at_10pct": False,
            "dsr_degenerate": False,
            "n_trials": int(n_trials),
            "n_obs": int(n_obs),
        }

    expected_max = _expected_max_sharpe(n_trials)
    sigma = _sharpe_standard_error(sharpe, skew, kurt, n_obs)
    degenerate = not np.isfinite(sigma) or sigma == 0
    if degenerate:
        # The non-normality SE estimate broke down (variance <= 0), which happens
        # for high-Sharpe positively-skewed sparse series. A degenerate SE is the
        # ABSENCE of a usable selection-bias correction, not evidence of a real
        # edge -- so fail-conservative (0.0), never the old fake 1.0 that
        # auto-passed both gate floors. The `dsr_degenerate` flag lets verdict
        # writers record WHY the DSR is zero.
        dsr = 0.0
    else:
        z = (sharpe - expected_max) / sigma
        dsr = float(stats.norm.cdf(z))

    return {
        "raw_sharpe": round(float(sharpe), 6),
        "expected_max_sharpe": round(expected_max, 6),
        "sharpe_std_error": round(float(sigma) if np.isfinite(sigma) else -1.0, 6),
        "dsr": round(dsr, 6),
        "passes_at_10pct": bool(dsr >= 0.10),
        "dsr_degenerate": bool(degenerate),
        "n_trials": int(n_trials),
        "n_obs": int(n_obs),
    }


def deflated_sharpe_from_returns(
    returns: Sequence[float],
    n_trials: int,
    ann_factor: float = 252.0,
) -> dict:
    """Convenience wrapper: compute DSR directly from a returns series.

    Args:
        returns: periodic return series (per-bar or per-trade returns, not PnLs)
        n_trials: N independent grid-search trials
        ann_factor: annualization factor, used ONLY to populate the
            informational `ann_sharpe` field below -- it is NOT fed into the
            DSR calculation. `_sharpe_standard_error`'s (T-1) scaling and
            `_expected_max_sharpe`'s null both assume the observed Sharpe is
            computed over the same T=n_obs observations at their native
            frequency; annualizing it first breaks that correspondence and
            can flip a fail into a false pass. (Incident 2026-07-10: MES's
            and MGC's live paper authorizations both recorded DSR=1.0 under
            the old annualized-input bug; the corrected raw-Sharpe DSR is
            0.11 and 0.00 respectively -- both below their required floor.)

    Returns:
        deflated_sharpe_ratio() output plus raw sample stats and an
        `ann_sharpe` field (reporting-only, not used for gating).
    """
    r = np.asarray(returns, dtype=float)
    T = len(r)
    if T < 2:
        return {
            "raw_sharpe": 0.0,
            "expected_max_sharpe": 0.0,
            "sharpe_std_error": float("inf"),
            "dsr": 0.0,
            "passes_at_10pct": False,
            "dsr_degenerate": False,
            "n_trials": int(n_trials),
            "n_obs": int(T),
            "skew": 0.0,
            "kurt": 3.0,
            "ann_sharpe": 0.0,
        }

    mean = float(r.mean())
    std = float(r.std(ddof=1))
    if std == 0:
        return {
            "raw_sharpe": 0.0,
            "expected_max_sharpe": _expected_max_sharpe(n_trials),
            "sharpe_std_error": float("inf"),
            "dsr": 0.0,
            "passes_at_10pct": False,
            "dsr_degenerate": False,
            "n_trials": int(n_trials),
            "n_obs": int(T),
            "skew": 0.0,
            "kurt": 3.0,
            "ann_sharpe": 0.0,
        }

    raw_sharpe = mean / std
    ann_sharpe = raw_sharpe * np.sqrt(ann_factor)
    skew_val = float(stats.skew(r, bias=False))
    # scipy returns excess kurtosis by default; convert to raw kurtosis.
    kurt_excess = float(stats.kurtosis(r, bias=False))
    kurt_raw = kurt_excess + 3.0

    out = deflated_sharpe_ratio(
        sharpe=raw_sharpe,
        n_trials=n_trials,
        n_obs=T,
        skew=skew_val,
        kurt=kurt_raw,
    )
    out["skew"] = round(skew_val, 6)
    out["kurt"] = round(kurt_raw, 6)
    out["ann_sharpe"] = round(ann_sharpe, 6)
    return out

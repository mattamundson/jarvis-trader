"""
JARVIS TRADER — Pair-Spread Cointegration Screen (Strategy Novel #5)
====================================================================
Rolling Engle-Granger cointegration screen for futures pairs (MCL/MES/MNQ).
When two price series are cointegrated, their linear combination is
mean-reverting and can be traded as a market-neutral pair.

Source: docs/digest/strategy-synthesis.md Novel #5 (@moondevonyt stat-arb post).

Implementation notes
--------------------
This module does NOT require statsmodels (not in engine requirements). The
Engle-Granger 2-step is implemented with scipy + numpy:

  Step 1: OLS regression  y_t = α + β·x_t + ε_t   →   hedge ratio β
  Step 2: Mean-reversion test on spread ε_t       →   AR(1) half-life

A cointegrated pair has finite, short half-life (we treat <= half_life_max
bars as tradeable). Non-cointegrated pairs have half-life → ∞ (random walk
spread) and are filtered out before signal generation.

KNOWN LIMITATION (false-positive noise floor): pure Engle-Granger without
an ADF significance gate has a measurable false-positive rate on
finite-sample independent random walks — a 300-bar pair of independent
random walks can occasionally show half-life ≈ 15 bars by chance. For
production use, prefer half_life_max <= 5-10 bars and pair with regime
gating (e.g. only screen when VIX > threshold so spreads are likely
genuinely co-driven). This is documented in
test_screen_pair_random_walk_not_cointegrated_at_strict_threshold.

Signal contract
---------------
For each pair (symbol_y, symbol_x):
  * z > +z_entry    → SHORT spread (short y, long β·x)
  * z < -z_entry    → LONG  spread (long  y, short β·x)
  * |z| <= z_exit   → FLAT (close any open spread position)
  * not cointegrated → FLAT (do not initiate)

Live-wiring (DEFERRED)
----------------------
Wiring this into `engine/agents/pipeline.py` as a sibling signal to
Hidden Pivots, plus reasoning about short-leg sizing in
`engine/agents/safety_layer.py`, touches sizing-and-kill-switch logic and
warrants explicit Tier 3 review per `.claude/rules/commits.md`. Today
this module is a pure research/screening tool.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

__all__ = [
    "PairSpreadResult",
    "compute_hedge_ratio",
    "compute_spread",
    "compute_half_life",
    "compute_spread_zscore",
    "screen_pair",
    "screen_all_pairs",
]


@dataclass
class PairSpreadResult:
    """One pair-screen output."""

    symbol_y: str
    symbol_x: str
    hedge_ratio: float                  # β from y = α + β·x + ε
    intercept: float                    # α from same regression
    current_spread: float               # most-recent ε_t = y - (α + β·x)
    current_z: float                    # z-score of current_spread vs lookback
    half_life_bars: float               # AR(1) half-life (∞ if non-mean-reverting)
    is_cointegrated: bool               # True if half_life finite and below threshold
    signal: str                         # "LONG_PAIR" | "SHORT_PAIR" | "FLAT"
    n_obs: int                          # number of observations used
    notes: str = ""


# ── Pure math helpers ───────────────────────────────────────────────────────

def compute_hedge_ratio(y_prices: np.ndarray, x_prices: np.ndarray) -> tuple[float, float]:
    """
    OLS regression y = α + β·x. Returns (intercept α, slope β).

    Implements (X'X)^-1 X'y with X = [1, x] — no scipy/statsmodels dependency.
    """
    if len(y_prices) != len(x_prices):
        raise ValueError(f"Length mismatch: y={len(y_prices)}, x={len(x_prices)}")
    if len(y_prices) < 2:
        raise ValueError("Need at least 2 observations for regression")

    y = np.asarray(y_prices, dtype=float)
    x = np.asarray(x_prices, dtype=float)

    x_mean = x.mean()
    y_mean = y.mean()

    cov_xy = np.sum((x - x_mean) * (y - y_mean))
    var_x = np.sum((x - x_mean) ** 2)

    if var_x == 0:
        # x is constant — slope undefined; treat as no-cointegration
        return (y_mean, 0.0)

    beta = cov_xy / var_x
    alpha = y_mean - beta * x_mean
    return (alpha, beta)


def compute_spread(
    y_prices: np.ndarray,
    x_prices: np.ndarray,
    hedge_ratio: float,
    intercept: float,
) -> np.ndarray:
    """Spread series ε_t = y_t - (α + β·x_t)."""
    y = np.asarray(y_prices, dtype=float)
    x = np.asarray(x_prices, dtype=float)
    return y - (intercept + hedge_ratio * x)


def compute_half_life(spread: np.ndarray) -> float:
    """
    AR(1) regression: Δs_t = α + λ·s_{t-1} + ν_t.

    Half-life of mean reversion = -ln(2) / ln(1 + λ) when λ ∈ (-1, 0).
    Returns float('inf') when:
      * series too short
      * λ >= 0 (random walk or explosive — not mean-reverting)
      * λ <= -2 (anti-persistent oscillation, not stable)
    """
    s = np.asarray(spread, dtype=float)
    if len(s) < 10:
        return float("inf")

    s_lag = s[:-1]
    delta_s = np.diff(s)

    # Δs = α + λ·s_lag + ν → use compute_hedge_ratio with target=delta_s, regressor=s_lag
    _alpha, lam = compute_hedge_ratio(delta_s, s_lag)

    # Mean-reverting requires λ in (-2, 0). Anything else → no half-life.
    if lam >= 0 or lam <= -2:
        return float("inf")

    half_life = -math.log(2.0) / math.log(1.0 + lam)
    if half_life <= 0 or not math.isfinite(half_life):
        return float("inf")
    return half_life


def compute_spread_zscore(
    spread: np.ndarray,
    lookback: Optional[int] = None,
) -> float:
    """
    Z-score of the most-recent spread value over the lookback window.

    If lookback is None, uses the entire spread series. Returns 0.0 when
    the lookback std is 0 (degenerate).
    """
    s = np.asarray(spread, dtype=float)
    if len(s) < 2:
        return 0.0

    window = s if lookback is None else s[-lookback:]
    if len(window) < 2:
        return 0.0

    mu = window.mean()
    sigma = window.std(ddof=1)
    if sigma == 0:
        return 0.0
    return float((s[-1] - mu) / sigma)


# ── Pair screen ──────────────────────────────────────────────────────────────

def screen_pair(
    symbol_y: str,
    prices_y: pd.Series | np.ndarray,
    symbol_x: str,
    prices_x: pd.Series | np.ndarray,
    *,
    lookback: int = 126,
    z_entry: float = 2.0,
    z_exit: float = 0.5,
    half_life_max: float = 20.0,
) -> PairSpreadResult:
    """
    Screen one pair for cointegration and emit a current trading signal.

    lookback: trailing bars used for hedge-ratio fit + z-score normalisation
              (126 ≈ 6 months of daily bars, ~5 days of 1m bars)
    z_entry:  |z| above this opens a new pair position
    z_exit:   |z| at-or-below this closes an open position (held externally)
    half_life_max: pairs with half-life > this many bars are treated as
              non-tradeable random-walk spreads
    """
    y_arr = np.asarray(prices_y, dtype=float)
    x_arr = np.asarray(prices_x, dtype=float)

    if len(y_arr) != len(x_arr):
        raise ValueError(
            f"Length mismatch: {symbol_y}={len(y_arr)}, {symbol_x}={len(x_arr)}"
        )

    # Trim to lookback (keep the most-recent N bars)
    if lookback < len(y_arr):
        y_arr = y_arr[-lookback:]
        x_arr = x_arr[-lookback:]

    n = len(y_arr)
    if n < 30:
        return PairSpreadResult(
            symbol_y=symbol_y,
            symbol_x=symbol_x,
            hedge_ratio=0.0,
            intercept=0.0,
            current_spread=0.0,
            current_z=0.0,
            half_life_bars=float("inf"),
            is_cointegrated=False,
            signal="FLAT",
            n_obs=n,
            notes=f"insufficient observations ({n} < 30)",
        )

    alpha, beta = compute_hedge_ratio(y_arr, x_arr)
    spread = compute_spread(y_arr, x_arr, beta, alpha)
    half_life = compute_half_life(spread)
    z = compute_spread_zscore(spread)

    is_cointegrated = math.isfinite(half_life) and half_life <= half_life_max

    # Signal generation — only fire on cointegrated pairs
    if not is_cointegrated:
        signal = "FLAT"
    elif z > z_entry:
        signal = "SHORT_PAIR"     # spread is rich → short y, long β·x
    elif z < -z_entry:
        signal = "LONG_PAIR"      # spread is cheap → long y, short β·x
    elif abs(z) <= z_exit:
        signal = "FLAT"           # already mean-reverted
    else:
        signal = "FLAT"           # in-between zone — do not initiate

    return PairSpreadResult(
        symbol_y=symbol_y,
        symbol_x=symbol_x,
        hedge_ratio=float(beta),
        intercept=float(alpha),
        current_spread=float(spread[-1]),
        current_z=float(z),
        half_life_bars=float(half_life),
        is_cointegrated=is_cointegrated,
        signal=signal,
        n_obs=n,
    )


def screen_all_pairs(
    price_series: dict[str, pd.Series | np.ndarray],
    *,
    lookback: int = 126,
    z_entry: float = 2.0,
    z_exit: float = 0.5,
    half_life_max: float = 20.0,
) -> list[PairSpreadResult]:
    """
    Screen every unique unordered pair from the symbols in `price_series`.

    Returns one PairSpreadResult per pair (so {MCL, MES, MNQ} → 3 results).
    The pair (y, x) is normalised to alphabetical order for stable output.
    """
    symbols = sorted(price_series.keys())
    results: list[PairSpreadResult] = []
    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            sy, sx = symbols[i], symbols[j]
            results.append(
                screen_pair(
                    sy, price_series[sy],
                    sx, price_series[sx],
                    lookback=lookback,
                    z_entry=z_entry,
                    z_exit=z_exit,
                    half_life_max=half_life_max,
                )
            )
    return results

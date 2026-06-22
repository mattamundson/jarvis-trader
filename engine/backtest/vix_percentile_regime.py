"""Percentile-based VIX regime classifier for JARVIS TRADER.

Additive second regime lens. This does NOT replace ``backtest/regime_classifier.py``
(``RegimeClassifierV2``), which uses a fixed ``VIX > 35`` CRISIS threshold and feeds
gate v2 routing. This module classifies by *rolling VIX percentile* plus a price
momentum overlay, an approach that adapts to volatility-regime drift in a way a fixed
absolute print cannot.

Concept (ideas only, no code) from OnePunchMonk/AgentQuant's percentile regime detector:
    Crisis  : VIX percentile > 85th
    HighVol : VIX percentile > 65th
    MidVol  : VIX percentile > 35th
    LowVol  : VIX percentile <= 35th
plus a 3-month price-momentum overlay (Bull / Neutral / Bear).

Point-in-time discipline (``.claude/rules/testing.md``): the percentile at bar ``t`` is
computed only from VIX observations at bars ``<= t`` (a trailing window). No full-series
fit, no centered window, no ``shift(-n)``. The momentum overlay compares the current
close to a *past* close, never a future one. A decision at bar ``t`` is therefore
invariant to any mutation of bars ``> t`` — asserted in
``tests/test_vix_percentile_regime.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd

# Percentile tier cut points (upper-exclusive ordering applied top-down).
_CRISIS_PCTILE = 85.0
_HIGHVOL_PCTILE = 65.0
_MIDVOL_PCTILE = 35.0

# Defaults: 252 trading days ~= 1y of daily bars for the percentile window;
# 63 trading days ~= 3 months for the momentum lookback.
DEFAULT_PCTILE_LOOKBACK = 252
DEFAULT_MOMENTUM_WINDOW = 63

# Momentum overlay dead-band: |return| below this is treated as Neutral.
_MOMENTUM_DEADBAND = 0.0


class VixTier(str, Enum):
    """Volatility tier from rolling VIX percentile."""

    CRISIS = "Crisis"
    HIGH_VOL = "HighVol"
    MID_VOL = "MidVol"
    LOW_VOL = "LowVol"


class Momentum(str, Enum):
    """Price momentum overlay."""

    BULL = "Bull"
    NEUTRAL = "Neutral"
    BEAR = "Bear"


@dataclass(frozen=True)
class VixRegimeContext:
    """Latest-bar regime snapshot. Mirrors AgentQuant's RegimeContext shape."""

    vix: float
    vix_percentile: float        # 0..100, trailing-window rank of the latest VIX
    tier: VixTier
    momentum: Momentum
    confidence: float            # 0..1, distance of percentile from nearest tier edge


def _trailing_percentile_rank(window: np.ndarray) -> float:
    """Percentile rank (0..100) of the last element within ``window``.

    ``window`` holds VIX observations for bars ``<= t`` only (rolling supplies a
    trailing slice), so this is point-in-time safe. Rank counts the fraction of
    window observations ``<= the latest`` value.
    """
    if window.size == 0:
        return np.nan
    latest = window[-1]
    if np.isnan(latest):
        return np.nan
    valid = window[~np.isnan(window)]
    if valid.size == 0:
        return np.nan
    return 100.0 * np.count_nonzero(valid <= latest) / valid.size


def vix_percentile(vix: pd.Series, lookback: int = DEFAULT_PCTILE_LOOKBACK) -> pd.Series:
    """Rolling trailing percentile rank (0..100) of VIX.

    Uses ``min_periods=1`` so the series warms up gradually; callers that require a
    full window before acting should gate on bar index >= ``lookback``.
    """
    return vix.rolling(window=lookback, min_periods=1).apply(
        _trailing_percentile_rank, raw=True
    )


def _tier_for_percentile(pct: float) -> VixTier:
    if np.isnan(pct):
        return VixTier.LOW_VOL
    if pct > _CRISIS_PCTILE:
        return VixTier.CRISIS
    if pct > _HIGHVOL_PCTILE:
        return VixTier.HIGH_VOL
    if pct > _MIDVOL_PCTILE:
        return VixTier.MID_VOL
    return VixTier.LOW_VOL


def classify_vix_regime(
    vix: pd.Series, lookback: int = DEFAULT_PCTILE_LOOKBACK
) -> pd.Series:
    """Map each bar to a :class:`VixTier` from its trailing VIX percentile."""
    pct = vix_percentile(vix, lookback=lookback)
    return pct.map(_tier_for_percentile)


def momentum_overlay(
    price: pd.Series,
    window: int = DEFAULT_MOMENTUM_WINDOW,
    deadband: float = _MOMENTUM_DEADBAND,
) -> pd.Series:
    """Bull / Neutral / Bear from trailing ``window``-bar price return.

    Compares close[t] to close[t-window] (a past bar) — point-in-time safe. Bars
    before the window is available are Neutral.
    """
    ret = price / price.shift(window) - 1.0

    def _label(r: float) -> Momentum:
        if np.isnan(r):
            return Momentum.NEUTRAL
        if r > deadband:
            return Momentum.BULL
        if r < -deadband:
            return Momentum.BEAR
        return Momentum.NEUTRAL

    return ret.map(_label)


def _percentile_confidence(pct: float) -> float:
    """Distance (0..1) of ``pct`` from the nearest tier boundary.

    A percentile sitting on an edge (e.g. 85.0) is low-confidence; one deep inside a
    tier is high-confidence. Normalized by the widest tier half-width (~17.5 points).
    """
    if np.isnan(pct):
        return 0.0
    edges = (0.0, _MIDVOL_PCTILE, _HIGHVOL_PCTILE, _CRISIS_PCTILE, 100.0)
    nearest = min(abs(pct - e) for e in edges)
    return float(min(1.0, nearest / 17.5))


def classify_latest(
    vix: pd.Series,
    price: pd.Series,
    lookback: int = DEFAULT_PCTILE_LOOKBACK,
    momentum_window: int = DEFAULT_MOMENTUM_WINDOW,
) -> VixRegimeContext:
    """Return a :class:`VixRegimeContext` for the most recent bar.

    ``vix`` and ``price`` must be aligned (same index). Only the latest values are
    reported, but the full trailing windows are used to compute them.
    """
    if vix.empty:
        raise ValueError("vix series is empty")
    pct_series = vix_percentile(vix, lookback=lookback)
    mom_series = momentum_overlay(price, window=momentum_window)
    pct = float(pct_series.iloc[-1])
    return VixRegimeContext(
        vix=float(vix.iloc[-1]),
        vix_percentile=pct,
        tier=_tier_for_percentile(pct),
        momentum=mom_series.iloc[-1],
        confidence=_percentile_confidence(pct),
    )

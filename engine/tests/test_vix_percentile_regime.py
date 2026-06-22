"""Tests for backtest.vix_percentile_regime — percentile VIX regime classifier.

Synthetic series only; no network, no engine API. The no-look-ahead test is the
load-bearing one: a decision at bar t must be invariant to mutation of bars > t.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_engine = Path(__file__).parent.parent
if str(_engine) not in sys.path:
    sys.path.insert(0, str(_engine))

from backtest.vix_percentile_regime import (
    Momentum,
    VixTier,
    classify_latest,
    classify_vix_regime,
    momentum_overlay,
    vix_percentile,
)


def test_tier_thresholds_with_known_inputs():
    # A long flat run then a single spike at the end -> highest percentile -> Crisis.
    vix = pd.Series([15.0] * 100 + [80.0])
    tiers = classify_vix_regime(vix, lookback=252)
    assert tiers.iloc[-1] == VixTier.CRISIS
    # The flat low values sit at the top of their own trailing window (all equal ->
    # rank 100) early on, but a constant series ranks at 100 each bar; verify the
    # explicit mapping via a controlled distribution instead.


def test_percentile_rank_is_trailing():
    # Strictly increasing -> each bar is the max so far -> percentile 100 every bar.
    vix = pd.Series(np.arange(1, 51, dtype=float))
    pct = vix_percentile(vix, lookback=252)
    assert np.allclose(pct.to_numpy(), 100.0)

    # Strictly decreasing -> each new bar is the min so far -> percentile = 100/n.
    vix_dec = pd.Series(np.arange(50, 0, -1, dtype=float))
    pct_dec = vix_percentile(vix_dec, lookback=252)
    assert pct_dec.iloc[0] == 100.0
    assert pct_dec.iloc[-1] == 100.0 * (1.0 / 50.0)


def test_tier_mapping_across_distribution():
    # Uniform 1..100; the last bar's value sets its percentile within the window.
    base = list(np.arange(1, 101, dtype=float))
    # Append a value at ~the 90th percentile of the full distribution -> Crisis.
    crisis = classify_vix_regime(pd.Series(base + [91.0]), lookback=1000).iloc[-1]
    assert crisis == VixTier.CRISIS
    # ~70th percentile -> HighVol.
    highvol = classify_vix_regime(pd.Series(base + [71.0]), lookback=1000).iloc[-1]
    assert highvol == VixTier.HIGH_VOL
    # ~40th percentile -> MidVol.
    midvol = classify_vix_regime(pd.Series(base + [41.0]), lookback=1000).iloc[-1]
    assert midvol == VixTier.MID_VOL
    # ~10th percentile -> LowVol.
    lowvol = classify_vix_regime(pd.Series(base + [11.0]), lookback=1000).iloc[-1]
    assert lowvol == VixTier.LOW_VOL


def test_momentum_overlay_directions():
    up = pd.Series(np.linspace(100, 200, 80))
    assert momentum_overlay(up, window=63).iloc[-1] == Momentum.BULL
    down = pd.Series(np.linspace(200, 100, 80))
    assert momentum_overlay(down, window=63).iloc[-1] == Momentum.BEAR
    flat = pd.Series([100.0] * 80)
    assert momentum_overlay(flat, window=63).iloc[-1] == Momentum.NEUTRAL
    # Pre-window bars have no past reference -> Neutral.
    assert momentum_overlay(up, window=63).iloc[0] == Momentum.NEUTRAL


def test_no_look_ahead_decision_invariant_to_future_bars():
    rng = np.random.default_rng(42)
    vix = pd.Series(15.0 + rng.normal(0, 3, 300).cumsum() * 0.1 + 10.0)
    price = pd.Series(100.0 + rng.normal(0, 1, 300).cumsum())

    t = 200  # the decision bar
    tier_full = classify_vix_regime(vix, lookback=252)
    mom_full = momentum_overlay(price, window=63)

    # Mutate every bar AFTER t arbitrarily.
    vix_mut = vix.copy()
    price_mut = price.copy()
    vix_mut.iloc[t + 1 :] = 999.0
    price_mut.iloc[t + 1 :] = -999.0

    tier_mut = classify_vix_regime(vix_mut, lookback=252)
    mom_mut = momentum_overlay(price_mut, window=63)

    # The decision at bar t is unchanged by anything that happens after t.
    assert tier_full.iloc[t] == tier_mut.iloc[t]
    assert mom_full.iloc[t] == mom_mut.iloc[t]


def test_classify_latest_shape_and_confidence_bounds():
    rng = np.random.default_rng(7)
    vix = pd.Series(np.abs(rng.normal(20, 5, 260)))
    price = pd.Series(100.0 + rng.normal(0, 1, 260).cumsum())
    ctx = classify_latest(vix, price)
    assert isinstance(ctx.tier, VixTier)
    assert isinstance(ctx.momentum, Momentum)
    assert 0.0 <= ctx.vix_percentile <= 100.0
    assert 0.0 <= ctx.confidence <= 1.0
    assert ctx.vix == vix.iloc[-1]

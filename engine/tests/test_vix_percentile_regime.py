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
    gate_signals_by_vix_regime,
    momentum_overlay,
    regime_snapshot,
    vix_percentile,
)


def test_tier_thresholds_with_known_inputs():
    # A long flat run then a single spike at the end -> top of the trailing window
    # -> Crisis tier. The flat bars themselves read ~50th percentile (MidVol).
    vix = pd.Series([15.0] * 100 + [80.0])
    tiers = classify_vix_regime(vix, lookback=252)
    assert tiers.iloc[-1] == VixTier.CRISIS
    assert tiers.iloc[50] == VixTier.MID_VOL


def test_percentile_rank_is_trailing():
    # Mid-rank convention: a single observation ranks at the 50th percentile.
    # Strictly increasing -> latest is the max so far -> rank = 100*(n-0.5)/n.
    vix = pd.Series(np.arange(1, 51, dtype=float))
    pct = vix_percentile(vix, lookback=252)
    assert pct.iloc[0] == 50.0
    assert pct.iloc[-1] == 100.0 * (49.5 / 50.0)  # 99.0

    # Strictly decreasing -> latest is the min so far -> rank = 100*0.5/n.
    vix_dec = pd.Series(np.arange(50, 0, -1, dtype=float))
    pct_dec = vix_percentile(vix_dec, lookback=252)
    assert pct_dec.iloc[0] == 50.0
    assert pct_dec.iloc[-1] == 100.0 * (0.5 / 50.0)  # 1.0

    # A flat window must read ~50th percentile (MidVol), never Crisis.
    flat = pd.Series([20.0] * 60)
    assert vix_percentile(flat, lookback=252).iloc[-1] == 50.0


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


def test_gate_blocks_entries_in_crisis_tier():
    # Build a window where the final bar is a clear Crisis-tier spike.
    n = 120
    vix = pd.Series([15.0] * n)
    vix.iloc[-1] = 99.0  # top of its trailing window -> Crisis
    price = pd.Series(np.linspace(100, 110, n))
    signals = pd.Series([0] * n)
    signals.iloc[-1] = 1  # a long entry on the crisis bar
    gated = gate_signals_by_vix_regime(signals, vix, price)
    assert gated.iloc[-1] == 0  # suppressed
    # A long entry on a calm bar survives.
    signals2 = pd.Series([0] * n)
    signals2.iloc[-2] = 1
    gated2 = gate_signals_by_vix_regime(signals2, vix, price)
    assert gated2.iloc[-2] == 1


def test_gate_enforces_required_momentum():
    n = 120
    vix = pd.Series([15.0] * n)  # all LowVol, never blocked by tier
    price = pd.Series(np.linspace(200, 100, n))  # downtrend -> Bear momentum
    signals = pd.Series([0] * n)
    signals.iloc[-1] = 1  # long entry into a bear tape
    gated = gate_signals_by_vix_regime(signals, vix, price, long_requires_momentum=Momentum.BULL)
    assert gated.iloc[-1] == 0  # long requires Bull, tape is Bear -> suppressed


def test_gate_does_not_mutate_input_and_validates_length():
    n = 80
    vix = pd.Series([15.0] * n)
    price = pd.Series(np.linspace(100, 120, n))
    signals = pd.Series([1] * n)
    _ = gate_signals_by_vix_regime(signals, vix, price)
    assert (signals == 1).all()  # original untouched
    import pytest

    with pytest.raises(ValueError):
        gate_signals_by_vix_regime(signals, vix.iloc[:-1], price)


def test_regime_snapshot_is_json_serializable_dict():
    import json

    rng = np.random.default_rng(11)
    vix = pd.Series(np.abs(rng.normal(20, 5, 300)))
    price = pd.Series(100.0 + rng.normal(0, 1, 300).cumsum())
    snap = regime_snapshot(vix, price, lookback=252, momentum_window=63)
    # Round-trips through JSON (no numpy/enum leakage).
    json.dumps(snap)
    assert set(snap) >= {"vix", "vix_percentile", "tier", "momentum", "confidence"}
    assert snap["tier"] in {"Crisis", "HighVol", "MidVol", "LowVol"}
    assert snap["momentum"] in {"Bull", "Neutral", "Bear"}
    assert isinstance(snap["vix"], float)
    assert 0.0 <= snap["vix_percentile"] <= 100.0

"""Regression: generate_composite_signals must honor stop/target ATR mults.

Pre-2026-04-20 the constants COMP_STOP_ATR / COMP_T1_ATR / COMP_T2_ATR /
COMP_T3_ATR were hardcoded inside the function body, silently ignoring
four caller-supplied parameters. That defeated 4 of 6 Bayesian search
axes — 30+ of 40 search samples in the 2026-04-20 MES audit returned
identical PF=0.13 because the "search" was along dead dimensions.

This test locks the wiring so any future regression surfaces immediately.
"""

import numpy as np
import pandas as pd
import pytest

from backtest.composite_signals import generate_composite_signals


def _make_bullish_bars(n: int = 200, seed: int = 7) -> pd.DataFrame:
    """Build a synthetic DataFrame with a slow uptrend so STC fires long."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-02 09:30", periods=n, freq="1h", tz="UTC")
    close = np.cumsum(rng.normal(0.1, 1.0, n)) + 100
    high = close + np.abs(rng.normal(0.3, 0.2, n))
    low = close - np.abs(rng.normal(0.3, 0.2, n))
    open_ = close + rng.normal(0, 0.1, n)
    vol = rng.integers(1000, 5000, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


def _has_entry(df: pd.DataFrame) -> bool:
    return (df["entry_signal"] == "ENTRY_NOW").any()


def test_stop_atr_mult_param_changes_stop_level():
    """Different stop_atr_mult values must produce different stop_level columns."""
    df = _make_bullish_bars()

    tight = generate_composite_signals(df.copy(), symbol="MES", stop_atr_mult=0.5)
    loose = generate_composite_signals(df.copy(), symbol="MES", stop_atr_mult=2.0)

    if not (_has_entry(tight) or _has_entry(loose)):
        pytest.skip("Synthetic bars produced no entries; widen seed or skip")

    # Stop-level for the same entry must differ between tight/loose
    tight_entries = tight[tight["entry_signal"] == "ENTRY_NOW"]
    loose_entries = loose[loose["entry_signal"] == "ENTRY_NOW"]

    common = tight_entries.index.intersection(loose_entries.index)
    if len(common) == 0:
        pytest.skip("No overlapping entries between tight/loose (entry gate can shift with R:R filter)")

    for idx in common:
        t_stop = tight_entries.at[idx, "stop_level"]
        l_stop = loose_entries.at[idx, "stop_level"]
        assert t_stop != l_stop, (
            f"stop_level unchanged between stop_atr_mult=0.5 and stop_atr_mult=2.0 "
            f"at {idx}: tight={t_stop}, loose={l_stop}. Hardcoded stops likely regressed."
        )


def test_t1_atr_mult_param_changes_target_1():
    """Different t1_atr_mult values must produce different target_1 columns."""
    df = _make_bullish_bars()

    narrow = generate_composite_signals(df.copy(), symbol="MES", t1_atr_mult=1.5)
    wide = generate_composite_signals(df.copy(), symbol="MES", t1_atr_mult=5.0)

    narrow_entries = narrow[narrow["entry_signal"] == "ENTRY_NOW"]
    wide_entries = wide[wide["entry_signal"] == "ENTRY_NOW"]

    common = narrow_entries.index.intersection(wide_entries.index)
    if len(common) == 0:
        pytest.skip("No overlapping entries (R:R filter may drop narrow-target entries)")

    for idx in common:
        n_t1 = narrow_entries.at[idx, "target_1"]
        w_t1 = wide_entries.at[idx, "target_1"]
        assert n_t1 != w_t1, (
            f"target_1 unchanged between t1_atr_mult=1.5 and 5.0 at {idx}. "
            f"Hardcoded target likely regressed."
        )


def test_default_behavior_preserved():
    """Calling with no ATR-mult params must produce the same output as the
    pre-2026-04-20 hardcoded defaults (stop=1.00, T1=2.50, T2=4.00, T3=6.00)."""
    df = _make_bullish_bars()

    implicit = generate_composite_signals(df.copy(), symbol="MES")
    explicit = generate_composite_signals(
        df.copy(),
        symbol="MES",
        stop_atr_mult=1.00,
        t1_atr_mult=2.50,
        t2_atr_mult=4.00,
        t3_atr_mult=6.00,
    )

    # Implicit and explicit-with-defaults must match column-wise on stop/targets
    for col in ("stop_level", "target_1", "target_2", "target_3"):
        pd.testing.assert_series_equal(
            implicit[col], explicit[col], check_names=False, obj=col
        )


def test_rr_filter_still_fires_with_tight_targets():
    """Tiny t1_atr_mult with large stop_atr_mult should produce R:R < MIN_RR
    and result in entries being filtered out (entry_signal reverted to NO_TRADE)."""
    df = _make_bullish_bars()

    result = generate_composite_signals(
        df.copy(),
        symbol="MES",
        stop_atr_mult=5.0,   # very wide stop
        t1_atr_mult=0.5,     # very narrow target → R:R ≈ 0.1
    )
    # With R:R 0.1 < MIN_RR (1.2), no entries should survive
    assert (result["entry_signal"] == "ENTRY_NOW").sum() == 0, (
        "R:R filter should have rejected entries with extreme stop/target asymmetry"
    )

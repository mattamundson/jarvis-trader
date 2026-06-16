"""Structural invariants for the Saty ATR mechanical signal generator.

These guard the Backtester contract and the no-look-ahead discipline; the
*edge* question is answered separately by the gate-v2 WFO runner.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.saty_atr_signals import TRIGGER_RATIO, generate_saty_atr_signals


def _synth_sessions(n_days: int = 26, bars_per_day: int = 40, seed: int = 7) -> pd.DataFrame:
    """Build a synthetic 5m RTH frame across several ET weekdays."""
    rng = np.random.default_rng(seed)
    rows, idx = [], []
    price = 5000.0
    day = pd.Timestamp("2025-01-06 09:30", tz="America/New_York")  # a Monday
    for d in range(n_days):
        start = day + pd.Timedelta(days=d)
        # skip weekends
        while start.dayofweek >= 5:
            start = start + pd.Timedelta(days=1)
        # Alternating directional trend each day so triggers/bands get crossed
        # in both directions -> guarantees GO and FADE entries to test against.
        trend = 1.2 if d % 2 == 0 else -1.2
        for b in range(bars_per_day):
            ts = start + pd.Timedelta(minutes=5 * b)
            drift = rng.normal(0, 3) + trend
            o = price
            c = price + drift
            h = max(o, c) + abs(rng.normal(0, 2))
            low = min(o, c) - abs(rng.normal(0, 2))
            rows.append((o, h, low, c, 100.0))
            idx.append(ts)
            price = c
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])
    df.index = pd.DatetimeIndex(idx).tz_convert("UTC")
    return df


def test_go_entries_have_valid_contract_columns():
    df = _synth_sessions()
    sig = generate_saty_atr_signals(df, mode="go", target_ratio=1.0)
    for col in ("entry_signal", "bias", "stop_level", "target_1", "target_2", "atr", "exit_signal"):
        assert col in sig.columns
    ent = sig[sig["entry_signal"] == "ENTRY_NOW"]
    assert len(ent) > 0, "trended synthetic data should produce GO entries"
    # Every entry has a non-null stop and target and a directional bias.
    assert ent["stop_level"].notna().all()
    assert ent["target_1"].notna().all()
    assert set(ent["bias"].unique()) <= {"BULLISH", "BEARISH"}


def test_go_stop_and_target_on_correct_sides():
    df = _synth_sessions()
    sig = generate_saty_atr_signals(df, mode="go", target_ratio=1.0)
    ent = sig[sig["entry_signal"] == "ENTRY_NOW"]
    longs = ent[ent["bias"] == "BULLISH"]
    shorts = ent[ent["bias"] == "BEARISH"]
    # Long: target above stop; Short: target below stop.
    assert (longs["target_1"] > longs["stop_level"]).all()
    assert (shorts["target_1"] < shorts["stop_level"]).all()


def test_no_lookahead_first_session_has_no_anchor():
    df = _synth_sessions()
    sig = generate_saty_atr_signals(df, mode="go")
    # The earliest session has no prior close -> anchor NaN -> no entry possible.
    first_day = sig.index.tz_convert("America/New_York").date.min()
    first_mask = sig.index.tz_convert("America/New_York").date == first_day
    assert sig.loc[first_mask, "anchor"].isna().all()
    assert (sig.loc[first_mask, "entry_signal"] == "NO_TRADE").all()


def test_one_entry_per_session():
    df = _synth_sessions()
    sig = generate_saty_atr_signals(df, mode="go")
    ent = sig[sig["entry_signal"] == "ENTRY_NOW"].copy()
    if ent.empty:
        return  # vacuously true — invariant is "<= 1 per session"
    ent["d"] = ent.index.tz_convert("America/New_York").date
    assert ent.groupby("d").size().max() <= 1


def test_fade_respects_exhaustion_filter():
    df = _synth_sessions()
    # A very high exhaustion floor should suppress essentially all fades.
    strict = generate_saty_atr_signals(df, mode="fade", entry_band=1.0, min_range_consumed=5.0)
    assert (strict["entry_signal"] == "ENTRY_NOW").sum() == 0


def test_trigger_ratio_is_corey_canonical():
    assert TRIGGER_RATIO == 0.236


def test_invalid_mode_raises():
    df = _synth_sessions()
    with pytest.raises(ValueError):
        generate_saty_atr_signals(df, mode="sideways")

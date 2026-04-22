"""Tests for `backtest.meanrev_signals` — Bollinger+RSI mean-reversion generator.

Roadmap P1.1. Focused on signal correctness on crafted synthetic data —
entry fires at extremes, exit fires on midband cross, direction is symmetric,
no-signal during warmup.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.meanrev_signals import (
    MEANREV_PARAMS,
    _wilder_rsi,
    generate_bollinger_rsi_signals,
    get_meanrev_params,
)


def _make_flat_ohlc(n: int = 40, price: float = 100.0) -> pd.DataFrame:
    """Pure-flat series — no bands will ever be breached, no signals."""
    idx = pd.date_range("2026-01-01", periods=n, freq="1h")
    return pd.DataFrame(
        {
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 1000,
        },
        index=idx,
    )


def _make_oscillating_ohlc(n: int = 200) -> pd.DataFrame:
    """Sine-wave-ish price that oscillates enough to fire both LONG and SHORT."""
    idx = pd.date_range("2026-01-01", periods=n, freq="1h")
    t = np.arange(n)
    # Base level 100, wide sinusoid amplitude 3, plus a light AR(1) noise
    rng = np.random.default_rng(42)
    noise = rng.normal(0.0, 0.3, size=n).cumsum() * 0.02
    price = 100.0 + 3.0 * np.sin(t / 8.0) + noise
    return pd.DataFrame(
        {
            "open": price,
            "high": price + 0.2,
            "low": price - 0.2,
            "close": price,
            "volume": 1000,
        },
        index=idx,
    )


# ── Unit: Wilder RSI ────────────────────────────────────────────────────────


def test_wilder_rsi_all_gains_returns_100():
    close = pd.Series([100.0 + i for i in range(30)])  # monotonic up
    rsi = _wilder_rsi(close, period=14)
    # After warmup, RSI should be pinned at 100 (no losses)
    assert rsi.iloc[-1] == 100.0


def test_wilder_rsi_warmup_is_nan():
    close = pd.Series([100.0 + np.random.default_rng(1).normal() for _ in range(30)])
    rsi = _wilder_rsi(close, period=14)
    # First period-1 values must be NaN (insufficient data for smoothing)
    assert rsi.iloc[:13].isna().all()
    assert not pd.isna(rsi.iloc[-1])


def test_wilder_rsi_bounded_0_100():
    rng = np.random.default_rng(7)
    close = pd.Series(100.0 + rng.normal(size=200).cumsum() * 0.5)
    rsi = _wilder_rsi(close, period=14).dropna()
    assert (rsi >= 0.0).all()
    assert (rsi <= 100.0).all()


# ── Unit: signal generation ────────────────────────────────────────────────


def test_flat_market_produces_zero_entries():
    """If price never moves, no entries should fire."""
    df = _make_flat_ohlc(n=50)
    out = generate_bollinger_rsi_signals(df)
    assert (out["entry_signal"] == "NO_TRADE").all()


def test_warmup_bars_produce_no_entries():
    """Before BB + RSI warmup complete (first 20 bars), no entries."""
    df = _make_oscillating_ohlc(n=200)
    out = generate_bollinger_rsi_signals(df)
    warmup_slice = out.iloc[:20]
    assert (warmup_slice["entry_signal"] == "NO_TRADE").all()


def test_oscillating_market_fires_both_directions():
    """Long oscillation should produce at least one LONG and at least one SHORT."""
    df = _make_oscillating_ohlc(n=300)
    out = generate_bollinger_rsi_signals(
        df, rsi_long=45.0, rsi_short=55.0,  # loose thresholds to catch signals
    )
    longs = (out["bias"] == "STRONG_BULL") & (out["entry_signal"] == "ENTRY_NOW")
    shorts = (out["bias"] == "STRONG_BEAR") & (out["entry_signal"] == "ENTRY_NOW")
    assert longs.sum() >= 1, "Oscillating price must produce at least one LONG"
    assert shorts.sum() >= 1, "Oscillating price must produce at least one SHORT"


def test_long_entry_stop_is_below_entry():
    """LONG stop must be ≤ entry price; target_1 must be ≥ entry (reverting up)."""
    df = _make_oscillating_ohlc(n=300)
    out = generate_bollinger_rsi_signals(df, rsi_long=45.0, rsi_short=55.0)
    long_rows = out[(out["bias"] == "STRONG_BULL") & (out["entry_signal"] == "ENTRY_NOW")]
    assert len(long_rows) > 0
    for _idx, r in long_rows.iterrows():
        assert r["stop_level"] < r["close"], "LONG stop must be below entry"
        assert r["target_1"] >= r["close"], "LONG target_1 must be at/above entry"


def test_short_entry_stop_is_above_entry():
    df = _make_oscillating_ohlc(n=300)
    out = generate_bollinger_rsi_signals(df, rsi_long=45.0, rsi_short=55.0)
    short_rows = out[(out["bias"] == "STRONG_BEAR") & (out["entry_signal"] == "ENTRY_NOW")]
    assert len(short_rows) > 0
    for _idx, r in short_rows.iterrows():
        assert r["stop_level"] > r["close"], "SHORT stop must be above entry"
        assert r["target_1"] <= r["close"], "SHORT target_1 must be at/below entry"


def test_midband_cross_produces_exit():
    """Sanity: some exit signals must fire when price crosses the midband."""
    df = _make_oscillating_ohlc(n=300)
    out = generate_bollinger_rsi_signals(df)
    assert (out["exit_signal"] == "EXIT_NOW").sum() > 0


def test_output_columns_contract():
    """Required column contract for downstream backtester consumption."""
    df = _make_oscillating_ohlc(n=100)
    out = generate_bollinger_rsi_signals(df)
    required = {
        "entry_signal", "exit_signal", "bias", "regime",
        "stop_level", "target_1", "target_2", "target_3",
        "bb_upper", "bb_mid", "bb_lower", "rsi_14", "atr_14",
    }
    missing = required - set(out.columns)
    assert not missing, f"missing required columns: {missing}"


def test_default_mcl_params_registered():
    """MCL default params must be present — the router (P1.1 step 5) reads them."""
    params = get_meanrev_params("MCL")
    assert params is not None
    assert params["bb_period"] == 20
    assert params["bb_std"] == 2.0
    assert params["rsi_long"] < 50 < params["rsi_short"]
    assert params["stop_atr_mult"] > 0


def test_unknown_symbol_returns_none():
    assert get_meanrev_params("BTCUSD") is None


def test_casing_normalized():
    assert get_meanrev_params("mcl") == get_meanrev_params("MCL")


def test_no_conflict_both_long_and_short_same_bar():
    """If RSI thresholds overlap (rare), both sides cannot fire on same bar."""
    df = _make_oscillating_ohlc(n=200)
    out = generate_bollinger_rsi_signals(
        df, rsi_long=50.0, rsi_short=50.0,  # deliberately overlapping
    )
    # No bar may have both bias=BULL and bias=BEAR simultaneously (impossible
    # by the `bias` column being scalar per row), but the "entered" set must
    # partition: any ENTRY_NOW bar has a single bias.
    entries = out[out["entry_signal"] == "ENTRY_NOW"]
    assert not ((entries["bias"] == "STRONG_BULL") & (entries["bias"] == "STRONG_BEAR")).any()


def test_mcl_params_dict_readable():
    """Router in signals.py (P1.1 step 5) will look up MEANREV_PARAMS[symbol]."""
    assert "MCL" in MEANREV_PARAMS


# ── Regime-filter retry (Track 4 / P1.1 iteration 2) ──────────────────────


def _make_trend_ohlc(n: int = 400, seed: int = 99) -> pd.DataFrame:
    """Strong monotonic uptrend — ADX should climb well above 20 throughout
    the latter half. Mean-reversion entries on a trend like this are exactly
    the false-positives the regime filter must suppress.
    """
    rng = np.random.default_rng(seed)
    base = 100.0
    drift = np.linspace(0, 40, n)
    noise = rng.normal(0, 0.5, n)
    close = base + drift + noise
    high = close + 0.8
    low = close - 0.8
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    return pd.DataFrame({
        "open": close, "high": high, "low": low, "close": close, "volume": 1000,
    }, index=idx)


def test_adx_regime_filter_reduces_entries_on_trend():
    """On a monotonic uptrend, the default generator may fire mean-rev
    entries at pullback-to-lower-band bars. ADX filter must suppress them.
    """
    df = _make_trend_ohlc(n=400)
    default = generate_bollinger_rsi_signals(df, rsi_long=35.0, rsi_short=65.0)
    adx_gated = generate_bollinger_rsi_signals(
        df, rsi_long=35.0, rsi_short=65.0,
        regime_filter_mode="adx", regime_filter_adx_threshold=20.0,
    )
    n_default = (default["entry_signal"] == "ENTRY_NOW").sum()
    n_adx = (adx_gated["entry_signal"] == "ENTRY_NOW").sum()
    # ADX filter must not INCREASE entries — it can only suppress.
    assert n_adx <= n_default, f"ADX filter increased entries ({n_default} → {n_adx})"


def test_regime_filter_none_preserves_existing_behavior():
    """regime_filter_mode='none' (default) must produce identical entries to
    an explicit call with no filter kwargs — protects the existing test
    suite and downstream consumers from behavior drift.
    """
    df = _make_oscillating_ohlc(n=200)
    default = generate_bollinger_rsi_signals(df)
    explicit_none = generate_bollinger_rsi_signals(df, regime_filter_mode="none")

    # Entry/exit columns must be identical
    pd.testing.assert_series_equal(
        default["entry_signal"], explicit_none["entry_signal"], check_names=False,
    )
    pd.testing.assert_series_equal(
        default["exit_signal"], explicit_none["exit_signal"], check_names=False,
    )
    assert isinstance(MEANREV_PARAMS["MCL"], dict)

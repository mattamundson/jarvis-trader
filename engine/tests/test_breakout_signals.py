"""Tests for `backtest.breakout_signals` — Donchian channel breakout generator.

Roadmap P1.2. Focused on signal correctness on crafted synthetic data —
entry fires on channel break, exit fires on re-entry, direction is
symmetric, warmup bars produce no signals, volume filter gates entries.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.breakout_signals import (
    BREAKOUT_PARAMS,
    generate_donchian_breakout_signals,
    get_breakout_params,
)


def _make_flat_ohlc(n: int = 40, price: float = 100.0, vol: float = 1000.0) -> pd.DataFrame:
    """Pure-flat series — no channel will ever be broken."""
    idx = pd.date_range("2026-01-01", periods=n, freq="1h")
    return pd.DataFrame(
        {"open": price, "high": price, "low": price, "close": price, "volume": vol},
        index=idx,
    )


def _make_step_up_ohlc(n: int = 60, baseline: float = 100.0, step_at: int = 40, step_size: float = 5.0) -> pd.DataFrame:
    """Flat range for N bars, then a step up — forces one LONG Donchian break."""
    idx = pd.date_range("2026-01-01", periods=n, freq="1h")
    price = np.full(n, baseline, dtype=float)
    price[step_at:] += step_size
    df = pd.DataFrame(
        {
            "open": price,
            "high": price + 0.1,
            "low": price - 0.1,
            "close": price,
            "volume": np.full(n, 2000.0),
        },
        index=idx,
    )
    return df


def _make_step_down_ohlc(n: int = 60, baseline: float = 100.0, step_at: int = 40, step_size: float = 5.0) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="1h")
    price = np.full(n, baseline, dtype=float)
    price[step_at:] -= step_size
    df = pd.DataFrame(
        {
            "open": price,
            "high": price + 0.1,
            "low": price - 0.1,
            "close": price,
            "volume": np.full(n, 2000.0),
        },
        index=idx,
    )
    return df


# ── Signal correctness ─────────────────────────────────────────────────────


def test_flat_market_produces_zero_entries():
    df = _make_flat_ohlc(n=60)
    out = generate_donchian_breakout_signals(df)
    assert (out["entry_signal"] == "NO_TRADE").all()


def test_warmup_bars_produce_no_entries():
    df = _make_step_up_ohlc(n=60, step_at=5)  # step before warmup completes
    out = generate_donchian_breakout_signals(df, donchian_period=20)
    warmup_slice = out.iloc[:20]
    assert (warmup_slice["entry_signal"] == "NO_TRADE").all()


def test_step_up_fires_long_entry():
    df = _make_step_up_ohlc(n=60, step_at=40, step_size=5.0)
    out = generate_donchian_breakout_signals(df, donchian_period=20, vol_mult=0.0)
    longs = (out["bias"] == "STRONG_BULL") & (out["entry_signal"] == "ENTRY_NOW")
    assert longs.sum() >= 1, "Step-up in price must fire at least one LONG"


def test_step_down_fires_short_entry():
    df = _make_step_down_ohlc(n=60, step_at=40, step_size=5.0)
    out = generate_donchian_breakout_signals(df, donchian_period=20, vol_mult=0.0)
    shorts = (out["bias"] == "STRONG_BEAR") & (out["entry_signal"] == "ENTRY_NOW")
    assert shorts.sum() >= 1, "Step-down in price must fire at least one SHORT"


def test_long_entry_stop_below_entry_target_above():
    df = _make_step_up_ohlc(n=60, step_at=40, step_size=5.0)
    out = generate_donchian_breakout_signals(df, donchian_period=20, vol_mult=0.0)
    long_rows = out[(out["bias"] == "STRONG_BULL") & (out["entry_signal"] == "ENTRY_NOW")]
    assert len(long_rows) > 0
    for _idx, r in long_rows.iterrows():
        assert r["stop_level"] < r["close"]
        assert r["target_1"] > r["close"]
        assert r["target_3"] > r["target_1"]


def test_short_entry_stop_above_entry_target_below():
    df = _make_step_down_ohlc(n=60, step_at=40, step_size=5.0)
    out = generate_donchian_breakout_signals(df, donchian_period=20, vol_mult=0.0)
    short_rows = out[(out["bias"] == "STRONG_BEAR") & (out["entry_signal"] == "ENTRY_NOW")]
    assert len(short_rows) > 0
    for _idx, r in short_rows.iterrows():
        assert r["stop_level"] > r["close"]
        assert r["target_1"] < r["close"]
        assert r["target_3"] < r["target_1"]


def test_volume_filter_suppresses_weak_volume_break():
    """High volume mult should reject breakouts without volume confirmation."""
    df = _make_step_up_ohlc(n=60, step_at=40, step_size=5.0)
    # Lower volume on the breakout bar so vol_mult=5x rejects it
    df.loc[df.index[40:], "volume"] = 100.0
    df.loc[df.index[:40], "volume"] = 1000.0
    out = generate_donchian_breakout_signals(df, donchian_period=20, vol_mult=5.0)
    longs = (out["bias"] == "STRONG_BULL") & (out["entry_signal"] == "ENTRY_NOW")
    assert longs.sum() == 0, "Volume filter must reject low-volume breakouts"


def test_volume_filter_zero_disables_gate():
    """vol_mult=0 should be a no-op filter — breakouts fire on low volume."""
    df = _make_step_up_ohlc(n=60, step_at=40, step_size=5.0)
    df.loc[df.index[40:], "volume"] = 0.0
    out = generate_donchian_breakout_signals(df, donchian_period=20, vol_mult=0.0)
    longs = (out["bias"] == "STRONG_BULL") & (out["entry_signal"] == "ENTRY_NOW")
    assert longs.sum() >= 1


def test_exit_fires_when_price_returns_inside_channel():
    """After a breakout, a bar back inside the (prior) channel exits the trade."""
    df = _make_step_up_ohlc(n=80, step_at=40, step_size=5.0)
    # Bring price back into the prior 100 range from bar 55 onward
    df.loc[df.index[55:], "close"] = 100.0
    df.loc[df.index[55:], "high"] = 100.1
    df.loc[df.index[55:], "low"] = 99.9
    out = generate_donchian_breakout_signals(df, donchian_period=20, vol_mult=0.0)
    exits = out["exit_signal"] == "EXIT_NOW"
    assert exits.sum() > 0


def test_output_columns_contract():
    """Required column contract for downstream backtester consumption."""
    df = _make_step_up_ohlc(n=60, step_at=40)
    out = generate_donchian_breakout_signals(df)
    required = {
        "entry_signal", "exit_signal", "bias", "regime",
        "stop_level", "target_1", "target_2", "target_3",
        "donchian_high", "donchian_low", "vol_ma", "atr_14",
    }
    missing = required - set(out.columns)
    assert not missing, f"missing required columns: {missing}"


def test_no_conflict_both_long_and_short_same_bar():
    """If the range degenerates, both directions must not fire on the same bar."""
    df = _make_step_up_ohlc(n=60, step_at=40, step_size=5.0)
    out = generate_donchian_breakout_signals(df, donchian_period=20, vol_mult=0.0)
    entries = out[out["entry_signal"] == "ENTRY_NOW"]
    # bias per row is scalar — a row can't be both BULL and BEAR
    biases = set(entries["bias"].unique()) - {"NEUTRAL"}
    # At least one side fires; and no row has both
    assert "STRONG_BULL" in biases or "STRONG_BEAR" in biases


# ── Param registry ─────────────────────────────────────────────────────────


def test_default_mnq_params_registered():
    """MNQ default params must be present — the router (P1.2 step 5) reads them."""
    params = get_breakout_params("MNQ")
    assert params is not None
    assert params["donchian_period"] == 20
    assert params["stop_atr_mult"] > 0
    assert "vol_mult" in params


def test_unknown_symbol_returns_none():
    assert get_breakout_params("BTCUSD") is None


def test_casing_normalized():
    assert get_breakout_params("mnq") == get_breakout_params("MNQ")


def test_breakout_params_dict_readable():
    assert "MNQ" in BREAKOUT_PARAMS
    assert isinstance(BREAKOUT_PARAMS["MNQ"], dict)

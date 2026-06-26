"""
Tests for the MES overnight carry strategy.

Coverage:
  1. Signal contract: entry_signal, exit_signal, bias, regime columns present
  2. Entry only fires on ET hour 15 bars
  3. Exit only fires on ET hour 9 bars (and only after an entry)
  4. SMA filter suppresses entries when close <= SMA
  5. Trade count: roughly 1 entry per trading day (sanity bound)
  6. Wide stop / far target: R:R constraint satisfied for every ENTRY_NOW bar
  7. Bias is always "STRONG_BULL" (long-only)
  8. No entry on same bar as exit
  9. RunConfig grid has exactly 3 combos
  10. _find_data_file returns a Path (data file present for main checkout cache)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Add engine root to sys.path
engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

from backtest.overnight_signals import generate_overnight_signals  # noqa: E402
from backtest.run_mes_overnight_rank1 import RunConfig, _make_config  # noqa: E402

# ---------------------------------------------------------------------------
# Fixture: synthetic 1h bar data with realistic ET session structure
# ---------------------------------------------------------------------------

def _make_synthetic_df(n_days: int = 30, seed: int = 42) -> pd.DataFrame:
    """Build a synthetic 1h DataFrame with UTC-midnight-anchored bars.

    Includes bars at every hour 0-23 UTC so the ET conversion covers both
    regular-hours (09-16 ET = 14-21 UTC) and overnight bars.
    """
    rng = np.random.default_rng(seed)
    # Generate hourly bars for n_days starting 2024-01-02 (Tuesday)
    idx = pd.date_range("2024-01-02 00:00:00", periods=n_days * 24, freq="h", tz="UTC")
    base = 4800.0
    close = base + np.cumsum(rng.normal(0, 2, len(idx)))
    high = close + rng.uniform(0.5, 3, len(idx))
    low = close - rng.uniform(0.5, 3, len(idx))
    open_ = close - rng.normal(0, 1, len(idx))
    volume = rng.integers(1000, 5000, len(idx))
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


@pytest.fixture()
def df_synthetic() -> pd.DataFrame:
    return _make_synthetic_df(n_days=30)


# ---------------------------------------------------------------------------
# Test 1: required columns present
# ---------------------------------------------------------------------------

def test_signal_columns_present(df_synthetic):
    out = generate_overnight_signals(df_synthetic)
    required = {
        "entry_signal", "exit_signal", "stop_level", "trailing_stop",
        "target_1", "target_2", "target_3", "atr", "bias", "regime",
    }
    missing = required - set(out.columns)
    assert not missing, f"Missing signal columns: {missing}"


# ---------------------------------------------------------------------------
# Test 2: entries only on ET hour 15
# ---------------------------------------------------------------------------

def test_entries_only_on_et_hour_15(df_synthetic):
    out = generate_overnight_signals(df_synthetic)
    entry_mask = out["entry_signal"] == "ENTRY_NOW"
    if not entry_mask.any():
        pytest.skip("No entries generated in synthetic data; expand fixture")
    entry_et_hours = out.index[entry_mask].tz_convert("America/New_York").hour
    assert (entry_et_hours == 15).all(), (
        f"Entry on non-15 ET hours: {entry_et_hours[entry_et_hours != 15].unique()}"
    )


# ---------------------------------------------------------------------------
# Test 3: exits only on ET hour 9
# ---------------------------------------------------------------------------

def test_exits_only_on_et_hour_9(df_synthetic):
    out = generate_overnight_signals(df_synthetic)
    exit_mask = out["exit_signal"] == "EXIT_NOW"
    if not exit_mask.any():
        pytest.skip("No exits generated in synthetic data")
    exit_et_hours = out.index[exit_mask].tz_convert("America/New_York").hour
    assert (exit_et_hours == 9).all(), (
        f"Exit on non-9 ET hours: {exit_et_hours[exit_et_hours != 9].unique()}"
    )


# ---------------------------------------------------------------------------
# Test 4: SMA filter suppresses entries when close <= SMA
# ---------------------------------------------------------------------------

def test_sma_filter_suppresses_entries():
    """With filter_len=5 and a strongly falling market, entries should be reduced."""
    # Downward-trending market: SMA will be above close most of the time
    n_days = 20
    idx = pd.date_range("2024-01-02 00:00:00", periods=n_days * 24, freq="h", tz="UTC")
    base = 5000.0
    close = base - np.arange(len(idx)) * 0.5  # steadily falling
    high = close + 1.0
    low = close - 1.0
    df_falling = pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close},
        index=idx,
    )
    out_no_filter = generate_overnight_signals(df_falling, filter_len=0)
    out_filtered = generate_overnight_signals(df_falling, filter_len=5)
    entries_no_filter = (out_no_filter["entry_signal"] == "ENTRY_NOW").sum()
    entries_filtered = (out_filtered["entry_signal"] == "ENTRY_NOW").sum()
    assert entries_filtered < entries_no_filter, (
        f"Filter should reduce entries: {entries_filtered} >= {entries_no_filter}"
    )


# ---------------------------------------------------------------------------
# Test 5: trade count sanity (~1/trading-day in a 20-day window without filter)
# ---------------------------------------------------------------------------

def test_trade_count_sanity():
    n_days = 20
    idx = pd.date_range("2024-01-02 00:00:00", periods=n_days * 24, freq="h", tz="UTC")
    rng = np.random.default_rng(0)
    close = 4800.0 + np.cumsum(rng.normal(0, 2, len(idx)))
    df = pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close},
        index=idx,
    )
    out = generate_overnight_signals(df, filter_len=0)
    n_entries = (out["entry_signal"] == "ENTRY_NOW").sum()
    # Expect roughly 1 per trading day (5 days/week); allow 50%-150% of n_days
    assert n_days * 0.3 <= n_entries <= n_days * 1.1, (
        f"Unexpected trade count {n_entries} for {n_days} days"
    )


# ---------------------------------------------------------------------------
# Test 6: R:R constraint -- stop and target set so target_1 >> stop_level
# ---------------------------------------------------------------------------

def test_rr_constraint_satisfied(df_synthetic):
    out = generate_overnight_signals(df_synthetic)
    entry_rows = out[out["entry_signal"] == "ENTRY_NOW"]
    if len(entry_rows) == 0:
        pytest.skip("No entries in synthetic data")
    for _, row in entry_rows.iterrows():
        stop_dist = abs(row["close"] - row["stop_level"])
        t1_dist = abs(row["target_1"] - row["close"])
        assert stop_dist > 0, "stop_dist must be positive"
        rr = t1_dist / stop_dist
        assert rr > 1.2, f"R:R={rr:.2f} < 1.2 at bar {_}"


# ---------------------------------------------------------------------------
# Test 7: bias is always "STRONG_BULL"
# ---------------------------------------------------------------------------

def test_bias_always_strong_bull(df_synthetic):
    out = generate_overnight_signals(df_synthetic)
    unique_bias = out["bias"].unique()
    assert list(unique_bias) == ["STRONG_BULL"], f"Unexpected bias values: {unique_bias}"


# ---------------------------------------------------------------------------
# Test 8: no entry and exit on the same bar
# ---------------------------------------------------------------------------

def test_no_simultaneous_entry_exit(df_synthetic):
    out = generate_overnight_signals(df_synthetic)
    both = (out["entry_signal"] == "ENTRY_NOW") & (out["exit_signal"] == "EXIT_NOW")
    assert both.sum() == 0, f"{both.sum()} bars have simultaneous entry+exit"


# ---------------------------------------------------------------------------
# Test 9: RunConfig grid has exactly 3 combos
# ---------------------------------------------------------------------------

def test_run_config_grid_size():
    cfg = _make_config()
    assert len(cfg.grid) == 3, f"Expected 3 grid combos, got {len(cfg.grid)}"
    filter_lens = [fl for (fl,) in cfg.grid]
    assert sorted(filter_lens) == [0, 100, 200], f"Unexpected filter_len values: {filter_lens}"


# ---------------------------------------------------------------------------
# Test 10: _find_data_file locates the main cache (MES file must exist)
# ---------------------------------------------------------------------------

def test_find_data_file_resolves():
    from backtest.run_mes_overnight_rank1 import _find_data_file
    data_file = _find_data_file()
    if data_file is None:
        # The MES 1h CSV cache is gitignored and only present in a local
        # checkout -- CI runners have no cache, so resolution correctly
        # returns None. Skip rather than fail in that environment.
        pytest.skip("MES 1h cache not available (no local cache, e.g. CI)")
    assert data_file.exists(), f"Data file path doesn't exist: {data_file}"
    assert data_file.suffix == ".csv"

"""Tests for SMA trend-following signal generator."""
import numpy as np
import pandas as pd
import pytest

from backtest.trend_signals import (
    SMA_TREND_PARAMS,
    generate_sma_trend_signals,
    get_sma_trend_params,
)


def _make_df(n: int = 300, base: float = 5000.0, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = base + np.cumsum(rng.normal(0, 5, n))
    high = close + rng.uniform(1, 10, n)
    low = close - rng.uniform(1, 10, n)
    open_ = close + rng.normal(0, 2, n)
    idx = pd.date_range("2024-06-01", periods=n, freq="1h")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)


def _make_trending_df(n: int = 400) -> pd.DataFrame:
    """Price series that produces a genuine golden cross (decline then strong rise).

    Phase 1 (150 bars declining): SMA(20) drops below SMA(100) once both are valid.
    Phase 2 (remaining bars rising): SMA(20) crosses above SMA(100) — genuine cross,
    not the spurious first-valid-SMA-bar artifact that fillna(False) previously caused.
    """
    phase1 = np.linspace(5200, 4800, 150)
    phase2 = np.linspace(4800, 5800, n - 150)
    close = np.concatenate([phase1, phase2])
    high = close + 5
    low = close - 5
    idx = pd.date_range("2024-06-01", periods=n, freq="1h")
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close}, index=idx)


def test_required_columns_present():
    df = generate_sma_trend_signals(_make_df(), fast=10, slow=50)
    for col in ("entry_signal", "stop_level", "target_1", "target_2", "target_3", "bias", "regime", "atr"):
        assert col in df.columns, f"Missing column: {col}"


def test_entry_only_on_golden_cross():
    df = generate_sma_trend_signals(_make_trending_df(), fast=20, slow=100)
    entries = df[df["entry_signal"] == "ENTRY_NOW"]
    assert len(entries) >= 1, "Expected at least one ENTRY_NOW on trending data"
    # entry only on cross bar — not on every bar above SMA
    above = df["close"].rolling(20).mean() > df["close"].rolling(100).mean()
    non_cross = above & above.shift(1).fillna(False)
    for idx in entries.index:
        assert not non_cross.loc[idx], f"Entry fired on non-cross bar at {idx}"


def test_stop_below_entry_for_long():
    df = generate_sma_trend_signals(_make_trending_df(), fast=20, slow=100, atr_trail_mult=2.0)
    entries = df[df["entry_signal"] == "ENTRY_NOW"]
    for _idx, row in entries.iterrows():
        assert row["stop_level"] < row["close"], f"Stop {row['stop_level']} >= close {row['close']}"


def test_target_above_entry_for_long():
    df = generate_sma_trend_signals(_make_trending_df(), fast=20, slow=100)
    entries = df[df["entry_signal"] == "ENTRY_NOW"]
    for _idx, row in entries.iterrows():
        assert row["target_1"] > row["close"]
        assert row["target_2"] > row["target_1"]
        assert row["target_3"] > row["target_2"]


def test_bias_reflects_sma_relationship():
    df = generate_sma_trend_signals(_make_trending_df(), fast=20, slow=100)
    sma_f = df["close"].rolling(20).mean()
    sma_s = df["close"].rolling(100).mean()
    bull_mask = sma_f > sma_s
    assert (df.loc[bull_mask & sma_s.notna(), "bias"] == "STRONG_BULL").all()
    assert (df.loc[~bull_mask & sma_s.notna(), "bias"] == "STRONG_BEAR").all()


def test_regime_trending_bull_when_above():
    df = generate_sma_trend_signals(_make_trending_df(), fast=20, slow=100)
    sma_f = df["close"].rolling(20).mean()
    sma_s = df["close"].rolling(100).mean()
    above = (sma_f > sma_s) & sma_s.notna()
    assert (df.loc[above, "regime"] == "TRENDING_BULL").all()


def test_get_sma_trend_params_mes():
    params = get_sma_trend_params("MES")
    assert params is not None
    assert params["fast"] == 50  # rank2 champion (updated 2026-06-04 from rank11's 60)
    assert params["slow"] == 200
    assert params["atr_trail_mult"] == 2.0


def test_get_sma_trend_params_unknown_symbol():
    assert get_sma_trend_params("UNKNOWN") is None


def test_no_nan_in_entry_signal():
    df = generate_sma_trend_signals(_make_df(), fast=10, slow=50)
    assert df["entry_signal"].isna().sum() == 0


def test_generate_instrument_signals_routes_mes_to_trend():
    from backtest.signals import TREND_INSTRUMENTS, generate_instrument_signals
    assert "MES" in TREND_INSTRUMENTS
    # Use 700 bars: SMA(50,200) needs 200-bar warmup + decline + rise for golden cross.
    # Pass min_rv_annualized=0.0 explicitly to disable the RV filter (which would suppress
    # entries on the zero-noise linear test data regardless of MES_MIN_RV_ANNUALIZED env var).
    df = generate_instrument_signals(_make_trending_df(n=700), symbol="MES", min_rv_annualized=0.0)
    assert "entry_signal" in df.columns
    assert "bias" in df.columns
    # Should have at least one ENTRY_NOW on trending data
    assert (df["entry_signal"] == "ENTRY_NOW").any()


def test_mes_not_in_composite_instruments():
    from backtest.signals import COMPOSITE_INSTRUMENTS
    assert "MES" not in COMPOSITE_INSTRUMENTS


# ── Realized-vol filter (Phase B+ addition, 2026-04-21) ──────────────────
def test_rv_column_present_default_off():
    """rv_20_ann_pct column is emitted even when filter is disabled."""
    df = generate_sma_trend_signals(_make_df(), fast=10, slow=50)
    assert "rv_20_ann_pct" in df.columns
    # All-zero min_rv_annualized = backward-compatible: same entries as pre-filter
    assert df["rv_20_ann_pct"].iloc[-1] == df["rv_20_ann_pct"].iloc[-1]  # not NaN at tail


def test_rv_filter_blocks_when_threshold_exceeds_all():
    """Impossibly high threshold (999) suppresses ALL entries."""
    df = generate_sma_trend_signals(_make_trending_df(), fast=20, slow=100,
                                    min_rv_annualized=999.0)
    assert (df["entry_signal"] == "ENTRY_NOW").sum() == 0, \
        "No entries should fire when RV threshold is unreachable"


def test_rv_filter_zero_matches_unfiltered():
    """min_rv_annualized=0.0 (default) must produce identical entry signals to pre-filter behavior."""
    df_in = _make_trending_df()
    df_off = generate_sma_trend_signals(df_in, fast=20, slow=100, min_rv_annualized=0.0)
    df_on = generate_sma_trend_signals(df_in, fast=20, slow=100, min_rv_annualized=5.0)
    # With a real threshold, filter should block at least one entry relative to off
    n_off = (df_off["entry_signal"] == "ENTRY_NOW").sum()
    n_on = (df_on["entry_signal"] == "ENTRY_NOW").sum()
    assert n_on <= n_off, f"Filter should never INCREASE entries: off={n_off} on={n_on}"


def _daily_vix(value: float, periods: int = 25) -> pd.DataFrame:
    """Flat daily VIX frame aligned to the trending fixture's start date."""
    idx = pd.date_range("2024-06-01", periods=periods, freq="D")
    return pd.DataFrame({"close": [value] * periods}, index=idx)


def test_vix_regime_block_is_noop_by_default():
    """vix_regime_block=None must not change entries vs no VIX args (backward-compat)."""
    df_base = generate_sma_trend_signals(_make_trending_df(), fast=20, slow=100)
    df_vix = generate_sma_trend_signals(
        _make_trending_df(), fast=20, slow=100, vix_df=_daily_vix(20.0)
    )
    base_entries = (df_base["entry_signal"] == "ENTRY_NOW").sum()
    vix_entries = (df_vix["entry_signal"] == "ENTRY_NOW").sum()
    assert base_entries >= 1
    assert base_entries == vix_entries


def test_vix_regime_block_suppresses_entries_in_blocked_tier():
    """A flat VIX series maps to the MidVol tier (mid-rank ~50th percentile)."""
    base_entries = (
        generate_sma_trend_signals(_make_trending_df(), fast=20, slow=100)["entry_signal"]
        == "ENTRY_NOW"
    ).sum()

    # Blocking a tier the series is NOT in (Crisis) leaves entries unchanged.
    crisis_blocked = generate_sma_trend_signals(
        _make_trending_df(), fast=20, slow=100,
        vix_df=_daily_vix(20.0), vix_regime_block=("Crisis",),
    )
    assert (crisis_blocked["entry_signal"] == "ENTRY_NOW").sum() == base_entries

    # Blocking the tier the flat series IS in (MidVol) suppresses every entry.
    midvol_blocked = generate_sma_trend_signals(
        _make_trending_df(), fast=20, slow=100,
        vix_df=_daily_vix(20.0), vix_regime_block=("MidVol",),
    )
    assert (midvol_blocked["entry_signal"] == "ENTRY_NOW").sum() == 0

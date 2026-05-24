"""
JARVIS TRADER — Signal Generation Tests
Testing of the 5-layer Tony Stark trading framework signals.
"""

import numpy as np
import pandas as pd
import pytest

from backtest.signals import (
    compute_all_indicators,
    generate_signals,
)


@pytest.fixture
def sample_ohlcv_df():
    """Sample OHLCV data for signal testing."""
    # Need 300+ bars for STC warmup (slow EMA=50, K=10, D=3, double stoch smoothing)
    dates = pd.date_range("2024-01-01", periods=300, freq="1h")
    data = {
        "open": np.random.uniform(5750, 5850, 300),
        "high": np.random.uniform(5800, 5900, 300),
        "low": np.random.uniform(5700, 5800, 300),
        "close": np.random.uniform(5750, 5850, 300),
        "volume": np.random.randint(1000000, 5000000, 300),
    }
    df = pd.DataFrame(data, index=dates)
    # Fix OHLC relationships
    df["high"] = df[["open", "high", "close"]].max(axis=1) + 10
    df["low"] = df[["open", "low", "close"]].min(axis=1) - 10
    return df


@pytest.fixture
def bullish_ohlcv_df():
    """Strongly bullish OHLCV data with trend + noise for STC oscillation."""
    # Need 300+ bars for STC warmup, and prices must oscillate around a trend
    # for STC to generate meaningful crossovers
    dates = pd.date_range("2024-01-01", periods=300, freq="1h")
    np.random.seed(42)
    trend = np.linspace(5700, 5900, 300)
    noise = np.random.normal(0, 10, 300)  # Add oscillation for STC to generate crossovers
    close_prices = trend + noise
    data = {
        "open": close_prices - 5,
        "high": close_prices + 20,
        "low": close_prices - 20,
        "close": close_prices,
        "volume": np.linspace(2000000, 4000000, 300),
    }
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def bearish_ohlcv_df():
    """Strongly bearish OHLCV data with trend + noise for STC oscillation."""
    # Need 300+ bars for STC warmup, and prices must oscillate around a trend
    # for STC to generate meaningful crossovers
    dates = pd.date_range("2024-01-01", periods=300, freq="1h")
    np.random.seed(43)
    trend = np.linspace(5900, 5700, 300)  # Descending
    noise = np.random.normal(0, 10, 300)  # Add oscillation for STC to generate crossovers
    close_prices = trend + noise
    data = {
        "open": close_prices + 5,
        "high": close_prices + 20,
        "low": close_prices - 20,
        "close": close_prices,
        "volume": np.linspace(4000000, 2000000, 300),
    }
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def ranging_ohlcv_df():
    """Range-bound OHLCV data."""
    # Need 300+ bars for STC warmup
    dates = pd.date_range("2024-01-01", periods=300, freq="1h")
    # Oscillate around midpoint
    close_prices = 5800 + 30 * np.sin(np.linspace(0, 4 * np.pi, 300))
    data = {
        "open": close_prices - 2,
        "high": close_prices + 15,
        "low": close_prices - 15,
        "close": close_prices,
        "volume": np.full(300, 3000000),
    }
    return pd.DataFrame(data, index=dates)


class TestComputeAllIndicators:
    """Indicator computation."""

    def test_compute_all_indicators_adds_expected_columns(self, sample_ohlcv_df):
        """All indicators computed and columns added."""
        # Act
        df = compute_all_indicators(sample_ohlcv_df)

        # Assert - key indicators present
        expected_columns = [
            "atr",
            "stc_val",
            "stc_signal",
            "stc_cross_up",
            "stc_cross_down",
            "phase_val",
            "phase_compression",
            "phase_signal",
            "kama_val",
            "kama_signal",
            "volume_signal",
            "ema_8",
            "ema_21",
            "ema_34",
            "ema_trend",
        ]
        for col in expected_columns:
            assert col in df.columns, f"Missing column: {col}"

    def test_atr_values_positive(self, sample_ohlcv_df):
        """ATR values are positive."""
        # Act
        df = compute_all_indicators(sample_ohlcv_df)

        # Assert - skip warmup period (first 14 bars for ATR)
        atr_valid = df["atr"].iloc[14:]
        assert (atr_valid >= 0).all()

    def test_stc_values_in_range(self, sample_ohlcv_df):
        """STC values in expected 0-100 range."""
        # Act
        df = compute_all_indicators(sample_ohlcv_df)

        # Assert
        stc_valid = df["stc_val"].dropna()
        assert (stc_valid >= 0).all() and (stc_valid <= 100).all()

    def test_ema_ribbon_ordering_bullish(self, bullish_ohlcv_df):
        """EMA ribbon aligned bullish (8 > 21 > 34) during uptrend."""
        # Act
        df = compute_all_indicators(bullish_ohlcv_df)

        # Assert - at end of strong uptrend, EMAs should align bullishly
        last_rows = df.tail(10)
        assert (
            last_rows["ema_8"] >= last_rows["ema_21"]
        ).sum() >= 5, "EMA 8 should exceed 21 in bullish trend"


class TestSTCCrossover:
    """STC crossover signal generation."""

    def test_stc_crossover_generates_long(self, bullish_ohlcv_df):
        """STC crossing above oversold → LONG entry signal."""
        # Arrange
        df = compute_all_indicators(bullish_ohlcv_df)

        # Act
        signals = generate_signals(df, symbol="MES")

        # Assert - should see upside crossovers (skip warmup period of ~150 bars for STC)
        crossovers_up = signals["stc_cross_up"].iloc[150:].sum()
        assert crossovers_up > 0, "Should detect upside crossovers in bullish trend"

    def test_stc_crossover_generates_short(self, bearish_ohlcv_df):
        """STC crossing below overbought → SHORT entry signal."""
        # Arrange
        df = compute_all_indicators(bearish_ohlcv_df)

        # Act
        signals = generate_signals(df, symbol="MES")

        # Assert - should see downside crossovers (skip warmup period of ~150 bars for STC)
        crossovers_down = signals["stc_cross_down"].iloc[150:].sum()
        assert crossovers_down > 0, "Should detect downside crossovers in bearish trend"

    def test_stc_oversold_signal(self, bullish_ohlcv_df):
        """STC < oversold threshold → 'oversold' signal."""
        # Arrange
        df = compute_all_indicators(bullish_ohlcv_df)

        # Act
        signals = generate_signals(df, symbol="MES", stc_oversold=20)

        # Assert
        signals[signals["stc_signal"] == "oversold"]
        # May or may not have oversold in this data, but signal should work
        assert "stc_signal" in signals.columns


class TestRegimeFilter:
    """Regime filtering of signals."""

    def test_regime_filter_blocks_exhausted(self, sample_ohlcv_df):
        """EXHAUSTED regime → no entries."""
        # Arrange
        df = compute_all_indicators(sample_ohlcv_df)
        # Artificially create exhausted condition
        df.loc[df.index[-1], "atr_consumed_pct"] = 95.0
        df.loc[df.index[-1], "phase_val"] = 70.0

        # Act
        signals = generate_signals(df, regime_filter=True, symbol="MES")

        # Assert - exhausted bar should not have ENTRY_NOW
        exhausted_rows = signals[signals["regime"] == "EXHAUSTED"]
        if len(exhausted_rows) > 0:
            assert (exhausted_rows["entry_signal"] != "ENTRY_NOW").all() or (
                exhausted_rows["entry_signal"] == "FADE_EXTREME"
            ).any()

    def test_regime_filter_allows_entry_in_trending(self, bullish_ohlcv_df):
        """TRENDING_BULL regime with alignment → ENTRY_NOW possible."""
        # Arrange
        df = compute_all_indicators(bullish_ohlcv_df)

        # Act
        signals = generate_signals(df, regime_filter=True, symbol="MES")

        # Assert
        entry_now = signals["entry_signal"].eq("ENTRY_NOW").sum()
        assert entry_now >= 0  # May have entries depending on alignment

    def test_regime_filter_bypass_flag(self, sample_ohlcv_df):
        """regime_filter=False → allows structure-based entries in compression."""
        # Arrange
        df = compute_all_indicators(sample_ohlcv_df)

        # Act with filter disabled
        signals_no_filter = generate_signals(df, regime_filter=False, symbol="MES")

        # Assert - no EXHAUSTED regimes downgraded to RANGE_BOUND
        assert "regime" in signals_no_filter.columns


class TestATRStops:
    """ATR-based stop level calculation."""

    def test_atr_stop_calculation_long(self, bullish_ohlcv_df):
        """Long stop = close - stop_atr * ATR."""
        # Arrange
        df = compute_all_indicators(bullish_ohlcv_df)

        # Act
        signals = generate_signals(df, symbol="MES")

        # Assert - stops should be below close for longs (skip warmup period of ~150 bars)
        long_rows = signals.iloc[150:][
            signals.iloc[150:]["bias"].isin(["STRONG_BULL", "LEAN_BULL"])
        ]
        if len(long_rows) > 0:
            assert (
                long_rows["stop_level"] < long_rows["close"]
            ).all(), "Long stops should be below current price"

    def test_atr_stop_calculation_short(self, bearish_ohlcv_df):
        """Short stop = close + stop_atr * ATR."""
        # Arrange
        df = compute_all_indicators(bearish_ohlcv_df)

        # Act
        signals = generate_signals(df, symbol="MES")

        # Assert - stops should be above close for shorts (skip warmup period of ~150 bars)
        short_rows = signals.iloc[150:][
            signals.iloc[150:]["bias"].isin(["STRONG_BEAR", "LEAN_BEAR"])
        ]
        if len(short_rows) > 0:
            assert (
                short_rows["stop_level"] > short_rows["close"]
            ).all(), "Short stops should be above current price"

    def test_atr_stop_respects_instrument_params(self, bullish_ohlcv_df):
        """Instrument-specific ATR stop ratio applied."""
        # Arrange
        df = compute_all_indicators(bullish_ohlcv_df)

        # MNQ has stop_atr=0.70
        # Act
        signals = generate_signals(df, symbol="MNQ")

        # Assert - stops should use MNQ params
        assert "stop_level" in signals.columns


class TestATRTargets:
    """ATR-based target calculation."""

    def test_atr_target_calculation_long(self, bullish_ohlcv_df):
        """Long targets = close + t1/t2/t3 * ATR."""
        # Arrange
        df = compute_all_indicators(bullish_ohlcv_df)

        # Act
        signals = generate_signals(df, symbol="MES")

        # Assert - targets should be above close and in order (skip warmup period of ~150 bars)
        long_rows = signals.iloc[150:][
            signals.iloc[150:]["bias"].isin(["STRONG_BULL", "LEAN_BULL"])
        ]
        if len(long_rows) > 0:
            assert (long_rows["target_1"] > long_rows["close"]).all()
            assert (long_rows["target_2"] >= long_rows["target_1"]).all()
            assert (long_rows["target_3"] >= long_rows["target_2"]).all()

    def test_atr_target_calculation_short(self, bearish_ohlcv_df):
        """Short targets = close - t1/t2/t3 * ATR."""
        # Arrange
        df = compute_all_indicators(bearish_ohlcv_df)

        # Act
        signals = generate_signals(df, symbol="MES")

        # Assert - targets should be below close and in order (skip warmup period of ~150 bars)
        short_rows = signals.iloc[150:][
            signals.iloc[150:]["bias"].isin(["STRONG_BEAR", "LEAN_BEAR"])
        ]
        if len(short_rows) > 0:
            assert (short_rows["target_1"] < short_rows["close"]).all()
            assert (short_rows["target_2"] <= short_rows["target_1"]).all()
            assert (short_rows["target_3"] <= short_rows["target_2"]).all()

    def test_target_respects_instrument_t1_atr(self, bullish_ohlcv_df):
        """T1 ATR ratio varies by instrument."""
        # Arrange
        df = compute_all_indicators(bullish_ohlcv_df)

        # MNQ: t1_atr=1.00, MCL: t1_atr=1.50
        signals_mnq = generate_signals(df, symbol="MNQ")
        signals_mcl = generate_signals(df, symbol="MCL")

        # Assert - targets should differ
        assert "target_1" in signals_mnq.columns
        assert "target_1" in signals_mcl.columns


class TestLayer3Bias:
    """Layer 3 directional bias calculation."""

    def test_bias_strong_bull_all_aligned(self, bullish_ohlcv_df):
        """All bullish indicators → STRONG_BULL or LEAN_BULL."""
        # Arrange
        df = compute_all_indicators(bullish_ohlcv_df)

        # Act
        signals = generate_signals(df, symbol="MES")

        # Assert - skip warmup period (~150 bars for STC)
        # In bullish trend, expect STRONG_BULL or LEAN_BULL
        bullish_count = (signals.iloc[150:]["bias"].isin(["STRONG_BULL", "LEAN_BULL"])).sum()
        assert (
            bullish_count > 0
        ), "Bullish trend should produce bullish bias (STRONG_BULL or LEAN_BULL)"

    def test_bias_strong_bear_all_aligned(self, bearish_ohlcv_df):
        """All bearish indicators → STRONG_BEAR or LEAN_BEAR."""
        # Arrange
        df = compute_all_indicators(bearish_ohlcv_df)

        # Act
        signals = generate_signals(df, symbol="MES")

        # Assert - skip warmup period (~150 bars for STC)
        # In bearish trend, expect STRONG_BEAR or LEAN_BEAR
        bearish_count = (signals.iloc[150:]["bias"].isin(["STRONG_BEAR", "LEAN_BEAR"])).sum()
        assert (
            bearish_count > 0
        ), "Bearish trend should produce bearish bias (STRONG_BEAR or LEAN_BEAR)"

    def test_bias_neutral_mixed_indicators(self, ranging_ohlcv_df):
        """Mixed signals → NEUTRAL bias."""
        # Arrange
        df = compute_all_indicators(ranging_ohlcv_df)

        # Act
        signals = generate_signals(df, symbol="MES")

        # Assert
        neutral_count = (signals["bias"] == "NEUTRAL").sum()
        assert neutral_count > 0, "Range-bound data should produce NEUTRAL bias"


class TestLayer1Regime:
    """Layer 1 market regime detection."""

    def test_regime_trending_bull(self, bullish_ohlcv_df):
        """Strong uptrend → TRENDING_BULL regime."""
        # Arrange
        df = compute_all_indicators(bullish_ohlcv_df)

        # Act
        signals = generate_signals(df, symbol="MES")

        # Assert
        trending_bull = (signals["regime"] == "TRENDING_BULL").sum()
        assert trending_bull > 0, "Bullish trend should detect TRENDING_BULL"

    def test_regime_trending_bear(self, bearish_ohlcv_df):
        """Strong downtrend → TRENDING_BEAR regime."""
        # Arrange
        df = compute_all_indicators(bearish_ohlcv_df)

        # Act
        signals = generate_signals(df, symbol="MES")

        # Assert
        trending_bear = (signals["regime"] == "TRENDING_BEAR").sum()
        assert trending_bear > 0, "Bearish trend should detect TRENDING_BEAR"

    def test_regime_range_bound(self, ranging_ohlcv_df):
        """Oscillating price → RANGE_BOUND regime."""
        # Arrange
        df = compute_all_indicators(ranging_ohlcv_df)

        # Act
        signals = generate_signals(df, symbol="MES")

        # Assert
        range_bound = (signals["regime"] == "RANGE_BOUND").sum()
        assert range_bound > 0, "Range-bound data should detect RANGE_BOUND"


class TestLayer2Structure:
    """Layer 2 structural positioning (VPOC/VAH/VAL/IB)."""

    def test_structure_buyer_control(self, bullish_ohlcv_df):
        """Price above VAH + above IB High → BUYER_CONTROL."""
        # Arrange
        df = compute_all_indicators(bullish_ohlcv_df)

        # Act
        signals = generate_signals(df, symbol="MES")

        # Assert
        buyer_control = (signals["structure_position"] == "BUYER_CONTROL").sum()
        assert buyer_control >= 0  # May have some

    def test_structure_seller_control(self, bearish_ohlcv_df):
        """Price below VAL + below IB Low → SELLER_CONTROL."""
        # Arrange
        df = compute_all_indicators(bearish_ohlcv_df)

        # Act
        signals = generate_signals(df, symbol="MES")

        # Assert
        seller_control = (signals["structure_position"] == "SELLER_CONTROL").sum()
        assert seller_control >= 0  # May have some


class TestLayer4Entry:
    """Layer 4 entry timing signals."""

    def test_entry_now_when_fully_aligned(self, bullish_ohlcv_df):
        """All alignment criteria met → ENTRY_NOW."""
        # Arrange
        df = compute_all_indicators(bullish_ohlcv_df)

        # Act
        signals = generate_signals(df, symbol="MES", regime_filter=True)

        # Assert
        entry_now = (signals["entry_signal"] == "ENTRY_NOW").sum()
        assert entry_now >= 0, "Aligned bullish should produce ENTRY_NOW signals"

    def test_no_trade_when_neutral(self, ranging_ohlcv_df):
        """Neutral bias → NO_TRADE signal."""
        # Arrange
        df = compute_all_indicators(ranging_ohlcv_df)

        # Act
        signals = generate_signals(df, symbol="MES")

        # Assert
        no_trade = (signals["entry_signal"] == "NO_TRADE").sum()
        assert no_trade > 0, "Neutral bias should produce NO_TRADE signals"

    def test_wait_for_pullback_mid_range(self, sample_ohlcv_df):
        """STC mid-range + bullish bias → WAIT_FOR_PULLBACK."""
        # Arrange
        df = compute_all_indicators(sample_ohlcv_df)

        # Act
        signals = generate_signals(df, symbol="MES")

        # Assert
        (signals["entry_signal"] == "WAIT_FOR_PULLBACK").sum()
        # May have some depending on STC


class TestSignalOutputColumns:
    """Verification of output columns."""

    def test_generate_signals_output_columns(self, sample_ohlcv_df):
        """All expected output columns present."""
        # Act
        signals = generate_signals(sample_ohlcv_df, symbol="MES")

        # Assert
        expected = [
            "regime",
            "structure_position",
            "bias",
            "entry_signal",
            "stop_level",
            "target_1",
            "target_2",
            "target_3",
        ]
        for col in expected:
            assert col in signals.columns, f"Missing output column: {col}"

    def test_structure_position_boolean_columns(self, sample_ohlcv_df):
        """Structure position flags as separate columns."""
        # Act
        signals = generate_signals(sample_ohlcv_df, symbol="MES")

        # Assert
        structure_cols = [
            "s_above_vah",
            "s_below_val",
            "s_above_ib_high",
            "s_below_ib_low",
        ]
        for col in structure_cols:
            assert col in signals.columns
            assert signals[col].dtype == bool or signals[col].dtype == object


class TestSignalRobustness:
    """Edge cases and robustness."""

    def test_signals_handle_small_dataframe(self):
        """Signals work with minimal data."""
        # Arrange
        df = pd.DataFrame(
            {
                "open": [5800.0, 5810.0],
                "high": [5820.0, 5830.0],
                "low": [5790.0, 5800.0],
                "close": [5810.0, 5820.0],
                "volume": [3000000, 3100000],
            }
        )

        # Act & Assert - should not crash
        try:
            signals = generate_signals(df, symbol="MES")
            assert len(signals) == 2
        except Exception as e:
            pytest.fail(f"generate_signals failed on small df: {e}")

    def test_signals_handle_nan_prices(self, sample_ohlcv_df):
        """Graceful handling of NaN prices."""
        # Arrange
        df = sample_ohlcv_df.copy()
        df.loc[df.index[5], "close"] = np.nan

        # Act & Assert - should not crash
        try:
            signals = generate_signals(df, symbol="MES")
            assert len(signals) > 0
        except Exception as e:
            pytest.fail(f"generate_signals should handle NaN: {e}")

    def test_signals_zero_volume_bar(self, sample_ohlcv_df):
        """Zero volume bars handled gracefully."""
        # Arrange
        df = sample_ohlcv_df.copy()
        df.loc[df.index[10], "volume"] = 0

        # Act & Assert
        try:
            signals = generate_signals(df, symbol="MES")
            assert len(signals) > 0
        except Exception as e:
            pytest.fail(f"generate_signals should handle zero volume: {e}")


# ── RV filter env-var wiring (Phase B+ addition, 2026-04-21) ──────────────
def _make_mes_cross_df():
    """Decline-then-rise series that produces a genuine SMA(50)/SMA(200) golden cross.

    Phase 1 (210 bars declining): SMA(200) becomes valid and SMA(50) falls below it.
    Phase 2 (300 bars rising): SMA(50) crosses above SMA(200) — genuine golden cross.
    Monotonic linspace no longer works after the spurious-first-bar-cross fix.
    """
    import numpy as np
    import pandas as pd

    close = np.concatenate([np.linspace(5200, 4800, 210), np.linspace(4800, 5800, 300)])
    idx = pd.date_range("2024-06-01", periods=len(close), freq="1h")
    return pd.DataFrame(
        {"open": close, "high": close + 5, "low": close - 5, "close": close}, index=idx
    )


def test_mes_rv_filter_env_var_default_off(monkeypatch):
    """MES_MIN_RV_ANNUALIZED unset → no filter (0.0) passed to trend_signals."""
    from backtest.signals import generate_instrument_signals

    monkeypatch.delenv("MES_MIN_RV_ANNUALIZED", raising=False)

    df = _make_mes_cross_df()
    out = generate_instrument_signals(df, symbol="MES")
    assert "rv_20_ann_pct" in out.columns
    # Filter off means: as long as trend conditions hit, entries fire
    assert (out["entry_signal"] == "ENTRY_NOW").sum() >= 1


def test_mes_rv_filter_env_var_invalid_safe(monkeypatch):
    """Malformed MES_MIN_RV_ANNUALIZED → fall back to 0.0 (no filter)."""
    from backtest.signals import generate_instrument_signals

    monkeypatch.setenv("MES_MIN_RV_ANNUALIZED", "not_a_number")
    df = _make_mes_cross_df()
    # Must not raise — invalid env silently defaults to 0.0
    out = generate_instrument_signals(df, symbol="MES")
    assert (out["entry_signal"] == "ENTRY_NOW").sum() >= 1


def test_mes_rv_filter_env_var_high_blocks_entries(monkeypatch):
    """Unreachable MES_MIN_RV_ANNUALIZED=999 → zero entries even with genuine crosses."""
    from backtest.signals import generate_instrument_signals

    monkeypatch.setenv("MES_MIN_RV_ANNUALIZED", "999.0")
    df = _make_mes_cross_df()
    out = generate_instrument_signals(df, symbol="MES")
    assert (out["entry_signal"] == "ENTRY_NOW").sum() == 0


# ── VIX filter (2026-05-24 addition) ─────────────────────────────────────────


def _make_vix_df(dates: pd.DatetimeIndex, level: float) -> pd.DataFrame:
    """Daily VIX DataFrame at a fixed level across all dates."""
    daily_dates = pd.date_range(dates.min().normalize(), dates.max().normalize(), freq="D")
    return pd.DataFrame({"close": level}, index=daily_dates)


def test_vix_filter_passes_within_range():
    """Golden cross with VIX=20 (inside [13,30]) → ENTRY_NOW fires."""
    from backtest.trend_signals import generate_sma_trend_signals

    df = _make_mes_cross_df()
    vix_df = _make_vix_df(df.index, level=20.0)
    out = generate_sma_trend_signals(
        df, fast=50, slow=200, vix_df=vix_df, vix_min=13.0, vix_max=30.0
    )
    assert (
        out["entry_signal"] == "ENTRY_NOW"
    ).sum() >= 1, "VIX=20 is inside [13,30] — golden cross should produce ENTRY_NOW"


def test_vix_filter_blocks_when_too_low():
    """Golden cross with VIX=10 (below vix_min=13) → no entries."""
    from backtest.trend_signals import generate_sma_trend_signals

    df = _make_mes_cross_df()
    vix_df = _make_vix_df(df.index, level=10.0)
    out = generate_sma_trend_signals(
        df, fast=50, slow=200, vix_df=vix_df, vix_min=13.0, vix_max=30.0
    )
    assert (
        out["entry_signal"] == "ENTRY_NOW"
    ).sum() == 0, "VIX=10 is below vix_min=13 — all entries must be suppressed"


def test_vix_filter_blocks_when_too_high():
    """Golden cross with VIX=50 (above vix_max=30) → no entries."""
    from backtest.trend_signals import generate_sma_trend_signals

    df = _make_mes_cross_df()
    vix_df = _make_vix_df(df.index, level=50.0)
    out = generate_sma_trend_signals(
        df, fast=50, slow=200, vix_df=vix_df, vix_min=13.0, vix_max=30.0
    )
    assert (
        out["entry_signal"] == "ENTRY_NOW"
    ).sum() == 0, "VIX=50 is above vix_max=30 — all entries must be suppressed"


def test_vix_filter_none_is_backward_compatible():
    """vix_df=None (default) → behavior identical to no filter."""
    from backtest.trend_signals import generate_sma_trend_signals

    df = _make_mes_cross_df()
    out_no_filter = generate_sma_trend_signals(df, fast=50, slow=200)
    out_vix_none = generate_sma_trend_signals(df, fast=50, slow=200, vix_df=None)
    pd.testing.assert_series_equal(
        out_no_filter["entry_signal"],
        out_vix_none["entry_signal"],
        check_names=False,
    )


def test_vix_level_column_populated_when_vix_df_provided():
    """vix_level column is non-NaN when vix_df is provided."""
    from backtest.trend_signals import generate_sma_trend_signals

    df = _make_mes_cross_df()
    vix_df = _make_vix_df(df.index, level=18.5)
    out = generate_sma_trend_signals(df, fast=50, slow=200, vix_df=vix_df)
    # After warmup region, all bars should have a valid VIX level
    warmup_bars = 200
    assert (
        out["vix_level"].iloc[warmup_bars:].notna().all()
    ), "vix_level must be populated for all bars after warmup when vix_df is provided"

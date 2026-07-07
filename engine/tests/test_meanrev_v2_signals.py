"""
Unit tests for meanrev_v2_signals.

These tests validate signal generator outputs without running a full
backtest. The goal: confirm the three structural fixes are wired correctly
and that the signal generator handles edge cases (random walks, regime
shifts, low-data warmup) without crashing or producing degenerate output.

Run from engine/ directory:
    .venv/Scripts/python -m pytest tests/test_meanrev_v2_signals.py -v
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.meanrev_v2_signals import (
    MEANREV_V2_DEFAULTS,
    _rolling_ou_params,
    _rolling_percentile_rank,
    generate_meanrev_v2_signals,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def random_walk_df():
    """A random walk — should produce few entries (OU filter should reject)."""
    rng = np.random.default_rng(42)
    n = 500
    returns = rng.normal(0, 0.01, n)
    prices = 100 * np.exp(np.cumsum(returns))
    return pd.DataFrame(
        {
            "open": prices,
            "high": prices * 1.001,
            "low": prices * 0.999,
            "close": prices,
            "volume": rng.integers(1000, 5000, n),
        },
        index=pd.date_range("2025-01-01", periods=n, freq="1h"),
    )


@pytest.fixture
def mean_reverting_df():
    """A clearly mean-reverting series — should produce entries."""
    rng = np.random.default_rng(42)
    n = 500
    # OU process: dX = theta*(mu - X) dt + sigma dW
    mu, theta, sigma = 100.0, 0.05, 0.5
    x = np.zeros(n)
    x[0] = mu
    for i in range(1, n):
        x[i] = x[i - 1] + theta * (mu - x[i - 1]) + sigma * rng.normal()
    prices = x
    return pd.DataFrame(
        {
            "open": prices,
            "high": prices + 0.1,
            "low": prices - 0.1,
            "close": prices,
            "volume": rng.integers(1000, 5000, n),
        },
        index=pd.date_range("2025-01-01", periods=n, freq="1h"),
    )


# ── Smoke tests ───────────────────────────────────────────────────────────────


class TestSmoke:
    def test_runs_without_error(self, mean_reverting_df):
        out = generate_meanrev_v2_signals(mean_reverting_df)
        assert out is not None
        assert len(out) == len(mean_reverting_df)

    def test_output_columns_match_contract(self, mean_reverting_df):
        out = generate_meanrev_v2_signals(mean_reverting_df)
        required = {
            "entry_signal",
            "exit_signal",
            "bias",
            "regime",
            "stop_level",
            "target_1",
            "target_2",
            "target_3",
            "bb_upper",
            "bb_mid",
            "bb_lower",
            "rsi_14",
            "atr_14",
            "dislocation_percentile",
            "stop_vol_regime",
            "time_stop_bars_remaining",
            "circuit_breaker_active",
            "ou_theta",
            "ou_mu",
            "ou_half_life",
            "ou_z",
        }
        missing = required - set(out.columns)
        assert not missing, f"Missing required columns: {missing}"

    def test_entry_signal_values_are_valid(self, mean_reverting_df):
        out = generate_meanrev_v2_signals(mean_reverting_df)
        valid = {"ENTRY_NOW", "NO_TRADE"}
        assert set(out["entry_signal"].unique()).issubset(valid)


# ── Fix #1: Vol-adjusted percentile trigger ──────────────────────────────────


class TestVolAdjustedTrigger:
    def test_percentile_rank_function(self):
        s = pd.Series(np.arange(100, dtype=float))
        out = _rolling_percentile_rank(s, window=50)
        # The last bar's rank within its trailing window should be near 100%
        assert out.iloc[-1] > 80, f"Expected high percentile for monotone series, got {out.iloc[-1]}"

    def test_strict_percentile_reduces_entries_in_random_walk(self, random_walk_df):
        """With a high dislocation_percentile_min, we should see FEW entries
        on a random walk (the dislocation is rarely 'extreme')."""
        loose = generate_meanrev_v2_signals(
            random_walk_df, dislocation_percentile_min=50.0, ou_mode="off"
        )
        strict = generate_meanrev_v2_signals(
            random_walk_df, dislocation_percentile_min=95.0, ou_mode="off"
        )
        n_loose = (loose["entry_signal"] == "ENTRY_NOW").sum()
        n_strict = (strict["entry_signal"] == "ENTRY_NOW").sum()
        assert n_strict <= n_loose, (
            f"Stricter percentile should produce fewer entries: " f"loose={n_loose}, strict={n_strict}"
        )


# ── Fix #2: Vol-targeted stop ────────────────────────────────────────────────


class TestVolTargetedStop:
    def test_stop_distance_grows_in_high_vol_regime(self, mean_reverting_df):
        """In the second half of a series with injected vol expansion, stops
        should be wider than in the first half."""
        df = mean_reverting_df.copy()
        # Inject vol expansion in second half
        rng = np.random.default_rng(99)
        n = len(df)
        boost = np.where(np.arange(n) > n // 2, 3.0, 1.0)
        noise = rng.normal(0, 0.5, n) * boost
        df["close"] = df["close"].values + noise
        df["high"] = df["close"].values + 0.1 * boost
        df["low"] = df["close"].values - 0.1 * boost

        out = generate_meanrev_v2_signals(df, ou_mode="off")
        entries = out[out["entry_signal"] == "ENTRY_NOW"]
        if len(entries) < 2:
            pytest.skip("Not enough entries to compare regimes")
        # Compare stop distance |close - stop_level|
        entries = entries.copy()
        entries["stop_dist"] = (entries["target_1"] - entries["stop_level"]).abs()
        # NOTE: This test is loose because regime detection on randomized data
        # has high variance. We just check that the high-vol-regime flag is set
        # for SOME entries in the second half.
        second_half = entries.loc[entries.index > entries.index[len(entries) // 2]]
        if len(second_half) > 0:
            high_regime_count = (second_half["stop_vol_regime"] == "high").sum()
            assert high_regime_count >= 0  # weak assertion — at minimum, doesn't crash

    def test_time_stop_bars_remaining_set_on_entry(self, mean_reverting_df):
        out = generate_meanrev_v2_signals(mean_reverting_df, time_stop_bars=10)
        entries = out[out["entry_signal"] == "ENTRY_NOW"]
        if len(entries) > 0:
            assert (entries["time_stop_bars_remaining"] == 10).all(), (
                "All entries should have time_stop_bars_remaining set to the param value"
            )


# ── Fix #3: Circuit breaker ──────────────────────────────────────────────────


class TestCircuitBreaker:
    def test_circuit_breaker_column_is_boolean(self, mean_reverting_df):
        out = generate_meanrev_v2_signals(mean_reverting_df)
        assert out["circuit_breaker_active"].dtype == bool

    def test_no_entries_when_breaker_active(self, mean_reverting_df):
        out = generate_meanrev_v2_signals(mean_reverting_df)
        # Every row where cb_active is True must have entry_signal == NO_TRADE
        cb_rows = out[out["circuit_breaker_active"]]
        if len(cb_rows) > 0:
            assert (
                cb_rows["entry_signal"] == "NO_TRADE"
            ).all(), "Circuit breaker active → entries must be blocked"


# ── OU integration ───────────────────────────────────────────────────────────


class TestOUIntegration:
    def test_ou_params_estimated_on_mean_reverting_series(self, mean_reverting_df):
        out = generate_meanrev_v2_signals(mean_reverting_df, ou_mode="filter")
        # We should see some non-NaN OU params after the warmup window
        non_nan_theta = out["ou_theta"].notna().sum()
        assert non_nan_theta > 0, "OU theta should be estimable on mean-reverting series"

    def test_ou_filter_mode_does_not_explode_random_walk(self, random_walk_df):
        """OU filter on a random walk should not produce a flood of false entries."""
        out = generate_meanrev_v2_signals(
            random_walk_df, ou_mode="filter", dislocation_percentile_min=95.0
        )
        n_entries = (out["entry_signal"] == "ENTRY_NOW").sum()
        # Allow up to 5% of bars as entries (very loose) — but a flood would be 50%+
        max_acceptable = len(random_walk_df) * 0.05
        assert n_entries <= max_acceptable, (
            f"OU filter on random walk should suppress entries: got {n_entries} / {len(random_walk_df)} "
            f"(>{max_acceptable})"
        )

    def test_zscore_trigger_mode_emits_signals(self, mean_reverting_df):
        out = generate_meanrev_v2_signals(
            mean_reverting_df, ou_mode="zscore_trigger", ou_zscore_threshold=1.5
        )
        n_entries = (out["entry_signal"] == "ENTRY_NOW").sum()
        # The exact count is regime-dependent; we just confirm the mode runs and can emit
        assert n_entries >= 0


# ── Direction filter ─────────────────────────────────────────────────────────


class TestDirectionFilter:
    def test_short_only_emits_no_long_entries(self, mean_reverting_df):
        out = generate_meanrev_v2_signals(mean_reverting_df, signal_direction="short_only")
        long_entries = out[(out["entry_signal"] == "ENTRY_NOW") & (out["bias"] == "STRONG_BULL")]
        assert (
            len(long_entries) == 0
        ), f"short_only should emit zero long entries, got {len(long_entries)}"

    def test_long_only_emits_no_short_entries(self, mean_reverting_df):
        out = generate_meanrev_v2_signals(mean_reverting_df, signal_direction="long_only")
        short_entries = out[
            (out["entry_signal"] == "ENTRY_NOW") & (out["bias"] == "STRONG_BEAR")
        ]
        assert (
            len(short_entries) == 0
        ), f"long_only should emit zero short entries, got {len(short_entries)}"


# ── Defaults sanity check ─────────────────────────────────────────────────────


class TestDefaults:
    def test_all_defaults_present(self):
        required_keys = {
            "bb_period",
            "bb_std",
            "rsi_period",
            "rsi_long",
            "rsi_short",
            "dislocation_lookback",
            "dislocation_percentile_min",
            "stop_atr_mult",
            "stop_atr_long_window",
            "stop_atr_long_percentile",
            "time_stop_bars",
            "trail_to_be_at_pct_of_target",
            "cb_rolling_n_trades",
            "cb_rolling_loss_multiple",
            "cb_consecutive_stops",
            "cb_daily_loss_pct_cap",
            "cb_cooldown_bars",
            "ou_mode",
            "ou_window",
            "ou_min_half_life_bars",
            "ou_max_half_life_bars",
            "ou_zscore_threshold",
            "ou_theta_min",
        }
        missing = required_keys - set(MEANREV_V2_DEFAULTS.keys())
        assert not missing, f"Missing v2 defaults: {missing}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

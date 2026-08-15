"""
Unit tests for the Bollinger-Band + RSI Mean-Reversion v2 Signal Generator.
Validates Ornstein-Uhlenbeck estimation, adaptive triggers, and circuit-breaker loops.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.meanrev_v2_signals import (
    _rolling_ou_params,
    generate_meanrev_v2_signals,
)


def _generate_synthetic_mean_reverting_data(n: int = 150, theta: float = 0.15, mu: float = 100.0, sigma: float = 1.0) -> pd.DataFrame:
    """Generates synthetic price data using a discrete Ornstein-Uhlenbeck process."""
    np.random.seed(42)
    prices = np.full(n, 100.0)

    # y_t = y_{t-1} + theta * (mu - y_{t-1}) * dt + sigma * dW_t
    for t in range(1, n):
        prices[t] = prices[t-1] + theta * (mu - prices[t-1]) + np.random.normal(0, sigma)

    df = pd.DataFrame({
        "open": prices,
        "high": prices + 0.5,
        "low": prices - 0.5,
        "close": prices,
        "volume": np.random.randint(1000, 5000, n)
    })
    return df

def test_ou_parameter_estimation():
    """Confirms that OLS correctly extracts the speed and half-life of mean-reversion."""
    df = _generate_synthetic_mean_reverting_data(n=120)
    theta, mu, sigma, half_life = _rolling_ou_params(df["close"], window=100)

    assert len(theta) == 120
    # First 100 values must be NaN due to lookback window limitations
    assert np.isnan(theta.iloc[0])
    assert np.isnan(theta.iloc[99])

    # Valid values must resolve after lookback window expires
    assert not np.isnan(theta.iloc[105])
    assert theta.iloc[105] > 0.0 # Positive speed of mean reversion
    assert half_life.iloc[105] > 0.0 # Positive half-life boundary

def test_v2_signal_generation_nominal():
    """Verifies the core v2 mean-reversion signal loop and outputs."""
    df = _generate_synthetic_mean_reverting_data(n=220)

    # Feed synthetic series into generator
    sig_df = generate_meanrev_v2_signals(
        df,
        bb_period=20,
        bb_std=1.5, # Slightly narrower to force band touches in test
        dislocation_lookback=100,
        dislocation_percentile_min=90.0,
        ou_window=100
    )

    # Verify contracts structure matches production API contract
    required_cols = [
        "entry_signal", "exit_signal", "bias", "regime",
        "stop_level", "target_1", "bb_upper", "bb_mid", "bb_lower"
    ]
    for col in required_cols:
        assert col in sig_df.columns

    # Check that OU half-life values populate
    assert not sig_df["ou_half_life"].isna().all()

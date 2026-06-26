"""End-to-end smoke of the funnel driver on a real generator.

These tests do NOT assert a PASS verdict (synthetic data carries no edge). They
assert the driver runs the full path without error and returns the contract the
orchestrator depends on: smoke -> (bool, dict); gauntlet -> gate dict carrying the
global-trial DSR + PBO wiring.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.factory.funnel import (
    robustness_gauntlet,
    smoke_test,
)
from backtest.factory.strategy_card import StrategyCard


def _intraday(
    start: str = "2024-01-01", end: str = "2025-04-01", freq: str = "4h", seed: int = 7
) -> pd.DataFrame:
    """Span real calendar time (so >=4 WFO windows form) at a coarse intraday freq
    (so the event-loop backtester stays fast)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, end, freq=freq, tz="America/New_York")
    n = len(idx)
    drift = np.linspace(0, 8, n)
    noise = np.cumsum(rng.normal(0, 0.4, n))
    close = 100 + drift + noise
    high = close + np.abs(rng.normal(0, 0.3, n))
    low = close - np.abs(rng.normal(0, 0.3, n))
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close}, index=idx)


def _thin(months: int = 2, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = months * 120
    idx = pd.date_range("2024-01-01", periods=n, freq="4h", tz="America/New_York")
    close = 100 + np.cumsum(rng.normal(0, 0.4, n))
    return pd.DataFrame(
        {"open": close, "high": close + 0.3, "low": close - 0.3, "close": close}, index=idx
    )


def _donchian_card() -> StrategyCard:
    return StrategyCard(
        name="donchian_breakout",
        family="breakout",
        signal_ref="backtest.donchian_signals:generate_donchian_signals",
        entry="close breaks N-bar high",
        exit="opposite channel / ATR trail",
        economic_rationale="Trend persistence: a fresh N-bar breakout reflects genuine "
        "order-flow imbalance that tends to continue over the next bars.",
        native_instruments=["MES"],
        native_timeframes=["1h"],
        default_params={"lookback_entry": 20, "lookback_exit": 10},
        param_grid={"lookback_entry": [20, 40], "lookback_exit": [10, 20]},
    )


def test_smoke_returns_bool_and_metrics():
    survives, metrics = smoke_test(_donchian_card(), _intraday(), symbol="MES", multiplier=5.0)
    assert isinstance(survives, bool)
    assert metrics["stage"] == "smoke"
    assert "pre_sharpe" in metrics and "pre_pf" in metrics
    # if it clears the pre-cost floor, the post-cost fields must be present
    if survives or metrics.get("post_cost_pf") is not None:
        assert "post_cost_pf" in metrics


def test_gauntlet_runs_full_path_with_global_wiring():
    """Real end-to-end: enough calendar span that >=4 windows form, so DSR + PBO
    actually compute (not the insufficient-data early-out)."""
    gate = robustness_gauntlet(
        _donchian_card(),
        _intraday(),
        symbol="MES",
        multiplier=5.0,
        global_trial_count=250,
    )
    assert isinstance(gate, dict)
    # Must reach the full gate path, NOT the insufficient-data early-out.
    assert "reason" not in gate, f"expected full gate, got early-out: {gate.get('reason')}"
    assert "dsr_global" in gate
    assert 0.0 <= gate["dsr_global"] <= 1.0
    assert gate["global_trial_count"] == 250
    assert gate["n_grid_combos"] == 4
    # >=4 windows + 4 combos -> PBO must have computed to a probability.
    assert gate["pbo"] is not None and 0.0 <= gate["pbo"] <= 1.0


def test_gauntlet_handles_thin_data_gracefully():
    gate = robustness_gauntlet(
        _donchian_card(), _thin(months=2), symbol="MES", multiplier=5.0, global_trial_count=10
    )
    assert gate.get("verdict") == "FAIL"
    assert "reason" in gate

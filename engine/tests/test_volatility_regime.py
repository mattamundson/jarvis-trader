from __future__ import annotations

import pandas as pd

from analysis.volatility_regime import (
    add_forward_outcomes,
    build_regime_frame,
    classify_regime,
    classify_term_state,
    prepare_price_frame,
    summarize_by_regime,
)


def _price_df(days: int = 90, start: float = 100.0, step: float = 1.0) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=days, freq="B")
    closes = [start + i * step for i in range(days)]
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": 1_000,
        }
    )


def test_prepare_price_frame_normalizes_dates_and_returns() -> None:
    frame = prepare_price_frame(_price_df(5), symbol="SPY")
    assert list(frame.columns)[:3] == ["symbol", "close", "log_return"]
    assert frame["symbol"].iloc[0] == "SPY"
    assert frame.index.is_monotonic_increasing
    assert pd.isna(frame["log_return"].iloc[0])
    assert frame["log_return"].iloc[1] > 0


def test_term_state_classification() -> None:
    assert classify_term_state(0.02) == "contango"
    assert classify_term_state(-0.02) == "backwardation"
    assert classify_term_state(0.0) == "flat"
    assert classify_term_state(None) == "unknown"


def test_crash_risk_regime_from_backwardation_downtrend() -> None:
    row = pd.Series(
        {
            "trend_state": "trend_down",
            "rv_20d": 0.30,
            "vix_percentile": 0.75,
            "term_state": "backwardation",
            "iv_rv_spread": 0.05,
        }
    )
    assert classify_regime(row) == "crash_risk"


def test_premium_cheap_trend_up_regime() -> None:
    row = pd.Series(
        {
            "trend_state": "trend_up",
            "rv_20d": 0.15,
            "vix_percentile": 0.35,
            "term_state": "contango",
            "iv_rv_spread": -0.04,
        }
    )
    assert classify_regime(row) == "premium_cheap_trend_up"


def test_forward_outcomes_are_forward_not_backward() -> None:
    frame = prepare_price_frame(_price_df(10, start=100.0, step=1.0), symbol="SPY")
    frame = add_forward_outcomes(frame)
    first = frame.iloc[0]
    assert round(first["fwd_return_1d"], 6) == 0.01
    assert round(first["fwd_return_3d"], 6) == 0.03
    assert round(first["fwd_return_5d"], 6) == 0.05


def test_build_regime_frame_and_summary_with_vix_context() -> None:
    price = _price_df(120, start=100.0, step=0.5)
    dates = pd.date_range("2026-01-01", periods=120, freq="B")
    vix = pd.DataFrame({"date": dates, "close": [15 + (i % 20) * 0.2 for i in range(120)]})
    vix3m = pd.DataFrame({"date": dates, "close": [18 + (i % 20) * 0.1 for i in range(120)]})

    frame = build_regime_frame(price, symbol="SPY", vix=vix, vix3m=vix3m)
    assert "regime" in frame.columns
    assert "iv_rv_spread" in frame.columns
    assert "term_state" in frame.columns
    summary = summarize_by_regime(frame)
    assert {"regime", "n_days"}.issubset(summary.columns)
    assert int(summary["n_days"].sum()) == len(frame)

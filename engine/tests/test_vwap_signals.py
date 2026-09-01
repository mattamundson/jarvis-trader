"""
Tests for engine/backtest/vwap_signals.py.
All DataFrames are synthetic and stay offline.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.vwap_signals import generate_vwap_signals


def _bars(values: list[tuple[str, float]], tz: str = "America/New_York") -> pd.DataFrame:
    records = []
    for ts, price in values:
        records.append(
            {
                "timestamp": pd.Timestamp(ts, tz=tz),
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 1.0,
            }
        )
    return pd.DataFrame(records).set_index("timestamp")


def test_vwap_is_not_populated_before_rth_open():
    """Premarket Globex rows must not receive an RTH-anchored session VWAP."""
    df = _bars(
        [
            ("2026-01-05 08:00:00", 90.0),
            ("2026-01-05 08:30:00", 95.0),
            ("2026-01-05 09:30:00", 100.0),
            ("2026-01-05 09:35:00", 110.0),
            ("2026-01-05 10:00:00", 120.0),
            ("2026-01-05 10:30:00", 130.0),
            ("2026-01-05 14:30:00", 140.0),
            ("2026-01-05 15:00:00", 150.0),
        ]
    )

    result = generate_vwap_signals(df, atr_period=2, require_reversal_bar=False)

    assert result.iloc[0]["vwap_signal"] == ""
    assert result.iloc[1]["vwap_signal"] == ""
    assert np.isnan(result.iloc[0]["vwap"])
    assert np.isnan(result.iloc[1]["vwap"])
    assert result.iloc[2]["vwap"] == pytest.approx(100.0)


def test_vwap_resets_once_on_first_rth_bar_not_every_9xx_bar():
    """Sub-hour 09:xx RTH rows must build one cumulative session VWAP."""
    df = _bars(
        [
            ("2026-01-05 09:30:00", 100.0),
            ("2026-01-05 09:35:00", 110.0),
            ("2026-01-05 09:40:00", 120.0),
            ("2026-01-05 09:45:00", 130.0),
            ("2026-01-05 10:00:00", 140.0),
            ("2026-01-05 10:05:00", 150.0),
            ("2026-01-05 10:10:00", 160.0),
        ]
    )

    result = generate_vwap_signals(df, atr_period=2, require_reversal_bar=False)

    assert result.iloc[0]["vwap"] == pytest.approx(100.0)
    assert result.iloc[1]["vwap"] == pytest.approx(105.0)
    assert result.iloc[2]["vwap"] == pytest.approx(110.0)

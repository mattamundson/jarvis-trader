"""Tests for causal Opening Range / Initial Balance reference implementation."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.studies.opening_range_causal import (
    compute_initial_balance_causal,
    compute_opening_range_causal,
)


def _fixture() -> pd.DataFrame:
    index = pd.DatetimeIndex(
        [
            "2026-08-31 08:00",
            "2026-08-31 09:30",
            "2026-08-31 10:00",
            "2026-08-31 10:30",
            "2026-08-31 10:35",
            "2026-08-31 10:40",
        ]
    )
    return pd.DataFrame(
        {
            "high": [100.0, 101.0, 105.0, 104.0, 106.0, 107.0],
            "low": [99.0, 100.0, 98.0, 102.0, 103.0, 104.0],
            "close": [99.5, 100.5, 104.0, 103.0, 105.5, 106.5],
        },
        index=index,
    )


def test_initial_balance_never_backfills_completed_level_to_premarket() -> None:
    result = compute_initial_balance_causal(_fixture())
    premarket = result.loc[pd.Timestamp("2026-08-31 08:00")]

    assert np.isnan(premarket["range_high"])
    assert np.isnan(premarket["range_low"])
    assert np.isnan(premarket["range_high_developing"])
    assert not premarket["range_complete"]


def test_initial_balance_exposes_only_developing_values_during_capture_window() -> None:
    result = compute_initial_balance_causal(_fixture())

    first = result.loc[pd.Timestamp("2026-08-31 09:30")]
    second = result.loc[pd.Timestamp("2026-08-31 10:00")]
    assert first["range_high_developing"] == 101.0
    assert first["range_low_developing"] == 100.0
    assert second["range_high_developing"] == 105.0
    assert second["range_low_developing"] == 98.0
    assert np.isnan(first["range_high"])
    assert np.isnan(second["range_low"])


def test_completed_initial_balance_first_appears_at_range_end() -> None:
    result = compute_initial_balance_causal(_fixture())
    completed = result.loc[pd.Timestamp("2026-08-31 10:30")]

    assert completed["range_complete"]
    assert completed["range_high"] == 105.0
    assert completed["range_low"] == 98.0
    assert completed["range_mid"] == 101.5


def test_fresh_breakout_fires_once_after_range_is_complete() -> None:
    result = compute_initial_balance_causal(_fixture())

    assert not result.loc[pd.Timestamp("2026-08-31 10:30"), "range_high_fresh_breakout"]
    assert result.loc[pd.Timestamp("2026-08-31 10:35"), "range_high_fresh_breakout"]
    assert not result.loc[pd.Timestamp("2026-08-31 10:40"), "range_high_fresh_breakout"]


def test_orb30_completes_at_1000_with_only_0930_capture_bar_in_sparse_fixture() -> None:
    result = compute_opening_range_causal(_fixture(), range_minutes=30)
    completed = result.loc[pd.Timestamp("2026-08-31 10:00")]

    assert completed["range_complete"]
    assert completed["range_high"] == 101.0
    assert completed["range_low"] == 100.0

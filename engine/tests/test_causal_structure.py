"""Tests for causal Rangefinder and delayed-confirmation Singlefinder ports."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.studies.causal_structure import rangefinder_expansion_core, singlefinder_confirmed


def test_rangefinder_core_flags_only_current_outside_bar() -> None:
    open_ = pd.Series([10.0, 10.4, 10.2, 10.8])
    high = pd.Series([11.0, 11.2, 12.0, 11.7])
    low = pd.Series([9.5, 9.8, 9.0, 10.1])
    close = pd.Series([10.6, 10.1, 11.5, 10.9])

    result = rangefinder_expansion_core(open_, high, low, close)

    assert result["range_expansion"].tolist() == [False, False, True, False]
    assert result.loc[2, "range_high"] == 12.0
    assert result.loc[2, "range_low"] == 9.0
    assert result.loc[2, "range_mid"] == 10.5
    assert result.loc[2, "direction"] == 1.0
    assert result.loc[2, "extension_1_000"] == 15.0  # high + one 3-point range


def test_rangefinder_bearish_extensions_follow_source_direction() -> None:
    open_ = pd.Series([10.0, 10.5])
    high = pd.Series([11.0, 12.0])
    low = pd.Series([9.5, 9.0])
    close = pd.Series([10.5, 9.5])

    result = rangefinder_expansion_core(open_, high, low, close)

    assert result.loc[1, "range_expansion"]
    assert result.loc[1, "direction"] == -1.0
    assert result.loc[1, "extension_1_000"] == 6.0  # low - one 3-point range


def test_singlefinder_bearish_signal_appears_only_on_confirmation_bar() -> None:
    # Candidate is conceptual bar t=1. It cannot be known until bar j=2 closes.
    high = pd.Series([10.0, 11.0, 8.0, 8.5])
    low = pd.Series([9.0, 9.5, 7.0, 7.5])

    result = singlefinder_confirmed(high, low)

    assert not result.loc[1, "bearish_single_confirmed"]
    assert result.loc[2, "bearish_single_confirmed"]
    assert result.loc[2, "bearish_zone_low"] == 8.0
    assert result.loc[2, "bearish_zone_high"] == 9.0
    assert result.loc[2, "confirmation_delay_bars"] == 1.0


def test_singlefinder_bullish_signal_appears_only_on_confirmation_bar() -> None:
    high = pd.Series([8.0, 11.0, 12.0, 12.5])
    low = pd.Series([7.0, 8.5, 9.0, 10.0])

    result = singlefinder_confirmed(high, low)

    assert not result.loc[1, "bullish_single_confirmed"]
    assert result.loc[2, "bullish_single_confirmed"]
    assert result.loc[2, "bullish_zone_low"] == 8.0
    assert result.loc[2, "bullish_zone_high"] == 9.0
    assert result.loc[2, "confirmation_delay_bars"] == 1.0


def test_singlefinder_never_backfills_zone_to_candidate_bar() -> None:
    high = pd.Series([10.0, 11.0, 8.0])
    low = pd.Series([9.0, 9.5, 7.0])

    result = singlefinder_confirmed(high, low)

    assert np.isnan(result.loc[1, "bearish_zone_low"])
    assert np.isnan(result.loc[1, "bearish_zone_high"])
    assert result.loc[2, "bearish_single_confirmed"]

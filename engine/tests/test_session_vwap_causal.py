"""Golden-vector and session-integrity tests for causal RTH VWAP."""

from __future__ import annotations

from datetime import time

import numpy as np
import pandas as pd

from backtest.studies.session_vwap_causal import compute_session_vwap_causal


def _et_index(values: list[str]) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(values).tz_localize("America/New_York")


def test_premarket_and_afterhours_are_not_vwap_or_entry_eligible() -> None:
    index = _et_index(
        [
            "2026-08-31 08:00",
            "2026-08-31 09:30",
            "2026-08-31 15:30",
            "2026-08-31 16:15",
        ]
    )
    df = pd.DataFrame(
        {"high": [100, 101, 102, 103], "low": [99, 100, 101, 102], "close": [99.5, 100.5, 101.5, 102.5], "volume": [100, 100, 100, 100]},
        index=index,
    )
    result = compute_session_vwap_causal(df)

    assert np.isnan(result.iloc[0]["session_vwap"])
    assert not result.iloc[0]["rth_eligible"]
    assert result.iloc[1]["entry_eligible"]
    assert result.iloc[2]["rth_eligible"]
    assert not result.iloc[2]["entry_eligible"]
    assert np.isnan(result.iloc[3]["session_vwap"])


def test_vwap_accumulates_across_multiple_09xx_bars_without_resetting() -> None:
    index = _et_index(["2026-08-31 09:30", "2026-08-31 09:35", "2026-08-31 09:40"])
    df = pd.DataFrame(
        {
            "high": [101.0, 103.0, 104.0],
            "low": [99.0, 101.0, 102.0],
            "close": [100.0, 102.0, 103.0],
            "volume": [100.0, 200.0, 100.0],
        },
        index=index,
    )
    result = compute_session_vwap_causal(df)

    # Typical prices are 100, 102, 103. Weighted cumulative VWAPs:
    # 100; (100*100 + 102*200)/300 = 101.333333...;
    # previous numerator + 103*100 over 400 = 101.75.
    np.testing.assert_allclose(
        result["session_vwap"].to_numpy(),
        [100.0, 101.33333333333333, 101.75],
        rtol=0,
        atol=1e-12,
    )


def test_zero_volume_bar_does_not_change_existing_vwap() -> None:
    index = _et_index(["2026-08-31 09:30", "2026-08-31 09:35"])
    df = pd.DataFrame(
        {"high": [101.0, 110.0], "low": [99.0, 108.0], "close": [100.0, 109.0], "volume": [100.0, 0.0]},
        index=index,
    )
    result = compute_session_vwap_causal(df)
    assert result.iloc[0]["session_vwap"] == 100.0
    assert result.iloc[1]["session_vwap"] == 100.0
    assert result.iloc[1]["session_cum_volume"] == 100.0


def test_first_zero_volume_rth_bar_uses_typical_price_fallback() -> None:
    index = _et_index(["2026-08-31 09:30"])
    df = pd.DataFrame(
        {"high": [103.0], "low": [100.0], "close": [102.0], "volume": [0.0]}, index=index
    )
    result = compute_session_vwap_causal(df)
    assert result.iloc[0]["session_vwap"] == 101.66666666666667
    assert result.iloc[0]["session_cum_volume"] == 0.0


def test_vwap_resets_once_on_new_session() -> None:
    index = _et_index(["2026-08-31 09:30", "2026-08-31 10:30", "2026-09-01 09:30"])
    df = pd.DataFrame(
        {"high": [101.0, 103.0, 201.0], "low": [99.0, 101.0, 199.0], "close": [100.0, 102.0, 200.0], "volume": [100.0, 100.0, 100.0]},
        index=index,
    )
    result = compute_session_vwap_causal(df)
    assert result.iloc[1]["session_vwap"] == 101.0
    assert result.iloc[2]["session_vwap"] == 200.0


def test_timezone_naive_cache_is_interpreted_as_utc_then_converted() -> None:
    # 13:30 UTC = 09:30 EDT on 2026-08-31.
    index = pd.DatetimeIndex(["2026-08-31 13:30"])
    df = pd.DataFrame(
        {"high": [101.0], "low": [99.0], "close": [100.0], "volume": [100.0]}, index=index
    )
    result = compute_session_vwap_causal(df, naive_tz="UTC")
    assert result.iloc[0]["rth_eligible"]
    assert result.iloc[0]["session_vwap"] == 100.0


def test_custom_entry_cutoff_is_enforced_independently_of_rth() -> None:
    index = _et_index(["2026-08-31 14:00", "2026-08-31 14:30"])
    df = pd.DataFrame(
        {"high": [101, 102], "low": [99, 100], "close": [100, 101], "volume": [100, 100]}, index=index
    )
    result = compute_session_vwap_causal(df, entry_cutoff=time(14, 15))
    assert result.iloc[0]["entry_eligible"]
    assert not result.iloc[1]["entry_eligible"]
    assert result.iloc[1]["rth_eligible"]

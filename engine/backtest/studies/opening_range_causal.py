"""Research-only causal Opening Range / Initial Balance implementation.

This module exists because the current production/backtest ``compute_initial_balance``
joins the completed session IB back onto premarket rows.  These helpers provide a
fail-closed point-in-time reference without modifying existing signal paths.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd


def compute_opening_range_causal(
    df: pd.DataFrame,
    *,
    range_minutes: int,
    market_open_hour: int = 9,
    market_open_minute: int = 30,
    tz: str = "America/Chicago",
) -> pd.DataFrame:
    """Compute developing and completed opening-range levels without backfill.

    Final range levels remain NaN until the first bar at or after the range end.
    During the capture window only *developing* levels are exposed. Premarket bars
    receive neither developing nor final values.
    """
    if range_minutes <= 0:
        raise ValueError("range_minutes must be positive")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("DataFrame must have a DatetimeIndex")
    required = {"high", "low", "close"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"missing required columns: {missing}")

    result = df.copy()
    local_index = result.index
    if local_index.tz is not None:
        local_index = local_index.tz_convert(tz)
    else:
        local_index = local_index.tz_localize(tz, ambiguous="NaT", nonexistent="NaT")

    session_dates = pd.Index(local_index.date)
    result["_session_date"] = session_dates
    result["range_high_developing"] = np.nan
    result["range_low_developing"] = np.nan
    result["range_high"] = np.nan
    result["range_low"] = np.nan
    result["range_complete"] = False

    for session_date in pd.unique(session_dates):
        positions = np.flatnonzero(session_dates == session_date)
        if len(positions) == 0:
            continue

        session_midnight = pd.Timestamp(session_date, tz=tz)
        market_open = session_midnight + pd.Timedelta(
            hours=market_open_hour,
            minutes=market_open_minute,
        )
        range_end = market_open + timedelta(minutes=range_minutes)
        local_times = local_index[positions]
        capture_mask = (local_times >= market_open) & (local_times < range_end)
        capture_positions = positions[capture_mask]
        if len(capture_positions) == 0:
            continue

        developing_high = -np.inf
        developing_low = np.inf
        for position in capture_positions:
            developing_high = max(developing_high, float(result.iloc[position]["high"]))
            developing_low = min(developing_low, float(result.iloc[position]["low"]))
            result.iloc[position, result.columns.get_loc("range_high_developing")] = developing_high
            result.iloc[position, result.columns.get_loc("range_low_developing")] = developing_low

        final_high = developing_high
        final_low = developing_low
        completed_positions = positions[local_times >= range_end]
        if len(completed_positions) == 0:
            continue
        result.iloc[completed_positions, result.columns.get_loc("range_high")] = final_high
        result.iloc[completed_positions, result.columns.get_loc("range_low")] = final_low
        result.iloc[completed_positions, result.columns.get_loc("range_complete")] = True

    result["range_mid"] = (result["range_high"] + result["range_low"]) / 2.0
    result["above_range_high"] = result["range_complete"] & (
        result["close"] > result["range_high"]
    )
    result["below_range_low"] = result["range_complete"] & (
        result["close"] < result["range_low"]
    )

    def _first_true(group: pd.Series) -> pd.Series:
        count = group.cumsum()
        return group & (count == 1)

    result["range_high_fresh_breakout"] = result.groupby("_session_date")[
        "above_range_high"
    ].transform(_first_true)
    result["range_low_fresh_breakout"] = result.groupby("_session_date")[
        "below_range_low"
    ].transform(_first_true)
    result.drop(columns=["_session_date"], inplace=True)
    return result


def compute_initial_balance_causal(
    df: pd.DataFrame,
    *,
    open_minutes: int = 60,
    market_open_hour: int = 9,
    market_open_minute: int = 30,
    tz: str = "America/Chicago",
) -> pd.DataFrame:
    """Convenience wrapper for the standard 60-minute Initial Balance."""
    return compute_opening_range_causal(
        df,
        range_minutes=open_minutes,
        market_open_hour=market_open_hour,
        market_open_minute=market_open_minute,
        tz=tz,
    )

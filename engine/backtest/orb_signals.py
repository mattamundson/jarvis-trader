"""
JARVIS TRADER — Opening Range Breakout (ORB) Signal Generator
==============================================================
Generates ORB signals for MES (Micro E-mini S&P 500) on 1-hour bars.

Strategy Logic:
  - Opening Range = high/low of the FIRST bar of each RTH session (09:30 ET)
  - LONG entry  when price closes above OR High with volume confirmation
  - SHORT entry when price closes below OR Low with volume confirmation
  - Stop loss: opposite side of OR (for longs: OR Low; for shorts: OR High)
  - T1: 1× OR range extension (entry + range)
  - T2: 2× OR range extension
  - No new entries in the final hour (15:00–16:00 ET) to avoid closing volatility
  - Regime filter: block entries in EXHAUSTED or COMPRESSION regimes (optional)

Why ORB for MES:
  S&P 500 exhibits directional momentum in the first 1-2 hours after open
  as institutional participants establish their positions. The opening range
  captures this: a breakout above the first-hour high tends to continue
  (at least to T1) with higher probability than STC trend signals which
  attempt to capture sustained multi-hour trends (for which MES WFE=0.00).

Output columns added to DataFrame:
  - or_high        : OR High for this session
  - or_low         : OR Low for this session
  - or_range       : or_high - or_low
  - is_or_bar      : True for the first bar of each RTH session
  - ORB_signal     : "LONG_ENTRY" | "SHORT_ENTRY" | ""
  - orb_stop       : Stop price for the entry
  - orb_target_1   : T1 price (1× OR range)
  - orb_target_2   : T2 price (2× OR range)
  - orb_rr         : Reward:Risk ratio at T1

RTH Session detection:
  yfinance returns 1h bars with timestamps in America/New_York timezone.
  The first bar of each RTH session has hour == 9 (09:30–10:30 ET).
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("orb_signals")

# RTH session start hour (Eastern Time, 9 = 09:30–10:30 bar)
RTH_OPEN_HOUR = 9
# Block entries in the final hour before close (15:00 ET)
RTH_FINAL_HOUR = 15
# Minimum OR range as fraction of price to avoid micro-range false signals
MIN_OR_RANGE_PCT = 0.0008  # 0.08% of price (e.g., 4+ pts on MES ~5000)
# Volume multiplier: require at least 80% of 20-bar average volume on breakout bar
VOLUME_FILTER_MULTIPLIER = 0.80


def _detect_rth_open_bar(df: pd.DataFrame) -> pd.Series:
    """
    Return a boolean Series True for bars that are the first bar of an RTH session.

    Handles both timezone-aware and timezone-naive DatetimeIndex.
    Assumes index is already in or convertible to Eastern Time.
    """
    # Sprint A / B3 fix: defensive DatetimeIndex normalization prevents crash
    # when merging tz-aware IB bars with tz-naive backtest frames.
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    idx = df.index

    if hasattr(idx, "tz") and idx.tz is not None:
        eastern = idx.tz_convert("America/New_York")
    else:
        eastern = idx

    hours = eastern.hour
    # First RTH bar: hour 9 (the 09:30–10:30 bar in yfinance 1h data)
    # Also require it's not a weekday 0=Mon ... 4=Fri
    weekday = eastern.dayofweek
    is_open = (pd.Series(hours, index=df.index) == RTH_OPEN_HOUR) & (
        pd.Series(weekday, index=df.index) < 5
    )
    return is_open


def _volume_ok(df: pd.DataFrame, idx: int, multiplier: float = VOLUME_FILTER_MULTIPLIER) -> bool:
    """Check if bar volume >= multiplier × 20-bar rolling average volume."""
    if "volume" not in df.columns:
        return True  # No volume data — skip filter

    vol = df["volume"].iloc[idx]
    if vol == 0 or np.isnan(vol):
        return True  # Missing volume — pass

    window_start = max(0, idx - 20)
    avg_vol = df["volume"].iloc[window_start:idx].mean()
    if avg_vol == 0 or np.isnan(avg_vol):
        return True

    return bool(vol >= avg_vol * multiplier)


def generate_orb_signals(
    df: pd.DataFrame,
    symbol: str = "MES",
    volume_filter: bool = True,
    regime_filter: bool = False,
    min_or_range_pct: float = MIN_OR_RANGE_PCT,
) -> pd.DataFrame:
    """
    Add ORB signal columns to a 1-hour OHLCV DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        1-hour OHLCV data with DatetimeIndex in Eastern Time (or UTC).
        Required columns: open, high, low, close, volume.
    symbol : str
        Symbol name for logging.
    volume_filter : bool
        Require breakout bar volume >= 80% of 20-bar average.
    regime_filter : bool
        If True and 'regime' column is present, block entries in
        EXHAUSTED and COMPRESSION regimes.
    min_or_range_pct : float
        Minimum OR range as a fraction of close price. Micro-ranges
        (e.g. on half-session days) are skipped.

    Returns
    -------
    pd.DataFrame
        Input df with ORB signal columns added.
    """
    df = df.copy()

    # Initialise output columns
    df["or_high"] = np.nan
    df["or_low"] = np.nan
    df["or_range"] = np.nan
    df["is_or_bar"] = False
    df["ORB_signal"] = ""
    df["orb_stop"] = np.nan
    df["orb_target_1"] = np.nan
    df["orb_target_2"] = np.nan
    df["orb_rr"] = np.nan

    if df.empty or len(df) < 2:
        return df

    # Detect opening range bars
    is_or_bar = _detect_rth_open_bar(df)
    df["is_or_bar"] = is_or_bar.values

    # Detect final hour (no new entries)
    idx = df.index
    if hasattr(idx, "tz") and idx.tz is not None:
        eastern = idx.tz_convert("America/New_York")
    else:
        eastern = idx
    df["_bar_hour"] = pd.Series(eastern.hour, index=df.index).values

    # Carry forward OR High/Low from the opening bar into subsequent session bars
    current_or_high: Optional[float] = None
    current_or_low: Optional[float] = None

    for i in range(len(df)):
        if bool(is_or_bar.iloc[i]):
            # New session: record OR
            current_or_high = float(df["high"].iloc[i])
            current_or_low = float(df["low"].iloc[i])
            df.at[df.index[i], "or_high"] = current_or_high
            df.at[df.index[i], "or_low"] = current_or_low
            df.at[df.index[i], "or_range"] = current_or_high - current_or_low
        elif current_or_high is not None:
            # Carry forward
            df.at[df.index[i], "or_high"] = current_or_high
            df.at[df.index[i], "or_low"] = current_or_low
            df.at[df.index[i], "or_range"] = current_or_high - current_or_low

    # Generate signals on non-OR bars only (can't enter during the OR itself)
    for i in range(1, len(df)):
        if bool(df["is_or_bar"].iloc[i]):
            continue  # Skip OR bar itself

        or_high = df["or_high"].iloc[i]
        or_low = df["or_low"].iloc[i]

        if np.isnan(or_high) or np.isnan(or_low):
            continue  # No OR set for this session

        or_range = or_high - or_low
        bar_close = float(df["close"].iloc[i])
        bar_hour = int(df["_bar_hour"].iloc[i])

        # Skip final hour (15:00 ET)
        if bar_hour >= RTH_FINAL_HOUR:
            continue

        # Skip micro-range sessions
        if or_range < bar_close * min_or_range_pct:
            logger.debug(f"{symbol} bar {i}: OR range too small ({or_range:.2f}) — skip")
            continue

        # Regime filter (optional)
        if regime_filter and "regime" in df.columns:
            regime = str(df["regime"].iloc[i])
            if regime in ("EXHAUSTED", "COMPRESSION"):
                continue

        # Volume filter
        if volume_filter and not _volume_ok(df, i):
            continue

        # LONG: close breaks above OR High
        if bar_close > or_high:
            # Only signal once per session (first breakout)
            # Check if we've already signalled LONG today
            already_signalled = False
            for j in range(i - 1, -1, -1):
                if bool(df["is_or_bar"].iloc[j]):
                    break
                if df["ORB_signal"].iloc[j] == "LONG_ENTRY":
                    already_signalled = True
                    break
            if not already_signalled:
                stop = or_low
                t1 = or_high + or_range  # 1× extension
                t2 = or_high + 2 * or_range  # 2× extension
                risk = bar_close - stop
                reward = t1 - bar_close
                rr = reward / risk if risk > 0 else 0.0

                df.at[df.index[i], "ORB_signal"] = "LONG_ENTRY"
                df.at[df.index[i], "orb_stop"] = round(stop, 4)
                df.at[df.index[i], "orb_target_1"] = round(t1, 4)
                df.at[df.index[i], "orb_target_2"] = round(t2, 4)
                df.at[df.index[i], "orb_rr"] = round(rr, 3)

        # SHORT: close breaks below OR Low
        elif bar_close < or_low:
            already_signalled = False
            for j in range(i - 1, -1, -1):
                if bool(df["is_or_bar"].iloc[j]):
                    break
                if df["ORB_signal"].iloc[j] == "SHORT_ENTRY":
                    already_signalled = True
                    break
            if not already_signalled:
                stop = or_high
                t1 = or_low - or_range  # 1× extension down
                t2 = or_low - 2 * or_range  # 2× extension down
                risk = stop - bar_close
                reward = bar_close - t1
                rr = reward / risk if risk > 0 else 0.0

                df.at[df.index[i], "ORB_signal"] = "SHORT_ENTRY"
                df.at[df.index[i], "orb_stop"] = round(stop, 4)
                df.at[df.index[i], "orb_target_1"] = round(t1, 4)
                df.at[df.index[i], "orb_target_2"] = round(t2, 4)
                df.at[df.index[i], "orb_rr"] = round(rr, 3)

    # Drop internal helper column
    df.drop(columns=["_bar_hour"], inplace=True, errors="ignore")

    n_long = (df["ORB_signal"] == "LONG_ENTRY").sum()
    n_short = (df["ORB_signal"] == "SHORT_ENTRY").sum()
    logger.info(
        f"{symbol} ORB signals: {n_long} LONG + {n_short} SHORT = {n_long + n_short} total "
        f"over {len(df)} bars"
    )

    return df

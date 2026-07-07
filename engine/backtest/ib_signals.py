"""
JARVIS TRADER — Initial Balance Signals
Port of Corey Surles' ThinkorSwim study AA_CoreyIBv1STUDY.ts.

Source study : thinkorswim-scripts/AA_CoreyIBv1STUDY.ts
Spec         : thinkorswim-scripts/docs/corey_ib_v1.md
JARVIS signals: ib_high, ib_low, above_ib_high, below_ib_low
               (consumed by engine/backtest/signals.py::layer4_entry and
                engine/agents/pipeline.py::layer4_entry)

IB = highest high / lowest low during the first `open_minutes` of RTH each day.
Pre-market bars are excluded from IB calculation; IB levels are then carried
forward to all bars in the same trading session.
"""

from __future__ import annotations

import pandas as pd


def compute_initial_balance(
    df: pd.DataFrame,
    open_minutes: int = 60,
    market_open_hour: int = 9,
    market_open_minute: int = 30,
    tz: str = "America/Chicago",
) -> pd.DataFrame:
    """
    Compute Initial Balance levels for every bar in *df* and return *df*
    with the following columns added (or overwritten):

    ib_high                 : float  — IB high for that session (NaN until IB closes)
    ib_low                  : float  — IB low for that session (NaN until IB closes)
    ib_mid                  : float  — (ib_high + ib_low) / 2
    above_ib_high           : bool   — close > ib_high
    below_ib_low            : bool   — close < ib_low
    ib_high_fresh_breakout  : bool   — first bar where close crosses above ib_high
    ib_low_fresh_breakout   : bool   — first bar where close crosses below ib_low

    Parameters
    ----------
    df : DataFrame with a DatetimeIndex.  Must contain columns: high, low, close.
    open_minutes : Number of RTH minutes that define the Initial Balance window.
    market_open_hour, market_open_minute : Local wall-clock time of RTH open.
    tz : Timezone for the wall-clock comparison.  DataFrame index is converted
         to this tz if it is tz-aware; if tz-naive it is *assumed* to already be
         in this timezone.

    Works on any bar frequency (1-min, 5-min, etc.) — IB is the range of all
    bars whose bar-open falls within [market_open, market_open + open_minutes).
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError(
            "DataFrame must have a DatetimeIndex. "
            f"Got index type: {type(df.index).__name__}"
        )

    df = df.copy()

    # Normalise timezone so wall-clock comparisons work correctly.
    idx = df.index
    if idx.tz is not None:
        idx = idx.tz_convert(tz)
    else:
        # Assume the caller already aligned to the target tz (e.g. CSV data in CT).
        idx = idx.tz_localize(tz, ambiguous="NaT", nonexistent="NaT")

    # Session date: each bar belongs to the *trading* date whose RTH it falls in.
    # Bars before the RTH open on a given calendar date still belong to that date.
    session_date = idx.date

    # Mark bars that fall inside the IB capture window.
    bar_minutes_from_open = (idx.hour - market_open_hour) * 60 + (
        idx.minute - market_open_minute
    )
    in_ib_window = (bar_minutes_from_open >= 0) & (bar_minutes_from_open < open_minutes)

    df["_session_date"] = session_date
    df["_in_ib_window"] = in_ib_window

    # Compute per-session IB high / low from bars inside the window only.
    ib_window_df = df[df["_in_ib_window"]]
    session_ib = ib_window_df.groupby("_session_date").agg(
        _ib_high_raw=("high", "max"),
        _ib_low_raw=("low", "min"),
    )

    # Map back to every bar via session date.
    df = df.join(session_ib, on="_session_date")

    # IB levels are only valid *after* the IB window closes.  During the window
    # itself we forward-fill within the window so that callers can inspect the
    # running IB, but we deliberately leave them as NaN for the standard
    # above_ib / below_ib flags which the spec says fire post-IB only.
    #
    # Design choice: expose the final, frozen IB level for the entire session
    # (matches TOS "extends to next day open" behaviour).  Pre-IB bars get NaN.
    df["ib_high"] = df["_ib_high_raw"].where(~df["_in_ib_window"], other=float("nan"))
    df["ib_low"] = df["_ib_low_raw"].where(~df["_in_ib_window"], other=float("nan"))

    # Forward-fill within each session so post-IB bars all carry the frozen level.
    df["ib_high"] = df.groupby("_session_date")["ib_high"].transform(
        lambda s: s.ffill()
    )
    df["ib_low"] = df.groupby("_session_date")["ib_low"].transform(
        lambda s: s.ffill()
    )

    df["ib_mid"] = (df["ib_high"] + df["ib_low"]) / 2.0

    # Boolean proximity flags — meaningful only when ib_high/ib_low are not NaN.
    df["above_ib_high"] = df["close"] > df["ib_high"]
    df["below_ib_low"] = df["close"] < df["ib_low"]

    # Fresh breakout: True on the FIRST bar where the close crosses the level.
    # Uses a per-session cumulative-max approach so the flag never re-fires within
    # the same session even if price dips back and re-breaks.
    def _first_cross(group: pd.Series) -> pd.Series:
        """True only on the first bar where the boolean signal becomes True."""
        cummax = group.cumsum()
        return (cummax == 1) & group

    df["ib_high_fresh_breakout"] = df.groupby("_session_date")["above_ib_high"].transform(
        _first_cross
    )
    df["ib_low_fresh_breakout"] = df.groupby("_session_date")["below_ib_low"].transform(
        _first_cross
    )

    # Drop internal working columns.
    df.drop(
        columns=["_session_date", "_in_ib_window", "_ib_high_raw", "_ib_low_raw"],
        inplace=True,
    )

    return df

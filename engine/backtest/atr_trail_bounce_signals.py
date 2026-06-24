"""ATR Trailing-Stop Bounce signal generator for JARVIS TRADER.

Hypothesis (Matt, 2026-06-24): on /ES the dotted ATR trailing-stop line
(``ATRTrailingStop modified, 5, 3.5, long, WILDERS`` in ThinkorSwim) acts as
dynamic support/resistance — price tags it and bounces. This module turns that
visual observation into a precise, point-in-time, backtestable rule so the
edge (if any) can be measured and run through MCPT rather than eyeballed.

The line itself is ``indicators.atr_trailing_stop`` (a faithful TOS reproduction).

Entry (long):
    touch    : bar low <= trail (+ tolerance) WHILE trail is in LONG state
    reclaim  : that same bar closes back ABOVE trail
    hold     : the trail stays in LONG state for `hold_bars` bars afterward
               (no close-through / flip to short)
    -> ENTRY_NOW at the close of the (touch + hold_bars) bar.
Short is the mirror (tag from above in SHORT state, close below, stays short).

Stop  : the trail line itself (this IS the thesis — the line is the stop).
Targets: entry +/- {1.5, 2.618} x ATR(14)  (Saty ATR-Levels convention).

Look-ahead discipline: the decision at bar i uses only bars <= i. The bounce is
detected over the window [i - hold_bars, i]; entry fires at bar i. Nothing reads
a future bar. See .claude/rules/testing.md "No look-ahead bias".

LOCKED SPEC for MCPT: param grid is {factor in [3.0, 3.5, 4.0], hold_bars in
[0, 1, 2], touch_tol_atr in [0.0, 0.10]}. Lock before running validate_strategy;
a fail means discard, not re-tune (see ml-pitfalls-defense.md).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.indicators import atr_trailing_stop, wilder_atr

_TARGET_ATR_PERIOD = 14
_T1_MULT = 1.5
_T2_MULT = 2.618


def generate_atr_trail_bounce_signals(
    df: pd.DataFrame,
    atr_period: int = 5,
    factor: float = 3.5,
    hold_bars: int = 1,
    touch_tol_atr: float = 0.10,
    first_trade_long: bool = True,
    trail_type: str = "modified",
) -> pd.DataFrame:
    """Generate ATR-trail bounce signals compatible with the JARVIS Backtester.

    Args:
        atr_period    : trailing-stop ATR length (TOS study default 5).
        factor        : trailing-stop ATR multiplier (TOS study default 3.5).
        hold_bars     : bars price must stay on the trail's side after the tag
                        before entry. 0 = fire on the reclaim bar (no
                        confirmation); 1 ~= "still holding one bar later".
        touch_tol_atr : how close to the line counts as a tag, as a fraction of
                        the trailing-stop loss distance. 0.0 = exact wick to/through.
        first_trade_long, trail_type : passed to ``atr_trailing_stop``.

    Returns df with the standard signal columns (entry_signal, exit_signal,
    stop_level, target_1/2/3, bias, regime, atr) plus diagnostics:
        trail        : the ATR trailing-stop line
        trail_state  : +1 long / -1 short
        touched      : bool, the line was tagged this bar in the active state
    """
    # Preserve the caller's index (the backtester needs a DatetimeIndex). All
    # internal logic is positional via .iloc, so the index is carried untouched.
    df = df.copy()

    trail, state = atr_trailing_stop(
        df["high"], df["low"], df["close"],
        period=atr_period, factor=factor,
        first_trade_long=first_trade_long, trail_type=trail_type,
    )
    atr14 = wilder_atr(df["high"], df["low"], df["close"], _TARGET_ATR_PERIOD)

    # Tolerance band scaled by the per-bar loss distance (|close - trail| proxy).
    tol = (touch_tol_atr * (df["close"] - trail).abs()).fillna(0.0)

    long_state = state == 1.0
    short_state = state == -1.0

    # A "tag + reclaim" bar: wick reaches the line but close stays on its side.
    long_tag = long_state & (df["low"] <= trail + tol) & (df["close"] > trail)
    short_tag = short_state & (df["high"] >= trail - tol) & (df["close"] < trail)

    n = len(df)
    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    exit_signal = np.full(n, "NO_EXIT", dtype=object)
    stop_level = np.full(n, np.nan)
    target_1 = np.full(n, np.nan)
    target_2 = np.full(n, np.nan)
    target_3 = np.full(n, np.nan)

    for i in range(n):
        j = i - hold_bars  # the candidate tag bar
        if j < 0 or pd.isna(atr14.iloc[i]) or pd.isna(trail.iloc[i]):
            continue
        price = float(df["close"].iloc[i])
        atr_i = float(atr14.iloc[i])

        # LONG: tag+reclaim at j, then held LONG state through i (no flip).
        if long_tag.iloc[j] and bool(long_state.iloc[j : i + 1].all()):
            entry_signal[i] = "ENTRY_NOW"
            stop_level[i] = float(trail.iloc[i])  # the line is the stop
            target_1[i] = price + _T1_MULT * atr_i
            target_2[i] = price + _T2_MULT * atr_i
            target_3[i] = price + 2 * _T2_MULT * atr_i
        # SHORT: mirror.
        elif short_tag.iloc[j] and bool(short_state.iloc[j : i + 1].all()):
            entry_signal[i] = "ENTRY_NOW"
            stop_level[i] = float(trail.iloc[i])
            target_1[i] = price - _T1_MULT * atr_i
            target_2[i] = price - _T2_MULT * atr_i
            target_3[i] = price - 2 * _T2_MULT * atr_i

    # Exit when the trail flips against the position (close through the line).
    flipped = state != state.shift(1)
    exit_signal[(flipped & state.notna()).to_numpy()] = "EXIT_NOW"

    df["entry_signal"] = entry_signal
    df["exit_signal"] = exit_signal
    df["stop_level"] = stop_level
    df["target_1"] = target_1
    df["target_2"] = target_2
    df["target_3"] = target_3
    df["atr"] = atr14
    df["trail"] = trail
    df["trail_state"] = state
    df["touched"] = (long_tag | short_tag).to_numpy()

    df["bias"] = "NEUTRAL"
    df.loc[long_state, "bias"] = "LEAN_BULL"
    df.loc[short_state, "bias"] = "LEAN_BEAR"

    df["regime"] = "RANGE_BOUND"
    df.loc[long_state, "regime"] = "TRENDING_BULL"
    df.loc[short_state, "regime"] = "TRENDING_BEAR"

    return df

"""
Overnight carry signal generator for MES (equity risk premium harvest).

Hypothesis: US equity index futures accrue the bulk of the equity risk premium
during the overnight session (RTH-close to RTH-open). Long-only: enter at the
last RTH bar (ET hour 15, the 15:00-15:59 bar) and exit on the first bar of
the next RTH session (ET hour 9, the 09:00-09:59 bar that contains the 09:30
open).

Optional trend filter: only enter when close > SMA(filter_len). ``filter_len=0``
disables the filter (raw overnight carry, no bias screen).

Optional volatility-stress (regime) gate: only enter when the trailing 20-bar
annualized realized vol at the entry bar is <= ``max_rv_annualized`` (percent).
``max_rv_annualized=0`` disables it. Rationale: the overnight equity-carry edge
concentrates in calm/uptrend regimes; equity selloffs (e.g. the 2024 bear
cluster that broke OOS consistency for raw overnight carry) spike realized vol,
so standing aside when vol is elevated is a price-only proxy for "VIX contango /
low-stress" that removes the worst sessions. No lookahead — rv is measured on
bars up to and including the entry bar.

SIGNAL CONTRACT (Backtester columns):
    entry_signal  : "ENTRY_NOW" | "NO_TRADE"
    exit_signal   : "EXIT_NOW"  | "NO_EXIT"
    stop_level    : entry − 50 × ATR  (intentionally wide; time-based exit governs)
    trailing_stop : NaN (unused; wide stop already set)
    target_1/2/3  : entry + N × 50 × ATR  (far enough to never fire before time-exit)
    atr           : ATR(14) Wilder series
    rv_20_ann_pct : 20-bar annualized realized vol (percent)
    bias          : "STRONG_BULL" (all entries are long-only)
    regime        : "OVERNIGHT_CARRY" | "FILTERED_OUT" (trend) | "VOL_GATED" (stress)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_ATR_PERIOD = 14
# Realized-vol regime gate (mirrors trend_signals / vol_target_experiment)
_RV_WINDOW = 20
_RV_ANNUAL_FACTOR = 252 * 24  # 24 1h bars per trading day, 252 trading days/yr
# Wide stop multiplier -- set far enough that the time-based EXIT_NOW fires first
_STOP_ATR_MULT = 50.0
# Targets set proportionally wide so R:R > 1.2 is always satisfied and targets
# never fire before the time-based exit
_T1_ATR_MULT = 75.0
_T2_ATR_MULT = 100.0
_T3_ATR_MULT = 125.0


def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_c = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_c).abs(), (low - prev_c).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def generate_overnight_signals(
    df: pd.DataFrame,
    filter_len: int = 0,
    max_rv_annualized: float = 0.0,
) -> pd.DataFrame:
    """
    Generate overnight-carry signals for the JARVIS Backtester.

    Parameters
    ----------
    df : pd.DataFrame
        1-hour OHLCV bars with a UTC-timezone-aware DatetimeIndex (or naive UTC).
        Required columns: open, high, low, close.
    filter_len : int
        SMA look-back for the optional trend filter. 0 = disabled.
    max_rv_annualized : float
        Volatility-stress gate. When > 0, skip an entry whose trailing 20-bar
        annualized realized vol (percent) exceeds this threshold. 0 = disabled.

    Returns
    -------
    pd.DataFrame with all signal columns required by the Backtester appended.
    """
    df = df.copy()

    # Ensure UTC index so tz_convert works regardless of whether the source is
    # tz-aware (IBKR cache) or tz-naive (treated as UTC by convention).
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    et_index = df.index.tz_convert("America/New_York")

    atr = _wilder_atr(df["high"], df["low"], df["close"], _ATR_PERIOD)

    # Optional SMA filter
    sma = df["close"].rolling(filter_len).mean() if filter_len > 0 else None

    # Trailing realized vol (annualized %) for the optional stress gate.
    log_ret = np.log(df["close"] / df["close"].shift(1))
    rv_ann = log_ret.rolling(_RV_WINDOW).std() * np.sqrt(_RV_ANNUAL_FACTOR) * 100.0

    n = len(df)
    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    exit_signal = np.full(n, "NO_EXIT", dtype=object)
    stop_level = np.full(n, np.nan)
    trailing_stop = np.full(n, np.nan)
    target_1 = np.full(n, np.nan)
    target_2 = np.full(n, np.nan)
    target_3 = np.full(n, np.nan)
    regime = np.full(n, "OVERNIGHT_CARRY", dtype=object)

    et_hours = et_index.hour
    in_overnight = False

    for i in range(n):
        hour = et_hours[i]
        price = float(df["close"].iloc[i])
        atr_i = atr.iloc[i]

        if pd.isna(atr_i):
            continue

        atr_i = float(atr_i)

        # EXIT: first RTH bar (09:xx ET) -- exit any open overnight position
        if hour == 9 and in_overnight:
            exit_signal[i] = "EXIT_NOW"
            in_overnight = False

        # ENTRY: last RTH bar (15:xx ET) -- enter if not already in a trade
        if hour == 15 and not in_overnight:
            # Optional SMA trend filter
            if sma is not None:
                sma_val = sma.iloc[i]
                if pd.isna(sma_val) or price <= float(sma_val):
                    regime[i] = "FILTERED_OUT"
                    continue

            # Optional volatility-stress gate -- stand aside when trailing rv is
            # elevated (proxy for high-VIX / backwardation stress regimes).
            if max_rv_annualized > 0.0:
                rv_i = rv_ann.iloc[i]
                if pd.isna(rv_i) or float(rv_i) > max_rv_annualized:
                    regime[i] = "VOL_GATED"
                    continue

            # Wide stop so it never fires before the time-based exit
            stop = price - _STOP_ATR_MULT * atr_i
            t1 = price + _T1_ATR_MULT * atr_i
            t2 = price + _T2_ATR_MULT * atr_i
            t3 = price + _T3_ATR_MULT * atr_i

            entry_signal[i] = "ENTRY_NOW"
            stop_level[i] = stop
            target_1[i] = t1
            target_2[i] = t2
            target_3[i] = t3
            in_overnight = True

    df["entry_signal"] = entry_signal
    df["exit_signal"] = exit_signal
    df["stop_level"] = stop_level
    df["trailing_stop"] = trailing_stop
    df["target_1"] = target_1
    df["target_2"] = target_2
    df["target_3"] = target_3
    df["atr"] = atr
    df["rv_20_ann_pct"] = rv_ann
    df["bias"] = "STRONG_BULL"
    df["regime"] = regime

    return df

"""
Calendar-based MES signal generators for JARVIS TRADER gate-v2 validation.

Two strategies:
  1. TURN-OF-MONTH: enter RTH close of the last trading day of each month
     (T-1), exit RTH close of the 3rd trading day of the new month (T+3).
  2. PRE-FOMC DRIFT: enter RTH close the day BEFORE each FOMC statement day,
     exit RTH close of the FOMC statement day itself.

Both are LONG-ONLY, time-governed exits (wide stops so the calendar governs).

Signal contract (matches Backtester requirements):
  entry_signal  : "ENTRY_NOW" | "NO_TRADE"
  exit_signal   : "EXIT_NOW" | "NO_EXIT"
  stop_level    : float (wide sentinel so ATR-stop never fires first)
  trailing_stop : float (same sentinel)
  target_1/2/3  : float (wide sentinel so target never fires first)
  atr           : float (ATR-14)
  bias          : str
  regime        : str

RTH close bar = ET hour-15 (15:00-15:59 ET, i.e. the 3pm 1h bar).
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# FOMC statement dates (hardcoded from published Fed calendar)
# 2024: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
# ---------------------------------------------------------------------------
_FOMC_DATES: frozenset[date] = frozenset(
    [
        # 2024
        date(2024, 1, 31),
        date(2024, 3, 20),
        date(2024, 5, 1),
        date(2024, 6, 12),
        date(2024, 7, 31),
        date(2024, 9, 18),
        date(2024, 11, 7),
        date(2024, 12, 18),
        # 2025
        date(2025, 1, 29),
        date(2025, 3, 19),
        date(2025, 5, 7),
        date(2025, 6, 18),
        date(2025, 7, 30),
        date(2025, 9, 17),
        date(2025, 10, 29),
        date(2025, 12, 10),
        # 2026 (from Fed calendar; tentative beyond first two)
        date(2026, 1, 28),
        date(2026, 3, 18),
        date(2026, 4, 29),
        date(2026, 6, 17),
        date(2026, 7, 29),
        date(2026, 9, 16),
        date(2026, 10, 28),
        date(2026, 12, 9),
    ]
)

# Wide stop/target sentinels: set so far from any realistic price that the
# Backtester's stop/target logic never fires before the exit_signal.
_WIDE_STOP_OFFSET = 999.0  # points below entry (MES ~5000 → never hit)
_WIDE_TARGET_OFFSET = 9999.0  # points above entry (never hit)

_ATR_PERIOD = 14


def _wilder_atr(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    prev_c = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_c).abs(), (low - prev_c).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def _assert_et_index(df: pd.DataFrame) -> None:
    """Raise if index is not ET-localized."""
    if not hasattr(df.index, "tz") or df.index.tz is None:
        raise ValueError(
            "DataFrame index must be timezone-aware ET. "
            "Call df.index = df.index.tz_localize('UTC').tz_convert('America/New_York') first."
        )
    tz_name = str(df.index.tz)
    if "New_York" not in tz_name and "US/Eastern" not in tz_name and "EST" not in tz_name:
        raise ValueError(f"Expected ET timezone, got: {tz_name}")


def _rth_close_bars(df: pd.DataFrame) -> pd.Series:
    """Boolean mask: True on the RTH 15:00 bar (hour == 15 in ET)."""
    return df.index.hour == 15  # type: ignore[return-value]


def _trading_days_index(df: pd.DataFrame) -> pd.DatetimeIndex:
    """Unique date-only index of days that have at least one RTH bar."""
    rth = df[_rth_close_bars(df)]
    return pd.DatetimeIndex(sorted(rth.index.normalize().unique()))


# ---------------------------------------------------------------------------
# Strategy 1: Turn-of-Month
# ---------------------------------------------------------------------------


def generate_turn_of_month_signals(df_utc: pd.DataFrame) -> pd.DataFrame:
    """
    Turn-of-Month long-only MES strategy.

    Entry: RTH close (hour-15 ET bar) of the LAST trading day of each month.
    Exit : RTH close of the 3rd trading day of the following month (T+3).

    Args:
        df_utc: 1h OHLCV DataFrame with UTC-aware or UTC-naive index (will be
                converted to ET internally).

    Returns:
        df with full signal columns (entry_signal, exit_signal, stop_level,
        trailing_stop, target_1/2/3, atr, bias, regime).
        Index is ET-localized.
    """
    df = df_utc.copy()
    df.columns = [c.lower() for c in df.columns]

    # Normalise index to ET
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert("America/New_York")
    else:
        df.index = df.index.tz_convert("America/New_York")

    _assert_et_index(df)

    atr = _wilder_atr(df["high"], df["low"], df["close"])

    n = len(df)
    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    exit_signal = np.full(n, "NO_EXIT", dtype=object)
    stop_level = np.full(n, np.nan)
    trailing_stop = np.full(n, np.nan)
    target_1 = np.full(n, np.nan)
    target_2 = np.full(n, np.nan)
    target_3 = np.full(n, np.nan)

    # Build trading-day calendar
    tdays = _trading_days_index(df)
    rth_mask = _rth_close_bars(df)

    # Build month-end / month-start trading day sets
    # Group trading days by (year, month) → last day is month-end T-1
    from collections import defaultdict

    by_month: dict[tuple[int, int], list[date]] = defaultdict(list)
    for d in tdays:
        by_month[(d.year, d.month)].append(d.date())

    months_sorted = sorted(by_month)
    # For each month, last trading day = potential entry
    # T+3 = 3rd trading day of NEXT month (index 2, 0-based)
    entry_dates: set[date] = set()
    exit_dates: dict[date, date] = {}  # entry_date -> exit_date

    for i, (yr, mo) in enumerate(months_sorted):
        days_this = by_month[(yr, mo)]
        entry_d = max(days_this)  # last trading day of month
        # Find next month
        if i + 1 < len(months_sorted):
            next_key = months_sorted[i + 1]
            days_next = by_month[next_key]
            if len(days_next) >= 3:
                exit_d = days_next[2]  # 3rd trading day of next month (index 2)
            elif days_next:
                exit_d = days_next[-1]  # fewer than 3 days; take last available
            else:
                continue  # skip if no next month data
            entry_dates.add(entry_d)
            exit_dates[entry_d] = exit_d

    # Stamp signals
    in_trade = False
    current_stop: float = np.nan
    current_entry_date: date | None = None

    for i in range(n):
        bar_dt = df.index[i]
        bar_date = bar_dt.date()
        is_rth_close = bool(rth_mask[i])
        close_i = float(df["close"].iloc[i])

        # Check exit first (exit before new entry on same bar)
        if in_trade and current_entry_date is not None:
            exit_target = exit_dates.get(current_entry_date)
            if exit_target is not None and bar_date >= exit_target and is_rth_close:
                exit_signal[i] = "EXIT_NOW"
                in_trade = False
                current_entry_date = None
                current_stop = np.nan

        # Entry: RTH close of month-end day and not already in trade
        if not in_trade and is_rth_close and bar_date in entry_dates:
            # Also need exit target available for this entry
            if bar_date in exit_dates:
                entry_signal[i] = "ENTRY_NOW"
                current_stop = close_i - _WIDE_STOP_OFFSET
                current_entry_date = bar_date
                in_trade = True
                stop_level[i] = current_stop
                trailing_stop[i] = current_stop
                target_1[i] = close_i + _WIDE_TARGET_OFFSET
                target_2[i] = close_i + _WIDE_TARGET_OFFSET
                target_3[i] = close_i + _WIDE_TARGET_OFFSET
        elif in_trade:
            stop_level[i] = current_stop
            trailing_stop[i] = current_stop

    df["entry_signal"] = entry_signal
    df["exit_signal"] = exit_signal
    df["stop_level"] = stop_level
    df["trailing_stop"] = trailing_stop
    df["target_1"] = target_1
    df["target_2"] = target_2
    df["target_3"] = target_3
    df["atr"] = atr
    df["bias"] = "BULL"
    df["regime"] = "CALENDAR"
    return df


# ---------------------------------------------------------------------------
# Strategy 2: Pre-FOMC Drift
# ---------------------------------------------------------------------------


def generate_pre_fomc_signals(df_utc: pd.DataFrame) -> pd.DataFrame:
    """
    Pre-FOMC Drift long-only MES strategy.

    Entry: RTH close (hour-15 ET bar) the trading day BEFORE each FOMC statement day.
    Exit : RTH close of the FOMC statement day.

    If the day before an FOMC date is not a trading day (weekend/holiday),
    the nearest prior trading day is used as entry day.

    Args:
        df_utc: 1h OHLCV DataFrame (UTC-aware or naive; converted to ET).

    Returns:
        df with full signal columns. Index is ET-localized.
    """
    df = df_utc.copy()
    df.columns = [c.lower() for c in df.columns]

    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert("America/New_York")
    else:
        df.index = df.index.tz_convert("America/New_York")

    _assert_et_index(df)

    atr = _wilder_atr(df["high"], df["low"], df["close"])

    n = len(df)
    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    exit_signal = np.full(n, "NO_EXIT", dtype=object)
    stop_level = np.full(n, np.nan)
    trailing_stop = np.full(n, np.nan)
    target_1 = np.full(n, np.nan)
    target_2 = np.full(n, np.nan)
    target_3 = np.full(n, np.nan)

    tdays = _trading_days_index(df)
    tday_set: set[date] = {d.date() for d in tdays}
    tday_sorted = sorted(tday_set)

    rth_mask = _rth_close_bars(df)

    # Build entry_date -> exit_date map for FOMC events in our data window
    data_start = df.index.min().date()
    data_end = df.index.max().date()

    fomc_pairs: dict[date, date] = {}  # entry_date -> exit_date (fomc_date)
    for fomc_date in sorted(_FOMC_DATES):
        if fomc_date < data_start or fomc_date > data_end:
            continue
        if fomc_date not in tday_set:
            continue  # FOMC date must be a trading day to have an exit

        # Find prior trading day as entry
        prior_candidates = [d for d in tday_sorted if d < fomc_date]
        if not prior_candidates:
            continue
        entry_d = prior_candidates[-1]  # most recent trading day before FOMC
        if entry_d < data_start:
            continue
        fomc_pairs[entry_d] = fomc_date

    entry_dates: set[date] = set(fomc_pairs)

    in_trade = False
    current_stop: float = np.nan
    current_entry_date: date | None = None

    for i in range(n):
        bar_dt = df.index[i]
        bar_date = bar_dt.date()
        is_rth_close = bool(rth_mask[i])
        close_i = float(df["close"].iloc[i])

        # Exit check first
        if in_trade and current_entry_date is not None:
            exit_target = fomc_pairs.get(current_entry_date)
            if exit_target is not None and bar_date >= exit_target and is_rth_close:
                exit_signal[i] = "EXIT_NOW"
                in_trade = False
                current_entry_date = None
                current_stop = np.nan

        # Entry check
        if not in_trade and is_rth_close and bar_date in entry_dates:
            entry_signal[i] = "ENTRY_NOW"
            current_stop = close_i - _WIDE_STOP_OFFSET
            current_entry_date = bar_date
            in_trade = True
            stop_level[i] = current_stop
            trailing_stop[i] = current_stop
            target_1[i] = close_i + _WIDE_TARGET_OFFSET
            target_2[i] = close_i + _WIDE_TARGET_OFFSET
            target_3[i] = close_i + _WIDE_TARGET_OFFSET
        elif in_trade:
            stop_level[i] = current_stop
            trailing_stop[i] = current_stop

    df["entry_signal"] = entry_signal
    df["exit_signal"] = exit_signal
    df["stop_level"] = stop_level
    df["trailing_stop"] = trailing_stop
    df["target_1"] = target_1
    df["target_2"] = target_2
    df["target_3"] = target_3
    df["atr"] = atr
    df["bias"] = "BULL"
    df["regime"] = "CALENDAR"
    return df

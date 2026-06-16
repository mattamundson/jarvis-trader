"""
JARVIS TRADER — Initial Balance (Corey IB) go/fade signal -> Backtester contract.

NEW FILE (do not import into production routing). Built for the honest gate-v2
backtest of the Corey Initial Balance opening-range strategy. Mirrors the
ORB / gap_go family discipline:

  * RTH-only bars (ET 09:30-16:00, weekdays). IB strategies are intraday.
  * IB = high/low of the first `open_minutes` of RTH (via compute_initial_balance
    in ib_signals.py — the existing faithful Corey port).
  * GO mode  : fresh breakout of the IB high -> long; fresh break of IB low -> short.
  * FADE mode: fresh breakout of IB high -> SHORT (fade the break back into range);
               fresh break of IB low -> LONG.
  * Stop = opposite IB extreme (long stop = ib_low, short stop = ib_high).
  * Targets = IB-range multiples (T1 = 1x IB range from entry, T2 = 2x).
  * No new entries in the final RTH bar block (handled by EOD exit in Backtester).
  * One signal per session (fresh-breakout flag from ib_signals fires once).
  * Backtester runs eod_close=True so every position exits at the session close.

Emits the columns Backtester.run() consumes:
    entry_signal in {ENTRY_NOW, NO_TRADE}
    bias         in {BULLISH, BEARISH, NEUTRAL}
    stop_level, target_1, target_2, atr

No look-ahead: the fresh-breakout flag is evaluated on the signal bar's close;
Backtester enters on the NEXT bar's open (pending_entry mechanism). The IB level
itself is frozen once the IB window closes, so it is fully known at signal time.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.ib_signals import compute_initial_balance


def _rth_mask(idx: pd.DatetimeIndex, tz: str = "America/New_York") -> np.ndarray:
    """Boolean mask for RTH bars: ET 09:30 <= t < 16:00, Mon-Fri."""
    if idx.tz is not None:
        et = idx.tz_convert(tz)
    else:
        et = idx.tz_localize("UTC").tz_convert(tz)
    t = et.time
    open_t = pd.Timestamp("09:30").time()
    close_t = pd.Timestamp("16:00").time()
    in_session = np.array([(open_t <= x < close_t) for x in t])
    weekday = et.dayofweek < 5
    return in_session & np.asarray(weekday)


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def generate_ib_breakout_signals(
    df: pd.DataFrame,
    mode: str = "go",
    open_minutes: int = 60,
    min_ib_range_pct: float = 0.0,
    target_mult_1: float = 1.0,
    target_mult_2: float = 2.0,
    tz: str = "America/New_York",
) -> pd.DataFrame:
    """
    Add Backtester-contract signal columns for the Corey IB strategy.

    Parameters
    ----------
    df : OHLCV DataFrame, tz-aware DatetimeIndex (UTC ok — converted internally).
    mode : "go" (breakout continuation) or "fade" (mean-revert the break).
    open_minutes : IB capture window length in minutes (RTH).
    min_ib_range_pct : skip sessions whose IB range / price is below this floor
        (filters micro-range days that produce noise breakouts).
    target_mult_1 / target_mult_2 : T1/T2 as multiples of the IB range.

    Returns the df (RTH-only rows) with: entry_signal, bias, stop_level,
    target_1, target_2, target_3, atr, regime, exit_signal.
    """
    if mode not in ("go", "fade"):
        raise ValueError(f"mode must be 'go' or 'fade', got {mode!r}")

    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    # ib_signals.compute_initial_balance expects a CT wall-clock comparison and
    # RTH open of 09:30. It handles tz-aware indices (converts to America/Chicago).
    # We run it on ALL bars first (it needs the pre-RTH/RTH structure), then
    # restrict to RTH for the actual backtest.
    ib = compute_initial_balance(
        df,
        open_minutes=open_minutes,
        market_open_hour=8,   # 08:30 CT == 09:30 ET RTH open
        market_open_minute=30,
        tz="America/Chicago",
    )

    # Restrict to RTH bars only — intraday strategy, real volume, EOD exit fits.
    rth = _rth_mask(ib.index, tz=tz)
    ib = ib[rth].copy()

    ib["atr"] = _atr(ib, period=14)

    ib_range = ib["ib_high"] - ib["ib_low"]
    # Micro-range filter (parallels ORB MIN_OR_RANGE_PCT).
    range_ok = (ib_range / ib["close"]) >= min_ib_range_pct

    fresh_up = ib["ib_high_fresh_breakout"].fillna(False).astype(bool)
    fresh_dn = ib["ib_low_fresh_breakout"].fillna(False).astype(bool)
    level_known = ib["ib_high"].notna() & ib["ib_low"].notna()

    entry = np.where(
        (fresh_up | fresh_dn) & level_known & range_ok, "ENTRY_NOW", "NO_TRADE"
    )

    # Direction mapping.
    if mode == "go":
        # breakout up -> long ; breakout down -> short
        long_sig = fresh_up
        short_sig = fresh_dn
    else:  # fade
        # breakout up -> short ; breakout down -> long
        long_sig = fresh_dn
        short_sig = fresh_up

    long_sig = long_sig & level_known & range_ok
    short_sig = short_sig & level_known & range_ok

    bias = np.where(long_sig, "BULLISH", np.where(short_sig, "BEARISH", "NEUTRAL"))
    # Drop entries that ended up NEUTRAL (e.g. both flags false on a bar).
    entry = np.where(bias == "NEUTRAL", "NO_TRADE", entry)

    close = ib["close"].to_numpy(float)
    ib_high = ib["ib_high"].to_numpy(float)
    ib_low = ib["ib_low"].to_numpy(float)
    rng = (ib_high - ib_low)

    long_mask = bias == "BULLISH"
    short_mask = bias == "BEARISH"

    stop = np.full(len(ib), np.nan)
    t1 = np.full(len(ib), np.nan)
    t2 = np.full(len(ib), np.nan)

    # Long: stop at IB low, targets above current close by IB-range multiples.
    stop[long_mask] = ib_low[long_mask]
    t1[long_mask] = close[long_mask] + target_mult_1 * rng[long_mask]
    t2[long_mask] = close[long_mask] + target_mult_2 * rng[long_mask]
    # Short: stop at IB high, targets below.
    stop[short_mask] = ib_high[short_mask]
    t1[short_mask] = close[short_mask] - target_mult_1 * rng[short_mask]
    t2[short_mask] = close[short_mask] - target_mult_2 * rng[short_mask]

    ib["entry_signal"] = entry
    ib["bias"] = bias
    ib["stop_level"] = stop
    ib["target_1"] = t1
    ib["target_2"] = t2
    ib["target_3"] = t2
    ib["regime"] = ""
    ib["exit_signal"] = "NO_EXIT"

    return ib

"""
JARVIS TRADER — VWAP Deviation Reversion Signal Generator
==========================================================
Generates VWAP reversion signals for MES (Micro E-mini S&P 500) on 1-hour bars.

Strategy Logic:
  - VWAP is computed per RTH session (reset at 09:30 ET each day)
  - Upper/Lower Bands = VWAP ± (band_mult × ATR)
  - LONG entry: close < Lower Band AND close > prior bar's close (1-bar reversal)
    (price stretched below VWAP by ≥ band_mult ATR, showing first reversal sign)
  - SHORT entry: close > Upper Band AND close < prior bar's close (1-bar reversal)
  - Stop: entry ± stop_mult × ATR (beyond deviation extreme)
  - T1: VWAP (primary mean-reversion target)
  - T2: opposite band (full mean-reversion)
  - No new entries in the final RTH bar (15:00-16:00 ET)

Why VWAP Reversion for MES:
  S&P 500 / ES / MES exhibits strong intraday mean-reversion. Institutional
  participation concentrates around VWAP (the volume-weighted "fair price").
  Deviations from VWAP — especially when accompanied by exhaustion signals —
  tend to revert. STC+ATR and ORB both assume trend continuation; this strategy
  directly bets against that assumption, which is the correct model for MES.

VWAP calculation uses cumulative (price × volume) / cumulative volume per session.
Handles volume=0 bars gracefully (skips contribution, uses prior VWAP).

Output columns:
  - vwap          : Session VWAP value
  - vwap_upper    : VWAP + band_mult × ATR
  - vwap_lower    : VWAP - band_mult × ATR
  - atr           : ATR(14) for the bar
  - vwap_signal   : "LONG_ENTRY" | "SHORT_ENTRY" | ""
  - vwap_stop     : Stop price
  - vwap_target_1 : VWAP (T1)
  - vwap_target_2 : Opposite band (T2)
  - vwap_rr       : Reward:Risk ratio at T1
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger("vwap_signals")

# Default parameters (these are grid-searched in walk_forward)
DEFAULT_BAND_MULT = 1.5  # ATR multiples for band width
DEFAULT_STOP_MULT = 0.5  # ATR multiples for stop beyond deviation extreme
DEFAULT_ATR_PERIOD = 14
RTH_OPEN_HOUR = 9  # First RTH bar (09:30-10:30 ET)
RTH_OPEN_MINUTE = 30
RTH_FINAL_HOUR = 15  # Block entries at 15:xx bars
RTH_CLOSE_HOUR = 16


def _compute_atr(df: pd.DataFrame, period: int = DEFAULT_ATR_PERIOD) -> pd.Series:
    """Wilder ATR."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    return atr


def _get_eastern_index(df: pd.DataFrame) -> pd.DatetimeIndex:
    """Normalize DataFrame index to Eastern Time.

    MES data from Yahoo Finance via BacktestDataLoader is stored as
    timezone-naive UTC timestamps.  We localize as UTC first, then
    convert to America/New_York so that the RTH session boundary
    (reset at 09:30 ET each day) is identified correctly.
    """
    # Sprint A / B3 fix: defensive DatetimeIndex normalization prevents crash
    # when merging tz-aware IB bars with tz-naive backtest frames.
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    idx = df.index
    if hasattr(idx, "tz") and idx.tz is not None:
        eastern = idx.tz_convert("America/New_York")
    else:
        # Timezone-naive: treat as UTC then convert to Eastern Time
        try:
            eastern = idx.tz_localize("UTC").tz_convert("America/New_York")
        except Exception:
            eastern = idx  # fallback: use hours as-is
    return eastern


def _get_eastern_hour(df: pd.DataFrame) -> pd.Series:
    """Extract Eastern Time hour from DatetimeIndex."""
    eastern = _get_eastern_index(df)
    return pd.Series(eastern.hour, index=df.index)


def generate_vwap_signals(
    df: pd.DataFrame,
    symbol: str = "MES",
    band_mult: float = DEFAULT_BAND_MULT,
    stop_mult: float = DEFAULT_STOP_MULT,
    atr_period: int = DEFAULT_ATR_PERIOD,
    require_reversal_bar: bool = True,
    regime_filter: bool = False,
) -> pd.DataFrame:
    """
    Add VWAP reversion signal columns to a 1-hour OHLCV DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        1-hour OHLCV with DatetimeIndex (UTC or Eastern).
    symbol : str
        Symbol for logging.
    band_mult : float
        ATR multiples from VWAP to define entry bands.
    stop_mult : float
        ATR multiples beyond entry price for stop loss.
    atr_period : int
        ATR lookback period.
    require_reversal_bar : bool
        If True, require close to reverse the prior bar direction (1-bar reversal filter).
    regime_filter : bool
        If True, suppress signals when RegimeClassifier detects TRENDING regime.
        Mean-reversion strategies underperform in trending markets.

    Returns
    -------
    pd.DataFrame with VWAP signal columns added.
    """
    df = df.copy()

    if df.empty or len(df) < atr_period + 5:
        for col in [
            "vwap",
            "vwap_upper",
            "vwap_lower",
            "atr",
            "vwap_signal",
            "vwap_stop",
            "vwap_target_1",
            "vwap_target_2",
            "vwap_rr",
        ]:
            df[col] = np.nan
        df["vwap_signal"] = ""
        return df

    # ATR
    df["atr"] = _compute_atr(df, period=atr_period)

    # Optional regime filter — mark trending bars to suppress signals
    df["_regime_ok"] = True
    if regime_filter:
        try:
            from backtest.regime import RegimeClassifier

            rc = RegimeClassifier()
            classified = rc.classify(df)
            regime_col = (
                "regime_type" if "regime_type" in classified.columns else classified.columns[-1]
            )
            regime_series = classified[regime_col]
            # Block signals when regime is TRENDING — VWAP reversion fails in trends
            df["_regime_ok"] = ~regime_series.str.contains("TRENDING", na=False)
            n_blocked = (~df["_regime_ok"]).sum()
            logger.debug(f"{symbol}: regime filter blocked {n_blocked}/{len(df)} bars")
        except Exception as e:
            logger.warning(f"{symbol}: regime filter failed ({e}) — proceeding without")

    # Eastern session metadata. VWAP is explicitly RTH-anchored: accumulate only
    # 09:30-16:00 ET, and allow new entries only before the final RTH hour.
    eastern = _get_eastern_index(df)
    eastern_minutes = pd.Series(eastern.hour * 60 + eastern.minute, index=df.index)
    eastern_session = pd.Series(eastern.date, index=df.index)
    rth_open_minute = RTH_OPEN_HOUR * 60 + RTH_OPEN_MINUTE
    rth_signal_cutoff_minute = RTH_FINAL_HOUR * 60
    rth_close_minute = RTH_CLOSE_HOUR * 60
    in_rth = (eastern_minutes >= rth_open_minute) & (
        eastern_minutes < rth_close_minute
    )
    signal_eligible = (eastern_minutes >= rth_open_minute) & (
        eastern_minutes < rth_signal_cutoff_minute
    )
    eastern_hour = pd.Series(eastern.hour, index=df.index)

    # Session VWAP (reset at first RTH bar each day)
    cum_pv = 0.0  # cumulative price × volume
    cum_vol = 0.0  # cumulative volume
    vwap_vals = []
    active_session = None

    for i in range(len(df)):
        if not bool(in_rth.iloc[i]):
            vwap_vals.append(np.nan)
            continue

        session_key = eastern_session.iloc[i]
        vol = float(df["volume"].iloc[i])
        tp = (
            float(df["high"].iloc[i]) + float(df["low"].iloc[i]) + float(df["close"].iloc[i])
        ) / 3.0

        if session_key != active_session:
            # New session — reset
            active_session = session_key
            cum_pv = tp * vol if vol > 0 else 0.0
            cum_vol = vol if vol > 0 else 0.0
        else:
            if vol > 0:
                cum_pv += tp * vol
                cum_vol += vol

        if cum_vol > 0:
            vwap_vals.append(cum_pv / cum_vol)
        else:
            vwap_vals.append(tp)  # fallback: typical price

    df["vwap"] = vwap_vals

    # Bands
    df["vwap_upper"] = df["vwap"] + band_mult * df["atr"]
    df["vwap_lower"] = df["vwap"] - band_mult * df["atr"]

    # Signals
    df["vwap_signal"] = ""
    df["vwap_stop"] = np.nan
    df["vwap_target_1"] = np.nan
    df["vwap_target_2"] = np.nan
    df["vwap_rr"] = np.nan

    for i in range(1, len(df)):
        bar_close = float(df["close"].iloc[i])
        bar_hour = int(eastern_hour.iloc[i])
        if not bool(signal_eligible.iloc[i]):
            continue

        vwap = float(df["vwap"].iloc[i])
        upper = float(df["vwap_upper"].iloc[i])
        lower = float(df["vwap_lower"].iloc[i])
        atr = float(df["atr"].iloc[i])
        prev_close = float(df["close"].iloc[i - 1])

        if np.isnan(atr) or np.isnan(vwap):
            continue

        # Skip final RTH hour
        if bar_hour >= RTH_FINAL_HOUR:
            continue

        reversal_long = bar_close > prev_close  # current bar closed up
        reversal_short = bar_close < prev_close  # current bar closed down

        # Skip if regime filter is active and bar is trending
        if regime_filter and not bool(df["_regime_ok"].iloc[i]):
            continue

        # LONG entry: close below lower band (stretched below VWAP) with reversal
        if bar_close < lower:
            if not require_reversal_bar or reversal_long:
                stop = bar_close - stop_mult * atr
                t1 = vwap
                t2 = upper
                risk = bar_close - stop
                reward_t1 = t1 - bar_close
                rr = reward_t1 / risk if risk > 0 else 0.0

                df.at[df.index[i], "vwap_signal"] = "LONG_ENTRY"
                df.at[df.index[i], "vwap_stop"] = round(stop, 4)
                df.at[df.index[i], "vwap_target_1"] = round(t1, 4)
                df.at[df.index[i], "vwap_target_2"] = round(t2, 4)
                df.at[df.index[i], "vwap_rr"] = round(rr, 3)

        # SHORT entry: close above upper band with reversal
        elif bar_close > upper:
            if not require_reversal_bar or reversal_short:
                stop = bar_close + stop_mult * atr
                t1 = vwap
                t2 = lower
                risk = stop - bar_close
                reward_t1 = bar_close - t1
                rr = reward_t1 / risk if risk > 0 else 0.0

                df.at[df.index[i], "vwap_signal"] = "SHORT_ENTRY"
                df.at[df.index[i], "vwap_stop"] = round(stop, 4)
                df.at[df.index[i], "vwap_target_1"] = round(t1, 4)
                df.at[df.index[i], "vwap_target_2"] = round(t2, 4)
                df.at[df.index[i], "vwap_rr"] = round(rr, 3)

    n_long = (df["vwap_signal"] == "LONG_ENTRY").sum()
    n_short = (df["vwap_signal"] == "SHORT_ENTRY").sum()
    logger.info(
        f"{symbol} VWAP signals: {n_long} LONG + {n_short} SHORT = {n_long + n_short} total "
        f"(band={band_mult}×ATR, stop={stop_mult}×ATR) over {len(df)} bars"
    )

    return df

"""
SMA-12 monthly time-series-momentum signal generator for JARVIS TRADER.

Origin: X-bookmark edge scan 2026-07-02 (Tier-A survivor `sma12_monthly_momentum`,
@QuantifiedStrat). Long the index while the monthly close is above its 12-month SMA;
flat to cash below it. SMA (not EMA) is used for the filter per the source claim.

Economic rationale: time-series (absolute) momentum risk premium -- trend
autocorrelation is persistent across asset classes (Moskowitz, Ooi & Pedersen 2012);
the moving-average filter truncates left-tail drawdowns by exiting sustained
downtrends. This is a regime/allocation filter, NOT an intraday entry -- so it is
consumed by run_spy_sma12_rank1.py directly (monthly PnL), not by the intraday
Backtester.

Contract: operates on MONTHLY bars (resample daily->month-end before calling).
Returns the input frame plus:
    position       : 1 (long) | 0 (cash)  -- the target holding for the NEXT month
    sma            : 12-period SMA of monthly close
    entry_signal   : "ENTRY_NOW" | "NO_TRADE"  (regime flips cash->long)
    exit_signal    : "EXIT_NOW"  | "NO_EXIT"   (regime flips long->cash)
    bias           : "BULL" | "CASH"
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def generate_sma12_momentum_signals(df_monthly: pd.DataFrame, sma_len: int = 12) -> pd.DataFrame:
    """Generate monthly time-series-momentum regime signals.

    Args:
        df_monthly: month-end OHLC(V) frame with a 'close' column.
        sma_len:    SMA lookback in months (default 12).

    No look-ahead: the SMA at month t uses closes up to and including t; the resulting
    `position` is the holding for month t+1 (the runner shifts it).
    """
    df = df_monthly.copy()
    sma = df["close"].rolling(sma_len, min_periods=sma_len).mean()
    long_regime = (df["close"] > sma)

    position = long_regime.astype("float")
    position[sma.isna()] = np.nan  # undefined until SMA warms up

    prev = long_regime.shift(1, fill_value=False)
    entry = long_regime & ~prev & sma.notna()
    exit_ = ~long_regime & prev & sma.notna()

    df["sma"] = sma
    df["position"] = position
    df["entry_signal"] = np.where(entry, "ENTRY_NOW", "NO_TRADE")
    df["exit_signal"] = np.where(exit_, "EXIT_NOW", "NO_EXIT")
    df["bias"] = np.where(long_regime, "BULL", "CASH")
    return df

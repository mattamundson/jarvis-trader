"""
Overnight-hold signal generator for JARVIS TRADER.

Origin: X-bookmark edge scan 2026-07-02 (Tier-A survivor `spy_overnight_hold`,
@QuantifiedStrat). Buy market-on-close, sell market-on-open the next session; flat
intraday. Captures the well-documented close-to-open drift / overnight risk premium
(the bulk of SPY's historical return has accrued overnight while the RTH session is
roughly flat).

Economic rationale: overnight risk-bearing compensation + index-futures fair-value
carry accrue to holders across the close-to-open gap; intraday participants demand a
premium to warehouse overnight risk. Trivially testable on daily OHLC -- no options
or microstructure data.

Contract: operates on DAILY bars with 'open' and 'close'. Returns the input frame plus:
    overnight_ret  : open_t / close_{t-1} - 1   (the return of one held night)
    position       : 1 (always hold overnight in the base variant)
    entry_signal   : "ENTRY_NOW" each session (enter at close)
    exit_signal    : "EXIT_NOW"  each session (exit at next open)

Optional regime filter (vix_series / prior-day) is left to the runner; the base
generator is parameter-free to keep the multiple-testing surface honest.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def generate_overnight_hold_signals(df_daily: pd.DataFrame, skip_after_up_days: int = 0) -> pd.DataFrame:
    """Generate overnight close-to-open hold signals.

    Args:
        df_daily: daily OHLC frame with 'open' and 'close'.
        skip_after_up_days: if >0, stand aside for a night after N consecutive up
            RTH sessions (a simple, documented mean-reversion overlay). 0 = always hold.
    """
    df = df_daily.copy()
    prev_close = df["close"].shift(1)
    df["overnight_ret"] = df["open"] / prev_close - 1.0

    hold = pd.Series(True, index=df.index)
    if skip_after_up_days > 0:
        rth_ret = df["close"] / df["open"] - 1.0
        up = (rth_ret > 0).astype(int)
        streak = up.groupby((up != up.shift()).cumsum()).cumsum()
        hold = ~(streak.shift(1) >= skip_after_up_days)

    df["position"] = np.where(hold & prev_close.notna(), 1.0, 0.0)
    df["entry_signal"] = np.where(df["position"] > 0, "ENTRY_NOW", "NO_TRADE")
    df["exit_signal"] = np.where(df["position"] > 0, "EXIT_NOW", "NO_EXIT")
    return df

"""
ATR-band signal generator for JARVIS TRADER.

Origin: X-bookmark edge scan 2026-07-02 (Tier-B survivor `atr_band_breakout`,
@QuantifiedStrat). Bands at MA +/- k*ATR. The OPEN QUESTION is polarity: does closing
beyond a band lead to continuation (breakout) or reversion? This generator supports
both modes so the runner can test which (if either) carries edge.

Economic rationale (breakout): volatility expansion after contraction tends to trend;
ATR-scaling adapts entry distance to current vol so signals fire on regime shifts, not
noise. (reversion): a stretched close snaps back to the mean.

Contract: returns the input frame plus:
    ma, atr, upper, lower
    position    : +1 long | -1 short | 0 flat  (the target holding for the NEXT bar)
    entry_signal / exit_signal
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    prev_c = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_c).abs(), (low - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def generate_atr_band_signals(
    df: pd.DataFrame,
    ma_len: int = 20,
    atr_period: int = 14,
    k: float = 2.5,
    mode: str = "breakout",
    long_only: bool = False,
) -> pd.DataFrame:
    """Generate ATR-band signals.

    mode="breakout": long when close > upper, short when close < lower; exit when close
        crosses back through the MA.
    mode="meanrev":  short when close > upper, long when close < lower; exit at the MA.
    Bands use shift(1) so a bar's signal depends only on the prior bar's band (no look-ahead).
    """
    df = df.copy()
    ma = df["close"].rolling(ma_len, min_periods=ma_len).mean()
    atr = _wilder_atr(df["high"], df["low"], df["close"], atr_period)
    upper = (ma + k * atr).shift(1)
    lower = (ma - k * atr).shift(1)
    ma_prev = ma.shift(1)
    close = df["close"]

    n = len(df)
    pos = np.zeros(n)
    cur = 0.0
    c = close.to_numpy()
    up = upper.to_numpy()
    lo = lower.to_numpy()
    mp = ma_prev.to_numpy()
    breakout = (mode == "breakout")
    for i in range(n):
        if np.isnan(up[i]) or np.isnan(mp[i]):
            pos[i] = 0.0
            continue
        # exit on MA cross
        if cur > 0 and c[i] < mp[i]:
            cur = 0.0
        elif cur < 0 and c[i] > mp[i]:
            cur = 0.0
        # entries
        if cur == 0.0:
            if c[i] > up[i]:
                cur = 1.0 if breakout else -1.0
            elif c[i] < lo[i]:
                cur = -1.0 if breakout else 1.0
        pos[i] = cur

    if long_only:
        pos = np.where(pos < 0, 0.0, pos)

    df["ma"] = ma
    df["atr"] = atr
    df["upper"] = upper
    df["lower"] = lower
    df["position"] = pos
    chg = np.diff(pos, prepend=0.0)
    df["entry_signal"] = np.where(chg != 0, "ENTRY_NOW", "NO_TRADE")
    df["exit_signal"] = np.where(chg != 0, "EXIT_NOW", "NO_EXIT")
    return df

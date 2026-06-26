"""Range-expansion breakout signal generator for JARVIS TRADER.

Idea (sourced from an X bookmark @onlybreakouts -- "the best indicator across
4,115 strategies ... bar range relative to ATR", tested across 3,500 NASDAQ
names): a bar whose true range is large relative to ATR marks a volatility
expansion. When that expansion bar also closes near its extreme, it signals
directional conviction -- momentum that tends to continue on the next bars.

Entry : bar_range = high-low > range_mult x ATR(14)  AND  close in the top
        (long) / bottom (short) `close_frac` of the bar's range.
Stop  : entry -/+ stop_atr_mult x ATR.
Targets: entry +/- N x ATR (N = 3/5/7, matching the trend/donchian convention).

Long-and-short. Contract matches generate_donchian_signals so it plugs straight
into the Backtester via the factory signal adapter.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_ATR_PERIOD = 14
_T1_MULT = 3.0
_T2_MULT = 5.0
_T3_MULT = 7.0


def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_c = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_c).abs(), (low - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def generate_range_expansion_signals(
    df: pd.DataFrame,
    range_mult: float = 1.5,
    close_frac: float = 0.66,
    stop_atr_mult: float = 1.5,
    signal_direction: str = "both",
) -> pd.DataFrame:
    """Generate range-expansion momentum signals compatible with the Backtester.

    Args:
        range_mult: bar true range must exceed this multiple of ATR to qualify.
        close_frac: close must sit in the top `close_frac` of the bar range for a
            long (or bottom `close_frac` for a short). 0.66 = upper/lower third.
        stop_atr_mult: stop distance in ATR multiples.
        signal_direction: "long", "short", or "both".

    Returns df with entry_signal/exit_signal/stop_level/target_1..3/bias/regime/atr.
    """
    df = df.copy()
    high, low, close = df["high"], df["low"], df["close"]
    atr = _wilder_atr(high, low, close, _ATR_PERIOD)

    bar_range = (high - low).replace(0, np.nan)
    expansion = bar_range > (range_mult * atr)
    # Where in the bar did we close? 1.0 = at the high, 0.0 = at the low.
    close_pos = (close - low) / bar_range
    want_long = signal_direction in ("both", "long")
    want_short = signal_direction in ("both", "short")
    long_sig = expansion & (close_pos >= close_frac) & atr.notna()
    short_sig = expansion & (close_pos <= (1.0 - close_frac)) & atr.notna()

    n = len(df)
    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    exit_signal = np.full(n, "NO_EXIT", dtype=object)
    stop_level = np.full(n, np.nan)
    target_1 = np.full(n, np.nan)
    target_2 = np.full(n, np.nan)
    target_3 = np.full(n, np.nan)
    bias = np.full(n, "NEUTRAL", dtype=object)
    regime = np.full(n, "RANGE_BOUND", dtype=object)

    for i in range(n):
        if pd.isna(atr.iloc[i]) or pd.isna(bar_range.iloc[i]):
            continue
        price = float(close.iloc[i])
        atr_i = float(atr.iloc[i])
        if want_long and bool(long_sig.iloc[i]):
            entry_signal[i] = "ENTRY_NOW"
            bias[i], regime[i] = "STRONG_BULL", "TRENDING_BULL"
            stop_level[i] = price - stop_atr_mult * atr_i
            target_1[i] = price + _T1_MULT * atr_i
            target_2[i] = price + _T2_MULT * atr_i
            target_3[i] = price + _T3_MULT * atr_i
        elif want_short and bool(short_sig.iloc[i]):
            entry_signal[i] = "ENTRY_NOW"
            bias[i], regime[i] = "STRONG_BEAR", "TRENDING_BEAR"
            stop_level[i] = price + stop_atr_mult * atr_i
            target_1[i] = price - _T1_MULT * atr_i
            target_2[i] = price - _T2_MULT * atr_i
            target_3[i] = price - _T3_MULT * atr_i

    df["entry_signal"] = entry_signal
    df["exit_signal"] = exit_signal
    df["stop_level"] = stop_level
    df["target_1"] = target_1
    df["target_2"] = target_2
    df["target_3"] = target_3
    df["bias"] = bias
    df["regime"] = regime
    df["atr"] = atr
    return df

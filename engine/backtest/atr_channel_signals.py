"""
STATUS: ARCHIVED — FAILED gate v2 (2026-04-22). Test PF 0.433 on MES 1h.
Keltner-style breakout surrendered the edge under ATR-regime filter.
Retained for reference; see backtest/archive/failed/README.md.

ATR-channel volatility breakout signal generator for JARVIS TRADER.

Entry  : close breaks above midline + atr_mult*ATR (long) / below midline -
         atr_mult*ATR (short), WHILE atr_regime is expanding (ATR > SMA(ATR)).
Exit   : close crosses back through midline (re-entry into channel).
Stop   : entry -/+ atr_stop_mult * ATR at entry bar.
Targets: entry +/- {3, 5, 7} * ATR  (matches repo convention).

Rationale: classic Keltner-style volatility breakout. The ATR-regime gate
filters out false breakouts that happen during contracting volatility —
those are usually range noise that mean-reverts fast. When ATR is expanding
(regime HIGH), the breakout is more likely to trend.

Midline is an EMA of close, making the channel auto-center on drift.
Symmetric long/short by design.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.indicators import atr_regime, wilder_atr

ATR_CHANNEL_PARAMS: dict[str, dict] = {
    # Placeholder — tune via scripts/mes_atr_channel_search.py.
    "MES": {
        "ema_period": 20,
        "atr_period": 14,
        "atr_mult": 2.0,
        "atr_stop_mult": 2.0,
        "regime_sma_period": 20,
        "require_regime_expanding": True,
    },
}

_T1_MULT = 3.0
_T2_MULT = 5.0
_T3_MULT = 7.0


def generate_atr_channel_signals(
    df: pd.DataFrame,
    ema_period: int = 20,
    atr_period: int = 14,
    atr_mult: float = 2.0,
    atr_stop_mult: float = 2.0,
    regime_sma_period: int = 20,
    require_regime_expanding: bool = True,
) -> pd.DataFrame:
    """
    Generate ATR-channel breakout signals.

    Args:
        ema_period: EMA period used as channel midline.
        atr_period: Wilder ATR period.
        atr_mult: channel width in ATR multiples (upper = ema + atr_mult*ATR).
        atr_stop_mult: initial stop distance in ATR multiples.
        regime_sma_period: SMA period for ATR-regime filter.
        require_regime_expanding: if True, only enter when ATR > SMA(ATR).

    Returns df with standard signal columns:
        entry_signal, exit_signal, stop_level, target_1/2/3, bias, regime,
        atr, midline, upper, lower.
    """
    df = df.copy()

    midline = df["close"].ewm(span=ema_period, adjust=False).mean()
    atr = wilder_atr(df["high"], df["low"], df["close"], period=atr_period)
    upper = midline + atr_mult * atr
    lower = midline - atr_mult * atr

    regime_expanding = atr_regime(
        df["high"], df["low"], df["close"],
        atr_period=atr_period, sma_period=regime_sma_period,
    )

    # Use prior bar's channel levels to avoid look-ahead (today's close vs
    # yesterday's envelope — today's bar is the confirming breakout).
    upper_prev = upper.shift(1)
    lower_prev = lower.shift(1)

    breakout_up = df["close"] > upper_prev
    breakout_dn = df["close"] < lower_prev

    regime_gate = regime_expanding if require_regime_expanding else pd.Series(True, index=df.index)

    long_cond = (breakout_up & regime_gate).fillna(False)
    short_cond = (breakout_dn & regime_gate).fillna(False)

    # Edge-detect: fire only on first bar breakout holds.
    enter_long = long_cond & ~long_cond.shift(1, fill_value=False)
    enter_short = short_cond & ~short_cond.shift(1, fill_value=False)

    # Exit: close crosses back through midline (channel re-entry).
    above_mid = df["close"] > midline
    below_mid = df["close"] < midline
    # Long exit: was above midline, now below → re-entry from above
    long_re_entry = below_mid & above_mid.shift(1, fill_value=False)
    # Short exit: was below midline, now above → re-entry from below
    short_re_entry = above_mid & below_mid.shift(1, fill_value=False)
    exit_trigger = (long_re_entry | short_re_entry).fillna(False)

    n = len(df)
    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    exit_signal = np.full(n, "NO_EXIT", dtype=object)
    stop_level = np.full(n, np.nan)
    target_1 = np.full(n, np.nan)
    target_2 = np.full(n, np.nan)
    target_3 = np.full(n, np.nan)

    for i in range(n):
        if pd.isna(atr.iloc[i]) or pd.isna(upper_prev.iloc[i]):
            continue
        price = float(df["close"].iloc[i])
        atr_i = float(atr.iloc[i])

        if enter_long.iloc[i]:
            entry_signal[i] = "ENTRY_NOW"
            stop_level[i] = price - atr_stop_mult * atr_i
            target_1[i] = price + _T1_MULT * atr_i
            target_2[i] = price + _T2_MULT * atr_i
            target_3[i] = price + _T3_MULT * atr_i
        elif enter_short.iloc[i]:
            entry_signal[i] = "ENTRY_NOW"
            stop_level[i] = price + atr_stop_mult * atr_i
            target_1[i] = price - _T1_MULT * atr_i
            target_2[i] = price - _T2_MULT * atr_i
            target_3[i] = price - _T3_MULT * atr_i
        elif exit_trigger.iloc[i]:
            exit_signal[i] = "EXIT_NOW"

    df["entry_signal"] = entry_signal
    df["exit_signal"] = exit_signal
    df["stop_level"] = stop_level
    df["target_1"] = target_1
    df["target_2"] = target_2
    df["target_3"] = target_3
    df["atr"] = atr
    df["midline"] = midline
    df["upper"] = upper
    df["lower"] = lower

    df["bias"] = "NEUTRAL"
    df.loc[long_cond, "bias"] = "VOL_BREAKOUT_UP"
    df.loc[short_cond, "bias"] = "VOL_BREAKOUT_DN"

    df["regime"] = "CONTRACTING"
    df.loc[regime_expanding.fillna(False), "regime"] = "EXPANDING"

    return df


def get_atr_channel_params(symbol: str) -> dict | None:
    """Return validated ATR-channel params for symbol, or None if not configured."""
    return ATR_CHANNEL_PARAMS.get(symbol.upper())

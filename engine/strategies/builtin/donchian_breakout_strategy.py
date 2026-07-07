"""
JARVIS TRADER — Donchian Breakout Strategy
Multi-confirmation entry with 5 gates + multi-exit system.
Ported from autotrade's keeper strategy (paxg_donchian_fibo_regime_4h).

Adapted for futures micro contracts (MCL, MNQ).
"""

from __future__ import annotations

from typing import Tuple

import pandas as pd

from strategies.base_strategy import BaseStrategy


class DonchianBreakoutStrategy(BaseStrategy):
    """
    Donchian channel breakout with 5-gate confirmation and multi-exit.

    Entry (ALL must pass — strict AND logic):
    1. EMA trend aligned (8 > 21) + slope positive
    2. ATR expanding (atr > sma_atr_20)
    3. Price above Donchian 20-period high (long) / below low (short)
    4. RSI > 54 (long) / < 46 (short)
    5. Volume > 20-period SMA

    Exit (OR logic — exit on ANY):
    1. ATR trailing stop (1.8x ATR from entry)
    2. Donchian exit channel (6-period low for longs)
    3. EMA crossover flip
    4. RSI midpoint cross (50)
    """

    name = "donchian_breakout_v1"
    description = "Donchian breakout + EMA slope + ATR regime + RSI + volume (5-gate)"
    version = "1.0"
    keep = False  # Needs WFE validation before promotion

    # Parameters (autotrade keeper defaults)
    fast_ema_period = 8
    slow_ema_period = 21
    breakout_period = 20
    exit_period = 6
    volume_lookback = 20
    atr_period = 14
    atr_regime_lookback = 20
    stop_atr_mult = 1.8
    rsi_period = 14
    long_rsi_threshold = 54
    short_rsi_threshold = 46

    def __init__(self, symbol: str = "MCL", timeframe: str = "1h") -> None:
        self.symbol = symbol
        self.timeframe = timeframe

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate Donchian breakout signals with 5-gate confirmation."""
        from backtest.indicators import (
            atr_regime,
            donchian_channels,
            ema_slope,
            rsi,
            volume_regime,
            wilder_atr,
        )

        result = df.copy()
        close = result["close"]
        high = result["high"]
        low = result["low"]
        volume = result["volume"]

        # Indicators
        fast_ema = close.ewm(span=self.fast_ema_period, adjust=False).mean()
        slow_ema = close.ewm(span=self.slow_ema_period, adjust=False).mean()
        slope = ema_slope(close, period=self.slow_ema_period, lookback=3)
        atr = wilder_atr(high, low, close, self.atr_period)
        expanding = atr_regime(high, low, close, self.atr_period, self.atr_regime_lookback)
        vol_reg = volume_regime(volume, self.volume_lookback)
        rsi_val = rsi(close, self.rsi_period)
        entry_high, entry_low, exit_high, exit_low = donchian_channels(
            high, low, self.breakout_period, self.exit_period
        )

        # Store for exit logic
        result["fast_ema"] = fast_ema
        result["slow_ema"] = slow_ema
        result["ema_slope"] = slope
        result["atr"] = atr
        result["atr_expanding"] = expanding
        result["rsi"] = rsi_val
        result["donchian_entry_high"] = entry_high
        result["donchian_entry_low"] = entry_low
        result["donchian_exit_high"] = exit_high
        result["donchian_exit_low"] = exit_low
        result["volume_regime"] = vol_reg
        result["vol_sma"] = volume.rolling(self.volume_lookback).mean()

        # Gate 1: EMA trend + slope
        trend_up = (fast_ema > slow_ema) & (slope > 0)
        trend_down = (fast_ema < slow_ema) & (slope < 0)

        # Gate 2: ATR expanding
        vol_expanding = expanding

        # Gate 3: Donchian breakout
        breakout_long = close > entry_high
        breakout_short = close < entry_low

        # Gate 4: RSI confirmation
        rsi_long = rsi_val > self.long_rsi_threshold
        rsi_short = rsi_val < self.short_rsi_threshold

        # Gate 5: Volume above average
        vol_confirm = volume > result["vol_sma"]

        # Entry signals (ALL gates must pass)
        long_entry = trend_up & vol_expanding & breakout_long & rsi_long & vol_confirm
        short_entry = trend_down & vol_expanding & breakout_short & rsi_short & vol_confirm

        # Signal column: 1=long, -1=short, 0=flat
        result["signal"] = 0
        result.loc[long_entry, "signal"] = 1
        result.loc[short_entry, "signal"] = -1

        # Exit signals for multi-exit system
        result["exit_ema_flip_long"] = fast_ema < slow_ema
        result["exit_ema_flip_short"] = fast_ema > slow_ema
        result["exit_rsi_long"] = rsi_val < 50
        result["exit_rsi_short"] = rsi_val > 50
        result["exit_donchian_long"] = close < exit_low
        result["exit_donchian_short"] = close > exit_high

        return result

    def get_stop_atr_mult(self) -> float:
        return self.stop_atr_mult

    def get_target_atr_mults(self) -> Tuple[float, float, float]:
        return (1.0, 2.618, 4.0)

    def get_params(self) -> dict:
        return {
            "fast_ema": self.fast_ema_period,
            "slow_ema": self.slow_ema_period,
            "breakout_period": self.breakout_period,
            "exit_period": self.exit_period,
            "stop_atr_mult": self.stop_atr_mult,
            "rsi_period": self.rsi_period,
            "long_rsi": self.long_rsi_threshold,
            "short_rsi": self.short_rsi_threshold,
        }

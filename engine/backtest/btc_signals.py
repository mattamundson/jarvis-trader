"""
BTCUSD Signal Generator for JARVIS TRADER (Phase 6.2)
=====================================================
Implements both Trend-Following (SMA) and Mean-Reversion (Bollinger)
signal families for Bitcoin spot/futures on Kraken.

Architecture mirrors MES (trend) and MCL (mean-rev) validated logic.
"""

from __future__ import annotations

import pandas as pd

from backtest.meanrev_signals import generate_bollinger_rsi_signals
from backtest.trend_signals import generate_sma_trend_signals

# Baseline BTC Parameters (to be refined via Gate v2)
BTC_TREND_PARAMS = {
    "fast": 50,
    "slow": 200,
    "atr_trail_mult": 2.5 # Bitcoin needs wider stops than equities
}

BTC_MEANREV_PARAMS = {
    "bb_period": 20,
    "bb_std": 2.5, # Bitcoin excursions are more volatile
    "rsi_period": 14,
    "rsi_long": 25.0, # Deeper oversold for crypto
    "rsi_short": 75.0,
    "stop_atr_mult": 2.0
}

def generate_btc_signals(df: pd.DataFrame, family: str = "trend") -> pd.DataFrame:
    """
    Dispatcher for BTCUSD signals.
    family: "trend" | "meanrev"
    """
    if family == "trend":
        return generate_sma_trend_signals(
            df,
            fast=BTC_TREND_PARAMS["fast"],
            slow=BTC_TREND_PARAMS["slow"],
            atr_trail_mult=BTC_TREND_PARAMS["atr_trail_mult"]
        )
    elif family == "meanrev":
        return generate_bollinger_rsi_signals(
            df,
            bb_period=BTC_MEANREV_PARAMS["bb_period"],
            bb_std=BTC_MEANREV_PARAMS["bb_std"],
            rsi_long=BTC_MEANREV_PARAMS["rsi_long"],
            rsi_short=BTC_MEANREV_PARAMS["rsi_short"],
            stop_atr_mult=BTC_MEANREV_PARAMS["stop_atr_mult"]
        )
    else:
        raise ValueError(f"Unknown signal family: {family}")

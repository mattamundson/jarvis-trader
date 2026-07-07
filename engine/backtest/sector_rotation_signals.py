"""
Sector Rotation Strategy (Phase 6.3)
=====================================
Calculates Weekly RSI for 11 SPDR Sector ETFs (XLK, XLF, XLE, etc.).
Generates signals: LONG the top 2 strength sectors, SHORT the bottom 2.

Implements the absolute momentum relative rotation thesis.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

# The 11 S&P 500 Sector SPDRs
SECTOR_ETFS = [
    "XLK", # Technology
    "XLF", # Financials
    "XLY", # Consumer Discretionary
    "XLP", # Consumer Staples
    "XLE", # Energy
    "XLI", # Industrials
    "XLB", # Materials
    "XLV", # Health Care
    "XLU", # Utilities
    "XLRE",# Real Estate
    "XLC"  # Communication Services
]

def _wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))

def generate_sector_rotation_signals(
    sector_dfs: Dict[str, pd.DataFrame],
    rsi_period: int = 14,
    top_n: int = 2,
    bottom_n: int = 2
) -> pd.DataFrame:
    """
    Generate rotation signals across multiple sector DataFrames.
    Expected sector_dfs: { "XLK": df_weekly, ... }

    Returns a unified signals DataFrame.
    """
    # 1. Calculate RSI for all sectors
    rsi_matrix = pd.DataFrame()
    for symbol, df in sector_dfs.items():
        if df.empty:
            continue
        rsi_matrix[symbol] = _wilder_rsi(df["close"], period=rsi_period)

    # 2. Generate signals at each timestamp
    # We rank sectors by RSI
    n = len(rsi_matrix)
    signals = []

    for i in range(n):
        row = rsi_matrix.iloc[i]
        if row.isna().any():
            signals.append({})
            continue

        ranked = row.sort_values(ascending=False)
        top = ranked.head(top_n).index.tolist()
        bottom = ranked.tail(bottom_n).index.tolist()

        signals.append({
            "top_sectors": top,
            "bottom_sectors": bottom,
            "rsi_ranks": ranked.to_dict()
        })

    result_df = pd.DataFrame(signals, index=rsi_matrix.index)

    # 3. Flatten into per-sector signal column for easier backtesting
    for symbol in sector_dfs.keys():
        col_name = f"{symbol}_signal"
        result_df[col_name] = "HOLD"

        # Long top N
        mask_long = result_df["top_sectors"].apply(
            lambda x, symbol=symbol: symbol in x if isinstance(x, list) else False
        )
        result_df.loc[mask_long, col_name] = "LONG"

        # Short bottom N
        mask_short = result_df["bottom_sectors"].apply(
            lambda x, symbol=symbol: symbol in x if isinstance(x, list) else False
        )
        result_df.loc[mask_short, col_name] = "SHORT"

    return result_df

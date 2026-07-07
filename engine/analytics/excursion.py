"""
JARVIS TRADER — MAE/MFE Excursion Analytics
=============================================
Pure, I/O-free module for computing Maximum Adverse Excursion (MAE) and
Maximum Favorable Excursion (MFE) for a single closed trade.

Definitions (per trade, over entry_time -> exit_time window):
    LONG:
        MAE = (entry_price - min(low  over window)) / entry_price  >= 0
        MFE = (max(high over window) - entry_price) / entry_price  >= 0
    SHORT:
        MAE = (max(high over window) - entry_price) / entry_price  >= 0
        MFE = (entry_price - min(low  over window)) / entry_price  >= 0

Both are expressed as unsigned % (0.0–1.0 floats) and optionally in USD
(multiplier * qty applied).

The function is pure: it takes a bars DataFrame (with 'high' and 'low'
columns), performs no I/O, and is trivially unit-testable.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("jarvis_trader.analytics.excursion")

# Recognised side labels that map to LONG direction
_LONG_SIDES = frozenset({"buy", "long", "buy_to_open", "buy to open"})


def compute_excursion(
    side: str,
    entry_price: float,
    bars_df,  # pd.DataFrame with columns: high, low (+ optionally timestamp)
    multiplier: float = 1.0,
    qty: float = 1.0,
) -> dict:
    """
    Compute MAE/MFE for a single closed trade.

    Parameters
    ----------
    side:
        Trade direction — any string in {'buy', 'long', 'buy_to_open', ...}
        is treated as LONG; everything else is SHORT.
    entry_price:
        Fill price at trade entry.
    bars_df:
        pd.DataFrame covering the trade window (entry_time -> exit_time
        inclusive).  Must contain columns ``high`` and ``low``.
        Rows outside the window are the caller's responsibility to pre-filter.
    multiplier:
        Dollar-per-point contract multiplier (e.g. 5.0 for MES).
        Defaults to 1.0 (pure price-point arithmetic).
    qty:
        Number of contracts.  Defaults to 1.0.

    Returns
    -------
    dict with keys:
        mae_pct   float  Maximum Adverse  Excursion as fraction (e.g. 0.015 = 1.5%)
        mfe_pct   float  Maximum Favorable Excursion as fraction
        mae_usd   float  MAE in dollars (mae_pct * entry_price * multiplier * qty)
        mfe_usd   float  MFE in dollars
        bar_count int    Number of bars used in the computation
    """

    if bars_df is None or (hasattr(bars_df, "__len__") and len(bars_df) == 0):
        return {"mae_pct": None, "mfe_pct": None, "mae_usd": None, "mfe_usd": None, "bar_count": 0}

    # Ensure we have 'high' and 'low' columns
    if "high" not in bars_df.columns or "low" not in bars_df.columns:
        logger.warning("compute_excursion: bars_df missing 'high' or 'low' columns")
        return {"mae_pct": None, "mfe_pct": None, "mae_usd": None, "mfe_usd": None, "bar_count": 0}

    max_high = float(bars_df["high"].max())
    min_low = float(bars_df["low"].min())
    bar_count = len(bars_df)

    is_long = side.lower().strip() in _LONG_SIDES

    if entry_price <= 0:
        logger.warning("compute_excursion: entry_price=%s is non-positive; skipping", entry_price)
        return {"mae_pct": None, "mfe_pct": None, "mae_usd": None, "mfe_usd": None, "bar_count": bar_count}

    if is_long:
        # Adverse move: price went below entry
        mae_pct = max(0.0, (entry_price - min_low) / entry_price)
        # Favorable move: price went above entry
        mfe_pct = max(0.0, (max_high - entry_price) / entry_price)
    else:
        # SHORT: adverse = high above entry; favorable = low below entry
        mae_pct = max(0.0, (max_high - entry_price) / entry_price)
        mfe_pct = max(0.0, (entry_price - min_low) / entry_price)

    dollar_factor = entry_price * multiplier * qty
    mae_usd = mae_pct * dollar_factor
    mfe_usd = mfe_pct * dollar_factor

    return {
        "mae_pct": round(mae_pct, 6),
        "mfe_pct": round(mfe_pct, 6),
        "mae_usd": round(mae_usd, 4),
        "mfe_usd": round(mfe_usd, 4),
        "bar_count": bar_count,
    }


def mfe_capture_ratio(mae_pct: Optional[float], mfe_pct: Optional[float]) -> Optional[float]:
    """
    MFE-capture ratio: how much of the available excursion did the trade
    actually capture (only meaningful for winning trades where mfe > 0).

    capture = (mfe_pct - mae_pct) / mfe_pct

    Returns None when inputs are missing or mfe_pct == 0.
    """
    if mae_pct is None or mfe_pct is None or mfe_pct == 0.0:
        return None
    return round((mfe_pct - mae_pct) / mfe_pct, 4)

"""
JARVIS TRADER — Keltner Channels (Python port)

Source: thinkorswim-scripts/shared_shared_shared_shared_kelt_3.01STUDY.ts
        (jp_keltner_multi_timeframe, J. Patel)

Ported logic (TOS defaults preserved):
- mid band  = SMA(price, length)                       [iAvgType = SIMPLE]
- shift     = factor * SMA(TrueRange, length)          [iTrueRangeAvgType = SIMPLE]
- upper     = mid + shift
- lower     = mid - shift
  with length=20, factor=3.0, price=CLOSE, displace=0 (the TOS input defaults).

The SMA-of-TrueRange basis is the existing ``backtest.indicators.sma_atr`` helper
(docstring: "used by Keltner channels"), so this reuses engine infrastructure
rather than recomputing True Range. The TOS multi-timeframe aggregation
(``iAggregationPeriod``) and ``iDisplace`` shift are not modelled — the port
operates on the passed bar series at its native timeframe with displace=0.

This is a pure indicator computation. It is NOT wired into signal routing or
auto-trade and reads no configuration — strictly an additional indicator/filter
layer (use-site can read kc_position / kc_pct_b as a regime or breakout gate).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.indicators import sma_atr

_KC_COLUMNS = (
    "kc_mid",
    "kc_upper",
    "kc_lower",
    "kc_width",
    "kc_pct_b",
    "kc_position",
)

_VALID_PRICES = ("close", "open", "high", "low", "hl2", "hlc3", "ohlc4")


def _price_series(df: pd.DataFrame, price: str) -> pd.Series:
    p = price.lower()
    if p == "hl2":
        return (df["high"] + df["low"]) / 2.0
    if p == "hlc3":
        return (df["high"] + df["low"] + df["close"]) / 3.0
    if p == "ohlc4":
        return (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0
    return df[p]


def compute_keltner(
    df: pd.DataFrame,
    length: int = 20,
    factor: float = 3.0,
    price: str = "close",
) -> pd.DataFrame:
    """
    Compute Keltner Channel columns on *df* (must have open/high/low/close).

    Returns *df* (a copy) with additional columns:
        kc_mid       — SMA(price, length), the channel mid-line
        kc_upper     — kc_mid + factor * SMA(TrueRange, length)
        kc_lower     — kc_mid - factor * SMA(TrueRange, length)
        kc_width     — kc_upper - kc_lower
        kc_pct_b     — (close - kc_lower) / kc_width  (0 at lower band, 1 at upper)
        kc_position  — "above" | "inside" | "below" | None  (None until bands warm up)

    Parameters
    ----------
    length : SMA lookback for both the mid-line and the True-Range shift (TOS iLength=20).
    factor : True-Range multiplier for the band half-width (TOS iFactor=3.0).
    price  : mid-line source — one of close/open/high/low/hl2/hlc3/ohlc4 (TOS iPrice, default CLOSE).
    """
    if price.lower() not in _VALID_PRICES:
        raise ValueError(f"price must be one of {_VALID_PRICES}, got {price!r}")

    out = df.copy()
    required = {"open", "high", "low", "close"}
    if df.empty or not required.issubset(df.columns):
        for col in _KC_COLUMNS:
            out[col] = None if col == "kc_position" else np.nan
        return out

    src = _price_series(out, price)
    mid = src.rolling(length).mean()
    shift = factor * sma_atr(out["high"], out["low"], out["close"], period=length)
    upper = mid + shift
    lower = mid - shift
    width = upper - lower

    close = out["close"]
    with np.errstate(invalid="ignore", divide="ignore"):
        pct_b = (close - lower) / width.where(width != 0)

    position = pd.Series([None] * len(out), index=out.index, dtype=object)
    defined = upper.notna() & lower.notna()
    position[defined & (close > upper)] = "above"
    position[defined & (close < lower)] = "below"
    position[defined & (close <= upper) & (close >= lower)] = "inside"

    out["kc_mid"] = mid
    out["kc_upper"] = upper
    out["kc_lower"] = lower
    out["kc_width"] = width
    out["kc_pct_b"] = pct_b
    out["kc_position"] = position
    return out

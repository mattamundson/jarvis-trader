"""
JARVIS TRADER — Entry Price Sanity Check
=========================================
Pre-submission validation that rejects orders where the proposed entry price
is so far from the current market price (measured in ATR units) that it
indicates a corrupted or mis-mapped price field.

Motivating incident: 2026-05-09 phantom-trade — 6 MES SHORT entries were
inserted at price 7398.5481, which was a stop_loss value copied into the
entry_price field.  The real market was ~7385; delta/ATR ~1.35 >> 1.0
threshold.  This check would have rejected all six.

Design constraints:
  - Pure Python — no async, no HTTP, no DB in the core predicate.
  - Does NOT modify safety_layer.py (additive sibling validation layer).
  - Does NOT modify config.py.
  - Default ON via ENABLE_ENTRY_PRICE_SANITY=1 (opt-out semantics).
  - Threshold tunable via ENTRY_PRICE_SANITY_MAX_ATR_DELTA (default 1.0).
"""

from __future__ import annotations

import logging
import os
from typing import Optional, Tuple

import pandas as pd

logger = logging.getLogger("jarvis_trader.risk.entry_price_sanity")

_ENV_ENABLE = "ENABLE_ENTRY_PRICE_SANITY"
_ENV_THRESHOLD = "ENTRY_PRICE_SANITY_MAX_ATR_DELTA"
_DEFAULT_MAX_ATR_DELTA = 1.0
_ATR_PERIOD = 14


# ---------------------------------------------------------------------------
# Feature flag (read fresh on every call — intentionally not module-cached)
# ---------------------------------------------------------------------------


def is_entry_price_sanity_enabled() -> bool:
    """Return True unless ENABLE_ENTRY_PRICE_SANITY is explicitly set to 0/false/no/off.

    Reads os.environ fresh on every call so the flag can be toggled at runtime
    without an engine restart (same pattern as ENABLE_AUTONOMOUS_PIPELINE).
    Default: enabled (opt-out semantics — safe-by-default).
    """
    raw = os.environ.get(_ENV_ENABLE, "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _get_max_atr_delta() -> float:
    """Read ENTRY_PRICE_SANITY_MAX_ATR_DELTA from env, default 1.0."""
    raw = os.environ.get(_ENV_THRESHOLD, "").strip()
    try:
        val = float(raw)
        if val > 0:
            return val
    except (TypeError, ValueError):
        pass
    return _DEFAULT_MAX_ATR_DELTA


# ---------------------------------------------------------------------------
# Pure predicate — no I/O
# ---------------------------------------------------------------------------


def is_entry_price_sane(
    symbol: str,
    entry_price: float,
    market_price: float,
    atr: float,
    max_atr_delta: float = _DEFAULT_MAX_ATR_DELTA,
) -> Tuple[bool, str]:
    """Check whether an entry price is plausible relative to market + ATR.

    Parameters
    ----------
    symbol:
        Instrument symbol (used only for logging context).
    entry_price:
        Proposed order entry price from the pipeline verdict.
    market_price:
        Current market price (last traded or mid price).
    atr:
        14-period ATR for the instrument (same unit as price).
    max_atr_delta:
        Maximum allowed |entry - market| / ATR ratio.  Default 1.0.

    Returns
    -------
    (is_sane: bool, reason: str)
        is_sane=True when the price passes. reason is the empty string on
        pass, or a human-readable rejection explanation on fail.
    """
    # Guard: market_price must be a positive finite number
    if market_price is None:
        return False, f"[{symbol}] market price unavailable — cannot validate entry {entry_price}"
    try:
        mkt = float(market_price)
    except (TypeError, ValueError):
        return False, f"[{symbol}] market price is not numeric ({market_price!r})"
    if mkt <= 0:
        return False, f"[{symbol}] market price unavailable — cannot validate entry {entry_price}"

    # Guard: ATR must be a positive finite number
    if atr is None:
        return False, f"[{symbol}] atr unavailable — cannot validate entry {entry_price}"
    try:
        atr_val = float(atr)
    except (TypeError, ValueError):
        return False, f"[{symbol}] atr is not numeric ({atr!r})"
    if atr_val <= 0:
        return (
            False,
            f"[{symbol}] atr={atr_val} is zero or negative — division guard triggered; "
            f"entry {entry_price} rejected",
        )

    # Core check
    delta_atr = abs(float(entry_price) - mkt) / atr_val
    if delta_atr > max_atr_delta:
        return (
            False,
            f"[{symbol}] entry_price={entry_price} is {delta_atr:.2f} ATR units from "
            f"market={mkt} (ATR={atr_val:.4f}); max allowed={max_atr_delta:.2f} — "
            "possible field corruption (stop_loss copied into entry_price?)",
        )

    return True, ""


# ---------------------------------------------------------------------------
# ATR helper — computes from a bars DataFrame
# ---------------------------------------------------------------------------


def _compute_atr_from_bars(df: "pd.DataFrame", period: int = _ATR_PERIOD) -> Optional[float]:
    """Compute the most recent Wilder ATR from an OHLCV DataFrame.

    Returns None if the DataFrame is empty or lacks the required columns.
    """
    if df is None or df.empty:
        return None
    required = {"high", "low", "close"}
    if not required.issubset(df.columns):
        return None
    if len(df) < period:
        return None

    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # Wilder smoothing (matches backtest/indicators.py wilder_atr)
    atr_series = pd.Series(index=tr.index, dtype=float)
    if len(tr) < period:
        return None
    atr_series.iloc[period - 1] = tr.iloc[:period].mean()
    for i in range(period, len(tr)):
        atr_series.iloc[i] = (atr_series.iloc[i - 1] * (period - 1) + tr.iloc[i]) / period

    last = atr_series.dropna()
    if last.empty:
        return None
    return float(last.iloc[-1])


# ---------------------------------------------------------------------------
# Async wrapper — fetches market price + ATR from data_manager
# ---------------------------------------------------------------------------


async def check_entry_price_sanity(
    symbol: str,
    entry_price: float,
    data_manager,
) -> Tuple[bool, str]:
    """Async wrapper that fetches market price and ATR from the data manager.

    Reads ENTRY_PRICE_SANITY_MAX_ATR_DELTA from env at call time so the
    threshold can be adjusted without an engine restart.

    Parameters
    ----------
    symbol:
        Instrument symbol.
    entry_price:
        Proposed entry price from the pipeline verdict.
    data_manager:
        MarketDataManager instance (engine/data/market_data.py).
        Must support get_current_price(symbol) and get_bars(symbol, ...).

    Returns
    -------
    (is_sane: bool, reason: str)
    """
    max_atr_delta = _get_max_atr_delta()

    # -- Fetch market price --
    market_price: Optional[float] = None
    try:
        price_result = await data_manager.get_current_price(symbol, is_futures=True)
        market_price = price_result.get("last_price")
    except Exception as exc:
        logger.warning("[ENTRY_PRICE_SANITY] get_current_price failed for %s: %s", symbol, exc)

    # -- Fetch ATR via bars --
    atr: Optional[float] = None
    try:
        bars = await data_manager.get_bars(
            symbol, lookback_days=30, timeframe="1h", is_futures=True
        )
        atr = _compute_atr_from_bars(bars, period=_ATR_PERIOD)
    except Exception as exc:
        logger.warning("[ENTRY_PRICE_SANITY] get_bars/atr failed for %s: %s", symbol, exc)

    is_sane, reason = is_entry_price_sane(
        symbol=symbol,
        entry_price=entry_price,
        market_price=market_price,
        atr=atr,
        max_atr_delta=max_atr_delta,
    )

    if not is_sane:
        logger.error("[ENTRY_PRICE_SANITY] rejected: %s", reason)

    return is_sane, reason

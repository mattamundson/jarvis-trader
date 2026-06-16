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
_ENV_MIN_ATR = "ENTRY_PRICE_SANITY_MIN_ATR"
_ENV_REF_ENABLE = "ENABLE_PRICE_REF_CONTAMINATION_CHECK"
_ENV_REF_DEVIATION = "ENTRY_PRICE_SANITY_MAX_REF_DEVIATION_PCT"
_DEFAULT_MAX_ATR_DELTA = 1.0
_DEFAULT_MIN_ATR_FLOOR = 0.0  # 0 = no floor (backward compatible default)
# Era-aware reference deviation: a candidate (or the spot quote itself) more
# than this fraction away from the robust median of recent bar closes is treated
# as a wrong-era / stale-cache contamination. 0.15 = 15%. Index futures never
# move 15% in an hour (daily limit-down halts kick in at 7/13/20%), so this is a
# safe corruption threshold while leaving real intraday moves untouched.
_DEFAULT_MAX_REF_DEVIATION_PCT = 0.15
_ATR_PERIOD = 14
# Bars sampled for the robust recent-price reference (median is outlier-robust,
# so a handful of contaminated bars among mostly-good ones does not move it).
_REF_RECENT_BARS = 48


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


def _get_min_atr_floor() -> float:
    """Read ENTRY_PRICE_SANITY_MIN_ATR from env, default 0.0 (no floor).

    When set to a positive value (e.g. 1.5 for MGC), the effective ATR used
    in the sanity check is max(measured_atr, floor). This prevents the check
    from over-triggering during low-volatility windows (e.g. MGC 10pm-2am CT
    where 1h ATR can drop to 0.5-0.8 pts) while leaving the check fully intact
    when the measured ATR is comfortably above the floor.
    """
    raw = os.environ.get(_ENV_MIN_ATR, "").strip()
    try:
        val = float(raw)
        if val >= 0:
            return val
    except (TypeError, ValueError):
        pass
    return _DEFAULT_MIN_ATR_FLOOR


def is_price_ref_check_enabled() -> bool:
    """Return True unless ENABLE_PRICE_REF_CONTAMINATION_CHECK is set to 0/false/no/off.

    Opt-out semantics (safe-by-default), read fresh each call so it can be
    toggled at runtime. Gates the era-aware reference-deviation check that
    catches wrong-era-but-band-valid prices (e.g. an MES 5300 bar in a 7400
    market — within the static futures band, so the band check misses it).
    """
    raw = os.environ.get(_ENV_REF_ENABLE, "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _get_max_ref_deviation_pct() -> float:
    """Read ENTRY_PRICE_SANITY_MAX_REF_DEVIATION_PCT from env, default 0.15."""
    raw = os.environ.get(_ENV_REF_DEVIATION, "").strip()
    try:
        val = float(raw)
        if val > 0:
            return val
    except (TypeError, ValueError):
        pass
    return _DEFAULT_MAX_REF_DEVIATION_PCT


# ---------------------------------------------------------------------------
# Pure predicate — no I/O
# ---------------------------------------------------------------------------


def is_entry_price_sane(
    symbol: str,
    entry_price: float,
    market_price: float,
    atr: float,
    max_atr_delta: float = _DEFAULT_MAX_ATR_DELTA,
    min_atr_floor: float = _DEFAULT_MIN_ATR_FLOOR,
    recent_ref: Optional[float] = None,
    max_ref_deviation_pct: float = _DEFAULT_MAX_REF_DEVIATION_PCT,
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
        Maximum allowed |entry - market| / effective_ATR ratio.  Default 1.0.
    min_atr_floor:
        Minimum ATR floor (default 0.0 = no floor). When set to a positive
        value the effective ATR is max(atr, min_atr_floor), preventing the
        check from over-triggering in low-vol sessions (e.g. MGC overnight).
        Set via ENTRY_PRICE_SANITY_MIN_ATR env var; does not weaken the check
        when measured ATR is above the floor.

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

    # Apply optional ATR floor (low-vol regime guard — e.g. MGC 10pm-2am CT)
    floor = float(min_atr_floor) if min_atr_floor and min_atr_floor > 0 else 0.0
    effective_atr = max(atr_val, floor)

    # Core check
    delta_atr = abs(float(entry_price) - mkt) / effective_atr
    if delta_atr > max_atr_delta:
        floor_note = (
            f" (floored from ATR={atr_val:.4f} by min_atr_floor={floor:.4f})"
            if effective_atr > atr_val
            else ""
        )
        return (
            False,
            f"[{symbol}] entry_price={entry_price} is {delta_atr:.2f} ATR units from "
            f"market={mkt} (effective_ATR={effective_atr:.4f}{floor_note}); "
            f"max allowed={max_atr_delta:.2f} — "
            "possible field corruption (stop_loss copied into entry_price?)",
        )

    # Era-aware reference cross-check — catches the failure mode the ATR check
    # above structurally CANNOT: when the spot quote itself is contaminated
    # (e.g. a stale-cache MES bar at 5300 in a 7400 market), entry≈market so
    # delta_atr≈0 and the ATR check passes. A static futures price band also
    # misses it (5300 is a valid *2024* MES price, inside the 3000-8500 band).
    # The robust median of recent bar closes stays ~7400 through a few bad
    # bars, so deviation-from-reference flags both the corrupted quote and the
    # corrupted entry. Only runs when a reference is supplied.
    if recent_ref is not None:
        try:
            ref = float(recent_ref)
        except (TypeError, ValueError):
            ref = 0.0
        if ref > 0 and max_ref_deviation_pct > 0:
            mkt_dev = abs(mkt - ref) / ref
            if mkt_dev > max_ref_deviation_pct:
                return (
                    False,
                    f"[{symbol}] market price={mkt} deviates {mkt_dev:.1%} from the recent "
                    f"price reference={ref:.4f} (max {max_ref_deviation_pct:.1%}) — the spot "
                    "quote itself looks stale/contaminated; refusing to validate against an "
                    "unreliable reference (fail-safe NO_TRADE).",
                )
            entry_dev = abs(float(entry_price) - ref) / ref
            if entry_dev > max_ref_deviation_pct:
                return (
                    False,
                    f"[{symbol}] entry_price={entry_price} deviates {entry_dev:.1%} from the "
                    f"recent price reference={ref:.4f} (max {max_ref_deviation_pct:.1%}) — "
                    "wrong-era / stale-cache price (band-valid but not current).",
                )

    return True, ""


def robust_recent_reference(df: "pd.DataFrame", n_bars: int = _REF_RECENT_BARS) -> Optional[float]:
    """Median close of the most recent ``n_bars`` bars — an outlier-robust price
    reference. The median (not mean) is deliberate: a handful of contaminated
    bars among mostly-good ones does not move it, so it stays a trustworthy
    anchor for the era-aware deviation check. Returns None if unavailable."""
    if df is None or getattr(df, "empty", True):
        return None
    if "close" not in df.columns:
        return None
    closes = df["close"].astype(float).dropna()
    if closes.empty:
        return None
    recent = closes.iloc[-n_bars:] if len(closes) > n_bars else closes
    try:
        return float(recent.median())
    except (TypeError, ValueError):
        return None


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
    min_atr_floor = _get_min_atr_floor()

    # -- Fetch market price --
    market_price: Optional[float] = None
    try:
        price_result = await data_manager.get_current_price(symbol, is_futures=True)
        market_price = price_result.get("last_price")
    except Exception as exc:
        logger.warning("[ENTRY_PRICE_SANITY] get_current_price failed for %s: %s", symbol, exc)

    # -- Fetch ATR + robust recent-price reference via bars (one fetch) --
    atr: Optional[float] = None
    recent_ref: Optional[float] = None
    try:
        bars = await data_manager.get_bars(
            symbol, lookback_days=30, timeframe="1h", is_futures=True
        )
        atr = _compute_atr_from_bars(bars, period=_ATR_PERIOD)
        if is_price_ref_check_enabled():
            recent_ref = robust_recent_reference(bars)
    except Exception as exc:
        logger.warning("[ENTRY_PRICE_SANITY] get_bars/atr failed for %s: %s", symbol, exc)

    is_sane, reason = is_entry_price_sane(
        symbol=symbol,
        entry_price=entry_price,
        market_price=market_price,
        atr=atr,
        max_atr_delta=max_atr_delta,
        min_atr_floor=min_atr_floor,
        recent_ref=recent_ref,
        max_ref_deviation_pct=_get_max_ref_deviation_pct(),
    )

    if not is_sane:
        logger.error("[ENTRY_PRICE_SANITY] rejected: %s", reason)

    return is_sane, reason

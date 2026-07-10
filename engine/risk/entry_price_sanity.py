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
_ENV_REQUIRE_LIVE = "ENTRY_PRICE_SANITY_REQUIRE_LIVE_SOURCE"
_ENV_FRESHNESS_ENABLE = "ENABLE_ENTRY_PRICE_FRESHNESS"
_ENV_MAX_BAR_AGE = "ENTRY_PRICE_MAX_BAR_AGE_SECONDS"
_DEFAULT_MAX_ATR_DELTA = 1.0

# Price-source provenance: the relative entry-sanity checks (ATR delta + recent
# reference) all go BLIND when the *entire* feed is degraded — when IBKR/Schwab/
# TradingView are all down, get_current_price + get_bars fall through to the
# offline CSV cache and can serve a self-consistent WRONG-ERA quote (e.g. a 2024
# MES ~5300 while the real market is ~7500). Entry≈market≈bars-median, so every
# relative check passes and a phantom trade is enqueued (the 2026-06-16 MES short
# @5299 vs a 7520 market). The provenance check is the absolute anchor those
# checks structurally cannot be: a price whose source is the offline fallback (or
# is unavailable) is refused for live trading outright — fail-safe NO_TRADE —
# regardless of how plausible the number looks. `source` strings come from
# MarketDataManager.get_current_price/get_tick_price.
#
# Only EXPLICIT offline-fallback sources are rejected. An unknown / missing source
# (e.g. an IBKR snapshot that doesn't tag itself) is treated as live and left to
# the relative checks — so this anchor never blocks a genuine live fill, it only
# trips on the data manager's own "I had to use the offline cache" admission.
# ibkr_delayed (2026-07-09): IB's marketDataType 3/4 (Delayed/Delayed-frozen,
# served when the account lacks a live subscription) is the same "I had to use
# a non-live tier" admission as csv_cache — a 15-20min-old futures quote is the
# same wrong-era risk this anchor exists to catch, just from a different feed.
_OFFLINE_FALLBACK_SOURCES = frozenset({"csv_cache", "unavailable", "error", "ibkr_delayed"})
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
# Bar-timestamp freshness ceiling. The provenance + ATR + era anchors are all
# blind to the ONE case where a stale CSV cache (a) tags itself as a live source
# (or carries no source tag, so the provenance anchor treats it as live) AND
# (b) is internally self-consistent — every bar is from the same wrong era, so
# entry ≈ market ≈ recent-median and all three relative checks pass. The 2026-06-29
# MES auto-approve contamination was exactly this: fills booked at a months-old
# cached ~5300 while the real market was ~7497. The orthogonal signal those checks
# structurally cannot see is the bar's own AGE: a price carried on a bar from hours
# ago is stale no matter how plausible the number. 7200s = 2h tolerates the ~1h CME
# maintenance break plus margin; a multi-hour freeze (or weekend-spanning stale
# cache) trips it. Fail-safe: tripping only ever REFUSES (NO_TRADE), never permits —
# so a false positive (e.g. just after a weekend reopen, before fresh bars print)
# simply skips a paper fill rather than risking a contaminated one.
_DEFAULT_MAX_BAR_AGE_SECONDS = 7200


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


def is_require_live_source_enabled() -> bool:
    """Return True unless ENTRY_PRICE_SANITY_REQUIRE_LIVE_SOURCE is set to 0/false/no/off.

    Opt-out semantics (safe-by-default), read fresh each call so it can be toggled
    at runtime. When enabled, an entry whose market price was sourced from the
    offline CSV fallback (or is unavailable) is rejected for live trading — the
    absolute provenance anchor that the relative ATR/reference checks cannot be.
    """
    raw = os.environ.get(_ENV_REQUIRE_LIVE, "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def is_offline_fallback_source(source: Optional[str]) -> bool:
    """True when ``source`` is an EXPLICIT offline-fallback / unavailable marker.

    Pure predicate over the ``source`` string returned by
    MarketDataManager.get_current_price/get_tick_price. Only ``csv_cache``,
    ``unavailable``, ``error`` and ``ibkr_delayed`` count — an unknown/missing
    source returns False (treated as live) so the anchor never blocks a genuine
    live fill.
    """
    return (source or "").strip().lower() in _OFFLINE_FALLBACK_SOURCES


def is_bar_freshness_check_enabled() -> bool:
    """Return True unless ENABLE_ENTRY_PRICE_FRESHNESS is set to 0/false/no/off.

    Opt-out semantics (safe-by-default), read fresh each call so it can be toggled
    at runtime. Gates the bar-timestamp freshness anchor that catches a stale/frozen
    feed whose price value is self-consistent and live-looking (the 2026-06-29
    frozen-MES-5300 auto-approve contamination), which the relative anchors miss.
    """
    raw = os.environ.get(_ENV_FRESHNESS_ENABLE, "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _get_max_bar_age_seconds() -> int:
    """Read ENTRY_PRICE_MAX_BAR_AGE_SECONDS from env, default 7200 (2h), floor 60."""
    raw = os.environ.get(_ENV_MAX_BAR_AGE, "").strip()
    try:
        val = int(raw)
        if val >= 60:
            return val
    except (TypeError, ValueError):
        pass
    return _DEFAULT_MAX_BAR_AGE_SECONDS


def latest_bar_age_seconds(
    df: "pd.DataFrame", now: Optional["pd.Timestamp"] = None
) -> Optional[float]:
    """Age in seconds of the most recent bar's timestamp; None if undeterminable.

    Pure over ``df`` + injected ``now`` (defaults to the current UTC time). Reads
    the timestamp from a DatetimeIndex first, then falls back to a
    timestamp/time/date/datetime column. Any naive timestamp is assumed UTC. A
    None return means "no usable timestamp" — the caller treats that as
    "freshness indeterminate, skip this anchor" rather than rejecting, so
    timestamp-less synthetic frames don't false-trip while real bars (which
    always carry their original timestamps, old ones included) are judged.
    """
    if df is None or getattr(df, "empty", True):
        return None
    ts = None
    idx = getattr(df, "index", None)
    try:
        if idx is not None and len(idx) > 0:
            candidate = idx[-1]
            # Only accept an index value that looks like a real datetime.
            if hasattr(candidate, "year") or isinstance(candidate, pd.Timestamp):
                ts = candidate
    except Exception:
        ts = None
    if ts is None:
        cols = getattr(df, "columns", [])
        for col in ("timestamp", "time", "date", "datetime"):
            if col in cols:
                try:
                    ts = df[col].iloc[-1]
                except Exception:
                    ts = None
                break
    if ts is None:
        return None
    try:
        ts = pd.Timestamp(ts)
    except Exception:
        return None
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    now_ts = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    if now_ts.tz is None:
        now_ts = now_ts.tz_localize("UTC")
    else:
        now_ts = now_ts.tz_convert("UTC")
    try:
        return float((now_ts - ts).total_seconds())
    except Exception:
        return None


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
    is_futures: bool = True,
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
    is_futures:
        Whether ``symbol`` is a futures contract. Routed to the data manager so
        equities (OPTIONS_WATCHLIST) are priced on the correct feed. Defaults to
        True to preserve the original futures-only behavior for existing callers.

    Returns
    -------
    (is_sane: bool, reason: str)
    """
    max_atr_delta = _get_max_atr_delta()
    min_atr_floor = _get_min_atr_floor()

    # -- Fetch market price (+ provenance) --
    market_price: Optional[float] = None
    price_source: Optional[str] = None
    try:
        price_result = await data_manager.get_current_price(symbol, is_futures=is_futures)
        market_price = price_result.get("last_price")
        price_source = price_result.get("source")
    except Exception as exc:
        logger.warning("[ENTRY_PRICE_SANITY] get_current_price failed for %s: %s", symbol, exc)

    # -- Provenance anchor (absolute, source-of-truth) --
    # If the quote came from the offline CSV fallback (or no source at all), the
    # live feed is degraded and EVERY relative check below is validating the entry
    # against the same possibly-contaminated source. Refuse outright — this is the
    # only check that catches a fully-self-consistent wrong-era feed.
    if is_require_live_source_enabled() and is_offline_fallback_source(price_source):
        reason = (
            f"[{symbol}] entry_price={entry_price} validated against the OFFLINE price "
            f"source '{price_source}' (live feeds degraded/down — fell through to the "
            f"CSV cache / unavailable). Refusing to trade on stale/offline data — "
            f"fail-safe NO_TRADE. The relative price checks cannot see wrong-era "
            f"contamination when the whole feed agrees with itself."
        )
        logger.error("[ENTRY_PRICE_SANITY] rejected (provenance): %s", reason)
        return False, reason

    # -- Fetch ATR + robust recent-price reference via bars (one fetch) --
    atr: Optional[float] = None
    recent_ref: Optional[float] = None
    bars = None
    try:
        bars = await data_manager.get_bars(
            symbol, lookback_days=30, timeframe="1h", is_futures=is_futures
        )
        atr = _compute_atr_from_bars(bars, period=_ATR_PERIOD)
        if is_price_ref_check_enabled():
            recent_ref = robust_recent_reference(bars)
    except Exception as exc:
        logger.warning("[ENTRY_PRICE_SANITY] get_bars/atr failed for %s: %s", symbol, exc)

    # -- Bar-timestamp freshness anchor (absolute, orthogonal to price value) --
    # Reuses the bars already fetched above (zero extra I/O). The provenance, ATR
    # and era anchors can all be fooled by a stale cache that looks live and is
    # internally self-consistent; the bar's own age cannot be. Fire only when the
    # timestamp is determinable (real bars always carry one — old timestamps
    # included); skip-with-warning when it isn't, so timestamp-less callers fall
    # through to the relative anchors rather than false-tripping. Refusing here is
    # fail-safe NO_TRADE — it can only block a fill, never permit a new one.
    if is_bar_freshness_check_enabled() and bars is not None and not getattr(bars, "empty", True):
        age = latest_bar_age_seconds(bars)
        if age is None:
            logger.warning(
                "[ENTRY_PRICE_SANITY] %s: latest-bar timestamp undeterminable — "
                "freshness anchor skipped (relative anchors still apply).",
                symbol,
            )
        else:
            max_age = _get_max_bar_age_seconds()
            if age > max_age:
                reason = (
                    f"[{symbol}] entry_price={entry_price} validated against a STALE bar: "
                    f"latest bar is {int(age)}s old (> {max_age}s ceiling). The price feed is "
                    f"frozen/stale (cache fallback while the live feed is degraded) — refusing "
                    f"to trade on a stale bar regardless of how plausible the number looks "
                    f"(fail-safe NO_TRADE)."
                )
                logger.error("[ENTRY_PRICE_SANITY] rejected (stale bar): %s", reason)
                return False, reason

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

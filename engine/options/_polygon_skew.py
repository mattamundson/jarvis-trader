"""
JARVIS Trader Options Engine — Polygon Skew & Term-Structure Helpers
====================================================================
Low-level helpers for fetching put/call IV skew and term-structure from
the Polygon options API.  Consumed exclusively by ``chain_fetcher.py``
(``get_pc_skew`` and ``get_term_structure``).

Not part of the public package API — import only from ``chain_fetcher``.

Key design decisions
--------------------
* **5-minute TTL module-level cache** — option chains are slow (Polygon
  free tier: ~5 req/min) and expensive.  A plain dict + ``time.monotonic``
  check avoids any external dependency.
* **Synchronous only** — both public callers (``OptionsAnalyst`` and
  ``options_router``) invoke the functions synchronously inside
  ``try / except ImportError`` guards.
* **Empty-dict / None on any failure** — callers abstain gracefully rather
  than crashing the debate stack.
"""

from __future__ import annotations

import logging
import math
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_POLYGON_BASE = "https://api.polygon.io"

# ---------------------------------------------------------------------------
# TTL cache
# ---------------------------------------------------------------------------

_CACHE: dict[str, tuple[Any, float]] = {}
_CACHE_TTL_SECONDS: float = 300.0  # 5 minutes


def _cache_get(key: str) -> Optional[Any]:
    """Return cached payload if unexpired, else None."""
    entry = _CACHE.get(key)
    if entry is None:
        return None
    payload, expiry_ts = entry
    if time.monotonic() > expiry_ts:
        del _CACHE[key]
        return None
    return payload


def _cache_set(key: str, value: Any, ttl: float = _CACHE_TTL_SECONDS) -> None:
    """Store value in the cache with a TTL-based expiry."""
    _CACHE[key] = (value, time.monotonic() + ttl)


# ---------------------------------------------------------------------------
# Polygon HTTP client
# ---------------------------------------------------------------------------


def _polygon_api_key() -> str:
    """Return POLYGON_API_KEY or raise RuntimeError."""
    key = os.environ.get("POLYGON_API_KEY", "").strip()
    if not key:
        raise RuntimeError("POLYGON_API_KEY not set in environment")
    return key


def _polygon_get(path: str, params: Optional[dict] = None) -> Any:
    """Synchronous GET against the Polygon REST API.

    Args:
        path:   URL path, e.g. ``"/v3/reference/options/contracts"``.
        params: Optional query-string parameters.

    Returns:
        Parsed JSON body (dict or list).

    Raises:
        httpx.HTTPStatusError on non-2xx responses.
        RuntimeError when POLYGON_API_KEY is absent.
    """
    import httpx

    api_key = _polygon_api_key()
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = httpx.get(
        f"{_POLYGON_BASE}{path}",
        params=params or {},
        headers=headers,
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Expiry selection
# ---------------------------------------------------------------------------


def list_expiries(symbol: str, min_days: int = 2, max_days: int = 14) -> list[str]:
    """Return sorted expiry date strings for ``symbol`` within [min_days, max_days].

    Queries Polygon ``/v3/reference/options/contracts`` and de-duplicates
    expiry dates.  Results are cached for 5 minutes.

    Args:
        symbol:   Underlying ticker.
        min_days: Minimum DTE (inclusive).  Default 2 avoids 0DTE noise.
        max_days: Maximum DTE (inclusive).  Default 14 avoids LEAPs.

    Returns:
        Sorted list of ``"YYYY-MM-DD"`` strings.  Empty on error.
    """
    cache_key = f"expiries:{symbol}:{min_days}:{max_days}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        today = datetime.now(tz=timezone.utc).date()
        body = _polygon_get(
            "/v3/reference/options/contracts",
            params={
                "underlying_ticker": symbol,
                "expiration_date.gte": (today + timedelta(days=min_days)).isoformat(),
                "expiration_date.lte": (today + timedelta(days=max_days)).isoformat(),
                "limit": 250,
            },
        )
        expiries = sorted(
            {r["expiration_date"] for r in body.get("results", []) if "expiration_date" in r}
        )
        _cache_set(cache_key, expiries)
        return expiries
    except Exception as exc:
        logger.debug("[_polygon_skew] list_expiries(%s) failed: %s", symbol, exc)
        return []


def nearest_expiry(symbol: str, min_days: int = 2, max_days: int = 14) -> Optional[str]:
    """Return the nearest expiry within [min_days, max_days], or None."""
    expiries = list_expiries(symbol, min_days=min_days, max_days=max_days)
    return expiries[0] if expiries else None


def front_n_expiries(symbol: str, n: int = 3) -> list[str]:
    """Return the front ``n`` expiries available (2–90 DTE window).

    Uses a wider window than ``list_expiries`` to guarantee front-week,
    front-month, and second-month candidates are available.
    """
    cache_key = f"front_expiries:{symbol}:{n}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        today = datetime.now(tz=timezone.utc).date()
        body = _polygon_get(
            "/v3/reference/options/contracts",
            params={
                "underlying_ticker": symbol,
                "expiration_date.gte": (today + timedelta(days=2)).isoformat(),
                "expiration_date.lte": (today + timedelta(days=90)).isoformat(),
                "limit": 250,
            },
        )
        expiries = sorted(
            {r["expiration_date"] for r in body.get("results", []) if "expiration_date" in r}
        )[:n]
        _cache_set(cache_key, expiries)
        return expiries
    except Exception as exc:
        logger.debug("[_polygon_skew] front_n_expiries(%s) failed: %s", symbol, exc)
        return []


# ---------------------------------------------------------------------------
# Polygon snapshot fetch
# ---------------------------------------------------------------------------


def fetch_chain_snapshot(symbol: str, expiry: str) -> list[dict]:
    """Fetch option snapshots for ``symbol`` / ``expiry`` from Polygon.

    Each result dict contains at minimum:
    * ``details.contract_type``  — ``"call"`` or ``"put"``
    * ``details.strike_price``   — float
    * ``implied_volatility``     — float (decimal, e.g. 0.22 for 22 %)
    * ``greeks.delta``           — float (signed)

    Results are cached for 5 minutes.

    Returns:
        List of contract dicts.  Empty list on any error.
    """
    cache_key = f"snapshot:{symbol}:{expiry}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        body = _polygon_get(
            f"/v3/snapshot/options/{symbol}",
            params={"expiration_date": expiry, "limit": 250},
        )
        results: list[dict] = body.get("results", [])
        _cache_set(cache_key, results)
        return results
    except Exception as exc:
        logger.debug("[_polygon_skew] fetch_chain_snapshot(%s, %s) failed: %s", symbol, expiry, exc)
        return []


def spot_price_from_polygon(symbol: str) -> Optional[float]:
    """Return previous-close price for ``symbol`` via Polygon, or None."""
    cache_key = f"spot:{symbol}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        body = _polygon_get(f"/v2/aggs/ticker/{symbol}/prev", params={"adjusted": "true"})
        results = body.get("results", [])
        if results:
            spot = float(results[0].get("c", 0))
            if spot > 0:
                _cache_set(cache_key, spot)
                return spot
    except Exception as exc:
        logger.debug("[_polygon_skew] spot_price_from_polygon(%s) failed: %s", symbol, exc)
    return None


# ---------------------------------------------------------------------------
# IV computation helpers
# ---------------------------------------------------------------------------


def iv_at_delta(
    contracts: list[dict],
    target_delta: float,
    side: str,
) -> Optional[float]:
    """Return the implied volatility closest to ``target_delta`` for ``side``.

    Searches all contracts of the specified side, filters out bad IV/delta
    values, and returns the IV of the contract whose absolute delta is
    nearest to ``target_delta``.

    Args:
        contracts:    Polygon snapshot contract list.
        target_delta: Absolute delta to target (e.g. ``0.25``).
        side:         ``"call"`` or ``"put"``.

    Returns:
        Implied volatility as a decimal fraction, or None.
    """
    side = side.lower()
    candidates: list[tuple[float, float]] = []  # (abs_delta, iv)

    for c in contracts:
        details = c.get("details", {}) or {}
        greeks = c.get("greeks", {}) or {}
        day = c.get("day", {}) or {}

        if details.get("contract_type", "").lower() != side:
            continue

        iv_raw = c.get("implied_volatility") or day.get("iv")
        delta_raw = greeks.get("delta")
        if iv_raw is None or delta_raw is None:
            continue

        iv = float(iv_raw)
        delta = abs(float(delta_raw))
        if iv <= 0 or not math.isfinite(iv) or not math.isfinite(delta):
            continue

        candidates.append((delta, iv))

    if not candidates:
        return None

    # Nearest-delta match
    return min(candidates, key=lambda x: abs(x[0] - target_delta))[1]


def atm_iv(contracts: list[dict], spot: float) -> Optional[float]:
    """Return the average IV of ATM call + put at the strike nearest to ``spot``.

    Args:
        contracts: Polygon snapshot contract list (mixed calls + puts).
        spot:      Current underlying price.

    Returns:
        Average ATM IV as a decimal fraction, or None if insufficient data.
    """
    if not contracts or spot <= 0:
        return None

    # Collect per-strike, per-side IVs
    by_strike: dict[float, dict[str, float]] = {}
    for c in contracts:
        details = c.get("details", {}) or {}
        day = c.get("day", {}) or {}
        ctype = details.get("contract_type", "").lower()
        strike_raw = details.get("strike_price")
        iv_raw = c.get("implied_volatility") or day.get("iv")
        if strike_raw is None or iv_raw is None:
            continue
        iv = float(iv_raw)
        if iv <= 0 or not math.isfinite(iv):
            continue
        strike = float(strike_raw)
        if strike not in by_strike:
            by_strike[strike] = {}
        if ctype in ("call", "put"):
            by_strike[strike][ctype] = iv

    if not by_strike:
        return None

    nearest = min(by_strike.keys(), key=lambda k: abs(k - spot))
    ivs = list(by_strike[nearest].values())
    return sum(ivs) / len(ivs) if ivs else None

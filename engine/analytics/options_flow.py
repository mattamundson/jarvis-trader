"""Dealer gamma-exposure (GEX) helper for the intraday regime snapshot.

`compute_gex` is pure and fully unit-testable: it turns an options-chain
snapshot into a {flow_signal, net_gex, gex_flip_level} reading. `get_options_flow`
is the thin, network-touching wrapper that fetches a chain from Polygon and feeds
it to `compute_gex`, returning None on any failure (no API key, no chain, no
gamma/OI). The regime endpoint treats None as "not wired" and never fakes a value.

Dealer-GEX convention (documented + unit tested):
  per-strike GEX = sign * gamma * open_interest * multiplier * spot^2 * 0.01
  where sign = +1 for calls, -1 for puts (dealers long calls / short puts).
  Positive net GEX  -> dealers are long gamma -> vol-suppressing / supportive  -> BULLISH lean.
  Negative net GEX  -> dealers are short gamma -> moves amplified to the downside -> BEARISH lean.
  Flip (zero-gamma) level = strike where cumulative GEX crosses zero.
"""

from __future__ import annotations

import logging
from typing import Optional, TypedDict

logger = logging.getLogger(__name__)

# Equity options contract size. Index/futures options would differ; equities are
# the only chain source wired today, so 100 is correct for SPY/QQQ/AAPL/etc.
_CONTRACT_MULTIPLIER = 100
# Net GEX within this fraction of gross GEX reads NEUTRAL (avoids sign jitter).
_NEUTRAL_BAND_FRAC = 0.05


class OptionsFlow(TypedDict):
    flow_signal: str  # "BULLISH" | "BEARISH" | "NEUTRAL"
    net_gex: float  # signed dollars
    gex_flip_level: float  # price


def _contract_fields(c: dict) -> Optional[tuple[float, float, float, int]]:
    """Extract (gamma, open_interest, strike, sign) or None if any are missing."""
    details = c.get("details") or {}
    greeks = c.get("greeks") or {}
    gamma = greeks.get("gamma")
    strike = details.get("strike_price")
    ctype = details.get("contract_type")
    # Polygon exposes OI at the top level on the v3 snapshot; fall back to day block.
    oi = c.get("open_interest")
    if oi is None:
        oi = (c.get("day") or {}).get("open_interest")
    if gamma is None or oi is None or strike is None or ctype not in ("call", "put"):
        return None
    sign = 1 if ctype == "call" else -1
    return float(gamma), float(oi), float(strike), sign


def _flip_level(per_strike: dict[float, float]) -> Optional[float]:
    """Zero-gamma strike: where cumulative GEX (low->high strike) crosses zero."""
    strikes = sorted(per_strike)
    if not strikes:
        return None
    if len(strikes) == 1:
        return round(strikes[0], 2)
    cum = 0.0
    prev_strike = strikes[0]
    prev_cum = 0.0
    for i, k in enumerate(strikes):
        cum += per_strike[k]
        if i > 0 and (prev_cum <= 0 < cum or prev_cum >= 0 > cum):
            # Linear-interpolate the strike where cumulative GEX == 0.
            span = cum - prev_cum
            frac = (0.0 - prev_cum) / span if span else 0.0
            return round(prev_strike + (k - prev_strike) * frac, 2)
        prev_strike, prev_cum = k, cum
    # No sign change — fall back to the strike whose cumulative is nearest zero.
    running = 0.0
    best_k, best_abs = strikes[0], float("inf")
    for k in strikes:
        running += per_strike[k]
        if abs(running) < best_abs:
            best_k, best_abs = k, abs(running)
    return round(best_k, 2)


def compute_gex(
    contracts: list[dict],
    spot: float,
    multiplier: int = _CONTRACT_MULTIPLIER,
    neutral_band_frac: float = _NEUTRAL_BAND_FRAC,
) -> Optional[OptionsFlow]:
    """Net GEX, flip level, and a flow signal from a chain snapshot.

    Returns None when no contract carries usable gamma + open interest, or when
    spot is non-positive. Never raises on malformed contract dicts.
    """
    if not contracts or spot is None or spot <= 0:
        return None

    per_strike: dict[float, float] = {}
    net_gex = 0.0
    gross_gex = 0.0
    used = 0
    spot_sq_scaled = spot * spot * 0.01
    for c in contracts:
        fields = _contract_fields(c)
        if fields is None:
            continue
        gamma, oi, strike, sign = fields
        gex = sign * gamma * oi * multiplier * spot_sq_scaled
        per_strike[strike] = per_strike.get(strike, 0.0) + gex
        net_gex += gex
        gross_gex += abs(gex)
        used += 1

    if used == 0 or gross_gex == 0:
        return None

    band = neutral_band_frac * gross_gex
    if net_gex > band:
        signal = "BULLISH"
    elif net_gex < -band:
        signal = "BEARISH"
    else:
        signal = "NEUTRAL"

    # Flip level is best-effort; a valid net GEX should not be discarded just
    # because the crossing can't be located — fall back to spot.
    flip = _flip_level(per_strike)
    if flip is None:
        flip = round(spot, 2)

    return {
        "flow_signal": signal,
        "net_gex": round(net_gex, 2),
        "gex_flip_level": flip,
    }


def get_options_flow(symbol: str) -> Optional[OptionsFlow]:
    """Fetch the nearest-expiry chain and compute GEX. None on any failure.

    Honest-null contract: with no POLYGON_API_KEY (the current paper-phase state)
    the underlying fetch returns empty and this returns None, so the regime
    endpoint reports options flow as "not wired" rather than fabricating it.
    """
    try:
        from options._polygon_skew import (
            fetch_chain_snapshot,
            nearest_expiry,
            spot_price_from_polygon,
        )

        expiry = nearest_expiry(symbol)
        spot = spot_price_from_polygon(symbol)
        if not expiry or not spot:
            return None
        contracts = fetch_chain_snapshot(symbol, expiry)
        if not contracts:
            return None
        return compute_gex(contracts, spot)
    except Exception as e:  # noqa: BLE001 — options flow is best-effort, never fatal
        logger.debug("[options_flow] get_options_flow(%s) unavailable: %s", symbol, e)
        return None

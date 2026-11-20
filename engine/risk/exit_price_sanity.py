"""JARVIS TRADER — Exit Price Sanity Check.

Sibling of :mod:`risk.entry_price_sanity`. Entry-sanity guards the price a
position OPENS at; this guards the price it CLOSES at. The close path computes
realized P&L directly from ``exit_price`` (``(exit-entry)*qty*mult``), so a
corrupt exit price — a wrong-era cache hit, a stop value copied into the exit
field, a non-finite sentinel — writes a phantom P&L row that then poisons
``daily_pnl`` and every downstream analytic.

Motivating incident: 2026-06-15 — a phantom MES close produced a -$11,314 row
(entry-era ~7530 vs a 5299-era exit price, ~30% apart) before it was voided by
hand. This guard rejects that class at write time, fail-closed.

Design constraints (mirrors entry_price_sanity):
  - Pure Python — no async, no HTTP, no DB, no market fetch in the predicate.
    The tracker close path has no data_manager, so unlike entry-sanity this
    check anchors on the trade's OWN entry price rather than a live market
    reference. That is a deliberately conservative corruption screen, not an
    execution-quality check.
  - Additive: does not modify safety_layer.py or config.py.
  - Default ON via ENABLE_EXIT_PRICE_SANITY=1 (opt-out semantics).
  - Threshold tunable via EXIT_PRICE_SANITY_MAX_DEVIATION_PCT (default 0.25).
    Index/metal/energy futures are limit-halted long before a single trade
    moves 25% intra-position, so this only ever fires on corruption. Fails
    LOUD (CRITICAL log + raise) so a false positive is immediately visible and
    can be loosened via the env flag without a code change.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Tuple

logger = logging.getLogger("jarvis_trader.risk.exit_price_sanity")

_ENV_ENABLE = "ENABLE_EXIT_PRICE_SANITY"
_ENV_DEVIATION = "EXIT_PRICE_SANITY_MAX_DEVIATION_PCT"
_DEFAULT_MAX_DEVIATION_PCT = 0.25

_TRUTHY = {"1", "true", "yes", "on"}
_FALSEY = {"0", "false", "no", "off"}


class ExitPriceSanityError(ValueError):
    """Raised when a proposed exit price fails the corruption screen.

    Subclasses ValueError so existing ``except ValueError`` close-path handlers
    degrade gracefully, while callers that care can catch it specifically.
    """


def is_exit_price_sanity_enabled() -> bool:
    """True unless ENABLE_EXIT_PRICE_SANITY is explicitly falsey. Read fresh."""
    return os.getenv(_ENV_ENABLE, "1").strip().lower() not in _FALSEY


def _max_deviation_pct() -> float:
    raw = os.getenv(_ENV_DEVIATION, "").strip()
    if not raw:
        return _DEFAULT_MAX_DEVIATION_PCT
    try:
        val = float(raw)
        return val if val > 0 else _DEFAULT_MAX_DEVIATION_PCT
    except ValueError:
        return _DEFAULT_MAX_DEVIATION_PCT


def check_exit_price_sanity(
    symbol: str,
    entry_price: float,
    exit_price: float,
    session_low: float | None = None,
    session_high: float | None = None,
    range_tolerance_pct: float = 0.0,
) -> Tuple[bool, str]:
    """Return (ok, reason). Pure — no I/O. ok=False means the price is corrupt.

    Rules (in order):
      1. exit_price must be finite and strictly positive.
      2. If entry_price is missing/non-positive we cannot anchor — pass (the
         entry guard owns that failure mode; we never block on a missing ref).
      3. |exit-entry|/entry must not exceed the deviation threshold.
      4. When a session range is supplied, exit_price must lie inside it
         (widened by ``range_tolerance_pct``).

    Rule 4 exists because the entry-anchored screen (rule 3) is STRUCTURALLY
    BLIND to moderate-magnitude corrupt exits. Motivating incident: 2026-08-18 —
    an MES row was closed at 7,483.00 while the instrument's real session range
    was 7,707.00-7,770.75 (224.00 points BELOW the session low). The deviation
    from entry (7,731.75) is only 3.2%, far under the 25% screen — a 249-point
    adverse move is a *plausible* real trade, so rule 3 passes it. The booked
    -$1,245.25 then tripped the daily-loss kill switch and halted all trading
    for 31 days. The only signal that distinguishes this from a genuine trade is
    that the price was never traded that session, which requires a market-data
    anchor. Callers that hold bars should pass the session low/high.

    The range anchor is opt-in: omitting ``session_low``/``session_high``
    preserves the original entry-anchored-only behavior exactly.
    """
    try:
        ep = float(exit_price)
    except (TypeError, ValueError):
        return False, f"exit_price not numeric: {exit_price!r}"

    if not math.isfinite(ep) or ep <= 0:
        return False, f"exit_price non-finite or non-positive: {ep}"

    # Rule 4 first — it is absolute and does not depend on an entry reference.
    ok, reason = is_exit_price_within_session_range(
        symbol, ep, session_low, session_high, range_tolerance_pct
    )
    if not ok:
        return False, reason

    try:
        entry = float(entry_price)
    except (TypeError, ValueError):
        return True, "no entry reference — exit not anchored"
    if not math.isfinite(entry) or entry <= 0:
        return True, "no entry reference — exit not anchored"

    deviation = abs(ep - entry) / entry
    threshold = _max_deviation_pct()
    if deviation > threshold:
        return (
            False,
            f"{symbol} exit {ep:.4f} deviates {deviation:.1%} from entry "
            f"{entry:.4f} (> {threshold:.0%}) — wrong-era/corrupt price",
        )
    return True, "ok"


def is_exit_price_within_session_range(
    symbol: str,
    exit_price: float,
    session_low: float | None,
    session_high: float | None,
    tolerance_pct: float = 0.0,
) -> Tuple[bool, str]:
    """Return (ok, reason) for the session-range anchor. Pure — no I/O.

    ``ok=False`` when a supplied range is self-inconsistent (low/high missing,
    non-finite, inverted, or non-positive) or when ``exit_price`` falls outside
    it beyond ``tolerance_pct``.

    A self-inconsistent range is treated as a FAILURE, not a skip: if we cannot
    trust the range we must not certify the price. This is fail-closed and can
    only ever refuse a write, never permit a new one.

    When NEITHER bound is supplied the anchor is inactive and returns ok=True —
    that is the backward-compatible path for callers without market data.
    """
    if session_low is None and session_high is None:
        return True, "no session range supplied — range anchor inactive"

    try:
        lo = float(session_low)
        hi = float(session_high)
    except (TypeError, ValueError):
        return False, (
            f"{symbol} session range not numeric "
            f"(low={session_low!r}, high={session_high!r}) — cannot certify exit {exit_price}"
        )

    if not (math.isfinite(lo) and math.isfinite(hi)):
        return False, f"{symbol} session range non-finite (low={lo}, high={hi}) — cannot certify exit"
    if lo <= 0 or hi <= 0 or hi < lo:
        return False, (
            f"{symbol} session range self-inconsistent (low={lo}, high={hi}) — cannot certify exit"
        )

    tol = 0.0
    try:
        tol = max(0.0, float(tolerance_pct))
    except (TypeError, ValueError):
        tol = 0.0
    pad = (hi - lo) * tol
    lo_b, hi_b = lo - pad, hi + pad

    if exit_price < lo_b or exit_price > hi_b:
        side = "BELOW the session low" if exit_price < lo_b else "ABOVE the session high"
        return (
            False,
            f"{symbol} exit {exit_price:.4f} is {side} "
            f"[{lo:.4f}, {hi:.4f}] — price was never traded this session "
            f"(wrong-era/stale print); refusing to book it",
        )
    return True, "within session range"


def assert_exit_price_sane(
    symbol: str,
    entry_price: float,
    exit_price: float,
    session_low: float | None = None,
    session_high: float | None = None,
    range_tolerance_pct: float = 0.0,
) -> None:
    """Raise :class:`ExitPriceSanityError` if the exit price is corrupt.

    No-op when the guard is disabled. Logs CRITICAL before raising so the
    rejection is never silent.

    ``session_low``/``session_high`` are optional. Callers that hold bars should
    pass them so the session-range anchor can catch moderate-magnitude stale
    prints that the entry-anchored screen cannot see. Omitting them preserves
    the original entry-anchored-only behavior.
    """
    if not is_exit_price_sanity_enabled():
        return
    ok, reason = check_exit_price_sanity(
        symbol,
        entry_price,
        exit_price,
        session_low=session_low,
        session_high=session_high,
        range_tolerance_pct=range_tolerance_pct,
    )
    if not ok:
        logger.critical("[EXIT_SANITY] REJECTED close for %s: %s", symbol, reason)
        raise ExitPriceSanityError(reason)

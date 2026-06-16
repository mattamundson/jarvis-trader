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
) -> Tuple[bool, str]:
    """Return (ok, reason). Pure — no I/O. ok=False means the price is corrupt.

    Rules (in order):
      1. exit_price must be finite and strictly positive.
      2. If entry_price is missing/non-positive we cannot anchor — pass (the
         entry guard owns that failure mode; we never block on a missing ref).
      3. |exit-entry|/entry must not exceed the deviation threshold.
    """
    try:
        ep = float(exit_price)
    except (TypeError, ValueError):
        return False, f"exit_price not numeric: {exit_price!r}"

    if not math.isfinite(ep) or ep <= 0:
        return False, f"exit_price non-finite or non-positive: {ep}"

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


def assert_exit_price_sane(symbol: str, entry_price: float, exit_price: float) -> None:
    """Raise :class:`ExitPriceSanityError` if the exit price is corrupt.

    No-op when the guard is disabled. Logs CRITICAL before raising so the
    rejection is never silent.
    """
    if not is_exit_price_sanity_enabled():
        return
    ok, reason = check_exit_price_sanity(symbol, entry_price, exit_price)
    if not ok:
        logger.critical("[EXIT_SANITY] REJECTED close for %s: %s", symbol, reason)
        raise ExitPriceSanityError(reason)

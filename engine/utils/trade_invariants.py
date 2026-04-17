"""
Shared invariants for trade-direction correctness.

Used by production code (DB write guards) and the regression test suite so the
definition of "inverted stop" cannot drift between the two.

Invariant: a stop_loss must sit on the losing side of entry for its direction.
- Long (buy/long/buy_to_open):   stop_loss < entry_price
- Short (sell/short/sell_to_open/sell_short): stop_loss > entry_price

See docs/incident-notes/2026-04-09-mcl-inverted-stop.md for background.
"""

from __future__ import annotations

LONG_SIDES = frozenset({"buy", "long", "buy_to_open"})
SHORT_SIDES = frozenset({"sell", "short", "sell_short", "sell_to_open"})


def is_inverted_stop(
    side: str | None,
    entry_price: float | None,
    stop_loss: float | None,
) -> bool:
    """True iff stop_loss is on the wrong side of entry_price for the given side.

    Returns False when any input is None — missing data is not an invariant
    violation, it just means the invariant doesn't apply.
    """
    if side is None or entry_price is None or stop_loss is None:
        return False
    s = side.lower()
    if s in LONG_SIDES and stop_loss > entry_price:
        return True
    if s in SHORT_SIDES and stop_loss < entry_price:
        return True
    return False

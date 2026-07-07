"""
JARVIS TRADER — Database Helpers
==================================
Private utility functions shared across all database mixin modules.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("jarvis_trader.database")


def compute_order_idempotency_key(
    symbol: str,
    side: str,
    quantity: float,
    entry_price: float,
    window_seconds: int = 5,
) -> str:
    """
    Compute a stable idempotency key for a paper-order submission.

    Two calls with the same (symbol, side, quantity, entry_price) that arrive
    within the same ``window_seconds`` bucket produce the same key.  Calls
    outside the bucket produce different keys — allowing re-entry after the
    window expires.

    Key components:
      - symbol      (upper-cased)
      - side        (lower-cased: 'buy' | 'sell')
      - quantity    (rounded to nearest integer to absorb float noise)
      - price_tick  (entry_price rounded to 2 decimal places)
      - time_bucket (floor(unix_epoch / window_seconds))

    Returns a 16-char hex prefix of the SHA-256 digest — long enough to be
    collision-resistant in practice (128-bit space for 3 trades/day is fine),
    short enough to fit in a secondary index without bloat.

    Args:
        symbol:         Instrument symbol, e.g. "MES"
        side:           Order direction — "buy" or "sell"
        quantity:       Number of contracts
        entry_price:    Fill price
        window_seconds: Dedup window length in seconds (default 5)
    """
    now_epoch = datetime.now(timezone.utc).timestamp()
    bucket = int(math.floor(now_epoch / window_seconds))

    # Round quantity to nearest int; round price to 2 dp for tick tolerance
    qty_int = int(round(quantity))
    price_rounded = round(float(entry_price), 2)

    raw = f"{symbol.upper()}|{side.lower()}|{qty_int}|{price_rounded:.2f}|{bucket}"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return digest[:32]  # 128-bit prefix — collision-safe for trading volumes


def _utcnow() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _to_json(value: Any) -> Optional[str]:
    """Serialise a dict/list to a JSON string; pass through strings/None."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str)


def _from_json(value: Optional[str]) -> Any:
    """Deserialise a JSON string; return None/non-string values unchanged."""
    if value is None or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return value  # return raw string if it is not valid JSON

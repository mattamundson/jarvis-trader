"""
Read-only client for amo-arbitrage's ML signal feed (GET /api/signals/ml).

Advisory only: this module NEVER feeds jarvis-trader's own trade/risk/fund
decisions -- it exists purely to surface amo-arbitrage's signals as an
informational cross-system data point in the session brief (see
analytics/session_brief.py's `cross_signals` parameter). Async with graceful
fallback per engine-python.md: any failure (timeout, connection error,
non-2xx, malformed JSON) degrades to an explicit "not available" result --
this function NEVER raises past its own boundary.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

AMOARB_SIGNALS_URL = os.environ.get(
    "AMOARB_SIGNALS_URL", "http://127.0.0.1:8000/api/signals/ml"
)
AMOARB_SIGNALS_TIMEOUT_S = 5.0


async def fetch_amoarb_signals() -> dict[str, Any]:
    """Fetch the latest amo-arbitrage ML signals. Never raises.

    Returns:
        {"available": bool, "signals": list[dict], "error": str | None,
         "fetched_at": str (ISO-8601 UTC)}
    """
    import httpx  # lazy import per engine-python.md

    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        async with httpx.AsyncClient(timeout=AMOARB_SIGNALS_TIMEOUT_S) as client:
            response = await client.get(AMOARB_SIGNALS_URL)
        response.raise_for_status()
        signals = response.json()
        if not isinstance(signals, list):
            raise ValueError(f"expected a list, got {type(signals).__name__}")
        return {
            "available": True,
            "signals": signals,
            "error": None,
            "fetched_at": fetched_at,
        }
    except Exception as exc:  # never let a dead amo-arbitrage break the caller
        logger.warning("[amoarb_signals] fetch failed: %s", exc)
        return {
            "available": False,
            "signals": [],
            "error": str(exc)[:200],
            "fetched_at": fetched_at,
        }

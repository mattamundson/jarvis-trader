"""
JARVIS TRADER — Signal-outcomes router.

GET /analytics/signal-outcomes — every recent directional pipeline decision
scored against subsequent daily bars (hit/stop/expired, MFE/MAE, hypothetical
P&L) plus the aggregate hit-rate. The calibration loop for PREDICTIONS —
independent of execution, so held/rejected/unfilled signals are scored too.

Read-only, fail-open (200 with ``available:false``), evaluation on demand —
no new table, no scheduler. Scoring lives in the pure
``analytics.signal_outcomes`` module; this router only reads the decision
rows and bars. Outcomes are evaluation targets only and never feed a
trading decision (testing.md point-in-time discipline).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query

from analytics.signal_outcomes import aggregate_outcomes, evaluate_signal

logger = logging.getLogger("jarvis_trader.routers.signal_outcomes")

router = APIRouter(prefix="/analytics", tags=["analytics", "signal-outcomes"])

# How much daily history to pull per symbol — must cover the oldest decision
# we evaluate plus the expiry window.
BARS_LOOKBACK_DAYS = 120

_db_manager = None
_data_manager = None


def inject_dependencies(db_manager, data_manager=None) -> None:
    global _db_manager, _data_manager
    _db_manager = db_manager
    _data_manager = data_manager


async def _daily_bars(symbol: str) -> list[dict]:
    """Daily OHLC dicts for symbol; empty list on any failure (fail open)."""
    if _data_manager is None:
        return []
    try:
        df = await _data_manager.get_bars(
            symbol, lookback_days=BARS_LOOKBACK_DAYS, timeframe="1d", is_futures=True
        )
        if df is None or df.empty:
            return []
        return df.to_dict("records")
    except Exception as exc:
        logger.warning("[SignalOutcomes] bars fetch failed for %s: %s", symbol, exc)
        return []


@router.get("/signal-outcomes")
async def get_signal_outcomes(
    # Capped at 50 to match get_recent_approvals_all_statuses()'s own clamp
    # (engine/database/_mixins_pending_approvals.py) -- a higher API limit
    # here would silently under-fill the aggregate with no indication in
    # the response that fewer rows were actually evaluated.
    limit: int = Query(50, ge=1, le=50),
) -> dict[str, Any]:
    """Score recent directional decisions against subsequent daily bars."""
    if _db_manager is None:
        return {
            "outcomes": [], "aggregate": aggregate_outcomes([]),
            "available": False, "note": "Database not available.",
        }

    try:
        rows = _db_manager.get_recent_approvals_all_statuses(limit=limit)
    except Exception as exc:
        logger.warning("[SignalOutcomes] approvals read failed: %s", exc)
        return {
            "outcomes": [], "aggregate": aggregate_outcomes([]),
            "available": False, "note": f"Approvals read failed: {exc}",
        }

    directional = [r for r in rows if (r.get("action") or "").lower() in ("buy", "sell")]
    now = datetime.now(tz=timezone.utc).date()

    bars_by_symbol: dict[str, list[dict]] = {}
    for symbol in sorted({(r.get("symbol") or "").upper() for r in directional}):
        if symbol:
            bars_by_symbol[symbol] = await _daily_bars(symbol)

    outcomes = [
        evaluate_signal(r, bars_by_symbol.get((r.get("symbol") or "").upper(), []), now=now)
        for r in directional
    ]

    note = None
    if directional and not any(bars_by_symbol.values()):
        note = (
            "No daily bars available from any data source — outcomes shown as "
            "not-evaluated rather than fabricated."
        )

    return {
        "outcomes": outcomes,
        "aggregate": aggregate_outcomes(outcomes),
        "available": True,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "note": note,
        # Explicit contract: the universe is the human-approval queue only.
        # Scheduler-only pipeline runs that never queued an approval row
        # (persisted via insert_pipeline_run / the decisions feed) are NOT
        # scored yet — expanding the universe to those sources without
        # double-counting the same run is a tracked follow-up.
        "universe": "pending_trade_approvals (human-approval queue) only",
        # Explicit granularity contract: outcomes are a DAILY-BAR, ~10-trading-
        # day-horizon read of each signal's geometry. The decision-day bar is
        # excluded (it contains pre-decision hours — look-ahead), so same-day
        # resolution of intraday (1h) signals is NOT captured; this is a
        # signal-direction horizon metric, not a live-trade replay. Scoring at
        # the row's own timeframe is a tracked follow-up (with the universe
        # expansion above).
        "model": (
            "Daily-bar granularity, ~10-trading-day horizon. Hypothetical fill at "
            "decision entry; exit T1 on target hit (conservative 1R), stop on stop "
            "hit, else mark-to-last-close; same-bar stop+target resolves to stop; "
            "decision-day bar excluded (no look-ahead), so same-day resolution of "
            "intraday signals is not captured — horizon metric, not a trade replay."
        ),
    }

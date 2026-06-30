"""GET /pnl/truth -- the honest realized paper-P&L surface.

Exposes ``engine/analytics/pnl_truth`` over HTTP so the dashboard (and ops) can
read ONE realized-P&L number with an explicit TRUSTED/DEGRADED verdict instead of
a number that might be silently fabricated. Read-only; never touches the order
path or the safety layer.

Fail-safe by construction: a missing or unreadable ledger returns ``DEGRADED``
with ``realized_pnl: null`` -- it says "I don't know" rather than emit a fake 0.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from analytics.pnl_truth import pnl_truth_from_sqlite

logger = logging.getLogger(__name__)
router = APIRouter(tags=["pnl-truth"])


class PnlTruthResponse(BaseModel):
    """Realized paper-P&L with provenance and a trust verdict."""

    status: str  # "TRUSTED" | "DEGRADED"
    realized_pnl: float | None
    closed_trades: int
    excluded_trades: int
    reasons: list[str]
    sources_present: list[str]
    trusted: bool


def _db_path() -> Path:
    """The canonical engine SQLite ledger. ``JARVIS_SQLITE_DB`` overrides (tests/ops)."""
    override = os.getenv("JARVIS_SQLITE_DB")
    if override:
        return Path(override)
    try:
        from config import settings

        return Path(settings.SQLITE_DB_PATH)
    except Exception:  # pragma: no cover - config import fallback
        return Path(__file__).resolve().parents[1] / "data" / "jarvis_trader.db"


@router.get("/pnl/truth", response_model=PnlTruthResponse)
async def get_pnl_truth() -> PnlTruthResponse:
    """Return the honest realized paper-P&L for the closed-trade ledger."""
    try:
        truth = pnl_truth_from_sqlite(_db_path())
    except Exception as exc:  # belt-and-suspenders; the loader is already fail-safe
        logger.exception("GET /pnl/truth failed")
        raise HTTPException(status_code=500, detail="pnl_truth computation failed") from exc
    return PnlTruthResponse(
        status=truth.status,
        realized_pnl=truth.realized_pnl,
        closed_trades=truth.closed_trades,
        excluded_trades=truth.excluded_trades,
        reasons=list(truth.reasons),
        sources_present=list(truth.sources_present),
        trusted=truth.trusted,
    )

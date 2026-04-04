"""
JARVIS TRADER — Trades Router
==============================
API endpoints for trade history, journal, and attribution data.

Provides:
  GET /trades/journal - Paper trades with full signal provenance and attribution
"""

from __future__ import annotations

import logging
import sqlite3
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger("jarvis_trader.routers.trades")

router = APIRouter(prefix="/trades", tags=["trades"])


class TradeJournalEntry(BaseModel):
    """A single paper trade with full signal provenance and attribution."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    trade_id: str
    symbol: str
    side: str
    quantity: float
    entry_price: float
    exit_price: Optional[float] = None
    entry_time: str
    exit_time: Optional[str] = None
    pnl: Optional[float] = None
    status: str
    strategy_params: Optional[str] = None
    notes: Optional[str] = None
    # Signal provenance (US-1404)
    regime: Optional[str] = None
    structure_position: Optional[str] = None
    bias: Optional[str] = None
    composite_score: Optional[float] = None
    stc_contrib: Optional[int] = None
    orb_contrib: Optional[int] = None
    vwap_contrib: Optional[int] = None
    # Trade attribution (US-2130)
    regime_tier: Optional[int] = None
    deciding_stage: Optional[str] = None
    bull_score: Optional[float] = None
    bear_score: Optional[float] = None
    debate_confidence: Optional[float] = None
    # Signal timeframe (US-2122)
    timeframe: Optional[str] = None


@router.get(
    "/journal",
    response_model=List[TradeJournalEntry],
    summary="Get paper trades with full signal provenance and attribution",
)
def get_trades_journal(
    symbol: Optional[str] = Query(None, description="Filter by symbol (e.g., MCL, MNQ)"),
    regime: Optional[str] = Query(None, description="Filter by regime (e.g., TRENDING_BULL)"),
    limit: int = Query(50, ge=1, le=200, description="Max trades to return"),
) -> List[TradeJournalEntry]:
    """
    Get all paper trades with full signal provenance (regime, structure, bias,
    composite_score, signal contributions) and trade attribution (regime tier,
    deciding stage, bull/bear scores, debate confidence).

    Optional filters:
      - **symbol**: MCL, MNQ, etc.
      - **regime**: TRENDING_BULL, TRENDING_BEAR, RANGE_BOUND, etc.
      - **limit**: max 200 (default 50)

    Returns trades ordered by entry_time DESC (most recent first).
    """
    try:
        from database import get_db as get_db_manager

        db = get_db_manager()
        conn = db._connect()  # type: ignore[attr-defined]

        # Build query
        query = "SELECT * FROM paper_trades WHERE 1=1"
        params: List[str | int] = []

        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)

        if regime:
            query += " AND regime = ?"
            params.append(regime)

        query += " ORDER BY entry_time DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(query, params)
        rows = cursor.fetchall()

        # Convert rows to dicts
        col_names = [description[0] for description in cursor.description]
        trades = [dict(zip(col_names, row, strict=False)) for row in rows]

        conn.close()
        return [TradeJournalEntry(**t) for t in trades]

    except sqlite3.OperationalError as e:
        logger.error("Database error querying trades journal: %s", e)
        raise HTTPException(status_code=500, detail="Database error") from e
    except Exception as e:
        logger.error("Unexpected error in get_trades_journal: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error") from e

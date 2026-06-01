"""
JARVIS TRADER — Trades Router
==============================
API endpoints for trade history, journal, and attribution data.

Provides:
  GET  /trades/journal                   - Paper trades with signal provenance
  GET  /trades/reviews                   - Paginated trade reviews with filters
  GET  /trades/{trade_id}/review         - Single trade + its review
  POST /trades/{trade_id}/review/regenerate - Re-run LLM analysis (Tier 3)
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger("jarvis_trader.routers.trades")

router = APIRouter(prefix="/trades", tags=["trades"])

# Injected at startup by main.py
_db_manager: Any = None
_llm_client: Any = None


def inject_dependencies(db_manager: Any, llm_client: Any) -> None:
    global _db_manager, _llm_client
    _db_manager = db_manager
    _llm_client = llm_client


# ── Pydantic models ───────────────────────────────────────────────────────────


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
    regime: Optional[str] = None
    structure_position: Optional[str] = None
    bias: Optional[str] = None
    composite_score: Optional[float] = None
    stc_contrib: Optional[int] = None
    orb_contrib: Optional[int] = None
    vwap_contrib: Optional[int] = None
    regime_tier: Optional[int] = None
    deciding_stage: Optional[str] = None
    bull_score: Optional[float] = None
    bear_score: Optional[float] = None
    debate_confidence: Optional[float] = None
    timeframe: Optional[str] = None


class TradeReview(BaseModel):
    grade: Optional[str] = None
    setup_quality: Optional[str] = None
    strengths: Optional[List[str]] = None
    weaknesses: Optional[List[str]] = None
    rule_violations: Optional[List[str]] = None
    lessons: Optional[str] = None
    improvement_tags: Optional[List[str]] = None
    llm_model: Optional[str] = None
    review_status: str
    pnl_usd: Optional[float] = None
    pnl_pct: Optional[float] = None
    hold_minutes: Optional[float] = None
    rr_ratio: Optional[float] = None
    actual_r: Optional[float] = None
    regime: Optional[str] = None
    conviction: Optional[float] = None
    bull_score: Optional[float] = None
    bear_score: Optional[float] = None
    pipeline_summary: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TradeWithReview(BaseModel):
    trade: Dict[str, Any]
    review: Optional[TradeReview] = None


class ReviewsListResponse(BaseModel):
    reviews: List[Dict[str, Any]]
    total: int
    grade_breakdown: Dict[str, int]


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/journal",
    response_model=List[TradeJournalEntry],
    summary="Paper trades with full signal provenance and attribution",
)
def get_trades_journal(
    symbol: Optional[str] = Query(None),
    regime: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> List[TradeJournalEntry]:
    try:
        from database import get_db as get_db_manager

        db = get_db_manager()
        conn = db._connect()  # type: ignore[attr-defined]

        query = "SELECT * FROM paper_trades WHERE 1=1"
        params: List[Any] = []

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
        col_names = [d[0] for d in cursor.description]
        trades = [dict(zip(col_names, row, strict=False)) for row in rows]
        conn.close()
        return [TradeJournalEntry(**t) for t in trades]

    except sqlite3.OperationalError as exc:
        logger.error("Database error querying trades journal: %s", exc)
        raise HTTPException(status_code=500, detail="Database error") from exc
    except Exception as exc:
        logger.error("Unexpected error in get_trades_journal: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get(
    "/reviews",
    response_model=ReviewsListResponse,
    summary="Paginated trade reviews with optional filters",
)
def list_reviews(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    grade: Optional[str] = Query(None, description="Comma-separated grades, e.g. A,B"),
    date_from: Optional[str] = Query(None, description="ISO date lower bound"),
    date_to: Optional[str] = Query(None, description="ISO date upper bound"),
    status: Optional[str] = Query(None, description="pending|complete|failed"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ReviewsListResponse:
    if _db_manager is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    grades = [g.strip() for g in grade.split(",") if g.strip()] if grade else None
    result = _db_manager.list_trade_reviews(
        symbol=symbol,
        grades=grades,
        date_from=date_from,
        date_to=date_to,
        status=status,
        limit=limit,
        offset=offset,
    )
    return ReviewsListResponse(**result)


@router.get(
    "/{trade_id}/review",
    response_model=TradeWithReview,
    summary="Single trade detail with its LLM review",
)
def get_trade_review(trade_id: str) -> TradeWithReview:
    if _db_manager is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    # Fetch trade record
    trade_row = _db_manager.fetch_one("SELECT * FROM paper_trades WHERE trade_id = ?", (trade_id,))
    if not trade_row:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")

    # Fetch review (may be None if never started)
    review_row = _db_manager.get_trade_review(trade_id)
    review = TradeReview(**review_row) if review_row else None

    return TradeWithReview(trade=trade_row, review=review)


@router.post(
    "/{trade_id}/review/regenerate",
    summary="Re-run LLM analysis for a historical trade (Tier 3 — use sparingly)",
)
async def regenerate_review(trade_id: str) -> Dict[str, str]:
    """
    Re-queues the LLM review for a historical trade.  Useful for re-grading
    after prompt updates, or recovering failed reviews.  Non-blocking —
    review appears in GET /trades/{id}/review within ~15s.
    """
    if _db_manager is None or _llm_client is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    trade_row = _db_manager.fetch_one(
        "SELECT * FROM paper_trades WHERE trade_id = ? AND status = 'closed'",
        (trade_id,),
    )
    if not trade_row:
        raise HTTPException(
            status_code=404,
            detail=f"Closed trade {trade_id} not found",
        )

    # Build a minimal PaperTrade-like object from the DB row
    from analytics.trade_review import TradeReviewService

    class _TradeLike:
        pass

    t = _TradeLike()
    for k, v in trade_row.items():
        setattr(t, k, v)
    # Ensure required fields exist
    for attr in ("stop_loss", "take_profit", "atr_value", "strategy_params"):
        if not hasattr(t, attr):
            setattr(t, attr, None)
    t.action = trade_row.get("side", "buy")  # type: ignore[attr-defined]
    t.quantity = trade_row.get("quantity", 1)  # type: ignore[attr-defined]

    svc = TradeReviewService(_llm_client, _db_manager)
    asyncio.create_task(svc.review_trade(t))

    return {"status": "queued", "trade_id": trade_id}

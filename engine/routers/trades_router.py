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

# /trades/journal response cache. Paper trades resolve minutes apart (a fill,
# a close), so a short TTL absorbs dashboard polling bursts and shields the
# SQLite connection from concurrent write-lock stalls under engine load.
JOURNAL_CACHE_TTL_SECONDS = 5.0
_journal_cache: dict[tuple, tuple[float, list[dict]]] = {}


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
    import time as _time

    # Narrow column list: only the fields the response model exposes. SELECT *
    # pulled all 36 paper_trades columns including large TEXT blobs
    # (strategy_params, notes) — the dominant cost once a connection is open.
    # Narrow column list: only the fields the response model exposes that also
    # EXIST in paper_trades. SELECT * pulled all 36 columns including large
    # TEXT blobs (strategy_params, notes) — the dominant cost once a connection
    # is open. Model fields with no backing column (regime_tier, deciding_stage,
    # bull/bear_score, debate_confidence, timeframe) are intentionally omitted —
    # they were never populated under SELECT * either, so they stay None.
    _JOURNAL_COLUMNS = (
        "id", "trade_id", "symbol", "side", "quantity", "entry_price",
        "exit_price", "entry_time", "exit_time", "pnl", "status",
        "strategy_params", "notes", "regime", "structure_position", "bias",
        "composite_score", "stc_contrib", "orb_contrib", "vwap_contrib",
        "regime_tier", "deciding_stage", "bull_score", "bear_score",
        "debate_confidence", "timeframe",
    )
    cache_key = (symbol, regime, limit)
    now = _time.monotonic()
    cached = _journal_cache.get(cache_key)
    if cached is not None and (now - cached[0]) < JOURNAL_CACHE_TTL_SECONDS:
        return [TradeJournalEntry(**t) for t in cached[1]]

    try:
        from database import get_db as get_db_manager

        db = get_db_manager()
        conn = db._connect()  # type: ignore[attr-defined]

        cols = ", ".join(_JOURNAL_COLUMNS)
        query = f"SELECT {cols} FROM paper_trades WHERE 1=1"
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

        _journal_cache[cache_key] = (_time.monotonic(), trades)
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


# ── Full review (closed-loop) ──────────────────────────────────────────────────
# One endpoint that joins, for a single placed trade, everything needed to answer
# "was this trade placed, WHY did the strategy fire, WHEN, what does its backtest
# say, and how is it doing live" — the trade-review loop, on one screen.


class FullReviewResponse(BaseModel):
    trade: Dict[str, Any]
    attribution: Dict[str, Any]  # parsed strategy_params (which strategy/signal fired)
    why: Optional[Dict[str, Any]] = None  # matched decision + full 5-stage pipeline
    backtest: Optional[Dict[str, Any]] = None  # gate-v2 verdict for the symbol
    forward: Optional[Dict[str, Any]] = None  # live/paper performance for the symbol
    review: Optional[Dict[str, Any]] = None  # A–F LLM grade, if any


def _parse_dt(value: Any) -> Optional["Any"]:
    """Parse an ISO timestamp to a tz-aware UTC datetime. decisions.timestamp is
    naive ISO; paper_trades.entry_time carries +00:00. Treat naive as UTC."""
    from datetime import datetime, timezone

    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _match_decision(symbol: str, entry_time: Any) -> Optional[Dict[str, Any]]:
    """Find the decision that best explains a trade: same symbol, nearest in time
    to entry (preferring at/just-before entry), within a 24h window. There is no
    FK between paper_trades and decisions, so this is time-proximity matching."""
    if _db_manager is None or not symbol:
        return None
    et = _parse_dt(entry_time)
    try:
        candidates = _db_manager.get_decisions(symbol=symbol, limit=400)
    except Exception:  # pragma: no cover - defensive
        return None
    if not candidates:
        return None
    if et is None:
        return candidates[0]  # already ordered timestamp DESC

    best = None
    best_delta = None
    for d in candidates:
        dt = _parse_dt(d.get("timestamp"))
        if dt is None:
            continue
        delta = abs((et - dt).total_seconds())
        # prefer decisions at/before entry by lightly penalising future ones
        if dt > et:
            delta += 1800  # 30-min penalty so a slightly-earlier match wins ties
        if best_delta is None or delta < best_delta:
            best, best_delta = d, delta
    if best is None or best_delta is None or best_delta > 86400:
        return None
    best["_match_delta_seconds"] = best_delta
    return best


@router.get(
    "/{trade_id}/full-review",
    response_model=FullReviewResponse,
    summary="Closed-loop review: trade + why it fired + backtest verdict + forward stats",
)
def get_trade_full_review(trade_id: str) -> FullReviewResponse:
    if _db_manager is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    trade = _db_manager.fetch_one(
        "SELECT * FROM paper_trades WHERE trade_id = ?", (trade_id,)
    )
    if not trade:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")

    symbol = trade.get("symbol")

    # ── Attribution: which strategy/signal fired (parse strategy_params JSON) ──
    import json as _json

    attribution: Dict[str, Any] = {}
    raw_sp = trade.get("strategy_params")
    if raw_sp:
        try:
            attribution = _json.loads(raw_sp) if isinstance(raw_sp, str) else dict(raw_sp)
        except (ValueError, TypeError):
            attribution = {"_raw": str(raw_sp)}
    # surface the structured attribution columns too (US-2130 provenance)
    for col in (
        "regime", "bias", "structure_position", "composite_score",
        "stc_contrib", "orb_contrib", "vwap_contrib",
    ):
        if trade.get(col) is not None:
            attribution.setdefault(col, trade.get(col))

    # ── Why: the matched decision + full 5-stage pipeline transcript ──────────
    why: Optional[Dict[str, Any]] = None
    match = _match_decision(symbol, trade.get("entry_time"))
    if match is not None:
        full = None
        try:
            detail = _db_manager.get_decision_by_id(int(match.get("id")))
            full = detail.get("full_pipeline_json") if detail else None
        except Exception:  # pragma: no cover - defensive
            full = None
        why = {
            "decision_id": match.get("id"),
            "matched_by": "symbol+time_proximity",
            "match_delta_seconds": match.get("_match_delta_seconds"),
            "timestamp": match.get("timestamp"),
            "action": match.get("action"),
            "confidence": match.get("confidence"),
            "regime": match.get("regime"),
            "reasoning": match.get("reasoning"),
            "pipeline": full,  # the full 5-stage dict (7 analysts → debate → trader → risk → fund mgr)
        }

    # ── Backtest verdict: the symbol's gate-v2 ledger entry ───────────────────
    backtest: Optional[Dict[str, Any]] = None
    if symbol:
        try:
            from routers.strategy_ledger_router import find_verdict

            backtest = find_verdict(symbol, attribution.get("family"))
        except Exception:  # pragma: no cover - defensive
            backtest = None

    # ── Forward test: live/paper performance for the symbol ───────────────────
    forward: Optional[Dict[str, Any]] = None
    if symbol:
        try:
            from analytics.performance import PerformanceCalculator

            metrics = PerformanceCalculator(_db_manager).calculate(symbol=symbol)
            forward = metrics.as_dict()
        except Exception:  # pragma: no cover - defensive
            forward = None

    # ── Review: A–F grade, if one exists ──────────────────────────────────────
    review: Optional[Dict[str, Any]] = None
    try:
        review = _db_manager.get_trade_review(trade_id)
    except Exception:  # pragma: no cover - defensive
        review = None

    return FullReviewResponse(
        trade=trade,
        attribution=attribution,
        why=why,
        backtest=backtest,
        forward=forward,
        review=review,
    )

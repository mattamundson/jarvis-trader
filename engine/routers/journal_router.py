"""
JARVIS TRADER — Trade Journal API Router
=========================================
Provides CRUD endpoints for the trade_journal table (entries) and the
journal_notes table (notes).

To register in main.py, add:
    from routers.journal_router import router as journal_router, set_db_manager as set_journal_db
    app.include_router(journal_router, prefix="/journal", tags=["journal"])
    set_journal_db(db_manager)  # call after db_manager initialized in lifespan
"""

from __future__ import annotations

import logging
import sqlite3
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from database.schema import DatabaseManager

logger = logging.getLogger("jarvis_trader.routers.journal")

# ---------------------------------------------------------------------------
# Module-level db_manager reference — injected at startup via set_db_manager()
# ---------------------------------------------------------------------------

_db: Optional[DatabaseManager] = None


def set_db_manager(db: DatabaseManager) -> None:
    """
    Inject the application-level DatabaseManager into this router.

    Call this once from main.py after the DatabaseManager has been
    initialised (i.e. inside the FastAPI lifespan startup block).
    """
    global _db
    _db = db


def _get_db() -> DatabaseManager:
    """Return the injected DatabaseManager or raise 503 if not yet set."""
    if _db is None:
        raise HTTPException(
            status_code=503,
            detail="Database manager not initialised.  Call set_db_manager() at startup.",
        )
    return _db


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class JournalEntryCreate(BaseModel):
    """Payload for creating a new journal entry."""

    trade_id: str
    note: str
    tags: Optional[str] = None  # comma-separated, e.g. "missed_entry,good_setup"
    mood: Optional[str] = None  # confident | uncertain | frustrated | neutral
    lesson: Optional[str] = None
    timestamp: Optional[str] = None  # ISO-8601 UTC; server fills in now() if omitted


class JournalEntryUpdate(BaseModel):
    """Payload for partially updating an existing journal entry."""

    note: Optional[str] = None
    tags: Optional[str] = None
    mood: Optional[str] = None
    lesson: Optional[str] = None


class JournalEntryResponse(BaseModel):
    """Response shape for a single journal entry row."""

    id: int
    trade_id: str
    timestamp: str
    note: str
    tags: Optional[str]
    mood: Optional[str]
    lesson: Optional[str]


class CreateEntryResponse(BaseModel):
    entry_id: int
    message: str


class DeleteResponse(BaseModel):
    deleted: bool
    message: str


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter()

_VALID_MOODS = {"confident", "uncertain", "frustrated", "neutral"}


# ── POST /journal/entries ──────────────────────────────────────────────────


@router.post(
    "/entries",
    response_model=CreateEntryResponse,
    status_code=201,
    summary="Create a new journal entry",
)
def create_journal_entry(payload: JournalEntryCreate) -> CreateEntryResponse:
    """
    Add a journal entry for a trade.

    - **trade_id**: UUID of the paper trade being annotated.
    - **note**: Free-text journal body (required).
    - **tags**: Optional comma-separated tags, e.g. ``"missed_entry,good_setup"``.
    - **mood**: Optional mood label — ``confident | uncertain | frustrated | neutral``.
    - **lesson**: Optional lesson / take-away from the trade.
    - **timestamp**: Optional ISO-8601 UTC string; defaults to server time.
    """
    if payload.mood and payload.mood not in _VALID_MOODS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid mood '{payload.mood}'.  Must be one of: {sorted(_VALID_MOODS)}",
        )
    db = _get_db()
    entry_id = db.add_journal_entry(
        trade_id=payload.trade_id,
        note=payload.note,
        tags=payload.tags,
        mood=payload.mood,
        lesson=payload.lesson,
        timestamp=payload.timestamp,
    )
    return CreateEntryResponse(
        entry_id=entry_id,
        message=f"Journal entry {entry_id} created.",
    )


# ── GET /journal/entries ───────────────────────────────────────────────────


@router.get(
    "/entries",
    response_model=List[JournalEntryResponse],
    summary="List journal entries",
)
def list_journal_entries(
    trade_id: Optional[str] = Query(default=None, description="Filter by paper trade UUID"),
    tag: Optional[str] = Query(default=None, description="Filter by a single tag token"),
    limit: int = Query(default=50, ge=1, le=500, description="Maximum number of results"),
) -> List[JournalEntryResponse]:
    """
    Return journal entries, ordered newest-first.

    - **trade_id**: Narrow results to a single trade.
    - **tag**: Return only entries that include this tag (exact token match).
    - **limit**: Cap the number of returned rows (1–500, default 50).
    """
    db = _get_db()
    rows = db.get_journal_entries(trade_id=trade_id, tag=tag, limit=limit)
    return [JournalEntryResponse(**row) for row in rows]


# ── PATCH /journal/entries/{entry_id} ─────────────────────────────────────


@router.patch(
    "/entries/{entry_id}",
    response_model=JournalEntryResponse,
    summary="Update a journal entry",
)
def update_journal_entry(
    entry_id: int,
    payload: JournalEntryUpdate,
) -> JournalEntryResponse:
    """
    Partially update an existing journal entry.

    Only fields included in the request body are modified.  Omitted fields
    retain their current database value.
    """
    if payload.mood and payload.mood not in _VALID_MOODS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid mood '{payload.mood}'.  Must be one of: {sorted(_VALID_MOODS)}",
        )
    db = _get_db()
    updated = db.update_journal_entry(
        entry_id=entry_id,
        note=payload.note,
        tags=payload.tags,
        mood=payload.mood,
        lesson=payload.lesson,
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Journal entry {entry_id} not found.")

    # Fetch the freshly updated row to return it.
    db.get_journal_entries(limit=1)  # fallback; prefer direct lookup
    # Direct lookup via a small helper query using the existing get_journal_entries:
    # We re-query with no filters and scan, but that is inefficient for large tables.
    # Instead use a raw approach through the public API with a known-unique filter.
    # Since get_journal_entries does not filter by id, fetch all and scan.
    # For correctness we do a fresh targeted query here.
    conn = db._connect()  # type: ignore[attr-defined]
    try:
        row = conn.execute("SELECT * FROM trade_journal WHERE id = ?", (entry_id,)).fetchone()
    finally:
        conn.close()

    if row is None:
        raise HTTPException(
            status_code=404, detail=f"Journal entry {entry_id} not found after update."
        )

    return JournalEntryResponse(**dict(row))


# ── DELETE /journal/entries/{entry_id} ────────────────────────────────────


@router.delete(
    "/entries/{entry_id}",
    response_model=DeleteResponse,
    summary="Delete a journal entry",
)
def delete_journal_entry(entry_id: int) -> DeleteResponse:
    """
    Permanently delete a journal entry by its integer id.

    Returns ``{ "deleted": true }`` on success or a 404 if the entry is
    not found.
    """
    db = _get_db()
    deleted = db.delete_journal_entry(entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Journal entry {entry_id} not found.")
    return DeleteResponse(deleted=True, message=f"Journal entry {entry_id} deleted.")


# ── GET /journal/tags ──────────────────────────────────────────────────────


@router.get(
    "/tags",
    response_model=List[str],
    summary="List all tags used in the journal",
)
def list_journal_tags() -> List[str]:
    """
    Return a sorted list of every unique tag token that appears in the
    ``tags`` column across all journal entries.

    Useful for building tag autocomplete UI or filtering dropdowns.
    """
    db = _get_db()
    return db.get_journal_tags()


# ---------------------------------------------------------------------------
# Journal Notes — Pydantic models
# ---------------------------------------------------------------------------

_VALID_NOTE_TYPES = {"observation", "lesson", "alert"}


class JournalNoteCreate(BaseModel):
    """Payload for creating a new journal note."""

    note_type: str = "observation"  # observation | lesson | alert
    title: str
    body: Optional[str] = ""
    tags: Optional[List[str]] = None  # JSON array of tag strings
    trade_id: Optional[str] = None  # optional soft FK to paper_trades


class JournalNoteResponse(BaseModel):
    """Response shape for a single journal note row."""

    id: int
    trade_id: Optional[str]
    note_type: str
    title: str
    body: Optional[str]
    tags: List[str]
    created_at: str
    updated_at: str


class CreateNoteResponse(BaseModel):
    id: int
    created: bool


class DeleteNoteResponse(BaseModel):
    deleted: bool


# ---------------------------------------------------------------------------
# Paper Trade Journal — Pydantic models (US-1404)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Paper Trade Journal — Endpoints (US-1404)
# ---------------------------------------------------------------------------

# ── Shared helper for trade journal queries ────────────────────────────────


def _query_trade_journal_entries(
    symbol: Optional[str] = None,
    regime: Optional[str] = None,
    limit: int = 50,
) -> List[TradeJournalEntry]:
    """
    Query paper trades with full signal provenance and attribution.
    Shared by both /trade-journal and /trades endpoints.
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
        logger.error("Database error querying trade journal: %s", e)
        raise HTTPException(status_code=500, detail="Database error") from e
    except Exception as e:
        logger.error("Unexpected error in trade journal query: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error") from e


# ── GET /journal/trade-journal and related ─────────────────────────────────


@router.get(
    "/trade-journal",
    response_model=List[TradeJournalEntry],
    summary="Get paper trades with full signal provenance and attribution",
)
def get_trade_journal(
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
    return _query_trade_journal_entries(symbol=symbol, regime=regime, limit=limit)


# ---------------------------------------------------------------------------
# Journal Notes — Endpoints
# ---------------------------------------------------------------------------

# ── GET /journal/notes ─────────────────────────────────────────────────────


@router.get(
    "/notes",
    response_model=List[JournalNoteResponse],
    summary="List journal notes",
)
def get_journal_notes(
    limit: int = Query(default=50, ge=1, le=200, description="Maximum number of results"),
    note_type: Optional[str] = Query(
        default=None, description="Filter by note type: observation | lesson | alert"
    ),
    trade_id: Optional[str] = Query(default=None, description="Filter by linked paper trade UUID"),
) -> List[JournalNoteResponse]:
    """
    Return journal notes, ordered newest-first.

    - **limit**: Cap the number of returned rows (1–200, default 50).
    - **note_type**: Filter by type — ``observation | lesson | alert``.
    - **trade_id**: Narrow results to notes linked to a specific trade.
    """
    if note_type and note_type not in _VALID_NOTE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid note_type '{note_type}'.  Must be one of: {sorted(_VALID_NOTE_TYPES)}",
        )
    db = _get_db()
    rows = db.get_journal_notes(limit=limit, note_type=note_type, trade_id=trade_id)
    return [
        JournalNoteResponse(
            id=r["id"],
            trade_id=r.get("trade_id"),
            note_type=r["note_type"],
            title=r["title"],
            body=r.get("body"),
            tags=r.get("tags") or [],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]


# ── POST /journal/notes ────────────────────────────────────────────────────


@router.post(
    "/notes",
    response_model=CreateNoteResponse,
    status_code=201,
    summary="Create a new journal note",
)
def create_journal_note(payload: JournalNoteCreate) -> CreateNoteResponse:
    """
    Add a new journal note.

    - **note_type**: ``observation`` (default) | ``lesson`` | ``alert``.
    - **title**: Short title (required).
    - **body**: Free-text body (optional).
    - **tags**: List of tag strings (optional).
    - **trade_id**: Optional UUID of a linked paper trade.
    """
    if payload.note_type not in _VALID_NOTE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid note_type '{payload.note_type}'.  Must be one of: {sorted(_VALID_NOTE_TYPES)}",
        )
    if not payload.title or not payload.title.strip():
        raise HTTPException(status_code=422, detail="title is required and must not be blank.")
    db = _get_db()
    note_id = db.insert_journal_note(
        note_type=payload.note_type,
        title=payload.title.strip(),
        body=payload.body or "",
        tags=payload.tags or [],
        trade_id=payload.trade_id,
    )
    return CreateNoteResponse(id=note_id, created=True)


# ── DELETE /journal/notes/{note_id} ───────────────────────────────────────


@router.delete(
    "/notes/{note_id}",
    response_model=DeleteNoteResponse,
    summary="Delete a journal note",
)
def delete_journal_note(note_id: int) -> DeleteNoteResponse:
    """
    Permanently delete a journal note by its integer id.

    Returns ``{ "deleted": true }`` on success or a 404 if the note is
    not found.
    """
    db = _get_db()
    deleted = db.delete_journal_note(note_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Journal note {note_id} not found.")
    return DeleteNoteResponse(deleted=True)


# ── GET /journal/regime-stats ──────────────────────────────────────────────


@router.get(
    "/regime-stats",
    response_model=None,
    summary="Win rate broken down by regime",
)
def get_regime_stats() -> dict:
    """
    Query closed paper trades grouped by regime (extracted from strategy_params JSON).

    Returns a list of regime buckets with:
      regime, trade_count, win_count, loss_count, win_rate, avg_pnl, total_pnl

    Regime label comes from strategy_params.regime JSON key written by pipeline_router.
    Trades with no regime are bucketed as 'unknown'.
    """
    from datetime import datetime as _dt

    db = _get_db()
    sql = """
        SELECT
            COALESCE(
                json_extract(strategy_params, '$.regime'),
                'unknown'
            )                                              AS regime,
            COUNT(*)                                       AS trade_count,
            SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)     AS win_count,
            SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END)    AS loss_count,
            ROUND(
                SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0.0 END) * 100.0 / COUNT(*),
                2
            )                                              AS win_rate_pct,
            ROUND(AVG(pnl), 4)                             AS avg_pnl,
            ROUND(SUM(pnl), 4)                             AS total_pnl
        FROM paper_trades
        WHERE status = 'closed'
          AND pnl IS NOT NULL
        GROUP BY regime
        ORDER BY trade_count DESC
    """
    try:
        with db._lock:
            conn = db._connect()
            try:
                rows = conn.execute(sql).fetchall()
            finally:
                conn.close()

        regimes = []
        for row in rows:
            row_dict = (
                dict(row)
                if hasattr(row, "keys")
                else {
                    "regime": row[0],
                    "trade_count": row[1],
                    "win_count": row[2],
                    "loss_count": row[3],
                    "win_rate_pct": row[4],
                    "avg_pnl": row[5],
                    "total_pnl": row[6],
                }
            )
            regimes.append(
                {
                    "regime": row_dict.get("regime") or "unknown",
                    "trade_count": int(row_dict.get("trade_count") or 0),
                    "win_count": int(row_dict.get("win_count") or 0),
                    "loss_count": int(row_dict.get("loss_count") or 0),
                    "win_rate_pct": float(row_dict.get("win_rate_pct") or 0.0),
                    "avg_pnl": float(row_dict.get("avg_pnl") or 0.0),
                    "total_pnl": float(row_dict.get("total_pnl") or 0.0),
                }
            )

        return {
            "regimes": regimes,
            "total_closed_trades": sum(r["trade_count"] for r in regimes),
            "timestamp": _dt.utcnow().isoformat() + "Z",
        }
    except Exception as exc:
        logger.error(f"[Journal] regime-stats error: {exc}")
        raise HTTPException(500, f"Regime stats error: {exc}") from exc

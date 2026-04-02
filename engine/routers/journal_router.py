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

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from database.schema import DatabaseManager

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

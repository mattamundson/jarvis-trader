"""research_journal_router.py — Research Journal API router.

Backs the Research Journal UI with a dedicated SQLite database at
engine/data/journal.db (separate from the trade journal DatabaseManager).

Table: journal_entries
Columns: id, date, category, status, entry, instrument, tags, created_at, updated_at

Categories : CRITICAL | FINDING | IMPROVEMENT | VERDICT | NOTE
Statuses   : Active | Resolved | Archived

Endpoints
---------
GET    /research-journal/entries            — list with optional filters
POST   /research-journal/entries            — create entry
GET    /research-journal/entries/{id}       — get single entry
PATCH  /research-journal/entries/{id}       — update status / text / tags
DELETE /research-journal/entries/{id}       — soft-delete (set status=Archived)
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger("jarvis_trader.routers.research_journal")

# ---------------------------------------------------------------------------
# Database path & schema bootstrap
# ---------------------------------------------------------------------------

_DB_PATH = Path(__file__).parent.parent / "data" / "journal.db"
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS journal_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT    NOT NULL,
    category    TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'Active',
    entry       TEXT    NOT NULL,
    instrument  TEXT,
    tags        TEXT,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
"""

_SEED_ENTRIES = [
    {
        "date": "2026-03-29",
        "category": "CRITICAL",
        "status": "Resolved",
        "entry": "MGC 1d adaptive WFE=0.88 (3-window) — small-sample bias exposed by 15-window",
        "instrument": "MGC",
        "tags": "[]",
    },
    {
        "date": "2026-03-29",
        "category": "FINDING",
        "status": "Active",
        "entry": "Regime classifier anti-predictive for gold daily (regime=ON loses money)",
        "instrument": "MGC",
        "tags": "[]",
    },
    {
        "date": "2026-03-29",
        "category": "IMPROVEMENT",
        "status": "Active",
        "entry": "MES v2.5 PF 0.96→1.69 with regime_filter=OFF",
        "instrument": "MES",
        "tags": "[]",
    },
    {
        "date": "2026-03-29",
        "category": "VERDICT",
        "status": "Active",
        "entry": "All static param sets fail 15-window WF — fundamental redesign needed",
        "instrument": None,
        "tags": "[]",
    },
]

_VALID_CATEGORIES = {"CRITICAL", "FINDING", "IMPROVEMENT", "VERDICT", "NOTE"}
_VALID_STATUSES = {"Active", "Resolved", "Archived"}


def _get_conn() -> sqlite3.Connection:
    """Open a row_factory-enabled connection to the research journal DB."""
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    """Create table and seed if empty. Called at module import."""
    with _get_conn() as conn:
        conn.execute(_CREATE_TABLE_SQL)
        conn.commit()

        row = conn.execute("SELECT COUNT(*) AS cnt FROM journal_entries").fetchone()
        if row["cnt"] == 0:
            now = datetime.now(timezone.utc).isoformat()
            for seed in _SEED_ENTRIES:
                conn.execute(
                    """
                    INSERT INTO journal_entries
                        (date, category, status, entry, instrument, tags, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        seed["date"],
                        seed["category"],
                        seed["status"],
                        seed["entry"],
                        seed["instrument"],
                        seed["tags"],
                        now,
                        now,
                    ),
                )
            conn.commit()
            logger.info("Research journal seeded with %d entries.", len(_SEED_ENTRIES))


# Run on import so the table is ready before any request arrives.
try:
    _init_db()
except Exception as _init_exc:  # noqa: BLE001
    logger.error("Research journal DB init failed: %s", _init_exc)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class JournalEntryCreate(BaseModel):
    date: str
    category: str
    status: str = "Active"
    entry: str
    instrument: Optional[str] = None
    tags: List[str] = []


class JournalEntryUpdate(BaseModel):
    status: Optional[str] = None
    entry: Optional[str] = None
    tags: Optional[List[str]] = None


class JournalEntryResponse(BaseModel):
    id: int
    date: str
    category: str
    status: str
    entry: str
    instrument: Optional[str] = None
    tags: List[str] = []
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_response(row: sqlite3.Row) -> JournalEntryResponse:
    """Convert a DB row into a JournalEntryResponse."""
    raw_tags = row["tags"] or "[]"
    try:
        tags = json.loads(raw_tags)
    except (json.JSONDecodeError, TypeError):
        tags = []
    return JournalEntryResponse(
        id=row["id"],
        date=row["date"],
        category=row["category"],
        status=row["status"],
        entry=row["entry"],
        instrument=row["instrument"],
        tags=tags,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _validate_category(category: str) -> None:
    if category not in _VALID_CATEGORIES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid category '{category}'. Must be one of: {sorted(_VALID_CATEGORIES)}",
        )


def _validate_status(status: str) -> None:
    if status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{status}'. Must be one of: {sorted(_VALID_STATUSES)}",
        )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/research-journal", tags=["research-journal"])


# ── GET /research-journal/entries ──────────────────────────────────────────


@router.get(
    "/entries",
    response_model=List[JournalEntryResponse],
    summary="List research journal entries",
)
def list_entries(
    category: Optional[str] = Query(
        default=None,
        description="Filter by category: CRITICAL | FINDING | IMPROVEMENT | VERDICT | NOTE",
    ),
    status: Optional[str] = Query(
        default=None,
        description="Filter by status: Active | Resolved | Archived",
    ),
    instrument: Optional[str] = Query(
        default=None,
        description="Filter by instrument symbol, e.g. MES, MGC",
    ),
    limit: int = Query(default=50, ge=1, le=500, description="Max rows to return"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
) -> List[JournalEntryResponse]:
    """
    Return research journal entries with optional filters, ordered newest-first
    (by ``created_at`` descending).

    - **category**: CRITICAL | FINDING | IMPROVEMENT | VERDICT | NOTE
    - **status**: Active | Resolved | Archived
    - **instrument**: Symbol filter (e.g. MES, MGC)
    - **limit**: Max rows (1–500, default 50)
    - **offset**: Pagination offset
    """
    if category:
        _validate_category(category)
    if status:
        _validate_status(status)

    sql = "SELECT * FROM journal_entries WHERE 1=1"
    params: list = []

    if category:
        sql += " AND category = ?"
        params.append(category)
    if status:
        sql += " AND status = ?"
        params.append(status)
    if instrument:
        sql += " AND instrument = ?"
        params.append(instrument)

    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    try:
        with _get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_response(r) for r in rows]
    except sqlite3.Error as exc:
        logger.error("DB error listing research journal entries: %s", exc)
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc


# ── POST /research-journal/entries ─────────────────────────────────────────


@router.post(
    "/entries",
    response_model=JournalEntryResponse,
    status_code=201,
    summary="Create a research journal entry",
)
def create_entry(payload: JournalEntryCreate) -> JournalEntryResponse:
    """
    Create a new research journal entry.

    - **date**: Session or research date (YYYY-MM-DD).
    - **category**: CRITICAL | FINDING | IMPROVEMENT | VERDICT | NOTE.
    - **status**: Active (default) | Resolved | Archived.
    - **entry**: Free-text body of the finding or note.
    - **instrument**: Optional symbol this entry relates to (e.g. MES, MGC).
    - **tags**: Optional list of tag strings.
    """
    # Validate date format
    try:
        datetime.strptime(payload.date, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid date format '{payload.date}'. Expected YYYY-MM-DD.",
        ) from exc

    _validate_category(payload.category)
    _validate_status(payload.status)

    if not payload.entry.strip():
        raise HTTPException(status_code=422, detail="entry must not be blank.")

    now = datetime.now(timezone.utc).isoformat()
    tags_json = json.dumps(payload.tags)

    try:
        with _get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO journal_entries
                    (date, category, status, entry, instrument, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.date,
                    payload.category,
                    payload.status,
                    payload.entry,
                    payload.instrument,
                    tags_json,
                    now,
                    now,
                ),
            )
            conn.commit()
            new_id = cursor.lastrowid

            row = conn.execute(
                "SELECT * FROM journal_entries WHERE id = ?", (new_id,)
            ).fetchone()

        if row is None:
            raise HTTPException(status_code=500, detail="Entry created but could not be retrieved.")
        return _row_to_response(row)

    except sqlite3.Error as exc:
        logger.error("DB error creating research journal entry: %s", exc)
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc


# ── GET /research-journal/entries/{id} ─────────────────────────────────────


@router.get(
    "/entries/{entry_id}",
    response_model=JournalEntryResponse,
    summary="Get a single research journal entry",
)
def get_entry(entry_id: int) -> JournalEntryResponse:
    """
    Return a single research journal entry by its integer ``id``.

    Raises 404 if the entry does not exist.
    """
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM journal_entries WHERE id = ?", (entry_id,)
            ).fetchone()
    except sqlite3.Error as exc:
        logger.error("DB error fetching research journal entry %d: %s", entry_id, exc)
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Research journal entry {entry_id} not found.",
        )
    return _row_to_response(row)


# ── PATCH /research-journal/entries/{id} ───────────────────────────────────


@router.patch(
    "/entries/{entry_id}",
    response_model=JournalEntryResponse,
    summary="Update a research journal entry",
)
def update_entry(entry_id: int, payload: JournalEntryUpdate) -> JournalEntryResponse:
    """
    Partially update a research journal entry.

    Only supplied fields are modified. At least one field must be provided.

    - **status**: Change lifecycle status (Active | Resolved | Archived).
    - **entry**: Replace the entry text.
    - **tags**: Replace the tags list.
    """
    if payload.status is None and payload.entry is None and payload.tags is None:
        raise HTTPException(
            status_code=422,
            detail="At least one of status, entry, or tags must be provided.",
        )

    if payload.status is not None:
        _validate_status(payload.status)
    if payload.entry is not None and not payload.entry.strip():
        raise HTTPException(status_code=422, detail="entry must not be blank.")

    # Build dynamic SET clause
    set_clauses: list[str] = []
    params: list = []

    if payload.status is not None:
        set_clauses.append("status = ?")
        params.append(payload.status)
    if payload.entry is not None:
        set_clauses.append("entry = ?")
        params.append(payload.entry)
    if payload.tags is not None:
        set_clauses.append("tags = ?")
        params.append(json.dumps(payload.tags))

    now = datetime.now(timezone.utc).isoformat()
    set_clauses.append("updated_at = ?")
    params.append(now)
    params.append(entry_id)

    sql = f"UPDATE journal_entries SET {', '.join(set_clauses)} WHERE id = ?"

    try:
        with _get_conn() as conn:
            cursor = conn.execute(sql, params)
            conn.commit()

            if cursor.rowcount == 0:
                raise HTTPException(
                    status_code=404,
                    detail=f"Research journal entry {entry_id} not found.",
                )

            row = conn.execute(
                "SELECT * FROM journal_entries WHERE id = ?", (entry_id,)
            ).fetchone()

    except HTTPException:
        raise
    except sqlite3.Error as exc:
        logger.error("DB error updating research journal entry %d: %s", entry_id, exc)
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    return _row_to_response(row)


# ── DELETE /research-journal/entries/{id} ──────────────────────────────────


@router.delete(
    "/entries/{entry_id}",
    response_model=JournalEntryResponse,
    summary="Soft-delete (archive) a research journal entry",
)
def delete_entry(entry_id: int) -> JournalEntryResponse:
    """
    Soft-delete a research journal entry by setting its status to ``Archived``.

    Returns the updated entry. Raises 404 if not found.
    """
    now = datetime.now(timezone.utc).isoformat()

    try:
        with _get_conn() as conn:
            cursor = conn.execute(
                "UPDATE journal_entries SET status = 'Archived', updated_at = ? WHERE id = ?",
                (now, entry_id),
            )
            conn.commit()

            if cursor.rowcount == 0:
                raise HTTPException(
                    status_code=404,
                    detail=f"Research journal entry {entry_id} not found.",
                )

            row = conn.execute(
                "SELECT * FROM journal_entries WHERE id = ?", (entry_id,)
            ).fetchone()

    except HTTPException:
        raise
    except sqlite3.Error as exc:
        logger.error("DB error archiving research journal entry %d: %s", entry_id, exc)
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    return _row_to_response(row)

"""
JARVIS TRADER — Framing Brief router (premarket + preclose)
=============================================================
Exposes ``GET /framing-brief/latest`` and ``GET /framing-brief/{date}``, serving
the markdown files ``engine/scripts/morning_framing_brief.py`` (premarket,
``{date}.md``) and ``engine/scripts/preclose_framing_brief.py`` (preclose,
``{date}-preclose.md``) write to ``engine/data/framing_briefs/``. This is the
dashboard's read surface — the persistent, unfragmented alternative to the
chunked Discord post (both come from the same generation run; this is not a
choice between them).

``session`` defaults to "premarket" on both routes, preserving the exact
no-param behavior that existed before the preclose brief was added — the
premarket glob (``????-??-??.md``, exactly 10 chars + ``.md``) never matches
the longer ``-preclose`` suffix, so this needs no defensive filtering either.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/framing-brief", tags=["framing-brief"])

_ROUTERS_DIR = Path(__file__).resolve().parent
_ENGINE_DIR = _ROUTERS_DIR.parent
_BRIEF_DIR = _ENGINE_DIR / "data" / "framing_briefs"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

Session = Literal["premarket", "preclose"]
_VALID_SESSIONS = ("premarket", "preclose")


def _validate_session(session: str) -> Session:
    if session not in _VALID_SESSIONS:
        raise HTTPException(status_code=400, detail=f"session must be one of {_VALID_SESSIONS}")
    return session  # type: ignore[return-value]


def _brief_path(brief_date: str, session: Session) -> Path:
    suffix = "-preclose" if session == "preclose" else ""
    return _BRIEF_DIR / f"{brief_date}{suffix}.md"


def _read_brief(path: Path, brief_date: str, session: Session) -> dict:
    return {
        "date": brief_date,
        "session": session,
        "markdown": path.read_text(encoding="utf-8"),
        "generated_at": path.stat().st_mtime,
    }


@router.get("/latest")
async def get_latest_framing_brief(session: str = "premarket"):
    """Return the most recently generated framing brief for the given session."""
    validated = _validate_session(session)
    if not _BRIEF_DIR.exists():
        raise HTTPException(status_code=404, detail="no framing briefs generated yet")

    glob_pattern = "????-??-??-preclose.md" if validated == "preclose" else "????-??-??.md"
    files = sorted(_BRIEF_DIR.glob(glob_pattern))
    if not files:
        raise HTTPException(status_code=404, detail=f"no {validated} framing briefs generated yet")

    latest = files[-1]
    brief_date = latest.stem.removesuffix("-preclose")
    return _read_brief(latest, brief_date, validated)


@router.get("/{brief_date}")
async def get_framing_brief(brief_date: str, session: str = "premarket"):
    """Return the framing brief for a specific date (YYYY-MM-DD) and session."""
    if not _DATE_RE.match(brief_date):
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    try:
        date.fromisoformat(brief_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid date") from exc
    validated = _validate_session(session)

    path = _brief_path(brief_date, validated)
    if not path.exists():
        raise HTTPException(
            status_code=404, detail=f"no {validated} framing brief for {brief_date}"
        )

    return _read_brief(path, brief_date, validated)

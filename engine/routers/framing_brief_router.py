"""
JARVIS TRADER — Morning Framing Brief router
=============================================
Exposes ``GET /framing-brief/latest`` and ``GET /framing-brief/{date}``, serving
the markdown files ``engine/scripts/morning_framing_brief.py`` writes to
``engine/data/framing_briefs/``. This is the dashboard's read surface — the
persistent, unfragmented alternative to the chunked Discord post (both come
from the same generation run; this is not a choice between them).
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/framing-brief", tags=["framing-brief"])

_ROUTERS_DIR = Path(__file__).resolve().parent
_ENGINE_DIR = _ROUTERS_DIR.parent
_BRIEF_DIR = _ENGINE_DIR / "data" / "framing_briefs"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _read_brief(path: Path, brief_date: str) -> dict:
    return {
        "date": brief_date,
        "markdown": path.read_text(encoding="utf-8"),
        "generated_at": path.stat().st_mtime,
    }


@router.get("/latest")
async def get_latest_framing_brief():
    """Return the most recently generated framing brief."""
    if not _BRIEF_DIR.exists():
        raise HTTPException(status_code=404, detail="no framing briefs generated yet")

    files = sorted(_BRIEF_DIR.glob("????-??-??.md"))
    if not files:
        raise HTTPException(status_code=404, detail="no framing briefs generated yet")

    latest = files[-1]
    return _read_brief(latest, latest.stem)


@router.get("/{brief_date}")
async def get_framing_brief(brief_date: str):
    """Return the framing brief for a specific date (YYYY-MM-DD)."""
    if not _DATE_RE.match(brief_date):
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    try:
        date.fromisoformat(brief_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid date") from exc

    path = _BRIEF_DIR / f"{brief_date}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"no framing brief for {brief_date}")

    return _read_brief(path, brief_date)

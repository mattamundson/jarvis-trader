"""
JARVIS TRADER — Options implied-signals router
===============================================
Serves the SPY/QQQ market-implied snapshot that
``engine/scripts/options_signals_snapshot.py`` writes to
``engine/data/options_signals/latest.json`` — the read surface for the
/signals dashboard page's Options section.

Prefix is ``/options-signals`` because ``/options`` is owned by the (disabled)
options automation module's router. Staleness is self-reported by the payload
(``generated_at`` + ``stale_after_s``), not computed here — the dashboard owns
the LIVE/STALE presentation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/options-signals", tags=["options-signals"])

_ROUTERS_DIR = Path(__file__).resolve().parent
_ENGINE_DIR = _ROUTERS_DIR.parent
_DATA_DIR = _ENGINE_DIR / "data" / "options_signals"


@router.get("/latest")
async def get_latest_options_signals():
    """Return the most recent options-implied snapshot, verbatim."""
    path = _DATA_DIR / "latest.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="no options signals snapshot generated yet")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.error("options signals snapshot corrupt: %s", exc)
        raise HTTPException(status_code=500, detail="snapshot file corrupt") from exc

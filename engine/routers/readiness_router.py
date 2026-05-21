"""
Phase 3 programmatic readiness router — GET /readiness/phase3
=============================================================
Returns a structured GO / WAIT / NO-GO report based on the 10 codified
criteria in engine/readiness/phase3_criteria.py.

This route is INFORMATIONAL ONLY.  It never reads or writes
LIVE_TRADING_ENABLED, safety_layer.py, or engine/.env.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse

from middleware.auth import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/readiness", tags=["readiness", "phase3"])


def _default_db_path() -> str:
    return os.environ.get(
        "DB_PATH",
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data",
            "jarvis_trader.db",
        ),
    )


@router.get(
    "/phase3",
    summary="Phase 3 live-trading readiness — GO / WAIT / NO-GO",
    response_model=None,
    response_description=(
        "Structured readiness report with per-criterion results and overall verdict. "
        "Use ?format=markdown for a human-readable version."
    ),
)
async def get_phase3_readiness(
    format: Annotated[
        Optional[str],
        Query(description="Set to 'markdown' for human-readable output"),
    ] = None,
    _api_key: str = Depends(verify_api_key),
):
    """
    Run all 10 Phase 3 readiness criteria and return the result.

    **Overall verdict logic:**
    - **GO** — all blocker criteria pass AND at most 1 warning fails
    - **WAIT** — all blockers pass but >1 warning fails
    - **NO-GO** — any blocker criterion fails

    This endpoint is read-only and informational.  It does not modify any
    config flags, trading state, or safety layer parameters.

    Add `?format=markdown` to receive a Markdown-formatted report
    (Content-Type: text/plain) suitable for copy-paste into a PR description.
    """
    from readiness.phase3_criteria import _render_markdown, evaluate_all_criteria

    db_path = _default_db_path()

    try:
        report = evaluate_all_criteria(db_path)
    except Exception as exc:
        logger.error("Phase3 readiness evaluation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Readiness evaluation failed: {exc}") from exc

    if format and format.lower() == "markdown":
        md = _render_markdown(report)
        return PlainTextResponse(content=md, media_type="text/markdown")

    return report

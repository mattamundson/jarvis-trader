"""
Phase 3 programmatic readiness router — GET /readiness/phase3
=============================================================
Returns a structured GO / WAIT / NO-GO report based on the 10 codified
criteria in engine/readiness/phase3_criteria.py.

Also exposes GET /readiness/gate-v2-calibration for the Bayesian
threshold calibrator (read-only recommendations; never auto-applied).

This router is INFORMATIONAL ONLY.  It never reads or writes
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
    edge_mode: Annotated[
        Optional[str],
        Query(
            description=(
                "Override readiness edge mode for inspection only: "
                "'paper_accrual' (default) or 'wfo_plus_fidelity'. Read-only; "
                "never persisted. When omitted, READINESS_EDGE_MODE env is honored."
            )
        ),
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

    **Edge mode:** the response includes an `edge_mode` key. By default the
    server honors `READINESS_EDGE_MODE` (default `paper_accrual`, the legacy
    10-criterion set). Pass `?edge_mode=wfo_plus_fidelity` to inspect the
    walk-forward-edge + execution-fidelity verdict without changing any env
    or persisted state; while `ALLOW_PAPER_SIMULATED_ORDERS=False` that mode
    is inert (yields NO-GO until real fills accrue).

    Add `?format=markdown` to receive a Markdown-formatted report
    (Content-Type: text/plain) suitable for copy-paste into a PR description.
    """
    from readiness.phase3_criteria import _render_markdown, evaluate_with_edge_mode

    db_path = _default_db_path()

    try:
        # mode=None -> honors READINESS_EDGE_MODE env (default paper_accrual,
        # byte-identical to the legacy evaluate_all_criteria plus an edge_mode key).
        # An explicit ?edge_mode= overrides for read-only inspection; never persisted.
        report = evaluate_with_edge_mode(db_path, mode=edge_mode)
    except Exception as exc:
        logger.error("Phase3 readiness evaluation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Readiness evaluation failed: {exc}") from exc

    if format and format.lower() == "markdown":
        md = _render_markdown(report)
        return PlainTextResponse(content=md, media_type="text/markdown")

    return report


@router.get(
    "/gate-v2-calibration",
    summary="Bayesian gate-v2 threshold calibration — recommended values only",
    response_model=None,
    response_description=(
        "Recommended thresholds based on accumulated verdict history. "
        "NEVER auto-applied — human review required. "
        "Use ?format=markdown for a vault-ingestible report."
    ),
)
async def get_gate_v2_calibration(
    days: Annotated[
        Optional[int],
        Query(
            ge=7,
            le=730,
            description="Lookback window in days (default 90)",
        ),
    ] = 90,
    format: Annotated[
        Optional[str],
        Query(description="Set to 'markdown' for vault-ingestible output"),
    ] = None,
    _api_key: str = Depends(verify_api_key),
):
    """
    Run the Bayesian gate-v2 threshold calibrator and return recommended values.

    **This endpoint is strictly read-only.**  It analyses accumulated verdict
    history and paper-trade outcomes to suggest whether gate thresholds should
    be tightened or loosened.  It does NOT modify ``GATE_V2_*`` env vars,
    ``engine/.env``, or any config file.

    **Recommendation strength:**
    - ``weak`` — n < 50 verdicts; prior dominates; treat as directional only
    - ``moderate`` — 50–199 verdicts; credible signal; review with intuition
    - ``strong`` — >= 200 verdicts; data dominates; worth considering change

    **When to act on recommendations:**  Only when strength is "strong" AND
    the direction aligns with current market-regime intuition.  See
    ``docs/runbooks/GATE_V2_CALIBRATOR_RUNBOOK.md`` for the full workflow.
    """
    from analytics.gate_v2_calibrator import (
        collect_historical_verdicts,
        diff_vs_current,
        recommended_thresholds,
        render_vault_markdown,
    )

    db_path = _default_db_path()
    lookback = days or 90

    try:
        verdicts_df = collect_historical_verdicts(db_path=db_path, lookback_days=lookback)
        rec = recommended_thresholds(verdicts_df)
        diff = diff_vs_current(rec)
    except Exception as exc:
        logger.error("Gate-v2 calibration failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Calibration failed: {exc}") from exc

    if format and format.lower() == "markdown":
        md = render_vault_markdown(rec, diff)
        return PlainTextResponse(content=md, media_type="text/markdown")

    return {
        "recommended_thresholds": {
            k: v
            for k, v in rec.items()
            if k not in {"sample_size", "confidence", "recommendation_strength"}
        },
        "sample_size": rec["sample_size"],
        "confidence": rec["confidence"],
        "recommendation_strength": rec["recommendation_strength"],
        "diff_vs_current": diff,
        "lookback_days": lookback,
        "note": (
            "Read-only. Recommendations never auto-applied. "
            "See docs/runbooks/GATE_V2_CALIBRATOR_RUNBOOK.md."
        ),
    }

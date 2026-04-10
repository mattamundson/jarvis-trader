"""
Trading decisions endpoints
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

from database import repository as db_repository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["decisions"])

# In-memory ring buffer — used as fallback when PostgreSQL is unavailable
_decision_log: list[dict] = []

# SQLite DatabaseManager — injected at startup via set_db_manager()
_db_manager = None


def set_db_manager(db) -> None:
    """Inject the application-level SQLite DatabaseManager into this router."""
    global _db_manager
    _db_manager = db


@router.get("/decisions/recent")
async def get_recent_decisions(limit: int = 20, symbol: str = None, agent: str = None):
    """Return most recent agent decisions from PostgreSQL, falling back to in-memory log"""
    try:
        rows = await db_repository.get_recent_decisions(
            agent_name=agent,
            symbol=symbol.upper() if symbol else None,
            limit=limit,
        )
        if rows:
            return rows
    except Exception as exc:
        logger.warning(f"[DB] get_recent_decisions from PostgreSQL failed: {exc}")
    # Fallback: return in-memory ring buffer
    return _decision_log[-limit:]


@router.get("/decisions/{decision_id}/detail")
async def get_decision_detail(decision_id: int):
    """
    Return the full stage-by-stage pipeline breakdown for a single decision.

    Includes all available data:
    - Stage 1: analyst_reports (technical, news, social, fundamental)
    - Stage 2: debate_result (bull_score, bear_score, verdict, debate_score)
    - Stage 3: trade_decision (action, confidence, reasoning, entry/stop/target)
    - Stage 4: risk_decision (approved, risk_score, reasoning, checks)
    - Stage 5: fund_decision (approved, final_conviction, reasoning)
    - Confidence gate: boosted_confidence, confidence_threshold, gate_triggered
    - Final: final_action, final_quantity, requires_human, summary

    Returns 404 if the decision row has no full_pipeline_json stored.
    Rows created before migration 019 will not have this data.
    """
    if _db_manager is None:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        row = _db_manager.get_decision_by_id(decision_id)
    except Exception as exc:
        logger.warning(f"[DB] get_decision_by_id({decision_id}) failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    if row is None:
        raise HTTPException(status_code=404, detail=f"Decision {decision_id} not found")

    full_pipeline = row.get("full_pipeline_json")
    if not full_pipeline:
        # Row exists but predates migration 019 — return what we have with a note
        return {
            "id": row.get("id"),
            "symbol": row.get("symbol"),
            "timestamp": row.get("timestamp"),
            "action": row.get("action"),
            "confidence": row.get("confidence"),
            "regime": row.get("regime"),
            "reasoning": row.get("reasoning"),
            "signal_data": row.get("signal_data_json"),
            "full_pipeline": None,
            "note": (
                "Full pipeline breakdown not available for this decision. "
                "Only decisions recorded after migration 019 include stage-by-stage data."
            ),
        }

    # Parse out key stage summaries for top-level convenience fields
    analyst_reports = full_pipeline.get("analyst_reports", {})
    debate_result = full_pipeline.get("debate_result", {})
    trade_decision = full_pipeline.get("trade_decision", {})
    risk_decision = full_pipeline.get("risk_decision", {})
    fund_decision = full_pipeline.get("fund_decision")

    # Build analyst summary table
    stage1_summary: dict = {}
    for agent_name in ("technical", "news", "social", "fundamental"):
        report = analyst_reports.get(agent_name, {})
        if report:
            stage1_summary[agent_name] = {
                "signal": report.get("signal"),
                "confidence": report.get("confidence"),
                "summary": report.get("summary", ""),
                "regime": report.get("regime"),
                "trend": report.get("trend"),
            }

    return {
        "id": row.get("id"),
        "symbol": row.get("symbol"),
        "timestamp": row.get("timestamp"),
        "action": row.get("action"),
        "confidence": row.get("confidence"),
        "regime": row.get("regime"),
        # ── Stage summaries (convenience layer) ────────────────────────
        "stage1_analysts": stage1_summary,
        "stage2_debate": {
            "verdict": debate_result.get("verdict"),
            "debate_score": debate_result.get("debate_score"),
            "bull_score": debate_result.get("bull_score"),
            "bear_score": debate_result.get("bear_score"),
            "summary": debate_result.get("summary", ""),
            "scoring_failed": debate_result.get("scoring_failed", False),
        },
        "stage3_trader": {
            "action": trade_decision.get("action"),
            "confidence": trade_decision.get("confidence"),
            "reasoning": trade_decision.get("reasoning", ""),
            "entry_price": trade_decision.get("entry_price"),
            "stop_price": trade_decision.get("stop_price"),
            "limit_price": trade_decision.get("limit_price"),
            "forced_hold": trade_decision.get("forced_hold", False),
        },
        "stage4_risk": {
            "approved": risk_decision.get("approved"),
            "risk_score": risk_decision.get("risk_score"),
            "reasoning": risk_decision.get("reasoning", ""),
            "forced_hold": risk_decision.get("forced_hold", False),
        },
        "stage5_fund": {
            "approved": fund_decision.get("approved") if fund_decision else None,
            "final_conviction": fund_decision.get("final_conviction") if fund_decision else None,
            "reasoning": fund_decision.get("reasoning", "") if fund_decision else None,
        } if fund_decision else None,
        # ── Confidence gate ─────────────────────────────────────────────
        "confidence_gate": {
            "triggered": full_pipeline.get("confidence_gate_triggered"),
            "raw_confidence": full_pipeline.get("raw_confidence"),
            "boosted_confidence": full_pipeline.get("boosted_confidence"),
            "threshold": full_pipeline.get("confidence_threshold"),
            "reason": full_pipeline.get("confidence_gate_reason"),
            "scorer_adjustment": full_pipeline.get("confidence_scorer_adjustment"),
        },
        # ── Final outcome ───────────────────────────────────────────────
        "final_action": full_pipeline.get("final_action"),
        "final_quantity": full_pipeline.get("final_quantity"),
        "requires_human": full_pipeline.get("requires_human"),
        "summary": full_pipeline.get("summary", ""),
        "errors": full_pipeline.get("errors", []),
        "completed_at": full_pipeline.get("completed_at"),
        # ── Raw full pipeline (for deep inspection) ─────────────────────
        "full_pipeline": full_pipeline,
    }


@router.post("/decisions/log")
async def log_decision(decision: dict):
    """Internal: agents call this to log decisions to the in-memory fallback buffer"""
    _decision_log.append({**decision, "id": len(_decision_log) + 1})
    if len(_decision_log) > 100:
        _decision_log.pop(0)
    return {"ok": True}


# ── Sentiment feed ────────────────────────────────────────────────────────

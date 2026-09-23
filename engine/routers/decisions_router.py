"""
Trading decisions endpoints
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from schemas.decision_log import DecisionRecord, parse_decision_row
<<<<<<< HEAD
=======
from utils.data_provenance import build_data_provenance, stamp_signal_data
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["decisions"])

# In-memory ring buffer — used as fallback when PostgreSQL is unavailable
_decision_log: list[dict] = []

# SQLite DatabaseManager — injected at startup via set_db_manager()
_db_manager = None

<<<<<<< HEAD
=======
# MarketDataManager — injected at startup via set_data_manager() (decision provenance)
_data_manager = None

>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2

def set_db_manager(db) -> None:
    """Inject the application-level SQLite DatabaseManager into this router."""
    global _db_manager
    _db_manager = db


<<<<<<< HEAD
=======
def set_data_manager(dm) -> None:
    """Inject the application-level MarketDataManager into this router.

    Used only to stamp {last_bar_source, serve_age_s} data-provenance onto
    persisted decisions (matches main.py's _log_decision, PR #286).
    """
    global _data_manager
    _data_manager = dm


>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
@router.get("/decisions/recent")
async def get_recent_decisions(limit: int = 20, symbol: str = None, agent: str = None):
    """Return most recent agent decisions from SQLite, falling back to in-memory log"""
    if _db_manager is not None:
        try:
            rows = _db_manager.get_decisions(
                symbol=symbol.upper() if symbol else None,
                limit=limit,
            )
            if rows is not None:
                return rows
        except Exception as exc:
            logger.warning(f"[DB] get_decisions from SQLite failed: {exc}")
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

    # Prefer the typed DecisionRecord path. On schema validation failure
    # (historical rows with shapes the model rejects), fall through to the
    # raw dict path — never break /detail on a schema-evolution edge case.
    record: Optional[DecisionRecord] = None
    try:
        record = parse_decision_row(row)
    except ValidationError as exc:
        logger.warning(
            "[decisions/detail] schema validation failed for id=%s — falling back to raw dict (%s)",
            decision_id, exc.error_count(),
        )

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

    # Typed path — record is the validated DecisionRecord from above.
    if record is not None and record.full_pipeline is not None:
        fp = record.full_pipeline

        stage1_summary: dict = {}
        for agent_name in ("technical", "news", "social", "fundamental"):
            report = fp.analyst_reports.get(agent_name)
            if report is not None:
                stage1_summary[agent_name] = {
                    "signal": report.signal,
                    "confidence": report.confidence,
                    "summary": report.summary,
                    "regime": report.regime,
                    "trend": report.trend,
                }

        stage2 = {
            "verdict": fp.debate_result.verdict if fp.debate_result else None,
            "debate_score": fp.debate_result.debate_score if fp.debate_result else None,
            "bull_score": fp.debate_result.bull_score if fp.debate_result else None,
            "bear_score": fp.debate_result.bear_score if fp.debate_result else None,
            "summary": (fp.debate_result.summary if fp.debate_result else ""),
            "scoring_failed": fp.debate_result.scoring_failed if fp.debate_result else False,
        }
        stage3 = {
            "action": fp.trade_decision.action if fp.trade_decision else None,
            "confidence": fp.trade_decision.confidence if fp.trade_decision else None,
            "reasoning": fp.trade_decision.reasoning if fp.trade_decision else "",
            "entry_price": fp.trade_decision.entry_price if fp.trade_decision else None,
            "stop_price": fp.trade_decision.stop_price if fp.trade_decision else None,
            "limit_price": fp.trade_decision.limit_price if fp.trade_decision else None,
            "forced_hold": fp.trade_decision.forced_hold if fp.trade_decision else False,
        }
        stage4 = {
            "approved": fp.risk_decision.approved if fp.risk_decision else None,
            "risk_score": fp.risk_decision.risk_score if fp.risk_decision else None,
            "reasoning": fp.risk_decision.reasoning if fp.risk_decision else "",
            "forced_hold": fp.risk_decision.forced_hold if fp.risk_decision else False,
        }
        stage5 = (
            {
                "approved": fp.fund_decision.approved,
                "final_quantity": fp.fund_decision.final_quantity,
                "priority": fp.fund_decision.priority,
                "reasoning": fp.fund_decision.reasoning or "",
            }
            if fp.fund_decision is not None
            else None
        )
        gate = fp.confidence_gate()

        return {
            "id": record.id,
            "symbol": record.symbol,
            "timestamp": record.timestamp,
            "action": record.action,
            "confidence": record.confidence,
            "regime": record.regime,
            "stage1_analysts": stage1_summary,
            "stage2_debate": stage2,
            "stage3_trader": stage3,
            "stage4_risk": stage4,
            "stage5_fund": stage5,
            "confidence_gate": {
                "triggered": gate.triggered,
                "raw_confidence": gate.raw_confidence,
                "boosted_confidence": gate.boosted_confidence,
                "threshold": gate.threshold,
                "reason": gate.reason,
                "scorer_adjustment": gate.scorer_adjustment,
            },
            "final_action": fp.final_action,
            "final_quantity": fp.final_quantity,
            "requires_human": fp.requires_human,
            "summary": fp.summary,
            "errors": fp.errors,
            "completed_at": fp.completed_at,
            "full_pipeline": full_pipeline,
        }

    # Fallback raw-dict path — reached when schema validation failed above.
    # Preserves the pre-refactor behavior for historical rows with odd shapes.
    analyst_reports = full_pipeline.get("analyst_reports", {})
    debate_result = full_pipeline.get("debate_result", {})
    trade_decision = full_pipeline.get("trade_decision", {})
    risk_decision = full_pipeline.get("risk_decision", {})
    fund_decision = full_pipeline.get("fund_decision")

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
            "final_quantity": fund_decision.get("final_quantity") if fund_decision else None,
            "priority": fund_decision.get("priority") if fund_decision else None,
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
    """Internal: agents call this to log decisions — persists to SQLite, falls back to memory."""
    import datetime

    entry = {
        **decision,
        "id": len(_decision_log) + 1,
        "timestamp": decision.get("timestamp") or datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    _decision_log.append(entry)
    if len(_decision_log) > 100:
        _decision_log.pop(0)

    if _db_manager is not None:
        try:
<<<<<<< HEAD
            _db_manager.insert_decision(
                symbol=decision.get("symbol", "UNKNOWN"),
                action=decision.get("action", "hold"),
                confidence=float(decision.get("confidence", 0.0)),
                regime=decision.get("regime"),
                signal_data=decision,
=======
            # Data-truth: stamp *what data* this decision was based on (tier +
            # per-symbol serve-age), matching main.py's _log_decision (PR #286).
            # Additive only — never changes a trade decision, never raises.
            symbol = decision.get("symbol", "UNKNOWN")
            provenance = build_data_provenance(_data_manager, symbol)
            sig = stamp_signal_data(decision, provenance)
            _db_manager.insert_decision(
                symbol=symbol,
                action=decision.get("action", "hold"),
                confidence=float(decision.get("confidence", 0.0)),
                regime=decision.get("regime"),
                signal_data=sig,
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
                reasoning=decision.get("reasoning") or decision.get("summary", ""),
                timestamp=entry["timestamp"],
                full_pipeline_data=decision.get("full_pipeline_data"),
            )
        except Exception as _db_err:
            logger.warning("[DECISION] SQLite persist failed: %s", _db_err)

    return {"ok": True}


# ── Sentiment feed ────────────────────────────────────────────────────────

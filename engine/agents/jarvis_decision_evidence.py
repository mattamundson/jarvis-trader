"""Strict adapter for JARVIS's persisted decisions, never for execution.

Consumes rows returned by DatabaseManager.get_decision_by_id() plus independent
point-in-time baseline and forward-outcome attestations. It does not read a live
database, invent historical prices, generate new agent opinions, or place orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any, Mapping

from agents.agent_evidence_research import AgentObservation

_ACTIONS = {"buy": "long", "sell": "short", "hold": "hold"}
_VERDICTS = {"BULL_WINS": "long", "BEAR_WINS": "short", "INCONCLUSIVE": "hold"}


@dataclass(frozen=True)
class HistoricalEvidence:
    """Attested *external* evidence for one decision and a frozen forward horizon.

    The caller MUST independently certify prices, as-of availability, horizon
    definition, baseline algorithm/version and immutable data identities.
    """

    symbol: str
    input_available_at: datetime
    baseline_action: str
    baseline_available_at: datetime
    baseline_identity: str
    forward_return: float
    outcome_available_at: datetime
    outcome_identity: str
    horizon: str


def _timestamp(value: Any, label: str) -> datetime:
    if isinstance(value, datetime):
        ts = value
    elif isinstance(value, str):
        try:
            ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{label} is not an ISO timestamp") from exc
    else:
        raise ValueError(f"{label} missing")
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError(f"{label} must have timezone")
    return ts


def observation_from_stored_decision(
    decision: Mapping[str, Any], evidence: HistoricalEvidence
) -> AgentObservation:
    """Use persisted *actual* JARVIS final action; never synthesize agent output.

    Bull and bear are *advocacy stances* in the existing JARVIS debate system,
    NOT independent bullish/bearish predictions. Debate verdict must still be
    present and valid; the comparator's disagreement is baseline-vs-final-action.
    """
    if type(decision.get("id")) is not int or decision["id"] <= 0:
        raise ValueError("stored decision id required")
    symbol = decision.get("symbol")
    if not isinstance(symbol, str) or not symbol.strip() or symbol.upper() != evidence.symbol.upper():
        raise ValueError("decision/outcome symbol mismatch")
    decided_at = _timestamp(decision.get("timestamp"), "decision.timestamp")
    available_at = _timestamp(evidence.input_available_at, "input_available_at")
    baseline_at = _timestamp(evidence.baseline_available_at, "baseline_available_at")
    outcome_at = _timestamp(evidence.outcome_available_at, "outcome_available_at")
    if available_at > decided_at or baseline_at > decided_at:
        raise ValueError("LOOKAHEAD: inputs or baseline available after decision")
    if outcome_at <= decided_at:
        raise ValueError("outcome must follow decision")
    for name in ("baseline_identity", "outcome_identity", "horizon"):
        if not isinstance(getattr(evidence, name), str) or not getattr(evidence, name).strip():
            raise ValueError(f"{name} evidence required")
    if evidence.baseline_action not in {"long", "short", "hold"}:
        raise ValueError("unsupported independent baseline")
    if not isfinite(evidence.forward_return):
        raise ValueError("nonfinite return")
    pipeline = decision.get("full_pipeline_json")
    if not isinstance(pipeline, dict):
        raise ValueError("full_pipeline_json missing: cannot reconstruct agents")
    debate = pipeline.get("debate_result")
    if not isinstance(debate, dict) or debate.get("verdict") not in _VERDICTS:
        raise ValueError("historical debate verdict missing")
    if debate.get("scoring_failed") or debate.get("credits_exhausted"):
        raise ValueError("degraded debate cannot be certified")
    if not isinstance(debate.get("bull_report"), dict) or not isinstance(
        debate.get("bear_report"), dict
    ):
        raise ValueError("real bull and bear reports required")
    for role in ("bull", "bear"):
        report = debate[f"{role}_report"]
        if str(report.get("symbol", "")).upper() != symbol.upper():
            raise ValueError("agent report symbol mismatch")
        report_at = _timestamp(report.get("timestamp"), f"{role}_report.timestamp")
        if report_at > decided_at:
            raise ValueError("LOOKAHEAD: agent report created after decision")
    if _timestamp(debate.get("timestamp"), "debate.timestamp") > decided_at:
        raise ValueError("LOOKAHEAD: debate created after decision")
    final = decision.get("action")
    if final not in _ACTIONS:
        raise ValueError("unsupported recorded final action")
    if pipeline.get("final_action") != final:
        raise ValueError("stored decision conflicts with pipeline final action")
    # Keep the timestamped, actual *final* pipeline decision separate from the
    # debate's intermediate verdict. Do not recast a debate bias as the final trade.
    return AgentObservation(
        event_id=f"jarvis-decision:{decision['id']}",
        symbol=symbol.upper(),
        decided_at=decided_at,
        available_at=max(available_at, baseline_at),
        bull="long",
        bear="short",
        baseline=evidence.baseline_action,
        agent=_ACTIONS[final],
        forward_return=evidence.forward_return,
        outcome_available_at=outcome_at,
    )

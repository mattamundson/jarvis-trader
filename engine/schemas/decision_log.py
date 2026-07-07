"""
JARVIS TRADER — Decision Log Schema
====================================
Typed Pydantic v2 models describing the shape of the ``decisions`` table
and the embedded ``full_pipeline_json`` payload.

The ``decisions`` table and its router/mixin infrastructure already exist
(see ``engine/routers/decisions_router.py``, ``engine/database/_mixins_decisions.py``,
migration 019 at ``engine/database/migrations.py:857``). This module adds the
type contract that those existing pieces had been passing around as raw
``dict`` objects.

Inspired by GoogleCloudPlatform/agent-starter-pack Vertex AI Evaluation
logging schema (Apache-2.0) — the pattern, not the code. Adapted to the
jarvis-trader 5-stage debate pipeline (analysts -> debate -> trade ->
risk -> fund) already implemented in ``engine/agents/pipeline.py``.

All models use ``extra='allow'`` so fields the pipeline adds in future
migrations don't break downstream parsers, and all stage fields are
``Optional`` because real pipelines have partial failures (abstentions,
missing market data, LLM errors) that ``pipeline._run_analysts`` handles
gracefully — the schema must too.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Shared config
# ---------------------------------------------------------------------------

_BASE_CONFIG = ConfigDict(
    extra="allow",
    str_strip_whitespace=True,
    populate_by_name=True,
)


ActionLiteral = Literal[
    "buy",
    "sell",
    "hold",
    "exit_long",
    "exit_short",
]


# ---------------------------------------------------------------------------
# Stage 1 — analyst reports (technical, news, social, fundamental, corey, ...)
# ---------------------------------------------------------------------------


class AnalystReport(BaseModel):
    """Single analyst's structured output.

    Real shapes come from ``engine/agents/technical_analyst.py::TechnicalReport``,
    ``news_analyst``, ``social_analyst``, ``corey_auction_analyst``, and the
    new ``pattern_vision_analyst``. The contract is intentionally narrow —
    analyst-specific fields (e.g. ``stc_context``) flow through via
    ``extra='allow'``.
    """

    model_config = _BASE_CONFIG

    signal: float = Field(0.0, ge=-1.0, le=1.0)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    summary: str = ""
    regime: Optional[str] = None
    trend: Optional[str] = None
    reasoning: Optional[str] = None


# ---------------------------------------------------------------------------
# Stage 2 — debate result
# ---------------------------------------------------------------------------


class DebateResult(BaseModel):
    """Output of ``engine/agents/debate.py`` bull/bear/neutral round."""

    model_config = _BASE_CONFIG

    verdict: Optional[str] = None
    debate_score: Optional[float] = None
    bull_score: Optional[float] = None
    bear_score: Optional[float] = None
    summary: str = ""
    scoring_failed: bool = False


# ---------------------------------------------------------------------------
# Stage 3 — trader decision
# ---------------------------------------------------------------------------


class TradeDecision(BaseModel):
    """Output of the trader agent translating debate verdict into a plan."""

    model_config = _BASE_CONFIG

    action: Optional[ActionLiteral] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    reasoning: str = ""
    entry_price: Optional[float] = None
    stop_price: Optional[float] = None
    limit_price: Optional[float] = None
    forced_hold: bool = False


# ---------------------------------------------------------------------------
# Stage 4 — risk decision
# ---------------------------------------------------------------------------


class RiskDecision(BaseModel):
    """Output of ``engine/risk/safety_layer.py`` check."""

    model_config = _BASE_CONFIG

    approved: Optional[bool] = None
    risk_score: Optional[float] = None
    reasoning: str = ""
    forced_hold: bool = False


# ---------------------------------------------------------------------------
# Stage 5 — fund manager decision (optional — only runs when bypass off)
# ---------------------------------------------------------------------------


class FundDecision(BaseModel):
    """Output of the fund-manager sizing/priority stage."""

    model_config = _BASE_CONFIG

    approved: Optional[bool] = None
    final_quantity: Optional[int] = None
    priority: Optional[str] = None
    reasoning: Optional[str] = None


# ---------------------------------------------------------------------------
# Confidence gate
# ---------------------------------------------------------------------------


class ConfidenceGate(BaseModel):
    """Metadata describing whether the confidence gate fired.

    The gate logic lives in ``engine/agents/pipeline.py`` and adjusts the
    final action based on boosted vs. raw confidence. This model records
    *what the gate saw*, not *what it did* — the final action is a
    top-level field on ``FullPipeline``.
    """

    model_config = _BASE_CONFIG

    triggered: Optional[bool] = Field(None, alias="confidence_gate_triggered")
    raw_confidence: Optional[float] = None
    boosted_confidence: Optional[float] = None
    threshold: Optional[float] = Field(None, alias="confidence_threshold")
    reason: Optional[str] = Field(None, alias="confidence_gate_reason")
    scorer_adjustment: Optional[float] = Field(None, alias="confidence_scorer_adjustment")


# ---------------------------------------------------------------------------
# Full pipeline payload — matches the dict shape embedded in
# decisions.full_pipeline_json (see decisions_router.py:96-167)
# ---------------------------------------------------------------------------


class FullPipeline(BaseModel):
    """Top-level shape of ``decisions.full_pipeline_json`` rows.

    Matches the dict handed back by ``GET /decisions/{id}/detail``
    before the router's convenience flattening. Pre-migration-019 rows
    will have ``full_pipeline_json=None`` at the outer ``DecisionRecord``
    level — this model only describes populated rows.
    """

    model_config = _BASE_CONFIG

    analyst_reports: dict[str, AnalystReport] = Field(default_factory=dict)
    debate_result: Optional[DebateResult] = None
    trade_decision: Optional[TradeDecision] = None
    risk_decision: Optional[RiskDecision] = None
    fund_decision: Optional[FundDecision] = None

    confidence_gate_triggered: Optional[bool] = None
    raw_confidence: Optional[float] = None
    boosted_confidence: Optional[float] = None
    confidence_threshold: Optional[float] = None
    confidence_gate_reason: Optional[str] = None
    confidence_scorer_adjustment: Optional[float] = None

    final_action: Optional[ActionLiteral] = None
    final_quantity: Optional[int] = None
    requires_human: Optional[bool] = None
    summary: str = ""
    errors: list[str] = Field(default_factory=list)
    completed_at: Optional[str] = None

    def confidence_gate(self) -> ConfidenceGate:
        """Assemble the nested ``ConfidenceGate`` view of the flat fields.

        The router returns gate metadata as a nested dict for consumer
        convenience; the stored shape is flat. This helper keeps both
        readers on the same contract without duplicating fields on disk.
        """
        return ConfidenceGate(
            confidence_gate_triggered=self.confidence_gate_triggered,
            raw_confidence=self.raw_confidence,
            boosted_confidence=self.boosted_confidence,
            confidence_threshold=self.confidence_threshold,
            confidence_gate_reason=self.confidence_gate_reason,
            confidence_scorer_adjustment=self.confidence_scorer_adjustment,
        )


# ---------------------------------------------------------------------------
# Top-level row
# ---------------------------------------------------------------------------


class DecisionRecord(BaseModel):
    """One row in the ``decisions`` table.

    Pre-migration-019 rows have ``full_pipeline`` as None. Post-019 rows
    populate the nested ``FullPipeline``. The database layer stores
    ``signal_data`` as JSON in ``signal_data_json`` and ``full_pipeline``
    as JSON in ``full_pipeline_json``; this model describes the parsed
    in-memory form that ``_mixins_decisions.get_decision_by_id`` returns.
    """

    model_config = _BASE_CONFIG

    id: Optional[int] = None
    symbol: str
    timestamp: str
    action: ActionLiteral
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    regime: Optional[str] = None
    reasoning: Optional[str] = None
    signal_data: Optional[Any] = Field(None, alias="signal_data_json")
    full_pipeline: Optional[FullPipeline] = Field(None, alias="full_pipeline_json")


def parse_decision_row(row: dict[str, Any]) -> DecisionRecord:
    """Validate a raw row dict from ``DatabaseManager.get_decision_by_id``.

    Convenience wrapper — the ``_mixins_decisions`` helpers return plain
    dicts with ``signal_data_json`` and ``full_pipeline_json`` already
    JSON-parsed. This function converts to a typed record, aliasing the
    ``_json`` suffixes back to the cleaner domain names.
    """
    return DecisionRecord.model_validate(row)

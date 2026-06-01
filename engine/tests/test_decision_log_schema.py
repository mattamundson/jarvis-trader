"""Tests for engine/schemas/decision_log.py.

Validates the Pydantic schema against row shapes that mirror what
``_mixins_decisions.get_decision_by_id`` actually returns and what
``decisions_router.py:96-171`` flattens back out for the dashboard.
Offline — no database, no router, no network.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from schemas.decision_log import (
    AnalystReport,
    ConfidenceGate,
    DebateResult,
    DecisionRecord,
    FullPipeline,
    RiskDecision,
    TradeDecision,
    parse_decision_row,
)

# ---------------------------------------------------------------------------
# Sample payloads — modeled after real row shapes
# ---------------------------------------------------------------------------


def _full_pipeline_payload() -> dict:
    """Dict matching the shape embedded in decisions.full_pipeline_json."""
    return {
        "analyst_reports": {
            "technical": {
                "signal": 0.4,
                "confidence": 0.65,
                "summary": "Bullish MACD cross; STC cross-above OS",
                "regime": "trending",
                "trend": "uptrend",
                "reasoning": "ADX 28, RSI 55",
                "stc_context": "STC cross-above OS=15",  # extra field — must pass via extra='allow'
            },
            "news": {
                "signal": 0.1,
                "confidence": 0.3,
                "summary": "No material news",
                "regime": None,
                "trend": None,
            },
            "social": {
                "signal": 0.0,
                "confidence": 0.0,
                "summary": "social analyst abstained (no sentiment)",
                "regime": None,
            },
        },
        "debate_result": {
            "verdict": "bull",
            "debate_score": 0.42,
            "bull_score": 0.68,
            "bear_score": 0.26,
            "summary": "Bull case supported by technical + regime alignment",
            "scoring_failed": False,
        },
        "trade_decision": {
            "action": "buy",
            "confidence": 0.55,
            "reasoning": "Enter on 15m close above VWAP",
            "entry_price": 82.15,
            "stop_price": 81.45,
            "limit_price": 82.20,
            "forced_hold": False,
        },
        "risk_decision": {
            "approved": True,
            "risk_score": 0.22,
            "reasoning": "Within daily loss budget; kill switch off",
            "forced_hold": False,
        },
        "fund_decision": {
            "approved": True,
            "final_quantity": 1,
            "priority": "normal",
            "reasoning": "Standard 1-contract sizing per VIX regime",
        },
        "confidence_gate_triggered": False,
        "raw_confidence": 0.55,
        "boosted_confidence": 0.58,
        "confidence_threshold": 0.50,
        "confidence_gate_reason": None,
        "confidence_scorer_adjustment": 0.03,
        "final_action": "buy",
        "final_quantity": 1,
        "requires_human": False,
        "summary": "BUY MCL 1 contract — debate bull, risk approved",
        "errors": [],
        "completed_at": "2026-04-17T16:30:00Z",
    }


def _decision_row_payload() -> dict:
    """Row shape returned by DatabaseManager.get_decision_by_id (post-019)."""
    return {
        "id": 42,
        "symbol": "MCL",
        "timestamp": "2026-04-17T16:30:00Z",
        "action": "buy",
        "confidence": 0.55,
        "regime": "trending",
        "reasoning": "Full debate stack approved long entry",
        "signal_data_json": {"stc": 18.2, "atr": 0.72, "adx": 28.4},
        "full_pipeline_json": _full_pipeline_payload(),
    }


# ---------------------------------------------------------------------------
# AnalystReport
# ---------------------------------------------------------------------------


def test_analyst_report_accepts_minimal_shape():
    report = AnalystReport.model_validate(
        {"signal": 0.5, "confidence": 0.6, "summary": "ok"}
    )
    assert report.signal == 0.5
    assert report.confidence == 0.6


def test_analyst_report_signal_out_of_range_rejected():
    with pytest.raises(ValidationError):
        AnalystReport.model_validate({"signal": 2.0, "confidence": 0.5, "summary": ""})


def test_analyst_report_confidence_out_of_range_rejected():
    with pytest.raises(ValidationError):
        AnalystReport.model_validate({"signal": 0.0, "confidence": 1.5, "summary": ""})


def test_analyst_report_allows_extra_fields():
    # Per-analyst fields (stc_context, mtf_alignment, etc.) must flow through.
    report = AnalystReport.model_validate(
        {
            "signal": 0.3,
            "confidence": 0.4,
            "summary": "",
            "stc_context": "oversold",
            "mtf_alignment": "4h and 1h bullish",
            "regime_readiness": "READY",
        }
    )
    assert report.model_dump().get("stc_context") == "oversold"


def test_analyst_report_defaults_to_zero_abstention():
    # An empty payload must decode as a clean zero-weight abstention,
    # matching TechnicalReport._no_price_report behavior.
    report = AnalystReport.model_validate({})
    assert report.signal == 0.0
    assert report.confidence == 0.0


# ---------------------------------------------------------------------------
# Stage models
# ---------------------------------------------------------------------------


def test_debate_result_accepts_scoring_failure():
    dr = DebateResult.model_validate(
        {"verdict": None, "scoring_failed": True, "summary": "debate math failure"}
    )
    assert dr.scoring_failed is True
    assert dr.verdict is None


def test_trade_decision_accepts_forced_hold():
    td = TradeDecision.model_validate(
        {"action": "hold", "forced_hold": True, "reasoning": "kill switch active"}
    )
    assert td.forced_hold is True


def test_trade_decision_rejects_unknown_action():
    with pytest.raises(ValidationError):
        TradeDecision.model_validate({"action": "teleport"})


def test_risk_decision_accepts_abstention_shape():
    # Risk layer can emit approved=None when safety-layer check itself errors.
    rd = RiskDecision.model_validate({"approved": None, "reasoning": ""})
    assert rd.approved is None


# ---------------------------------------------------------------------------
# FullPipeline
# ---------------------------------------------------------------------------


def test_full_pipeline_parses_canonical_payload():
    fp = FullPipeline.model_validate(_full_pipeline_payload())

    assert fp.final_action == "buy"
    assert fp.final_quantity == 1
    assert fp.requires_human is False
    assert fp.analyst_reports["technical"].signal == pytest.approx(0.4)
    assert fp.debate_result.verdict == "bull"
    assert fp.trade_decision.action == "buy"
    assert fp.risk_decision.approved is True
    assert fp.fund_decision.final_quantity == 1


def test_full_pipeline_confidence_gate_helper_returns_nested_view():
    fp = FullPipeline.model_validate(_full_pipeline_payload())
    gate = fp.confidence_gate()
    assert isinstance(gate, ConfidenceGate)
    assert gate.triggered is False
    assert gate.raw_confidence == pytest.approx(0.55)
    assert gate.boosted_confidence == pytest.approx(0.58)
    assert gate.threshold == pytest.approx(0.50)
    assert gate.scorer_adjustment == pytest.approx(0.03)


def test_full_pipeline_tolerates_missing_stages():
    # A pipeline that failed early (e.g. market data missing) writes a partial
    # payload. The schema must not blow up.
    partial = {
        "analyst_reports": {},
        "final_action": "hold",
        "summary": "data-layer fetch failed",
        "errors": ["polygon 429 rate limit", "ibkr disconnected"],
    }
    fp = FullPipeline.model_validate(partial)
    assert fp.debate_result is None
    assert fp.trade_decision is None
    assert fp.risk_decision is None
    assert fp.errors == ["polygon 429 rate limit", "ibkr disconnected"]


def test_full_pipeline_rejects_out_of_vocab_final_action():
    bad = _full_pipeline_payload()
    bad["final_action"] = "yolo"
    with pytest.raises(ValidationError):
        FullPipeline.model_validate(bad)


# ---------------------------------------------------------------------------
# DecisionRecord + parse_decision_row
# ---------------------------------------------------------------------------


def test_parse_decision_row_accepts_post_019_shape():
    record = parse_decision_row(_decision_row_payload())
    assert record.id == 42
    assert record.symbol == "MCL"
    assert record.action == "buy"
    assert record.full_pipeline is not None
    assert record.full_pipeline.final_action == "buy"
    assert record.signal_data == {"stc": 18.2, "atr": 0.72, "adx": 28.4}


def test_parse_decision_row_accepts_pre_019_shape():
    # Rows created before migration 019 won't have full_pipeline_json.
    # The router falls back to a note; the schema must accept this too.
    row = _decision_row_payload()
    row["full_pipeline_json"] = None
    record = parse_decision_row(row)
    assert record.full_pipeline is None
    assert record.symbol == "MCL"


def test_parse_decision_row_accepts_missing_signal_data():
    row = _decision_row_payload()
    row["signal_data_json"] = None
    record = parse_decision_row(row)
    assert record.signal_data is None


def test_decision_record_rejects_bad_action():
    with pytest.raises(ValidationError):
        DecisionRecord.model_validate(
            {"symbol": "MCL", "timestamp": "2026-04-17T16:30:00Z", "action": "sideways"}
        )


def test_decision_record_rejects_confidence_out_of_range():
    with pytest.raises(ValidationError):
        DecisionRecord.model_validate(
            {
                "symbol": "MCL",
                "timestamp": "2026-04-17T16:30:00Z",
                "action": "buy",
                "confidence": 5.0,
            }
        )


def test_decision_record_json_roundtrip():
    row = _decision_row_payload()
    record = parse_decision_row(row)
    # Dump via Pydantic, re-load via JSON, re-validate — contract must hold.
    blob = record.model_dump_json()
    restored = DecisionRecord.model_validate(json.loads(blob))
    assert restored.symbol == "MCL"
    assert restored.full_pipeline.final_action == "buy"


def test_decision_record_uppercase_symbol_not_auto_forced():
    # The insert helper uppercases symbol before storing, but the schema
    # itself does not transform — that's the DB layer's job, not the model's.
    row = _decision_row_payload()
    row["symbol"] = "mcl"
    record = parse_decision_row(row)
    assert record.symbol == "mcl"

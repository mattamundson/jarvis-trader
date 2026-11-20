"""JARVIS journal adapter: no database credentials, broker or market requests."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from agents.agent_evidence_research import compare_agent_to_baseline
from agents.jarvis_decision_evidence import (
    HistoricalEvidence,
    observation_from_stored_decision,
)

T0 = datetime(2026, 10, 1, 14, tzinfo=UTC)


def decision():
    return {
        "id": 42,
        "symbol": "MES",
        "timestamp": T0.isoformat(),
        "action": "buy",
        "full_pipeline_json": {
            "final_action": "buy",
            "debate_result": {
                "timestamp": (T0 - timedelta(minutes=1)).isoformat(),
                "verdict": "BULL_WINS",
                "scoring_failed": False,
                "credits_exhausted": False,
                "bull_report": {
                    "symbol": "MES",
                    "timestamp": (T0 - timedelta(minutes=2)).isoformat(),
                },
                "bear_report": {
                    "symbol": "MES",
                    "timestamp": (T0 - timedelta(minutes=2)).isoformat(),
                },
            },
        },
    }


def evidence():
    return HistoricalEvidence(
        symbol="MES",
        input_available_at=T0 - timedelta(minutes=5),
        baseline_action="hold",
        baseline_available_at=T0 - timedelta(minutes=4),
        baseline_identity="baseline:v1:hash",
        forward_return=0.015,
        outcome_available_at=T0 + timedelta(hours=1),
        outcome_identity="bars:sha256:123",
        horizon="1h",
    )


def test_uses_real_recorded_decision_not_intermediate_debate():
    row = observation_from_stored_decision(decision(), evidence())
    assert row.event_id == "jarvis-decision:42"
    assert row.agent == "long"
    assert row.baseline == "hold"
    result = compare_agent_to_baseline(
        [row], evaluation_at=T0 + timedelta(hours=2)
    )
    assert result.signed_return_increment == pytest.approx(0.015)
    assert result.disagreement_count == 1


def test_no_reconstruction_without_real_debate_reports():
    raw = decision()
    raw["full_pipeline_json"]["debate_result"]["bull_report"] = None
    with pytest.raises(ValueError, match="reports"):
        observation_from_stored_decision(raw, evidence())


def test_conflicting_pipeline_final_action_rejected():
    raw = decision()
    raw["full_pipeline_json"]["final_action"] = "sell"
    with pytest.raises(ValueError, match="conflicts"):
        observation_from_stored_decision(raw, evidence())


@pytest.mark.parametrize(
    "update",
    [
        {"input_available_at": T0 + timedelta(seconds=1)},
        {"baseline_available_at": T0 + timedelta(seconds=1)},
        {"outcome_available_at": T0},
        {"symbol": "ES"},
        {"baseline_identity": ""},
        {"horizon": ""},
        {"baseline_action": "buy"},
        {"forward_return": float("inf")},
    ],
)
def test_external_evidence_fails_closed(update):
    with pytest.raises(ValueError):
        observation_from_stored_decision(decision(), replace(evidence(), **update))


def test_degraded_or_partial_debate_rejected():
    raw = decision()
    raw["full_pipeline_json"]["debate_result"]["scoring_failed"] = True
    with pytest.raises(ValueError, match="degraded"):
        observation_from_stored_decision(raw, evidence())


def test_future_report_rejected():
    raw = decision()
    raw["full_pipeline_json"]["debate_result"]["bear_report"]["timestamp"] = (
        T0 + timedelta(seconds=1)
    ).isoformat()
    with pytest.raises(ValueError, match="LOOKAHEAD"):
        observation_from_stored_decision(raw, evidence())


def test_missing_full_pipeline_rejected():
    raw = decision()
    raw["full_pipeline_json"] = None
    with pytest.raises(ValueError, match="full_pipeline_json"):
        observation_from_stored_decision(raw, evidence())

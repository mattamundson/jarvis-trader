"""Offline replay harness contract tests; synthetic data only."""
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import pytest

from agents.agent_evidence_cli import evaluate_export
from agents.jarvis_decision_evidence import HistoricalEvidence

T0 = datetime(2026, 10, 1, 14, tzinfo=UTC)


def entry(horizon="1h"):
    decision = {
        "id": 17,
        "symbol": "MES",
        "timestamp": T0.isoformat(),
        "action": "sell",
        "full_pipeline_json": {
            "final_action": "sell",
            "debate_result": {
                "timestamp": (T0 - timedelta(minutes=1)).isoformat(),
                "verdict": "BEAR_WINS",
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
    evidence = HistoricalEvidence(
        symbol="MES",
        input_available_at=T0 - timedelta(minutes=3),
        baseline_action="hold",
        baseline_available_at=T0 - timedelta(minutes=3),
        baseline_identity="fixed:v1",
        forward_return=-0.02,
        outcome_available_at=T0 + timedelta(hours=1),
        outcome_identity="snapshot:abc",
        horizon=horizon,
    )
    return {
        "decision": decision,
        "evidence": {
            **asdict(evidence),
            "input_available_at": evidence.input_available_at.isoformat(),
            "baseline_available_at": evidence.baseline_available_at.isoformat(),
            "outcome_available_at": evidence.outcome_available_at.isoformat(),
        },
    }


def test_explicitly_unverified_descriptive_only():
    report = evaluate_export([entry()], evaluation_at=T0 + timedelta(hours=2))
    assert report["status"] == "DESCRIPTIVE_ONLY_UNVERIFIED_INPUT_ATTESTATIONS"
    assert report["comparison"]["signed_return_increment"] == pytest.approx(0.02)
    assert report["comparison"]["disagreement_count"] == 1


def test_mixed_horizons_rejected():
    other = entry("2h")
    other["decision"]["id"] = 18
    with pytest.raises(ValueError, match="mixed forward horizons"):
        evaluate_export([entry(), other], evaluation_at=T0 + timedelta(hours=3))


def test_missing_data_does_not_generate_results():
    with pytest.raises(ValueError, match="no observations"):
        evaluate_export([], evaluation_at=T0 + timedelta(hours=2))


def test_outcome_future_rejected():
    row = entry()
    row["evidence"]["outcome_available_at"] = (
        T0 + timedelta(days=3)
    ).isoformat()
    with pytest.raises(ValueError, match="LOOKAHEAD"):
        evaluate_export([row], evaluation_at=T0 + timedelta(hours=2))


def test_required_baseline_identity_is_not_invented():
    row = entry()
    row["evidence"]["baseline_identity"] = ""
    with pytest.raises(ValueError, match="baseline_identity"):
        evaluate_export([row], evaluation_at=T0 + timedelta(hours=2))

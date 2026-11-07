"""Unit tests for agent-evidence research; no broker or network required."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from agents.agent_evidence_research import AgentObservation, compare_agent_to_baseline


T0 = datetime(2026, 10, 1, 14, 0, tzinfo=UTC)


def observation(event_id="x", **overrides):
    row = AgentObservation(
        event_id=event_id,
        symbol="ES",
        decided_at=T0,
        available_at=T0 - timedelta(seconds=1),
        bull="long",
        bear="short",
        baseline="long",
        agent="hold",
        forward_return=-0.02,
        outcome_available_at=T0 + timedelta(hours=1),
    )
    return replace(row, **overrides)


def compare(rows):
    return compare_agent_to_baseline(rows, evaluation_at=T0 + timedelta(days=1))


def test_paired_comparison_and_hold_are_explicit():
    result = compare([observation()])
    assert result.count == 1
    assert result.disagreement_count == 1
    assert result.baseline.mean_signed_return == pytest.approx(-0.02)
    assert result.agent.mean_signed_return == 0.0
    assert result.signed_return_increment == pytest.approx(0.02)
    assert result.agent.participation == 0
    assert result.agent.directional_accuracy is None


def test_correct_short_prediction():
    row = observation(agent="short", baseline="hold", forward_return=-0.01)
    result = compare([row])
    assert result.agent.directional_accuracy == 1.0
    assert result.agent.mean_signed_return == pytest.approx(0.01)


@pytest.mark.parametrize(
    "overrides",
    [
        {"available_at": T0 + timedelta(seconds=1)},
        {"outcome_available_at": T0 + timedelta(days=2)},
        {"outcome_available_at": T0},
        {"agent": "buy"},
        {"forward_return": float("nan")},
        {"decided_at": T0.replace(tzinfo=None)},
    ],
)
def test_rejects_invalid_or_future_data(overrides):
    with pytest.raises(ValueError):
        compare([observation(**overrides)])


def test_duplicate_event_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        compare([observation(), observation()])


def test_empty_sample_not_misrepresented_as_zero_edge():
    with pytest.raises(ValueError, match="no observations"):
        compare([])

"""
Tests for engine/agents/research_agent.py

Covers:
  - ENABLE_RESEARCH_AGENT flag defaults to off
  - Flag can be enabled via environment variable
  - StrategyHypothesis Pydantic v2 roundtrip (model_dump / model_validate)
  - ResearchAgent.propose returns a valid, populated hypothesis
"""

from __future__ import annotations

import pytest

from agents.research_agent import (
    ResearchAgent,
    StrategyHypothesis,
    is_research_agent_enabled,
)


# ---------------------------------------------------------------------------
# Feature flag tests
# ---------------------------------------------------------------------------


def test_research_agent_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flag should be off when ENABLE_RESEARCH_AGENT is not in the environment."""
    monkeypatch.delenv("ENABLE_RESEARCH_AGENT", raising=False)
    assert is_research_agent_enabled() is False


def test_research_agent_enabled_when_flag_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Setting ENABLE_RESEARCH_AGENT=1 must return True."""
    monkeypatch.setenv("ENABLE_RESEARCH_AGENT", "1")
    assert is_research_agent_enabled() is True


def test_research_agent_not_enabled_by_other_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Values other than '1' must not enable the flag."""
    for value in ("true", "True", "yes", "on", "0", ""):
        monkeypatch.setenv("ENABLE_RESEARCH_AGENT", value)
        assert is_research_agent_enabled() is False, f"Expected False for value={value!r}"


# ---------------------------------------------------------------------------
# StrategyHypothesis model tests
# ---------------------------------------------------------------------------


def _minimal_hypothesis() -> StrategyHypothesis:
    """Build a minimal but fully-valid StrategyHypothesis for testing."""
    return StrategyHypothesis(
        name="test-hyp-v1",
        symbol="MES",
        timeframe="1h",
        entry_rules=["RSI(14) < 30"],
        exit_rules=["Price crosses above VWAP"],
        signal_weights={"rsi": 1.0},
        risk_params={"stop_atr_mult": 1.5, "tp_atr_mult": 2.5},
        rationale="Unit test hypothesis.",
        confidence=0.42,
    )


def test_strategy_hypothesis_pydantic_roundtrip() -> None:
    """model_dump() then model_validate() must produce an equal object."""
    original = _minimal_hypothesis()
    dumped = original.model_dump()
    restored = StrategyHypothesis.model_validate(dumped)

    assert restored == original
    assert restored.name == "test-hyp-v1"
    assert restored.symbol == "MES"
    assert restored.timeframe == "1h"
    assert restored.confidence == pytest.approx(0.42)


def test_strategy_hypothesis_confidence_bounds() -> None:
    """confidence must reject values outside [0, 1]."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        StrategyHypothesis(
            name="bad",
            symbol="MES",
            timeframe="1h",
            entry_rules=["rule"],
            exit_rules=["rule"],
            rationale="test",
            confidence=1.5,  # invalid
        )

    with pytest.raises(pydantic.ValidationError):
        StrategyHypothesis(
            name="bad",
            symbol="MES",
            timeframe="1h",
            entry_rules=["rule"],
            exit_rules=["rule"],
            rationale="test",
            confidence=-0.1,  # invalid
        )


def test_strategy_hypothesis_requires_entry_rules() -> None:
    """entry_rules must have at least one element."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        StrategyHypothesis(
            name="bad",
            symbol="MES",
            timeframe="1h",
            entry_rules=[],  # invalid — min_length=1
            exit_rules=["exit"],
            rationale="test",
        )


def test_strategy_hypothesis_default_confidence() -> None:
    """confidence defaults to 0.0 when not supplied."""
    h = StrategyHypothesis(
        name="default-conf",
        symbol="MNQ",
        timeframe="15m",
        entry_rules=["some rule"],
        exit_rules=["some rule"],
        rationale="test",
    )
    assert h.confidence == 0.0


# ---------------------------------------------------------------------------
# ResearchAgent.propose tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_returns_valid_hypothesis() -> None:
    """propose('MES') must return a StrategyHypothesis with all required fields."""
    agent = ResearchAgent()
    result = await agent.propose("MES")

    assert isinstance(result, StrategyHypothesis)
    assert result.symbol == "MES"
    assert result.name, "name must be non-empty"
    assert result.timeframe, "timeframe must be non-empty"
    assert len(result.entry_rules) >= 1
    assert len(result.exit_rules) >= 1
    assert result.rationale, "rationale must be non-empty"
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.asyncio
async def test_propose_injects_requested_symbol() -> None:
    """propose should inject the requested symbol, not hard-pin to 'MES'."""
    agent = ResearchAgent()

    for symbol in ("MES", "MNQ", "MGC"):
        result = await agent.propose(symbol)
        assert result.symbol == symbol, f"Expected symbol={symbol}, got {result.symbol}"


@pytest.mark.asyncio
async def test_propose_hypothesis_survives_roundtrip() -> None:
    """The hypothesis returned by propose must survive a Pydantic roundtrip."""
    agent = ResearchAgent()
    result = await agent.propose("MES")

    dumped = result.model_dump()
    restored = StrategyHypothesis.model_validate(dumped)
    assert restored == result

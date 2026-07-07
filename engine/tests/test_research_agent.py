"""
Tests for engine/agents/research_agent.py

Covers:
  - ENABLE_RESEARCH_AGENT flag behavior (on/off/other values)
  - StrategyHypothesis Pydantic v2 contract (roundtrip, bounds, required fields)
  - ResearchAgent.propose: stub path, LLM path (mocked), fallback on parse
    failure, cost gate blocking, cost gate spend recording
  - Weekend pass artifact writes (tmp dir)
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.research_agent import (
    ResearchAgent,
    StrategyHypothesis,
    _get_daily_budget,
    _get_today_spend,
    _increment_today_spend,
    is_research_agent_enabled,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_hypothesis(**overrides) -> StrategyHypothesis:
    """Build a minimal but fully-valid StrategyHypothesis for testing."""
    defaults: dict[str, Any] = {
        "name": "test-hyp-v1",
        "symbol": "MES",
        "timeframe": "1h",
        "entry_rules": ["RSI(14) < 30"],
        "exit_rules": ["Price crosses above VWAP"],
        "signal_weights": {"rsi_oversold": 1.0},
        "risk_params": {"stop_atr_mult": 1.5, "tp_atr_mult": 2.5},
        "rationale": "Unit test hypothesis.",
        "confidence": 0.42,
    }
    defaults.update(overrides)
    return StrategyHypothesis(**defaults)


def _make_llm_result(content: str, success: bool = True) -> MagicMock:
    """Return a mock LLMCallResult with the given content."""
    r = MagicMock()
    r.success = success
    r.content = content
    r.input_tokens = 500
    r.output_tokens = 300
    r.error = None if success else "mock error"
    return r


def _valid_hypothesis_json(symbol: str = "MES") -> str:
    """Return a valid JSON string for a StrategyHypothesis."""
    data = {
        "name": "llm-hyp-v1",
        "symbol": symbol,
        "timeframe": "1h",
        "entry_rules": ["STC crosses 20"],
        "exit_rules": ["Take profit at 2x ATR"],
        "signal_weights": {"stc_crossover": 0.6, "rsi_oversold": 0.4},
        "risk_params": {"stop_atr_mult": 1.5, "tp_atr_mult": 2.5},
        "rationale": "Mean reversion on oversold STC.",
        "confidence": 0.3,
    }
    return json.dumps(data)


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
        _minimal_hypothesis(confidence=1.5)

    with pytest.raises(pydantic.ValidationError):
        _minimal_hypothesis(confidence=-0.1)


def test_strategy_hypothesis_requires_entry_rules() -> None:
    """entry_rules must have at least one element."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        _minimal_hypothesis(entry_rules=[])


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
# test_propose_returns_stub_when_disabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_returns_stub_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """When flag is off, propose() returns the hardcoded MES stub — no LLM call."""
    monkeypatch.delenv("ENABLE_RESEARCH_AGENT", raising=False)

    # AdvisorClient is a lazy import inside propose(); patch it at its source module.
    with patch("agents.advisor_client.AdvisorClient") as mock_cls:
        agent = ResearchAgent()
        result = await agent.propose("MES")

    mock_cls.assert_not_called()  # AdvisorClient never instantiated when flag off
    assert isinstance(result, StrategyHypothesis)
    assert result.symbol == "MES"
    assert result.name == "mes-mean-rev-v1"
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_propose_stub_injects_symbol_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub must inject the requested symbol into the fallback hypothesis."""
    monkeypatch.delenv("ENABLE_RESEARCH_AGENT", raising=False)

    agent = ResearchAgent()
    for symbol in ("MNQ", "MCL", "MGC"):
        result = await agent.propose(symbol)
        assert result.symbol == symbol


# ---------------------------------------------------------------------------
# test_propose_calls_llm_when_enabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_calls_llm_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """When flag is on and budget is clear, propose() calls the LLM and parses the result."""
    monkeypatch.setenv("ENABLE_RESEARCH_AGENT", "1")

    # ignore_cleanup_errors: SQLite WAL files may still be open on Windows cleanup
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "test.db"
        # Seed zero spend so budget is not exhausted
        _increment_today_spend(db_path, 0.0)

        mock_llm = MagicMock()
        mock_llm.call = AsyncMock(return_value=_make_llm_result(_valid_hypothesis_json("MES")))

        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.llm = mock_llm

        # AdvisorClient is a lazy import inside propose(); patch at its definition.
        with patch("agents.advisor_client.AdvisorClient", return_value=mock_client):
            agent = ResearchAgent(db_path=db_path)
            result = await agent.propose("MES")

    assert isinstance(result, StrategyHypothesis)
    assert result.symbol == "MES"
    assert result.name == "llm-hyp-v1"
    # LLM must have been called
    mock_llm.call.assert_called_once()
    call_kwargs = mock_llm.call.call_args.kwargs
    assert call_kwargs["model"] == "claude-haiku-4-5-20251001"
    assert call_kwargs["agent_name"] == "research_agent"
    assert "MES" in call_kwargs["messages"][0]["content"]


# ---------------------------------------------------------------------------
# test_propose_falls_back_on_parse_failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_falls_back_on_parse_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the LLM returns garbage, propose() falls back to the hardcoded stub."""
    monkeypatch.setenv("ENABLE_RESEARCH_AGENT", "1")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "test.db"

        mock_llm = MagicMock()
        mock_llm.call = AsyncMock(
            return_value=_make_llm_result("NOT VALID JSON AT ALL !!! @@@ ###")
        )

        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.llm = mock_llm

        with patch("agents.advisor_client.AdvisorClient", return_value=mock_client):
            agent = ResearchAgent(db_path=db_path)
            result = await agent.propose("MES")

    assert isinstance(result, StrategyHypothesis)
    # Must fall back to the hardcoded stub
    assert result.name == "mes-mean-rev-v1"


# ---------------------------------------------------------------------------
# test_cost_gate_blocks_after_budget_exhausted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_gate_blocks_after_budget_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    """When today's spend >= budget, propose() returns the stub without calling LLM."""
    monkeypatch.setenv("ENABLE_RESEARCH_AGENT", "1")
    monkeypatch.setenv("RESEARCH_AGENT_DAILY_BUDGET_USD", "5.00")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "test.db"
        # Synthetic spend above budget
        _increment_today_spend(db_path, 5.01)

        mock_llm = MagicMock()
        mock_llm.call = AsyncMock()

        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.llm = mock_llm

        # No need to patch AdvisorClient here — cost gate fires before LLM import
        agent = ResearchAgent(db_path=db_path)
        result = await agent.propose("MES")

    mock_llm.call.assert_not_called()
    assert isinstance(result, StrategyHypothesis)
    assert result.name == "mes-mean-rev-v1"


# ---------------------------------------------------------------------------
# test_cost_gate_records_spend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_gate_records_spend(monkeypatch: pytest.MonkeyPatch) -> None:
    """After a successful LLM call, today's spend must be incremented in the DB."""
    monkeypatch.setenv("ENABLE_RESEARCH_AGENT", "1")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "test.db"
        spend_before = _get_today_spend(db_path)
        assert spend_before == pytest.approx(0.0)

        mock_llm = MagicMock()
        mock_llm.call = AsyncMock(return_value=_make_llm_result(_valid_hypothesis_json("MES")))

        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.llm = mock_llm

        with patch("agents.advisor_client.AdvisorClient", return_value=mock_client):
            agent = ResearchAgent(db_path=db_path)
            await agent.propose("MES")

        spend_after = _get_today_spend(db_path)

    # Must have recorded some positive spend
    assert spend_after > 0.0


# ---------------------------------------------------------------------------
# test_weekend_pass_writes_artifacts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weekend_pass_writes_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Weekend pass must write per-symbol JSON files and a Markdown summary
    to the configured tmp directory.
    """
    monkeypatch.delenv("ENABLE_RESEARCH_AGENT", raising=False)  # stub mode is fine

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        hypotheses_dir = tmp_path / "hypotheses"
        summary_dir = tmp_path / "summary"

        # Patch the module-level path constants in research_agent_weekend
        with (
            patch(
                "scheduler.research_agent_weekend._HYPOTHESES_DIR",
                hypotheses_dir,
            ),
            patch(
                "scheduler.research_agent_weekend._VAULT_SUMMARY_DIR",
                summary_dir,
            ),
        ):
            from scheduler.research_agent_weekend import run_weekend_research_pass

            result = await run_weekend_research_pass(
                symbols=["MES", "MNQ"],
                n_hypotheses_per_symbol=2,
            )

        # JSON artifacts
        assert result["total_written"] == 4  # 2 symbols * 2 hyps

        from datetime import date

        run_date = date.today().isoformat()
        dated_dir = hypotheses_dir / run_date
        assert dated_dir.exists()

        # Each symbol must have written its files
        for symbol in ("MES", "MNQ"):
            for n in (1, 2):
                f = dated_dir / f"{symbol}-{n}.json"
                assert f.exists(), f"Expected artifact {f}"
                data = json.loads(f.read_text())
                assert data["symbol"] == symbol
                assert "generated_at" in data

        # Markdown summary
        summary_file = summary_dir / f"research-pass-{run_date}.md"
        assert summary_file.exists()
        content = summary_file.read_text()
        assert "MES" in content
        assert "MNQ" in content
        assert "Research pass" in content

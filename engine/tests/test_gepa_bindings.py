"""Regression tests for engine/llm/gepa_bindings.py (#644: feat(llm): wire
GEPA prompt-optimizer to real trade outcomes) -- SqliteTradeEvalSource,
SonnetPromptMutator, and SonnetPromptScorer shipped with zero test coverage
(post-merge review of #644).

The Sonnet mutator/scorer LLM calls are mocked via a lightweight fake client
(the same DI seam gepa_bindings.py itself exposes -- `llm_client=`), matching
the FakeClient convention already used elsewhere in engine/tests (see
test_corey_llm_client_factory.py). SqliteTradeEvalSource is exercised against
a real, isolated SQLite DB -- no mocking of the DB layer.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from analytics.agent_feedback import AgentFeedbackTracker
from llm.gepa_bindings import (
    SonnetPromptMutator,
    SonnetPromptScorer,
    SqliteTradeEvalSource,
    _query_trade_outcomes,
    _rows_to_eval_trades,
)
from llm.prompt_evolution import EvalTrade

_AF_MOD = sys.modules[AgentFeedbackTracker.__module__]

_ANALYST_SIGNALS = {
    "technical": 0.5, "news": 0.1, "social": 0.0,
    "fundamental": 0.2, "corey": 0.3,
}


class _FakeLLMClient:
    """Duck-types JarvisLLMClient's async .call() -- no real API traffic."""

    def __init__(self, content: str = "", success: bool = True, error: str | None = None):
        self.content = content
        self.success = success
        self.error = error
        self.calls: list[dict] = []

    async def call(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(success=self.success, content=self.content, error=self.error)


# ── SqliteTradeEvalSource ────────────────────────────────────────────────────


def _seed_one_closed_trade(db_path: Path) -> None:
    with patch.object(_AF_MOD, "DB_PATH", db_path):
        AgentFeedbackTracker().record_outcome(
            trade_id="t1", symbol="MES", direction="LONG", pnl_usd=100.0,
            analyst_signals=_ANALYST_SIGNALS,
        )


def test_sqlite_trade_eval_source_default_db_path_uses_agent_feedback_tracker(tmp_path):
    """db_path=None routes through AgentFeedbackTracker's own DB_PATH
    resolution -- the production wiring gepa_runner.py uses by default."""
    db = tmp_path / "agent_feedback.db"
    _seed_one_closed_trade(db)

    with patch.object(_AF_MOD, "DB_PATH", db):
        source = SqliteTradeEvalSource(db_path=None)
        trades = source.get_trades(limit=10)

    assert len(trades) == 1
    trade = trades[0]
    assert isinstance(trade, EvalTrade)
    assert trade.trade_id == "t1"
    assert trade.symbol == "MES"
    assert trade.actual_winning_side == "LONG"
    assert trade.pnl_usd == 100.0
    assert trade.context["technical"] == 0.5


def test_sqlite_trade_eval_source_explicit_db_path_reads_directly(tmp_path):
    """An explicit db_path bypasses AgentFeedbackTracker entirely and reads
    the file directly (read-only) -- the cross-checkout smoke-test path."""
    db = tmp_path / "agent_feedback.db"
    _seed_one_closed_trade(db)

    source = SqliteTradeEvalSource(db_path=db)
    trades = source.get_trades(limit=10)

    assert len(trades) == 1
    assert trades[0].trade_id == "t1"
    assert trades[0].actual_winning_side == "LONG"


def test_query_trade_outcomes_respects_limit(tmp_path):
    db = tmp_path / "agent_feedback.db"
    with patch.object(_AF_MOD, "DB_PATH", db):
        tracker = AgentFeedbackTracker()
        for i in range(5):
            tracker.record_outcome(
                trade_id=f"t{i}", symbol="MES", direction="LONG", pnl_usd=1.0 + i,
                analyst_signals=_ANALYST_SIGNALS,
            )

    rows = _query_trade_outcomes(db, limit=2)
    assert len(rows) == 2


def test_rows_to_eval_trades_maps_all_fields():
    rows = [{
        "trade_id": "abc", "symbol": "MGC", "timestamp": "2026-08-15T00:00:00Z",
        "context": {"technical": 1.0, "news": 0.0, "social": 0.0, "fundamental": 0.0, "corey": 0.0},
        "actual_winning_side": "SHORT", "pnl_usd": -12.5,
    }]
    trades = _rows_to_eval_trades(rows)
    assert len(trades) == 1
    t = trades[0]
    assert isinstance(t, EvalTrade)
    assert t.trade_id == "abc"
    assert t.symbol == "MGC"
    assert t.actual_winning_side == "SHORT"
    assert t.pnl_usd == -12.5


# ── SonnetPromptMutator ───────────────────────────────────────────────────────


def test_parse_variants_extracts_multiple_variant_note_pairs():
    text = (
        "VARIANT: first mutated prompt\nNOTE: added evidence requirement\n---\n"
        "VARIANT: second mutated prompt\nNOTE: tightened rubric\n"
    )
    variants = SonnetPromptMutator._parse_variants(text)
    assert variants == [
        ("first mutated prompt", "added evidence requirement"),
        ("second mutated prompt", "tightened rubric"),
    ]


def test_parse_variants_defaults_note_when_missing():
    text = "VARIANT: only a variant, no note\n"
    variants = SonnetPromptMutator._parse_variants(text)
    assert variants == [("only a variant, no note", "unlabeled mutation")]


def test_parse_variants_empty_text_returns_empty_list():
    assert SonnetPromptMutator._parse_variants("") == []


@pytest.mark.asyncio
async def test_mutate_parses_llm_response_into_variants():
    fake = _FakeLLMClient(
        content="VARIANT: mutated prompt text\nNOTE: simplified\n---\n",
        success=True,
    )
    mutator = SonnetPromptMutator(llm_client=fake)

    variants = await mutator.mutate("base prompt", n_variants=1)

    assert variants == [("mutated prompt text", "simplified")]
    assert len(fake.calls) == 1
    assert fake.calls[0]["model"] == "claude-sonnet-4-6"
    assert "base prompt" in fake.calls[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_mutate_returns_empty_list_on_llm_failure():
    fake = _FakeLLMClient(content="", success=False, error="rate limited")
    mutator = SonnetPromptMutator(llm_client=fake)

    variants = await mutator.mutate("base prompt", n_variants=2)

    assert variants == []


# ── SonnetPromptScorer ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_predict_returns_parsed_side():
    fake = _FakeLLMClient(content="LONG", success=True)
    scorer = SonnetPromptScorer(llm_client=fake)

    side = await scorer.predict("system prompt", {"technical": 0.5})

    assert side == "LONG"
    assert fake.calls[0]["temperature"] == 0.0
    assert fake.calls[0]["max_tokens"] == 16


@pytest.mark.asyncio
async def test_predict_falls_back_to_flat_on_unparseable_response():
    fake = _FakeLLMClient(content="I am not sure what to say here", success=True)
    scorer = SonnetPromptScorer(llm_client=fake)

    side = await scorer.predict("system prompt", {})

    assert side == "FLAT"


@pytest.mark.asyncio
async def test_predict_falls_back_to_flat_on_llm_failure():
    fake = _FakeLLMClient(content="", success=False, error="timeout")
    scorer = SonnetPromptScorer(llm_client=fake)

    side = await scorer.predict("system prompt", {})

    assert side == "FLAT"

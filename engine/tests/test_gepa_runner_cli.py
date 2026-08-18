"""Smoke tests for engine/llm/gepa_runner.py's CLI entrypoint (#644: feat(llm):
wire GEPA prompt-optimizer to real trade outcomes) -- the runner shipped with
zero test coverage (post-merge review of #644).

The Sonnet mutator/scorer are swapped for lightweight fakes (no real LLM
calls); the SqliteTradeEvalSource + GEPAOptimizer + AgentFeedbackTracker
layers are exercised for real against an isolated tmp SQLite DB.
"""

from __future__ import annotations

import json
import sys
from unittest.mock import patch

from analytics.agent_feedback import AgentFeedbackTracker
from llm import gepa_runner

_AF_MOD = sys.modules[AgentFeedbackTracker.__module__]

_ANALYST_SIGNALS = {
    "technical": 0.5, "news": 0.1, "social": 0.0,
    "fundamental": 0.2, "corey": 0.3,
}


class _FakeMutator:
    """No-op mutator: returns a single trivial variant, no LLM call."""

    async def mutate(self, prompt: str, n_variants: int):
        if n_variants < 1:
            return []
        return [(prompt + " (mutated)", "smoke-test mutation")]


class _FakeScorer:
    """Deterministic scorer: always predicts the same side, no LLM call."""

    def __init__(self, answer: str = "LONG"):
        self.answer = answer

    async def predict(self, prompt: str, context: dict):
        return self.answer


def _run_cli(monkeypatch, argv: list[str]) -> int:
    monkeypatch.setattr(gepa_runner, "SonnetPromptMutator", lambda: _FakeMutator())
    monkeypatch.setattr(gepa_runner, "SonnetPromptScorer", lambda: _FakeScorer())
    monkeypatch.setattr(sys, "argv", argv)
    return gepa_runner.main()


def test_cli_empty_trade_data_exits_cleanly_without_crashing(tmp_path, monkeypatch):
    """Zero trades in the DB must degrade to a clean non-zero exit code, not
    an unhandled exception -- the empty/minimal-data smoke test."""
    db_path = tmp_path / "agent_feedback.db"
    out_path = tmp_path / "artifact.json"
    with patch.object(_AF_MOD, "DB_PATH", db_path):
        AgentFeedbackTracker()  # creates the trade_outcomes table, 0 rows

    exit_code = _run_cli(monkeypatch, [
        "gepa_runner.py",
        "--target-agent", "bull_researcher",
        "--n-generations", "1",
        "--db-path", str(db_path),
        "--out", str(out_path),
    ])

    assert exit_code == 1, "empty eval data should be a graceful ERROR exit, not a crash"
    assert out_path.exists()
    artifact = json.loads(out_path.read_text())
    assert artifact["frontier"] == []


def test_cli_minimal_trade_data_runs_end_to_end(tmp_path, monkeypatch):
    """A couple of closed trades must flow through SqliteTradeEvalSource ->
    GEPAOptimizer -> a written artifact -> exit code 0, without touching a
    real LLM."""
    db_path = tmp_path / "agent_feedback.db"
    out_path = tmp_path / "artifact.json"
    with patch.object(_AF_MOD, "DB_PATH", db_path):
        tracker = AgentFeedbackTracker()
        tracker.record_outcome(
            trade_id="t1", symbol="MES", direction="LONG", pnl_usd=100.0,
            analyst_signals=_ANALYST_SIGNALS,
        )
        tracker.record_outcome(
            trade_id="t2", symbol="MES", direction="SHORT", pnl_usd=-50.0,
            analyst_signals=_ANALYST_SIGNALS,
        )

    exit_code = _run_cli(monkeypatch, [
        "gepa_runner.py",
        "--target-agent", "bull_researcher",
        "--n-generations", "1",
        "--eval-sample-size", "10",
        "--db-path", str(db_path),
        "--out", str(out_path),
    ])

    assert exit_code == 0
    assert out_path.exists()
    artifact = json.loads(out_path.read_text())
    assert artifact["target_agent"] == "bull_researcher"
    assert artifact["frontier"], "expected at least the scored baseline candidate"
    assert artifact["frontier"][0]["n_evals"] == 2
    assert artifact["history"]

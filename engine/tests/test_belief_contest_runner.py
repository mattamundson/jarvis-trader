"""
JARVIS TRADER — Belief-Ensemble Contest Runner Tests
====================================================
Deterministic tests for the async orchestration in
engine/strategies/belief_contest_runner.py. Uses fake async decide_fns (no LLM)
so the whole path — per-belief fan-out, error isolation, judge selection,
default-OFF gating — is verified reproducibly.

Async is driven via asyncio.run() inside sync tests to avoid a pytest-asyncio
dependency.
"""

import asyncio
from dataclasses import dataclass

from strategies.belief_contest_runner import (
    BeliefContestOutcome,
    is_belief_ensemble_enabled,
    run_belief_contest,
)
from strategies.belief_ensemble import TraderBelief


@dataclass
class _FakeDecision:
    action: str
    confidence: float
    rr_ratio: float
    signal_score: float = 0.0


def _belief(name):
    return TraderBelief(name=name, description=name, prompt_suffix=f"be {name}")


_BELIEFS = [_belief("aggressive"), _belief("conservative"), _belief("defensive")]


def _run(decide_fn, consensus, **kw):
    return asyncio.run(
        run_belief_contest(decide_fn, consensus, beliefs=_BELIEFS, enabled=True, **kw)
    )


class TestGating:
    def test_disabled_returns_immediately(self):
        async def _decide(_b):
            raise AssertionError("decide_fn must not be called when disabled")

        outcome = asyncio.run(run_belief_contest(_decide, 0.5, enabled=False))
        assert outcome.enabled is False
        assert outcome.decision is None

    def test_flag_defaults_off_without_config(self):
        # No BELIEF_ENSEMBLE_ENABLED set anywhere ⇒ disabled by default.
        assert is_belief_ensemble_enabled() is False


class TestSelection:
    def test_best_aligned_belief_wins(self):
        # All buy under LONG consensus; conservative has the highest confidence*rr.
        table = {
            "aggressive": _FakeDecision("buy", 0.6, 2.0),
            "conservative": _FakeDecision("buy", 0.9, 2.0),  # 1.8 — best
            "defensive": _FakeDecision("buy", 0.5, 1.0),
        }

        async def _decide(b):
            return table[b.name]

        outcome = _run(_decide, 0.5)
        assert outcome.enabled is True
        assert outcome.winner_belief == "conservative"
        assert outcome.decision is table["conservative"]
        assert outcome.n_proposals == 3
        assert not outcome.is_hold

    def test_contrarian_belief_cannot_win(self):
        # aggressive proposes the strongest trade but SHORT against LONG consensus.
        table = {
            "aggressive": _FakeDecision("sell", 0.99, 5.0),  # disqualified
            "conservative": _FakeDecision("buy", 0.4, 1.0),  # only admissible
            "defensive": _FakeDecision("hold", 0.0, 0.0),
        }

        async def _decide(b):
            return table[b.name]

        outcome = _run(_decide, 0.6)
        assert outcome.winner_belief == "conservative"
        assert outcome.decision.action == "buy"

    def test_all_hold_resolves_to_hold(self):
        async def _decide(_b):
            return _FakeDecision("hold", 0.0, 0.0)

        outcome = _run(_decide, 0.4)
        assert outcome.enabled is True
        assert outcome.decision is None
        assert outcome.is_hold is True


class TestErrorIsolation:
    def test_one_failing_belief_is_skipped(self):
        table = {
            "aggressive": _FakeDecision("buy", 0.8, 2.0),
            "conservative": None,  # will raise
            "defensive": _FakeDecision("buy", 0.5, 1.0),
        }

        async def _decide(b):
            if table[b.name] is None:
                raise RuntimeError("llm down")
            return table[b.name]

        outcome = _run(_decide, 0.5)
        assert outcome.winner_belief == "aggressive"
        assert outcome.n_proposals == 2
        assert any("conservative" in e for e in outcome.errors)

    def test_all_beliefs_error_yields_no_proposals(self):
        async def _decide(_b):
            raise RuntimeError("llm down")

        outcome = _run(_decide, 0.5)
        assert outcome.enabled is True
        assert outcome.n_proposals == 0
        assert outcome.decision is None
        assert outcome.errors_only is True
        assert not outcome.is_hold  # errors, not a genuine HOLD verdict

    def test_none_return_is_treated_as_error(self):
        async def _decide(_b):
            return None

        outcome = _run(_decide, 0.5)
        assert outcome.n_proposals == 0
        assert outcome.errors_only is True


class TestEmptyBeliefs:
    def test_empty_belief_list_enabled_no_proposals(self):
        async def _decide(_b):
            return _FakeDecision("buy", 0.8, 2.0)

        outcome = asyncio.run(run_belief_contest(_decide, 0.5, beliefs=[], enabled=True))
        assert outcome.enabled is True
        assert outcome.n_proposals == 0
        assert isinstance(outcome, BeliefContestOutcome)

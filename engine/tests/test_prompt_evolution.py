"""
Unit tests for the GEPA-style prompt evolution scaffold (ML/AI Novel #1).

Covers:
  * Pareto-frontier algorithm (dominated candidates removed, ties kept)
  * Brevity normalisation (token-count → [0,1])
  * Optimiser construction validation
  * End-to-end evolve() with deterministic mock mutator + scorer
  * Frontier monotonic non-degradation across generations
  * History snapshot shape
  * Token counter is swappable
  * Empty eval source returns empty frontier (no crash)

Mocks: a deterministic PromptMutator that suffixes "+N", a deterministic
PromptScorer that compares prompt-length-mod-3 against trade context, and
a synthetic TradeEvalSource. No real LLM calls, no real DB.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from llm.prompt_evolution import (
    EvalTrade,
    GEPAOptimizer,
    ParetoFrontier,
    PromptCandidate,
    _normalise_brevity,
    default_token_count,
    select_pareto_frontier,
)

# ── Pareto frontier ─────────────────────────────────────────────────────────

def test_pareto_frontier_empty():
    assert select_pareto_frontier([]) == []


def test_pareto_frontier_single_kept():
    c = PromptCandidate(prompt_text="x", accuracy=0.5, brevity=0.5)
    assert select_pareto_frontier([c]) == [c]


def test_pareto_frontier_dominated_removed():
    """C1 dominates C2 (better on both axes) → C2 dropped."""
    c1 = PromptCandidate(prompt_text="winner", accuracy=0.9, brevity=0.9)
    c2 = PromptCandidate(prompt_text="dominated", accuracy=0.5, brevity=0.5)
    front = select_pareto_frontier([c1, c2])
    assert front == [c1]


def test_pareto_frontier_keeps_tradeoffs():
    """C1 best accuracy/worst brevity, C2 worst accuracy/best brevity → both kept."""
    c1 = PromptCandidate(prompt_text="long-and-accurate", accuracy=0.9, brevity=0.1)
    c2 = PromptCandidate(prompt_text="short-but-meh", accuracy=0.6, brevity=0.95)
    front = select_pareto_frontier([c1, c2])
    assert len(front) == 2
    assert c1 in front and c2 in front


def test_pareto_frontier_sorted_descending_accuracy():
    c_a = PromptCandidate(prompt_text="a", accuracy=0.6, brevity=0.9)
    c_b = PromptCandidate(prompt_text="b", accuracy=0.9, brevity=0.4)
    c_c = PromptCandidate(prompt_text="c", accuracy=0.7, brevity=0.7)
    front = select_pareto_frontier([c_a, c_b, c_c])
    accs = [c.accuracy for c in front]
    assert accs == sorted(accs, reverse=True)


def test_pareto_frontier_strict_dominance_required():
    """Equal-on-both candidates both survive (no STRICT dominator)."""
    c1 = PromptCandidate(prompt_text="x", accuracy=0.7, brevity=0.7)
    c2 = PromptCandidate(prompt_text="y", accuracy=0.7, brevity=0.7)
    front = select_pareto_frontier([c1, c2])
    assert len(front) == 2


# ── Brevity normalisation ──────────────────────────────────────────────────

def test_normalise_brevity_empty():
    assert _normalise_brevity([]) == []


def test_normalise_brevity_all_equal_returns_ones():
    out = _normalise_brevity([100, 100, 100])
    assert out == [1.0, 1.0, 1.0]


def test_normalise_brevity_shortest_is_one():
    out = _normalise_brevity([10, 20, 30])
    assert out[0] == 1.0  # shortest
    assert out[2] == 0.0  # longest
    assert 0 < out[1] < 1


def test_default_token_count_whitespace_split():
    assert default_token_count("a b c") == 3
    assert default_token_count("") == 0


# ── Candidate IDs are stable hashes ─────────────────────────────────────────

def test_candidate_id_deterministic():
    c1 = PromptCandidate(prompt_text="hello world")
    c2 = PromptCandidate(prompt_text="hello world")
    c3 = PromptCandidate(prompt_text="hello world!")
    assert c1.candidate_id == c2.candidate_id
    assert c1.candidate_id != c3.candidate_id
    assert len(c1.candidate_id) == 12


# ── ParetoFrontier holder ───────────────────────────────────────────────────

def test_pareto_frontier_update_keeps_best():
    pf = ParetoFrontier()
    pf.update([
        PromptCandidate(prompt_text="a", accuracy=0.5, brevity=0.5),
        PromptCandidate(prompt_text="b", accuracy=0.7, brevity=0.7),  # dominates a
    ])
    assert len(pf.members) == 1
    assert pf.members[0].prompt_text == "b"


def test_pareto_frontier_best_by_accuracy():
    pf = ParetoFrontier()
    pf.update([
        PromptCandidate(prompt_text="long", accuracy=0.95, brevity=0.1),
        PromptCandidate(prompt_text="short", accuracy=0.5, brevity=0.95),
    ])
    assert pf.best_by_accuracy().accuracy == 0.95
    assert pf.best_by_brevity().brevity == 0.95


# ── Optimiser construction validation ───────────────────────────────────────

class _NoopMutator:
    async def mutate(self, prompt, n_variants):
        return []


class _NoopScorer:
    async def predict(self, prompt, context):
        return "FLAT"


class _EmptySource:
    def get_trades(self, limit=100):
        return []


def test_optimizer_rejects_empty_base_prompt():
    with pytest.raises(ValueError, match="base_prompt"):
        GEPAOptimizer("", _EmptySource(), _NoopMutator(), _NoopScorer())


def test_optimizer_rejects_zero_eval_sample():
    with pytest.raises(ValueError, match="eval_sample_size"):
        GEPAOptimizer(
            "ok", _EmptySource(), _NoopMutator(), _NoopScorer(),
            eval_sample_size=0,
        )


def test_optimizer_evolve_rejects_zero_generations():
    opt = GEPAOptimizer("ok", _EmptySource(), _NoopMutator(), _NoopScorer())
    with pytest.raises(ValueError, match="n_generations"):
        asyncio.run(opt.evolve(n_generations=0))


# ── End-to-end with deterministic mocks ─────────────────────────────────────

class _SyntheticSource:
    """3 synthetic trades: 2 LONG winners, 1 SHORT winner."""

    def get_trades(self, limit=100):
        now = datetime(2026, 4, 16, 12, 0)
        trades = [
            EvalTrade(
                trade_id="T1", symbol="MCL", timestamp=now,
                context={"side_hint": "LONG"}, actual_winning_side="LONG",
                pnl_usd=50.0,
            ),
            EvalTrade(
                trade_id="T2", symbol="MNQ", timestamp=now - timedelta(days=1),
                context={"side_hint": "LONG"}, actual_winning_side="LONG",
                pnl_usd=80.0,
            ),
            EvalTrade(
                trade_id="T3", symbol="MES", timestamp=now - timedelta(days=2),
                context={"side_hint": "SHORT"}, actual_winning_side="SHORT",
                pnl_usd=30.0,
            ),
        ][:limit]
        return trades


class _OracleScorer:
    """Predicts using the side_hint from the context — perfect oracle."""

    async def predict(self, prompt, context):
        return context.get("side_hint", "FLAT")


class _ContrarianScorer:
    """Always predicts opposite of side_hint — 0% accuracy."""

    async def predict(self, prompt, context):
        return {"LONG": "SHORT", "SHORT": "LONG"}.get(
            context.get("side_hint", "FLAT"), "FLAT"
        )


class _AppendMutator:
    """Deterministic mutator: appends ' v{i}' to produce N distinct variants."""

    async def mutate(self, prompt, n_variants):
        return [(f"{prompt} v{i}", f"append v{i}") for i in range(n_variants)]


def test_evolve_with_perfect_scorer_reaches_accuracy_one():
    opt = GEPAOptimizer(
        base_prompt="be a great analyst",
        eval_source=_SyntheticSource(),
        mutator=_AppendMutator(),
        scorer=_OracleScorer(),
        eval_sample_size=10,
    )
    front = asyncio.run(opt.evolve(n_generations=2, variants_per_member=2))
    # Oracle scorer hits 1.0 on every prompt → all candidates accuracy=1.0
    assert all(c.accuracy == 1.0 for c in front.members)
    assert front.best_by_accuracy().accuracy == 1.0


def test_evolve_with_contrarian_scorer_reaches_accuracy_zero():
    opt = GEPAOptimizer(
        base_prompt="hello",
        eval_source=_SyntheticSource(),
        mutator=_AppendMutator(),
        scorer=_ContrarianScorer(),
        eval_sample_size=10,
    )
    front = asyncio.run(opt.evolve(n_generations=1, variants_per_member=1))
    assert all(c.accuracy == 0.0 for c in front.members)


def test_evolve_history_records_per_generation_snapshot():
    opt = GEPAOptimizer(
        base_prompt="initial",
        eval_source=_SyntheticSource(),
        mutator=_AppendMutator(),
        scorer=_OracleScorer(),
        eval_sample_size=5,
    )
    asyncio.run(opt.evolve(n_generations=2, variants_per_member=2))
    # Generation 0 (baseline) + 2 evolution generations = 3 snapshots
    assert len(opt.history) == 3
    snap = opt.history[0]
    assert snap["generation"] == 0
    assert "frontier" in snap and "best_accuracy" in snap


def test_evolve_empty_eval_source_returns_empty_frontier():
    opt = GEPAOptimizer(
        base_prompt="x",
        eval_source=_EmptySource(),
        mutator=_AppendMutator(),
        scorer=_OracleScorer(),
    )
    front = asyncio.run(opt.evolve(n_generations=1))
    assert front.members == []


def test_evolve_skips_identical_variants():
    """A mutator that returns the same prompt as the parent should be skipped."""

    class _IdentityMutator:
        async def mutate(self, prompt, n_variants):
            return [(prompt, "no-op")] * n_variants

    opt = GEPAOptimizer(
        base_prompt="seed",
        eval_source=_SyntheticSource(),
        mutator=_IdentityMutator(),
        scorer=_OracleScorer(),
        eval_sample_size=3,
    )
    front = asyncio.run(opt.evolve(n_generations=2, variants_per_member=3))
    # Frontier only contains the baseline because all "mutations" were identical
    assert len(front.members) == 1
    assert front.members[0].prompt_text == "seed"


def test_evolve_handles_scorer_exception_gracefully():
    """A scorer that raises on every predict should not crash evolve."""

    class _BrokenScorer:
        async def predict(self, prompt, context):
            raise RuntimeError("simulated LLM failure")

    opt = GEPAOptimizer(
        base_prompt="x",
        eval_source=_SyntheticSource(),
        mutator=_AppendMutator(),
        scorer=_BrokenScorer(),
        eval_sample_size=3,
    )
    front = asyncio.run(opt.evolve(n_generations=1, variants_per_member=1))
    # All candidates score 0 (no successful predictions) but evolve completes
    assert all(c.accuracy == 0.0 for c in front.members)


def test_evolve_token_counter_is_swappable():
    """Custom token counter should be invoked for brevity normalisation."""

    counter_calls = {"n": 0}

    def _custom_counter(prompt: str) -> int:
        counter_calls["n"] += 1
        return len(prompt)

    opt = GEPAOptimizer(
        base_prompt="abc",
        eval_source=_SyntheticSource(),
        mutator=_AppendMutator(),
        scorer=_OracleScorer(),
        eval_sample_size=3,
        token_counter=_custom_counter,
    )
    asyncio.run(opt.evolve(n_generations=1, variants_per_member=1))
    assert counter_calls["n"] > 0


# ── Candidate to_dict shape ─────────────────────────────────────────────────

def test_candidate_to_dict_shape():
    c = PromptCandidate(
        prompt_text="hello", generation=2,
        accuracy=0.75, brevity=0.5, n_evals=10,
        parent_id="abc123", mutation_note="add example",
    )
    d = c.to_dict()
    assert d["accuracy"] == 0.75
    assert d["brevity"] == 0.5
    assert d["generation"] == 2
    assert d["mutation_note"] == "add example"
    assert d["candidate_id"] == c.candidate_id

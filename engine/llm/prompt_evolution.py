"""
JARVIS TRADER — GEPA-style Prompt Evolution Scaffold (ML/AI Novel #1)
=====================================================================
Pareto-frontier evolutionary optimisation for analyst-agent system prompts.

Source: docs/digest/ml-ai-synthesis.md Novel #1
        (NousResearch/hermes-agent-self-evolution, ICLR 2026 oral).

Design intent
-------------
GEPA = Genetic-Pareto Prompt Evolution. The pipeline is:

  1. Read execution traces from `engine/analytics/agent_feedback.py`
     (the trade_outcomes SQLite table — direction, pnl_usd, outcome,
     plus the per-analyst signals that fed into the trade)
  2. For each candidate prompt, score on TWO axes:
       - accuracy: fraction of trades where the agent's
         direction prediction agreed with the realised winning side
       - brevity:  inverse-normalised token count (shorter = better)
  3. Keep the Pareto-frontier of candidates each generation
  4. Mutate frontier members via an LLM-driven mutator
     (add evidence requirement, tighten scoring rubric, add example,
      simplify, etc.) and re-score the new candidates
  5. After N generations, emit the winning prompts as a JSON artifact
     for human review and PR submission

NOT live-wired
--------------
This is an **offline research scaffold**. It does NOT modify
`engine/agents/bull_researcher.py`, `bear_researcher.py`, etc. It
produces evolved prompts as artifacts; promoting one to production
is a separate human-reviewed PR.

This separation matters because the system prompt of a debate-stack
agent is debate-critical — an over-fit prompt could poison the
ensemble even if it scores well on the eval window. The PR review
gate is the safety belt.

Eval source contract
--------------------
The optimiser depends only on a `TradeEvalSource` protocol that
yields `EvalTrade(context, predicted_direction, actual_winning_side)`
tuples. Production binds this to AgentFeedbackTracker, but tests
inject a synthetic source so no real DB or LLM call is needed.

Mutator contract
----------------
A `PromptMutator` takes a prompt string and returns N variant strings.
Production uses an LLM to produce semantic mutations; tests inject a
deterministic mock mutator that returns canned variants.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional, Protocol

logger = logging.getLogger(__name__)

__all__ = [
    "EvalTrade",
    "PromptCandidate",
    "TradeEvalSource",
    "PromptMutator",
    "PromptScorer",
    "ParetoFrontier",
    "GEPAOptimizer",
    "select_pareto_frontier",
    "default_token_count",
]


# ── Data types ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EvalTrade:
    """One historical trade used to evaluate a prompt."""

    trade_id: str
    symbol: str
    timestamp: datetime
    context: dict[str, Any]                 # analyst inputs that were available
    actual_winning_side: str                # "LONG" or "SHORT" — the side that won
    pnl_usd: float


@dataclass
class PromptCandidate:
    """One prompt + its multi-objective scores."""

    prompt_text: str
    generation: int = 0
    accuracy: float = 0.0                   # [0, 1] — directional hit rate
    brevity: float = 0.0                    # [0, 1] — 1.0 is shortest in cohort
    n_evals: int = 0
    parent_id: Optional[str] = None         # provenance: which prompt this mutated from
    mutation_note: str = ""

    @property
    def candidate_id(self) -> str:
        # First 12 chars of a stable hash of the prompt text
        import hashlib
        return hashlib.sha256(self.prompt_text.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "generation": self.generation,
            "accuracy": round(self.accuracy, 4),
            "brevity": round(self.brevity, 4),
            "n_evals": self.n_evals,
            "parent_id": self.parent_id,
            "mutation_note": self.mutation_note,
            "prompt_text": self.prompt_text,
        }


# ── Protocols (allows mocking in tests, real LLM/DB in prod) ────────────────

class TradeEvalSource(Protocol):
    """Yields historical trades for evaluation."""

    def get_trades(self, limit: int = 100) -> list[EvalTrade]:
        ...


class PromptMutator(Protocol):
    """Produces N variant prompts from a parent prompt."""

    async def mutate(self, prompt: str, n_variants: int) -> list[tuple[str, str]]:
        """Returns list of (mutated_prompt, mutation_note) pairs."""
        ...


class PromptScorer(Protocol):
    """Returns a 'predicted side' for a given prompt + context."""

    async def predict(self, prompt: str, context: dict[str, Any]) -> str:
        """Returns 'LONG', 'SHORT', or 'FLAT'."""
        ...


# ── Pure helpers ────────────────────────────────────────────────────────────

def default_token_count(prompt: str) -> int:
    """Cheap proxy for token count — split on whitespace.

    Production should swap in the Anthropic tokenizer; for evolution-loop
    relative comparison this is fine since all candidates are scored
    consistently."""
    return len(prompt.split())


def _normalise_brevity(token_counts: list[int]) -> list[float]:
    """Map token counts to [0, 1] where 1.0 = shortest in cohort."""
    if not token_counts:
        return []
    max_tc = max(token_counts)
    min_tc = min(token_counts)
    if max_tc == min_tc:
        return [1.0] * len(token_counts)
    # 1.0 for the shortest, 0.0 for the longest
    return [(max_tc - tc) / (max_tc - min_tc) for tc in token_counts]


def select_pareto_frontier(candidates: list[PromptCandidate]) -> list[PromptCandidate]:
    """
    Keep only non-dominated candidates on (accuracy↑, brevity↑).

    A candidate A dominates B if A.accuracy >= B.accuracy AND
    A.brevity >= B.brevity AND at least one is strictly greater.

    Returns the frontier sorted by descending accuracy (then descending
    brevity as the tie-breaker). This is the classic Pareto-non-dominated-set
    algorithm — O(N²) which is fine for population sizes < 1000.
    """
    if not candidates:
        return []

    frontier: list[PromptCandidate] = []
    for c in candidates:
        dominated_by_existing = False
        for other in candidates:
            if other is c:
                continue
            if (
                other.accuracy >= c.accuracy
                and other.brevity >= c.brevity
                and (other.accuracy > c.accuracy or other.brevity > c.brevity)
            ):
                dominated_by_existing = True
                break
        if not dominated_by_existing:
            frontier.append(c)

    # Stable sort: best accuracy first, brevity as tie-breaker
    frontier.sort(key=lambda x: (-x.accuracy, -x.brevity))
    return frontier


# ── Pareto frontier holder ──────────────────────────────────────────────────

@dataclass
class ParetoFrontier:
    """Mutable rolling Pareto frontier across generations."""

    members: list[PromptCandidate] = field(default_factory=list)

    def update(self, new_candidates: list[PromptCandidate]) -> None:
        """Merge new candidates with the existing frontier and re-prune."""
        all_candidates = self.members + new_candidates
        self.members = select_pareto_frontier(all_candidates)

    def best_by_accuracy(self) -> Optional[PromptCandidate]:
        if not self.members:
            return None
        return max(self.members, key=lambda c: c.accuracy)

    def best_by_brevity(self) -> Optional[PromptCandidate]:
        if not self.members:
            return None
        return max(self.members, key=lambda c: c.brevity)


# ── Optimiser ────────────────────────────────────────────────────────────────

class GEPAOptimizer:
    """
    Multi-generation evolutionary loop with Pareto selection.

    Caller responsibility:
      * Provide an eval_source with realised trades (held-out from training)
      * Provide a mutator (LLM-backed in prod, deterministic in tests)
      * Provide a scorer (LLM-backed in prod — runs the candidate prompt
        against each trade's context and returns a predicted side)
    """

    def __init__(
        self,
        base_prompt: str,
        eval_source: TradeEvalSource,
        mutator: PromptMutator,
        scorer: PromptScorer,
        *,
        eval_sample_size: int = 30,
        token_counter: Callable[[str], int] = default_token_count,
    ):
        if not base_prompt.strip():
            raise ValueError("base_prompt must be non-empty")
        if eval_sample_size < 1:
            raise ValueError("eval_sample_size must be positive")

        self.base_prompt = base_prompt
        self.eval_source = eval_source
        self.mutator = mutator
        self.scorer = scorer
        self.eval_sample_size = eval_sample_size
        self.token_counter = token_counter

        self.frontier = ParetoFrontier()
        self.history: list[dict] = []

    # ── Scoring one candidate ────────────────────────────────────────────

    async def _score_candidate(
        self,
        candidate: PromptCandidate,
        trades: list[EvalTrade],
    ) -> None:
        """Mutates candidate.accuracy and candidate.n_evals in place."""
        if not trades:
            candidate.accuracy = 0.0
            candidate.n_evals = 0
            return

        correct = 0
        for trade in trades:
            try:
                predicted = await self.scorer.predict(
                    candidate.prompt_text, trade.context
                )
            except Exception as exc:
                logger.warning(
                    "scorer.predict failed for candidate %s on trade %s: %s",
                    candidate.candidate_id, trade.trade_id, exc,
                )
                continue
            if predicted == trade.actual_winning_side:
                correct += 1

        candidate.n_evals = len(trades)
        candidate.accuracy = correct / candidate.n_evals if candidate.n_evals else 0.0

    # ── Brevity normalisation across a generation ────────────────────────

    def _assign_brevity(self, candidates: list[PromptCandidate]) -> None:
        token_counts = [self.token_counter(c.prompt_text) for c in candidates]
        norms = _normalise_brevity(token_counts)
        for c, b in zip(candidates, norms, strict=False):
            c.brevity = b

    # ── Main loop ────────────────────────────────────────────────────────

    async def evolve(
        self,
        n_generations: int = 3,
        variants_per_member: int = 2,
        max_frontier_size: int = 8,
    ) -> ParetoFrontier:
        """
        Run N generations of mutation + Pareto pruning.

        Returns the final ParetoFrontier. Also populates self.history with
        per-generation snapshots for offline analysis.
        """
        if n_generations < 1:
            raise ValueError("n_generations must be positive")
        if variants_per_member < 1:
            raise ValueError("variants_per_member must be positive")

        trades = self.eval_source.get_trades(limit=self.eval_sample_size)
        if not trades:
            logger.warning("eval_source returned 0 trades — nothing to optimise")
            return self.frontier

        # Generation 0 — score the baseline
        baseline = PromptCandidate(
            prompt_text=self.base_prompt,
            generation=0,
            mutation_note="baseline",
        )
        await self._score_candidate(baseline, trades)
        self._assign_brevity([baseline])
        self.frontier.update([baseline])
        self._snapshot(0, [baseline])

        # Subsequent generations
        for gen in range(1, n_generations + 1):
            new_candidates: list[PromptCandidate] = []
            # Mutate each frontier member
            for parent in list(self.frontier.members):
                variants = await self.mutator.mutate(
                    parent.prompt_text, variants_per_member
                )
                for variant_text, note in variants:
                    if not variant_text or variant_text == parent.prompt_text:
                        continue
                    child = PromptCandidate(
                        prompt_text=variant_text,
                        generation=gen,
                        parent_id=parent.candidate_id,
                        mutation_note=note,
                    )
                    await self._score_candidate(child, trades)
                    new_candidates.append(child)

            # Re-normalise brevity across baseline + frontier + new
            cohort = self.frontier.members + new_candidates
            self._assign_brevity(cohort)

            self.frontier.update(new_candidates)

            # Cap frontier size to keep next-gen mutation cost bounded
            if len(self.frontier.members) > max_frontier_size:
                self.frontier.members = self.frontier.members[:max_frontier_size]

            self._snapshot(gen, new_candidates)

        return self.frontier

    def _snapshot(self, generation: int, this_gen_candidates: list[PromptCandidate]) -> None:
        self.history.append({
            "generation": generation,
            "n_new_candidates": len(this_gen_candidates),
            "frontier_size": len(self.frontier.members),
            "best_accuracy": (
                max((c.accuracy for c in self.frontier.members), default=0.0)
            ),
            "best_brevity": (
                max((c.brevity for c in self.frontier.members), default=0.0)
            ),
            "frontier": [c.to_dict() for c in self.frontier.members],
        })

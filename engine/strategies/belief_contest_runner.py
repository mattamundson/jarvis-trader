"""
JARVIS TRADER — Belief-Ensemble Contest Runner (orchestration)
==============================================================
Async orchestration layer that turns the deterministic ContestJudge
(engine/strategies/belief_ensemble.py) into a drop-in trader-stage step: run a
trader decision under each belief persona, then let the judge pick the winner.

This is the wiring half of the ContestTrade follow-up. The judge (already
merged) is the *what*; this module is the *how it plugs into a pipeline*.

Design constraints (unchanged from the analysis doc):
- **Default OFF.** Gated on ``settings.BELIEF_ENSEMBLE_ENABLED`` read via
  ``getattr(..., False)`` — absent config ⇒ disabled ⇒ the runner returns an
  outcome telling the caller to use its normal single-trader path. No behavior
  change until a config flag is explicitly set.
- **Selection stays deterministic.** The winner is chosen by ``ContestJudge``
  (confidence × reward/risk, gated by the outcome-grounded IC consensus). No LLM
  decides the winner; the contest sits before the risk/fund-manager gates.
- **Decoupled + testable.** The runner takes a ``decide_fn`` callback
  ``(belief) -> awaitable[TradeDecision]`` rather than importing TraderAgent, so
  it unit-tests with fakes and never reaches into trader internals.

ACTIVATION IS GATED. Turning the flag on requires the backtest-regression
comparison vs. the single-trader baseline mandated in
docs/repo-integrations/FinStep-AI__ContestTrade.md (revert if it regresses) plus
Tier-3 sign-off. Until then the flag stays False and this code is dormant.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, List, Optional

try:  # dual-path import (engine.* as package vs bare under engine/ cwd)
    from engine.strategies.belief_ensemble import (
        BeliefProposal,
        ContestJudge,
        ContestResult,
        TraderBelief,
        load_beliefs,
    )
except ImportError:  # pragma: no cover
    from strategies.belief_ensemble import (
        BeliefProposal,
        ContestJudge,
        ContestResult,
        TraderBelief,
        load_beliefs,
    )

logger = logging.getLogger(__name__)

__all__ = ["BeliefContestOutcome", "run_belief_contest", "is_belief_ensemble_enabled"]

DecideFn = Callable[[TraderBelief], Awaitable[Any]]


def is_belief_ensemble_enabled() -> bool:
    """Read the default-OFF feature flag. Absent config ⇒ disabled."""
    try:
        from config import settings

        return bool(getattr(settings, "BELIEF_ENSEMBLE_ENABLED", False))
    except Exception:  # pragma: no cover — config unavailable ⇒ disabled
        return False


@dataclass
class BeliefContestOutcome:
    """
    Result of a belief contest, shaped for a caller that otherwise runs a single
    trader decision.

    - ``enabled`` False  → caller should use its normal single-trader path
      (``decision`` is None).
    - ``enabled`` True, ``is_hold`` False → use ``decision`` (the winning belief's
      TradeDecision) and ``winner_belief``.
    - ``enabled`` True, ``is_hold`` True  → the contest resolved to HOLD; caller
      should HOLD (no admissible directional proposal).
    """

    enabled: bool
    decision: Optional[Any] = None
    winner_belief: Optional[str] = None
    result: Optional[ContestResult] = None
    n_proposals: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def is_hold(self) -> bool:
        return self.enabled and self.decision is None and not self.errors_only

    @property
    def errors_only(self) -> bool:
        """True when the contest produced no proposals at all (every belief errored)."""
        return self.enabled and self.n_proposals == 0


async def run_belief_contest(
    decide_fn: DecideFn,
    consensus_score: float,
    *,
    beliefs: Optional[List[TraderBelief]] = None,
    judge: Optional[ContestJudge] = None,
    enabled: Optional[bool] = None,
) -> BeliefContestOutcome:
    """
    Run ``decide_fn`` under each belief persona, then select the winner.

    Args:
        decide_fn:        async callback producing a TradeDecision for one belief.
        consensus_score:  IC-weighted consensus in [-1, 1]
                          (ICWeightedEnsemble.weighted_consensus) — the
                          outcome-grounded direction gate for the judge.
        beliefs:          personas to run; defaults to load_beliefs().
        judge:            ContestJudge to use; defaults to a fresh one.
        enabled:          override the feature flag (for tests); defaults to
                          is_belief_ensemble_enabled().

    Returns a BeliefContestOutcome. When disabled, returns immediately with
    ``enabled=False`` so the caller runs its normal single-trader path.
    """
    if enabled is None:
        enabled = is_belief_ensemble_enabled()
    if not enabled:
        return BeliefContestOutcome(enabled=False)

    belief_list = beliefs if beliefs is not None else load_beliefs()
    if not belief_list:
        return BeliefContestOutcome(enabled=True)

    # Run each belief's trader decision concurrently; a failure in one belief is
    # isolated (return_exceptions) so a single bad decision can't sink the contest.
    results = await asyncio.gather(
        *(decide_fn(belief) for belief in belief_list),
        return_exceptions=True,
    )

    proposals: List[BeliefProposal] = []
    decisions_by_belief: dict = {}
    errors: List[str] = []
    for belief, res in zip(belief_list, results, strict=False):
        if isinstance(res, Exception):
            errors.append(f"{belief.name}: {res}")
            logger.warning("[BeliefContest] belief '%s' decision failed: %s", belief.name, res)
            continue
        if res is None:
            errors.append(f"{belief.name}: decide_fn returned None")
            continue
        proposals.append(BeliefProposal.from_decision(belief.name, res))
        decisions_by_belief[belief.name] = res

    if not proposals:
        return BeliefContestOutcome(enabled=True, n_proposals=0, errors=errors)

    contest = (judge or ContestJudge()).select(proposals, consensus_score)

    winner_decision = None
    winner_belief = None
    if contest.winner is not None:
        winner_belief = contest.winner.belief_name
        winner_decision = decisions_by_belief.get(winner_belief)

    logger.info(
        "[BeliefContest] %d proposals, consensus=%.3f → %s",
        len(proposals),
        consensus_score,
        contest.reason,
    )

    return BeliefContestOutcome(
        enabled=True,
        decision=winner_decision,
        winner_belief=winner_belief,
        result=contest,
        n_proposals=len(proposals),
        errors=errors,
    )

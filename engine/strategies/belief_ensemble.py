"""
JARVIS TRADER — Belief-Diverse Trader Ensemble (ContestTrade pattern)
=====================================================================
A tournament-style selection layer for trader proposals.

Where the existing pipeline runs a single adversarial bull/bear debate and a
single TraderAgent verdict, this module borrows the *many-candidates-then-select*
structure from FinStep-AI/ContestTrade (arXiv:2508.00554, Apache-2.0): the
TraderAgent is run under several distinct "beliefs" (personas), each producing a
candidate proposal, and a deterministic judge keeps the single best survivor.

Two hard safety constraints, both enforced here and stated in
docs/repo-integrations/FinStep-AI__ContestTrade.md:

1. The selection is **deterministic** — never LLM-driven. ContestTrade uses an
   LLM judge; we do not. The judge scores proposals from their own confidence
   and reward/risk, gated by the outcome-grounded IC consensus direction
   (engine/analytics/ic_ensemble.py). No model output decides the winner.
2. The contest sits **before** the risk/fund-manager stages and never replaces
   them. The winning proposal still passes every downstream gate unchanged.

This module is additive and standalone: it operates on already-produced
proposals (primitive fields lifted from a TradeDecision) and returns the winner.
Wiring it into the live trader stage is a separate, config-gated follow-up.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "TraderBelief",
    "BeliefProposal",
    "ContestResult",
    "ContestJudge",
    "load_beliefs",
    "DEFAULT_BELIEFS",
]

_BELIEF_CONFIG_PATH = Path(__file__).resolve().parent / "belief_list.json"

# Consensus scores within +/- this neutral band are treated as directionless, so
# a thin/noisy IC consensus does not disqualify directional proposals. Mirrors
# the |debate_score| > 0.30 conviction band used in agents/trader.py.
DEFAULT_NEUTRAL_BAND = 0.10

# Score assigned to a directional proposal that opposes a directional, outcome-
# grounded consensus. Strictly below any admissible score (which are >= 0), so a
# contrarian proposal can never win the contest.
_DISQUALIFIED = -1.0


@dataclass(frozen=True)
class TraderBelief:
    """A single trader persona the TraderAgent can run under."""

    name: str
    description: str
    prompt_suffix: str

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("TraderBelief.name must be a non-empty string")


# Fallback personas used when belief_list.json is missing or unreadable. Kept in
# sync with the shipped config; the file is the source of truth when present.
DEFAULT_BELIEFS: tuple[TraderBelief, ...] = (
    TraderBelief(
        name="aggressive_momentum",
        description="Trend-follower; leans into confirmed momentum and breakouts.",
        prompt_suffix="Adopt an AGGRESSIVE MOMENTUM belief.",
    ),
    TraderBelief(
        name="conservative_mean_reversion",
        description="Fades extremes; demands high R:R; quick to HOLD.",
        prompt_suffix="Adopt a CONSERVATIVE MEAN-REVERSION belief.",
    ),
    TraderBelief(
        name="event_driven",
        description="Weights news/catalysts heavily; stands aside without a catalyst.",
        prompt_suffix="Adopt an EVENT-DRIVEN belief.",
    ),
    TraderBelief(
        name="risk_parity_defensive",
        description="Capital-preservation first; strictest confluence; HOLD-biased.",
        prompt_suffix="Adopt a RISK-PARITY DEFENSIVE belief.",
    ),
)


def load_beliefs(config_path: Optional[Path] = None) -> List[TraderBelief]:
    """
    Load trader belief personas from belief_list.json.

    Returns DEFAULT_BELIEFS on any error (missing file, malformed JSON, empty
    list) — the ensemble must degrade gracefully, never raise, per the engine's
    async-with-fallback convention.
    """
    path = config_path or _BELIEF_CONFIG_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        entries = raw.get("beliefs", []) if isinstance(raw, dict) else []
        beliefs: List[TraderBelief] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "")).strip()
            if not name:
                continue
            beliefs.append(
                TraderBelief(
                    name=name,
                    description=str(entry.get("description", "")),
                    prompt_suffix=str(entry.get("prompt_suffix", "")),
                )
            )
        if not beliefs:
            logger.warning("belief_list.json has no usable beliefs; using DEFAULT_BELIEFS")
            return list(DEFAULT_BELIEFS)
        return beliefs
    except FileNotFoundError:
        logger.info("belief_list.json not found at %s; using DEFAULT_BELIEFS", path)
        return list(DEFAULT_BELIEFS)
    except (json.JSONDecodeError, OSError, ValueError) as err:
        logger.warning("Failed to load belief_list.json (%s); using DEFAULT_BELIEFS", err)
        return list(DEFAULT_BELIEFS)


def _direction_of(action: str) -> str:
    """Map a trade action to a contest direction."""
    a = (action or "").strip().lower()
    if a == "buy":
        return "LONG"
    if a == "sell":
        return "SHORT"
    return "HOLD"


def _consensus_direction(consensus_score: float, neutral_band: float) -> str:
    """Map an IC consensus score in [-1, 1] to a direction, with a neutral band."""
    if consensus_score > neutral_band:
        return "LONG"
    if consensus_score < -neutral_band:
        return "SHORT"
    return "HOLD"


@dataclass(frozen=True)
class BeliefProposal:
    """
    One belief persona's trade proposal — the primitive fields the judge needs,
    lifted from a TradeDecision so this module stays decoupled from trader.py.
    """

    belief_name: str
    action: str  # "buy" | "sell" | "hold"
    confidence: float  # 0.0 .. 1.0
    rr_ratio: float = 0.0  # reward-to-risk; 0 for hold or when unknown
    signal_score: float = 0.0  # -1.0 .. 1.0 (audit only; not scored directly)

    @property
    def direction(self) -> str:
        return _direction_of(self.action)

    @classmethod
    def from_decision(cls, belief_name: str, decision) -> "BeliefProposal":
        """
        Build a proposal from a TradeDecision (or any object/dict exposing
        action, confidence, rr_ratio, signal_score).
        """

        def _get(obj, key, default):
            if isinstance(obj, dict):
                val = obj.get(key, default)
            else:
                val = getattr(obj, key, default)
            return default if val is None else val

        return cls(
            belief_name=belief_name,
            action=str(_get(decision, "action", "hold")),
            confidence=float(_get(decision, "confidence", 0.0)),
            rr_ratio=float(_get(decision, "rr_ratio", 0.0) or 0.0),
            signal_score=float(_get(decision, "signal_score", 0.0) or 0.0),
        )


@dataclass
class ContestResult:
    """Outcome of a belief contest."""

    winner: Optional[BeliefProposal]
    direction: str  # "LONG" | "SHORT" | "HOLD"
    consensus_direction: str
    scores: dict = field(default_factory=dict)  # belief_name -> score
    reason: str = ""

    @property
    def is_hold(self) -> bool:
        return self.winner is None or self.direction == "HOLD"


class ContestJudge:
    """
    Deterministic selector across belief proposals.

    Scoring (no LLM, fully reproducible)::

        direction == HOLD                      -> 0.0
        directional but opposes IC consensus   -> _DISQUALIFIED (-1.0)
        otherwise                              -> confidence * max(rr_ratio, 0)
                                                  * (1 + |consensus|  if aligned
                                                     else 1.0)

    The judge keeps the highest-scoring proposal. Ties break by belief order
    (stable — first proposal in the input list wins), so the result is
    deterministic given identical inputs. When the best admissible score is
    <= 0 (all HOLD, or every directional proposal opposes the consensus) the
    contest returns HOLD with no winner — the safe default.

    The consensus direction comes from the outcome-grounded IC-weighted ensemble
    (engine/analytics/ic_ensemble.py), so a proposal can only win by agreeing
    with where realized P&L says the analysts have actually been right — never on
    LLM say-so alone.
    """

    def __init__(self, neutral_band: float = DEFAULT_NEUTRAL_BAND):
        self.neutral_band = neutral_band

    def score_proposal(self, proposal: BeliefProposal, consensus_score: float) -> float:
        """Deterministic score for a single proposal given the IC consensus."""
        consensus_dir = _consensus_direction(consensus_score, self.neutral_band)
        direction = proposal.direction

        if direction == "HOLD":
            return 0.0

        if consensus_dir != "HOLD" and direction != consensus_dir:
            return _DISQUALIFIED

        base = max(0.0, proposal.confidence) * max(0.0, proposal.rr_ratio)
        aligned = consensus_dir != "HOLD" and direction == consensus_dir
        alignment = (1.0 + abs(consensus_score)) if aligned else 1.0
        return base * alignment

    def select(
        self,
        proposals: List[BeliefProposal],
        consensus_score: float,
    ) -> ContestResult:
        """
        Run the contest and return the winning proposal (or HOLD).

        Args:
            proposals:        Candidate proposals, one per belief persona.
            consensus_score:  IC-weighted consensus in [-1, 1]
                              (ICWeightedEnsemble.weighted_consensus).
        """
        consensus_dir = _consensus_direction(consensus_score, self.neutral_band)

        if not proposals:
            return ContestResult(
                winner=None,
                direction="HOLD",
                consensus_direction=consensus_dir,
                scores={},
                reason="No proposals submitted; defaulting to HOLD.",
            )

        scores: dict = {}
        best: Optional[BeliefProposal] = None
        best_score = float("-inf")
        for proposal in proposals:
            s = self.score_proposal(proposal, consensus_score)
            scores[proposal.belief_name] = round(s, 6)
            # Strict > keeps the first proposal on ties (stable, deterministic).
            if s > best_score:
                best_score = s
                best = proposal

        if best is None or best_score <= 0.0:
            return ContestResult(
                winner=None,
                direction="HOLD",
                consensus_direction=consensus_dir,
                scores=scores,
                reason=(
                    "No admissible directional proposal (all HOLD or every "
                    "directional proposal opposed the IC consensus); HOLD."
                ),
            )

        return ContestResult(
            winner=best,
            direction=best.direction,
            consensus_direction=consensus_dir,
            scores=scores,
            reason=(
                f"Belief '{best.belief_name}' won with score {best_score:.4f} "
                f"(confidence={best.confidence:.2f}, rr={best.rr_ratio:.2f}, "
                f"consensus_dir={consensus_dir})."
            ),
        )


def run_contest(
    proposals: List[BeliefProposal],
    consensus_score: float,
    neutral_band: float = DEFAULT_NEUTRAL_BAND,
) -> ContestResult:
    """Convenience wrapper: build a judge and select in one call."""
    return ContestJudge(neutral_band=neutral_band).select(proposals, consensus_score)

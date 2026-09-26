"""
JARVIS TRADER -- Reflex decision contract
=========================================
The typed output a fast per-bar judge (the "reflex") is allowed to emit.

The judge only *judges*: it classifies regime, leans a direction, states how
confident it is, and grades the setup. It never names a size, a price, a stop,
or an order. Every threshold, size and side effect is owned by
``reflex.policy`` (deterministic Python), which reads this object and decides.

Anything that does not validate against :class:`ReflexDecision` is treated as
"no decision" by :func:`parse_decision` -- a malformed or partial model reply
fails closed to HOLD, never open.
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)

__all__ = [
    "Regime",
    "Direction",
    "RiskState",
    "ReflexDecision",
    "parse_decision",
    "MAX_SETUP_QUALITY",
]

MAX_SETUP_QUALITY = 3


class Regime(str, Enum):
    TRENDING = "trending"
    MEAN_REVERTING = "mean_reverting"
    HIGH_VOL = "high_vol"
    CRISIS = "crisis"


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


class RiskState(str, Enum):
    """Ordered least -> most conservative (see :data:`RISK_STATE_SEVERITY`)."""

    SAFE = "safe"
    NEAR_LIMIT = "near_limit"
    REDUCE = "reduce"


RISK_STATE_SEVERITY = {RiskState.SAFE: 0, RiskState.NEAR_LIMIT: 1, RiskState.REDUCE: 2}


def more_conservative(a: RiskState, b: RiskState) -> RiskState:
    """Return whichever risk state is stricter. Used so a judge can only ever
    *tighten* the code-computed risk state, never loosen it."""
    return a if RISK_STATE_SEVERITY[a] >= RISK_STATE_SEVERITY[b] else b


class ReflexDecision(BaseModel):
    """One per-bar judgment. Immutable; unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)

    regime: Regime
    direction: Direction
    direction_confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Judge's raw P(direction is right). Uncalibrated."
    )
    toxic_flow: bool = Field(
        ..., description="True if the tape looks adversely selected (sweeps, spoofing, news shock)."
    )
    setup_quality: int = Field(..., ge=0, le=MAX_SETUP_QUALITY)
    risk_state: RiskState
    rationale: str = Field("", max_length=280, description="Audit only. Never parsed by policy.")


def parse_decision(raw: Any) -> Optional[ReflexDecision]:
    """Validate a judge reply (JSON string or dict). Returns ``None`` on any
    failure -- callers must treat ``None`` as HOLD."""
    try:
        payload = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        return ReflexDecision.model_validate(payload)
    except (ValidationError, ValueError, TypeError) as exc:
        logger.warning("reflex decision rejected (fail-closed to HOLD): %s", exc)
        return None

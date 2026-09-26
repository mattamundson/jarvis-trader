"""
JARVIS TRADER -- Reflex layer (fast per-bar judgment, deterministic policy)
===========================================================================
Shadow-only. Nothing in this package routes, sizes into, or approves an order.
See ``reflex/README.md`` for the design and what it is (and is not) wired to.
"""

from reflex.policy import Action, PolicyConfig, PolicyOutcome, ReflexLimits, evaluate
from reflex.schema import Direction, ReflexDecision, Regime, RiskState, parse_decision
from reflex.state import AccountState, Bar, CausalityError, MarketSnapshot, Quote, build_snapshot

__all__ = [
    "AccountState",
    "Action",
    "Bar",
    "CausalityError",
    "Direction",
    "MarketSnapshot",
    "PolicyConfig",
    "PolicyOutcome",
    "Quote",
    "ReflexDecision",
    "ReflexLimits",
    "Regime",
    "RiskState",
    "build_snapshot",
    "evaluate",
    "parse_decision",
]

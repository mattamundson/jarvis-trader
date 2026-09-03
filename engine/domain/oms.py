"""OMS lifecycle contract for future execution consolidation.

The key safety property is explicit ambiguity: once broker invocation may have
occurred, an unknown acknowledgement can never be converted back to a retryable
pre-submit state automatically.
"""

from __future__ import annotations

from enum import Enum


class OmsState(str, Enum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    CLAIMED = "CLAIMED"
    ROUTING = "ROUTING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    AMBIGUOUS = "AMBIGUOUS"
    RECONCILED = "RECONCILED"
    EXPIRED = "EXPIRED"


TERMINAL_STATES = frozenset(
    {OmsState.FILLED, OmsState.REJECTED, OmsState.CANCELLED, OmsState.RECONCILED, OmsState.EXPIRED}
)
BROKER_INVOCATION_MAY_HAVE_OCCURRED = frozenset(
    {
        OmsState.ROUTING,
        OmsState.ACKNOWLEDGED,
        OmsState.PARTIALLY_FILLED,
        OmsState.CANCEL_PENDING,
        OmsState.AMBIGUOUS,
    }
)

ALLOWED_TRANSITIONS: dict[OmsState, frozenset[OmsState]] = {
    OmsState.CREATED: frozenset({OmsState.VALIDATED, OmsState.REJECTED, OmsState.EXPIRED}),
    OmsState.VALIDATED: frozenset({OmsState.CLAIMED, OmsState.REJECTED, OmsState.EXPIRED}),
    OmsState.CLAIMED: frozenset({OmsState.ROUTING, OmsState.REJECTED, OmsState.EXPIRED}),
    OmsState.ROUTING: frozenset({OmsState.ACKNOWLEDGED, OmsState.REJECTED, OmsState.AMBIGUOUS}),
    OmsState.ACKNOWLEDGED: frozenset(
        {OmsState.PARTIALLY_FILLED, OmsState.FILLED, OmsState.CANCEL_PENDING, OmsState.AMBIGUOUS}
    ),
    OmsState.PARTIALLY_FILLED: frozenset(
        {OmsState.PARTIALLY_FILLED, OmsState.FILLED, OmsState.CANCEL_PENDING, OmsState.AMBIGUOUS}
    ),
    OmsState.CANCEL_PENDING: frozenset({OmsState.CANCELLED, OmsState.FILLED, OmsState.AMBIGUOUS}),
    OmsState.AMBIGUOUS: frozenset({OmsState.RECONCILED}),
    OmsState.FILLED: frozenset(),
    OmsState.REJECTED: frozenset(),
    OmsState.CANCELLED: frozenset(),
    OmsState.RECONCILED: frozenset(),
    OmsState.EXPIRED: frozenset(),
}


def validate_transition(current: OmsState, target: OmsState) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"illegal OMS transition: {current.value} -> {target.value}")


def automatic_submit_retry_allowed(state: OmsState) -> bool:
    """Only pre-routing states may ever be eligible for a future retry policy."""
    return state in {OmsState.CREATED, OmsState.VALIDATED, OmsState.CLAIMED}


def requires_reconciliation_before_resubmit(state: OmsState) -> bool:
    return state in BROKER_INVOCATION_MAY_HAVE_OCCURRED

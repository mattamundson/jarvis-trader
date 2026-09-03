"""Phase-1 core domain contracts.

These types are intentionally inert. They define shared vocabulary and validation
boundaries but are not imported by active order, broker, risk, or strategy paths.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ExecutionEnvironment(str, Enum):
    RESEARCH = "RESEARCH"
    PAPER = "PAPER"
    LIVE = "LIVE"


class MutationEffect(str, Enum):
    INCREASE_EXPOSURE = "INCREASE_EXPOSURE"
    REDUCE_EXPOSURE = "REDUCE_EXPOSURE"
    FLATTEN = "FLATTEN"
    CANCEL = "CANCEL"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderKind(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class ActorKind(str, Enum):
    HUMAN = "HUMAN"
    STRATEGY = "STRATEGY"
    SYSTEM = "SYSTEM"


class IntentLifecycle(str, Enum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    CLAIMED = "CLAIMED"
    ROUTING = "ROUTING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"
    AMBIGUOUS = "AMBIGUOUS"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class TradeIntentContract:
    """Canonical intent envelope for future A-04 integration.

    This object does not size, approve, submit, or authorize an order. In
    particular, `environment=LIVE` is descriptive only and cannot confer live
    authority. Exposure-increasing mutations still require the future risk,
    environment, authorization, OMS, and broker gates.
    """

    intent_id: str
    idempotency_key: str
    symbol: str
    side: OrderSide
    order_kind: OrderKind
    mutation_effect: MutationEffect
    environment: ExecutionEnvironment
    actor_kind: ActorKind
    created_at_utc: dt.datetime
    requested_quantity: int | None = None
    limit_price: float | None = None
    stop_price: float | None = None
    protective_stop: float | None = None
    take_profit: float | None = None
    strategy_id: str | None = None
    correlation_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        intent_id = self.intent_id.strip()
        idem = self.idempotency_key.strip()
        symbol = self.symbol.strip().upper()
        if not intent_id:
            raise ValueError("intent_id is required")
        if len(idem) < 8:
            raise ValueError("idempotency_key must be at least 8 characters")
        if not symbol:
            raise ValueError("symbol is required")
        if self.created_at_utc.tzinfo is None:
            raise ValueError("created_at_utc must be timezone-aware")
        if self.requested_quantity is not None and self.requested_quantity < 1:
            raise ValueError("requested_quantity must be >= 1 when supplied")
        if self.order_kind is OrderKind.LIMIT and self.limit_price is None:
            raise ValueError("LIMIT intents require limit_price")
        if self.order_kind is OrderKind.STOP and self.stop_price is None:
            raise ValueError("STOP intents require stop_price")
        if self.mutation_effect is MutationEffect.INCREASE_EXPOSURE:
            if self.protective_stop is None or self.take_profit is None:
                raise ValueError(
                    "exposure-increasing intents require protective_stop and take_profit"
                )
        object.__setattr__(self, "intent_id", intent_id)
        object.__setattr__(self, "idempotency_key", idem)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "created_at_utc", self.created_at_utc.astimezone(dt.timezone.utc))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def can_self_authorize(self) -> bool:
        """Hard invariant: a data contract never authorizes execution."""
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "idempotency_key": self.idempotency_key,
            "symbol": self.symbol,
            "side": self.side.value,
            "order_kind": self.order_kind.value,
            "mutation_effect": self.mutation_effect.value,
            "environment": self.environment.value,
            "actor_kind": self.actor_kind.value,
            "created_at_utc": self.created_at_utc.isoformat(),
            "requested_quantity": self.requested_quantity,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "protective_stop": self.protective_stop,
            "take_profit": self.take_profit,
            "strategy_id": self.strategy_id,
            "correlation_id": self.correlation_id,
            "evidence_ids": list(self.evidence_ids),
            "metadata": dict(self.metadata),
            "can_self_authorize": False,
        }

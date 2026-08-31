"""Research-only contract for dashboard/manual trade intents.

The browser expresses operator intent; it does NOT construct a broker order and
it does NOT own final position size. A later engine adapter may translate an
approved intent through fresh-state validation -> SafetyLayer -> IBOrderManager.

No live execution imports are allowed in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import floor, isfinite
from typing import Literal


Side = Literal["BUY", "SELL"]
EntryType = Literal["MARKETABLE_LIMIT", "LIMIT"]


class TradeIntentError(ValueError):
    """Raised when a dashboard intent or risk-preview input is invalid."""


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TradeIntentError(f"{field} must be timezone-aware")


def _finite_positive(value: float, field: str) -> float:
    number = float(value)
    if not isfinite(number) or number <= 0.0:
        raise TradeIntentError(f"{field} must be finite and positive")
    return number


@dataclass(frozen=True)
class TradeIntent:
    intent_id: str
    idempotency_key: str
    symbol: str
    side: Side
    entry_type: EntryType
    reference_price: float
    stop_price: float
    target_price: float
    max_risk_fraction: float
    created_at: datetime
    expires_at: datetime
    requested_quantity: int | None = None
    limit_price: float | None = None
    candidate_id: str | None = None
    strategy_id: str | None = None
    contract_multiplier: float = 1.0
    version: str = "1"

    def __post_init__(self) -> None:
        if not self.intent_id.strip():
            raise TradeIntentError("intent_id must be non-empty")
        if not self.idempotency_key.strip():
            raise TradeIntentError("idempotency_key must be non-empty")
        if not self.symbol.strip():
            raise TradeIntentError("symbol must be non-empty")
        if self.side not in {"BUY", "SELL"}:
            raise TradeIntentError("side must be BUY or SELL")
        if self.entry_type not in {"MARKETABLE_LIMIT", "LIMIT"}:
            raise TradeIntentError("unsupported entry_type")

        ref = _finite_positive(self.reference_price, "reference_price")
        stop = _finite_positive(self.stop_price, "stop_price")
        target = _finite_positive(self.target_price, "target_price")
        multiplier = _finite_positive(self.contract_multiplier, "contract_multiplier")
        object.__setattr__(self, "reference_price", ref)
        object.__setattr__(self, "stop_price", stop)
        object.__setattr__(self, "target_price", target)
        object.__setattr__(self, "contract_multiplier", multiplier)

        if not 0.0 < self.max_risk_fraction < 1.0:
            raise TradeIntentError("max_risk_fraction must be in (0,1)")
        if self.requested_quantity is not None and self.requested_quantity < 1:
            raise TradeIntentError("requested_quantity must be >= 1 when provided")
        if self.entry_type == "LIMIT":
            if self.limit_price is None:
                raise TradeIntentError("LIMIT intent requires limit_price")
            _finite_positive(self.limit_price, "limit_price")

        _require_aware(self.created_at, "created_at")
        _require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.created_at:
            raise TradeIntentError("expires_at must be after created_at")

        if self.side == "BUY":
            if stop >= ref:
                raise TradeIntentError("BUY stop_price must be below reference_price")
            if target <= ref:
                raise TradeIntentError("BUY target_price must be above reference_price")
        else:
            if stop <= ref:
                raise TradeIntentError("SELL stop_price must be above reference_price")
            if target >= ref:
                raise TradeIntentError("SELL target_price must be below reference_price")

    def is_expired(self, now: datetime) -> bool:
        _require_aware(now, "now")
        return now >= self.expires_at

    @property
    def risk_per_unit(self) -> float:
        return abs(self.reference_price - self.stop_price) * self.contract_multiplier

    @property
    def reward_per_unit(self) -> float:
        return abs(self.target_price - self.reference_price) * self.contract_multiplier

    @property
    def planned_rr(self) -> float:
        return self.reward_per_unit / self.risk_per_unit


@dataclass(frozen=True)
class TradeRiskPreview:
    account_equity: float
    risk_budget: float
    risk_per_unit: float
    engine_max_quantity: int
    requested_quantity: int | None
    approved_preview_quantity: int
    planned_risk_dollars: float
    planned_risk_fraction: float
    planned_reward_dollars: float
    planned_rr: float
    quantity_was_reduced: bool


def preview_trade_risk(intent: TradeIntent, *, account_equity: float) -> TradeRiskPreview:
    """Compute a deterministic *preview* size from equity and stop geometry.

    This is not broker authorization. Live/paper submission must recompute from
    fresh broker equity, margin, portfolio heat, reconciliation and SafetyLayer.
    """
    equity = _finite_positive(account_equity, "account_equity")
    risk_budget = equity * intent.max_risk_fraction
    risk_per_unit = intent.risk_per_unit
    if risk_per_unit <= 0.0 or not isfinite(risk_per_unit):
        raise TradeIntentError("risk_per_unit must be finite and positive")

    max_quantity = max(0, floor(risk_budget / risk_per_unit))
    requested = intent.requested_quantity
    if requested is None:
        approved = max_quantity
        reduced = False
    else:
        approved = min(requested, max_quantity)
        reduced = approved < requested

    planned_risk = approved * risk_per_unit
    planned_reward = approved * intent.reward_per_unit
    return TradeRiskPreview(
        account_equity=equity,
        risk_budget=risk_budget,
        risk_per_unit=risk_per_unit,
        engine_max_quantity=max_quantity,
        requested_quantity=requested,
        approved_preview_quantity=approved,
        planned_risk_dollars=planned_risk,
        planned_risk_fraction=(planned_risk / equity if equity else 0.0),
        planned_reward_dollars=planned_reward,
        planned_rr=intent.planned_rr,
        quantity_was_reduced=reduced,
    )

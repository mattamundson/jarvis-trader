"""H-01 versioned risk-policy schema.

The schema maps future canonical policy fields to legacy config names without
changing or activating any runtime value. A policy object is data, not authority.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Mapping

LEGACY_RISK_FIELD_MAP = {
    "max_position_size_pct": "MAX_POSITION_SIZE_PCT",
    "max_daily_loss_pct": "MAX_DAILY_LOSS_PCT",
    "max_daily_loss_usd": "MAX_DAILY_LOSS_USD",
    "max_trade_loss_usd": "MAX_TRADE_LOSS_USD",
    "max_drawdown_pct": "MAX_DRAWDOWN_PCT",
    "max_orders_per_minute": "MAX_ORDERS_PER_MINUTE",
    "max_correlated_exposure_pct": "MAX_CORRELATED_EXPOSURE_PCT",
    "price_collar_pct": "PRICE_COLLAR_PCT",
    "max_single_order_value": "MAX_SINGLE_ORDER_VALUE",
    "max_margin_utilization": "MAX_MARGIN_UTILIZATION",
    "max_contracts_per_instrument": "MAX_CONTRACTS_PER_INSTRUMENT",
    "max_overnight_contracts": "MAX_OVERNIGHT_CONTRACTS",
    "correlated_pair_max_contracts": "CORRELATED_PAIR_MAX_CONTRACTS",
}


@dataclass(frozen=True)
class RiskPolicyV1:
    policy_id: str
    version: int
    effective_from_utc: dt.datetime
    max_position_size_pct: float
    max_daily_loss_pct: float
    max_daily_loss_usd: float
    max_trade_loss_usd: float
    max_drawdown_pct: float
    max_orders_per_minute: int
    max_correlated_exposure_pct: float
    price_collar_pct: float
    max_single_order_value: float
    max_margin_utilization: float
    max_contracts_per_instrument: int
    max_overnight_contracts: int
    correlated_pair_max_contracts: int

    def __post_init__(self) -> None:
        if not self.policy_id.strip():
            raise ValueError("policy_id is required")
        if self.version < 1:
            raise ValueError("version must be >= 1")
        if self.effective_from_utc.tzinfo is None:
            raise ValueError("effective_from_utc must be timezone-aware")
        pct_fields = (
            "max_position_size_pct",
            "max_daily_loss_pct",
            "max_drawdown_pct",
            "max_correlated_exposure_pct",
            "price_collar_pct",
            "max_margin_utilization",
        )
        for name in pct_fields:
            value = float(getattr(self, name))
            if not 0 < value <= 1:
                raise ValueError(f"{name} must be in (0, 1]")
        usd_fields = ("max_daily_loss_usd", "max_trade_loss_usd", "max_single_order_value")
        for name in usd_fields:
            if float(getattr(self, name)) <= 0:
                raise ValueError(f"{name} must be positive")
        int_fields = (
            "max_orders_per_minute",
            "max_contracts_per_instrument",
            "max_overnight_contracts",
            "correlated_pair_max_contracts",
        )
        for name in int_fields:
            value = getattr(self, name)
            if not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be an integer >= 1")
        object.__setattr__(self, "policy_id", self.policy_id.strip())
        object.__setattr__(
            self,
            "effective_from_utc",
            self.effective_from_utc.astimezone(dt.timezone.utc),
        )

    @property
    def active(self) -> bool:
        return False

    @property
    def can_activate_itself(self) -> bool:
        return False

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "RiskPolicyV1":
        required = {field for field in LEGACY_RISK_FIELD_MAP} | {
            "policy_id",
            "version",
            "effective_from_utc",
        }
        missing = sorted(required - set(payload))
        if missing:
            raise ValueError(f"missing risk policy fields: {', '.join(missing)}")
        return cls(**{name: payload[name] for name in required})

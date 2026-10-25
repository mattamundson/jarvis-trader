"""Shared authorization result contract for order-producing paths."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class AuthorizationReason(str, Enum):
    """Machine-readable reasons for approval/order authorization outcomes."""

    OK = "ok"
    KILL_SWITCH_ACTIVE = "kill_switch_active"
    LIVE_TRADING_ENABLED = "live_trading_enabled"
    SAFETY_LAYER_MISSING = "safety_layer_missing"
    SAFETY_STATUS_ERROR = "safety_status_error"
    SYMBOL_NOT_APPROVED = "symbol_not_approved"
    STRATEGY_NOT_AUTHORIZED = "strategy_not_authorized"
    VALIDATION_ONLY_STRATEGY = "validation_only_strategy"
    STOP_OUT_LOCKOUT = "stop_out_lockout"
    FEATURE_SNAPSHOT_BLOCKED = "feature_snapshot_blocked"


@dataclass(frozen=True)
class AuthorizationResult:
    """Result object shared by approval surfaces before order submission."""

    allowed: bool
    reason: AuthorizationReason
    detail: str
    status_code: int = 200
    context: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def allow(cls, detail: str = "authorized") -> "AuthorizationResult":
        return cls(
            allowed=True,
            reason=AuthorizationReason.OK,
            detail=detail,
            status_code=200,
        )

    @classmethod
    def refuse(
        cls,
        reason: AuthorizationReason,
        detail: str,
        *,
        status_code: int,
        context: Mapping[str, Any] | None = None,
    ) -> "AuthorizationResult":
        return cls(
            allowed=False,
            reason=reason,
            detail=detail,
            status_code=status_code,
            context=MappingProxyType(dict(context or {})),
        )

    @property
    def reason_code(self) -> str:
        return self.reason.value


def kill_switch_active_from_status(status: Mapping[str, Any]) -> bool:
    """Normalize internal and public kill-switch status keys."""
    return bool(status.get("is_killed") or status.get("kill_switch_active"))

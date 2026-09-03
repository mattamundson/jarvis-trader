"""N-02 environment and authorization contracts.

An environment label is never permission. These immutable records describe the
evidence a future authorization service must evaluate; they cannot grant execution.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum

from .contracts import ExecutionEnvironment, MutationEffect


class VerificationRung(int, Enum):
    V0 = 0
    V1 = 1
    V2 = 2
    V3 = 3
    V4 = 4
    V5 = 5


class AuthorizationTier(str, Enum):
    NONE = "NONE"
    RESEARCH = "RESEARCH"
    PAPER = "PAPER"
    LIVE_CANARY = "LIVE_CANARY"
    LIVE = "LIVE"


@dataclass(frozen=True)
class EnvironmentRequirement:
    environment: ExecutionEnvironment
    minimum_verification: VerificationRung
    human_approval_required: bool
    capital_authorization_required: bool


ENVIRONMENT_REQUIREMENTS = {
    ExecutionEnvironment.RESEARCH: EnvironmentRequirement(
        ExecutionEnvironment.RESEARCH, VerificationRung.V1, False, False
    ),
    ExecutionEnvironment.PAPER: EnvironmentRequirement(
        ExecutionEnvironment.PAPER, VerificationRung.V4, False, False
    ),
    ExecutionEnvironment.LIVE: EnvironmentRequirement(
        ExecutionEnvironment.LIVE, VerificationRung.V5, True, True
    ),
}


@dataclass(frozen=True)
class AuthorizationEvidence:
    authorization_id: str
    tier: AuthorizationTier
    environment: ExecutionEnvironment
    verification_rung: VerificationRung
    issued_at_utc: dt.datetime
    expires_at_utc: dt.datetime
    human_approved: bool = False
    capital_authorized: bool = False
    milestone: str | None = None
    allowed_effects: tuple[MutationEffect, ...] = ()

    def __post_init__(self) -> None:
        if not self.authorization_id.strip():
            raise ValueError("authorization_id is required")
        if self.issued_at_utc.tzinfo is None or self.expires_at_utc.tzinfo is None:
            raise ValueError("authorization timestamps must be timezone-aware")
        issued = self.issued_at_utc.astimezone(dt.timezone.utc)
        expires = self.expires_at_utc.astimezone(dt.timezone.utc)
        if expires <= issued:
            raise ValueError("expires_at_utc must be after issued_at_utc")
        object.__setattr__(self, "authorization_id", self.authorization_id.strip())
        object.__setattr__(self, "issued_at_utc", issued)
        object.__setattr__(self, "expires_at_utc", expires)
        object.__setattr__(self, "allowed_effects", tuple(self.allowed_effects))

    @property
    def can_self_authorize(self) -> bool:
        """Hard boundary: evidence data alone never activates execution."""
        return False

    def structural_findings(self, *, now: dt.datetime | None = None) -> tuple[str, ...]:
        """Report missing evidence without returning an execution verdict."""
        now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
        req = ENVIRONMENT_REQUIREMENTS[self.environment]
        findings: list[str] = []
        if now >= self.expires_at_utc:
            findings.append("authorization evidence is expired")
        if self.verification_rung < req.minimum_verification:
            findings.append(
                f"{self.environment.value} requires at least V{req.minimum_verification.value}"
            )
        if req.human_approval_required and not self.human_approved:
            findings.append("human approval evidence is required")
        if req.capital_authorization_required and not self.capital_authorized:
            findings.append("capital authorization evidence is required")
        if self.environment is ExecutionEnvironment.LIVE and self.tier not in {
            AuthorizationTier.LIVE_CANARY,
            AuthorizationTier.LIVE,
        }:
            findings.append("LIVE environment requires a live authorization tier")
        return tuple(findings)

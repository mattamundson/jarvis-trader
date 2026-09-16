from __future__ import annotations

import random
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from morning_alpha.models import SetupCandidate


class ControlKind(StrEnum):
    RANDOM_UNIVERSE = "random_universe"
    RANDOM_SAME_SECTOR = "random_same_sector"
    NEXT_OPEN = "next_open"
    SPY = "spy"
    SECTOR_ETF = "sector_etf"


class UniverseMember(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1)
    sector: str | None = None
    effective_from: datetime
    effective_to: datetime | None = None
    eligible: bool = True

    @model_validator(mode="after")
    def validate_times(self) -> "UniverseMember":
        for name in ("effective_from", "effective_to"):
            value = getattr(self, name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{name} must be timezone-aware")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be after effective_from")
        return self

    def active_at(self, as_of: datetime) -> bool:
        return self.eligible and self.effective_from <= as_of and (
            self.effective_to is None or as_of < self.effective_to
        )


class ControlObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: ControlKind
    as_of: datetime
    symbol: str | None = None
    available: bool
    reason: str | None = None


class ControlSelector:
    @staticmethod
    def _rng(
        candidate: SetupCandidate,
        *,
        kind: ControlKind,
        seed_namespace: str,
    ) -> random.Random:
        identity = "|".join(
            (
                seed_namespace,
                candidate.strategy.canonical,
                candidate.symbol,
                candidate.as_of.isoformat(),
                kind.value,
            )
        )
        seed = int.from_bytes(sha256(identity.encode("utf-8")).digest()[:8], "big")
        return random.Random(seed)

    def _choose(
        self,
        candidate: SetupCandidate,
        pool: list[UniverseMember],
        *,
        kind: ControlKind,
        seed_namespace: str,
        missing_reason: str,
    ) -> ControlObservation:
        if not pool:
            return ControlObservation(
                kind=kind,
                as_of=candidate.as_of,
                available=False,
                reason=missing_reason,
            )
        ordered = sorted(pool, key=lambda row: row.symbol)
        chosen = self._rng(candidate, kind=kind, seed_namespace=seed_namespace).choice(ordered)
        return ControlObservation(
            kind=kind,
            as_of=candidate.as_of,
            symbol=chosen.symbol,
            available=True,
        )

    def select(
        self,
        candidate: SetupCandidate,
        universe: Iterable[UniverseMember],
        *,
        sector_etf: str | None,
        seed_namespace: str,
    ) -> tuple[ControlObservation, ...]:
        if candidate.as_of.tzinfo is None or candidate.as_of.utcoffset() is None:
            raise ValueError("candidate as_of must be timezone-aware")

        active = [
            row
            for row in universe
            if row.symbol != candidate.symbol and row.active_at(candidate.as_of)
        ]
        same_sector = [row for row in active if row.sector == candidate.sector]

        random_universe = self._choose(
            candidate,
            active,
            kind=ControlKind.RANDOM_UNIVERSE,
            seed_namespace=seed_namespace,
            missing_reason="NO_ELIGIBLE_CONTROL",
        )
        random_sector = self._choose(
            candidate,
            same_sector,
            kind=ControlKind.RANDOM_SAME_SECTOR,
            seed_namespace=seed_namespace,
            missing_reason="NO_SAME_SECTOR_CONTROL",
        )
        next_open = ControlObservation(
            kind=ControlKind.NEXT_OPEN,
            as_of=candidate.as_of,
            symbol=candidate.symbol,
            available=True,
        )
        spy = ControlObservation(
            kind=ControlKind.SPY,
            as_of=candidate.as_of,
            symbol="SPY",
            available=True,
        )
        sector = ControlObservation(
            kind=ControlKind.SECTOR_ETF,
            as_of=candidate.as_of,
            symbol=sector_etf,
            available=sector_etf is not None,
            reason=None if sector_etf is not None else "SECTOR_ETF_UNAVAILABLE",
        )
        return (random_universe, random_sector, next_open, spy, sector)

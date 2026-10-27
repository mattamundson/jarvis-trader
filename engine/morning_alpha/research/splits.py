from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SplitKind(StrEnum):
    DEVELOPMENT = "development"
    VALIDATION = "validation"
    OOS = "oos"
    FORWARD = "forward"


_SPLIT_ORDER = {
    SplitKind.DEVELOPMENT: 0,
    SplitKind.VALIDATION: 1,
    SplitKind.OOS: 2,
    SplitKind.FORWARD: 3,
}


class TemporalSplit(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: SplitKind
    start: date
    end: date

    @model_validator(mode="after")
    def validate_interval(self) -> "TemporalSplit":
        if self.start > self.end:
            raise ValueError("split start must be <= end")
        return self


class PurgedTemporalSplit(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: SplitKind
    included_dates: tuple[date, ...]
    excluded_dates: tuple[date, ...]
    purge_sessions: int = Field(ge=0)
    embargo_sessions: int = Field(default=0, ge=0)


class SplitRegistry(BaseModel):
    model_config = ConfigDict(frozen=True)

    splits: tuple[TemporalSplit, ...]
    trading_dates: tuple[date, ...]
    purge_sessions: int = Field(default=20, ge=0)
    embargo_sessions: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_registry(self) -> "SplitRegistry":
        if tuple(sorted(set(self.trading_dates))) != self.trading_dates:
            raise ValueError("trading_dates must be sorted and unique")
        ordered = sorted(self.splits, key=lambda split: split.start)
        if tuple(ordered) != self.splits:
            raise ValueError("splits must be chronological")
        seen_kinds: set[SplitKind] = set()
        last_end: date | None = None
        last_order = -1
        for split in self.splits:
            if split.kind in seen_kinds:
                raise ValueError("split kinds must be unique")
            seen_kinds.add(split.kind)
            if last_end is not None and split.start <= last_end:
                raise ValueError("split intervals overlap")
            order = _SPLIT_ORDER[split.kind]
            if order <= last_order:
                raise ValueError("split kinds must follow chronological research order")
            last_order = order
            last_end = split.end
        return self

    def assign(self, timestamp: datetime) -> SplitKind | None:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        target = timestamp.date()
        for split in self.splits:
            if split.start <= target <= split.end:
                return split.kind
        return None

    def purged(self, kind: SplitKind) -> PurgedTemporalSplit:
        try:
            index = next(i for i, split in enumerate(self.splits) if split.kind is kind)
        except StopIteration as exc:
            raise KeyError(kind) from exc
        split = self.splits[index]
        dates = tuple(day for day in self.trading_dates if split.start <= day <= split.end)
        if not dates or self.purge_sessions == 0:
            return PurgedTemporalSplit(
                kind=kind,
                included_dates=dates,
                excluded_dates=(),
                purge_sessions=self.purge_sessions,
                embargo_sessions=self.embargo_sessions,
            )

        excluded: set[date] = set()
        if index > 0:
            excluded.update(dates[: self.purge_sessions])
            excluded.update(dates[: self.embargo_sessions])
        if index < len(self.splits) - 1:
            excluded.update(dates[-self.purge_sessions :])
        included_dates = tuple(day for day in dates if day not in excluded)
        excluded_dates = tuple(day for day in dates if day in excluded)
        return PurgedTemporalSplit(
            kind=kind,
            included_dates=included_dates,
            excluded_dates=excluded_dates,
            purge_sessions=self.purge_sessions,
            embargo_sessions=self.embargo_sessions,
        )

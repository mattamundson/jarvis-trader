from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from morning_alpha.models import CatalystSnapshot, InstrumentSnapshot, SetupCandidate, StrategyKey


class DetailedSetupCandidate(SetupCandidate):
    features: dict[str, float | int | bool | str | None] = Field(default_factory=dict)


class SetupContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    returns_20d: float | None = None
    return_percentile_20d: float | None = Field(default=None, ge=0, le=100)
    spy_return_20d: float | None = None
    sector_return_20d: float | None = None
    sma20: float | None = None
    sma50: float | None = None
    ema8: float | None = None
    ema21: float | None = None
    atr14: float | None = Field(default=None, gt=0)
    prior_high: float | None = None
    prior_low: float | None = None
    prior_close: float | None = None
    high_20d: float | None = None
    high_252d: float | None = None
    pullback_low: float | None = None
    prior_bar_high: float | None = None
    relative_volume: float | None = None
    gap_pct: float | None = None
    gap_retention: float | None = None
    gap_low: float | None = None
    sector_rank: int | None = Field(default=None, gt=0)
    sector_count: int = Field(default=11, gt=0)
    eps_surprise_pct: float | None = None
    revenue_surprise_pct: float | None = None
    catalyst: CatalystSnapshot | None = None
    theme: str | None = None

    @model_validator(mode="after")
    def validate_catalyst_time(self) -> "SetupContext":
        if self.catalyst and self.catalyst.published_at and self.catalyst.published_at > self.catalyst.as_of:
            raise ValueError("catalyst published_at cannot be after catalyst as_of")
        return self


class SetupDetector(Protocol):
    strategy: StrategyKey

    def evaluate(self, snapshot: InstrumentSnapshot, context: SetupContext) -> SetupCandidate | None: ...

    def explain_features(
        self, snapshot: InstrumentSnapshot, context: SetupContext
    ) -> dict[str, float | int | bool | str | None]: ...


def trigger_buffer(context: SetupContext) -> float:
    return max(0.01, 0.03 * (context.atr14 or 0.0))


def long_candidate(
    *,
    snapshot: InstrumentSnapshot,
    context: SetupContext,
    strategy: StrategyKey,
    setup_type: str,
    thesis_code: str,
    entry: float,
    stop: float,
    features: dict[str, float | int | bool | str | None],
    nearby_obstacle: float | None = None,
) -> DetailedSetupCandidate:
    return DetailedSetupCandidate(
        symbol=snapshot.symbol,
        strategy=strategy,
        as_of=snapshot.as_of,
        side="long",
        setup_type=setup_type,
        thesis_code=thesis_code,
        proposed_entry=entry,
        proposed_stop=stop,
        nearby_obstacle=nearby_obstacle,
        sector=snapshot.sector,
        theme=context.theme,
        features=features,
    )

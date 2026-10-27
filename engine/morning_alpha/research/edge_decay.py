from __future__ import annotations

from enum import StrEnum
from statistics import fmean

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EdgeState(StrEnum):
    NORMAL = "normal"
    WATCH = "watch"
    DEGRADED = "degraded"
    HALTED = "halted"


class EdgeMonitorSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    version: str = Field(min_length=1)
    min_samples: int = Field(default=30, gt=1)
    watch_expectancy_fraction: float = Field(default=0.5, ge=0)
    degraded_expectancy_r: float = 0.0
    halt_expectancy_r: float = -0.2
    slippage_watch_multiple: float = Field(default=1.5, ge=1)
    slippage_degraded_multiple: float = Field(default=2.0, ge=1)
    recovery_expectancy_fraction: float = Field(default=0.85, ge=0)

    @model_validator(mode="after")
    def validate_spec(self) -> "EdgeMonitorSpec":
        if self.halt_expectancy_r >= self.degraded_expectancy_r:
            raise ValueError("halt_expectancy_r must be below degraded_expectancy_r")
        if self.slippage_degraded_multiple < self.slippage_watch_multiple:
            raise ValueError("degraded slippage multiple must be >= watch multiple")
        return self


class EdgeMonitorResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    state: EdgeState
    reason: str
    sample_size: int
    rolling_expectancy_r: float | None
    average_slippage_r: float | None
    spec_version: str


class EdgeDecayMonitor:
    def __init__(self, spec: EdgeMonitorSpec | None = None) -> None:
        self.spec = spec or EdgeMonitorSpec(version="1.0.0")

    def evaluate(
        self,
        *,
        previous_state: EdgeState,
        recent_returns_r: tuple[float, ...] | list[float],
        recent_slippage_r: tuple[float, ...] | list[float],
        historical_expectancy_r: float,
        modeled_slippage_r: float,
        revalidation_approved: bool = False,
    ) -> EdgeMonitorResult:
        returns = tuple(recent_returns_r)
        slippage = tuple(recent_slippage_r)
        n = len(returns)
        if n < self.spec.min_samples:
            return EdgeMonitorResult(
                state=previous_state,
                reason="INSUFFICIENT_SAMPLE_NO_TRANSITION",
                sample_size=n,
                rolling_expectancy_r=fmean(returns) if returns else None,
                average_slippage_r=fmean(slippage) if slippage else None,
                spec_version=self.spec.version,
            )
        if previous_state is EdgeState.HALTED and not revalidation_approved:
            return EdgeMonitorResult(
                state=EdgeState.HALTED,
                reason="REVALIDATION_REQUIRED",
                sample_size=n,
                rolling_expectancy_r=fmean(returns),
                average_slippage_r=fmean(slippage) if slippage else None,
                spec_version=self.spec.version,
            )
        expectancy = fmean(returns)
        avg_slippage = fmean(slippage) if slippage else 0.0
        slip_ratio = (avg_slippage / modeled_slippage_r) if modeled_slippage_r > 0 else (float("inf") if avg_slippage > 0 else 1.0)

        if expectancy <= self.spec.halt_expectancy_r:
            state, reason = EdgeState.HALTED, "EXPECTANCY_HALT_THRESHOLD"
        elif expectancy <= self.spec.degraded_expectancy_r or slip_ratio >= self.spec.slippage_degraded_multiple:
            state = EdgeState.DEGRADED
            reason = "SLIPPAGE_DEGRADED" if slip_ratio >= self.spec.slippage_degraded_multiple else "EXPECTANCY_DEGRADED"
        elif expectancy < historical_expectancy_r * self.spec.watch_expectancy_fraction or slip_ratio >= self.spec.slippage_watch_multiple:
            state = EdgeState.WATCH
            reason = "SLIPPAGE_WATCH" if slip_ratio >= self.spec.slippage_watch_multiple else "EXPECTANCY_WATCH"
        else:
            state, reason = EdgeState.NORMAL, "HEALTHY"

        if previous_state is EdgeState.HALTED and revalidation_approved:
            if expectancy < historical_expectancy_r * self.spec.recovery_expectancy_fraction:
                state, reason = EdgeState.HALTED, "REVALIDATION_EVIDENCE_INSUFFICIENT"
            elif slip_ratio >= self.spec.slippage_watch_multiple:
                state, reason = EdgeState.HALTED, "REVALIDATION_EXECUTION_DRIFT"
            else:
                state, reason = EdgeState.NORMAL, "REVALIDATED"

        return EdgeMonitorResult(
            state=state,
            reason=reason,
            sample_size=n,
            rolling_expectancy_r=expectancy,
            average_slippage_r=avg_slippage,
            spec_version=self.spec.version,
        )

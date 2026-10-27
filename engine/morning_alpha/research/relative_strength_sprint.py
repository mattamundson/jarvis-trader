from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from morning_alpha.models import MarketBar, Session, SetupCandidate
from morning_alpha.research.attribution import EdgeAttribution, EdgeAttributionEngine
from morning_alpha.research.campaign import DataReadinessReport
from morning_alpha.research.controls import ControlKind, ControlSelector, UniverseMember
from morning_alpha.research.forward_returns import ForwardHorizon, ForwardReturnEngine
from morning_alpha.research.trial_ledger import InMemoryTrialLedger, ResearchTrial, TrialStatus

_FROZEN_STRATEGY = "relative_strength_breakout@1.0.0"


class SprintStatus(StrEnum):
    BLOCKED = "blocked"
    INSUFFICIENT_DATA = "insufficient_data"
    EVIDENCE_READY = "evidence_ready"


class RelativeStrengthSprintInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    readiness: DataReadinessReport
    candidate: SetupCandidate
    universe: tuple[UniverseMember, ...]
    sector_etf: str | None = None
    bars_by_symbol: dict[str, tuple[MarketBar, ...]]
    data_manifest_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    sample_start: datetime
    sample_end: datetime
    horizon: ForwardHorizon = ForwardHorizon.DAY_5
    seed_namespace: str = "relative_strength_sprint_1"

    @model_validator(mode="after")
    def validate_window(self) -> "RelativeStrengthSprintInput":
        for name in ("sample_start", "sample_end"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.sample_end < self.sample_start:
            raise ValueError("sample_end must be on or after sample_start")
        return self


class RelativeStrengthSprintReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_key: str
    status: SprintStatus
    control_counts: dict[str, int] = Field(default_factory=dict)
    control_symbols: dict[str, str | None] = Field(default_factory=dict)
    forward_returns: dict[str, float | None] = Field(default_factory=dict)
    attribution: EdgeAttribution | None = None
    trial_ids: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


class RelativeStrengthResearchSprint:
    def __init__(self, *, ledger: InMemoryTrialLedger | None = None) -> None:
        self.ledger = ledger or InMemoryTrialLedger()
        self._controls = ControlSelector()
        self._forward = ForwardReturnEngine()
        self._attribution = EdgeAttributionEngine()

    @staticmethod
    def _first_rth_bar(
        symbol: str,
        as_of: datetime,
        bars_by_symbol: dict[str, tuple[MarketBar, ...]],
    ) -> MarketBar | None:
        rows = sorted(
            (
                bar
                for bar in bars_by_symbol.get(symbol, ())
                if bar.timestamp > as_of and bar.session is Session.RTH
            ),
            key=lambda bar: bar.timestamp,
        )
        return rows[0] if rows else None

    def _measure_return(
        self,
        symbol: str,
        decision_time: datetime,
        entry_price: float,
        bars_by_symbol: dict[str, tuple[MarketBar, ...]],
        horizon: ForwardHorizon,
    ) -> float | None:
        observation = self._forward.measure(
            symbol,
            decision_time,
            entry_price,
            bars_by_symbol.get(symbol, ()),
            (horizon,),
        )[0]
        return observation.simple_return if observation.available else None

    def run(self, inputs: RelativeStrengthSprintInput) -> RelativeStrengthSprintReport:
        candidate = inputs.candidate
        if candidate.strategy.canonical != _FROZEN_STRATEGY:
            raise ValueError(f"Sprint 1 requires frozen strategy {_FROZEN_STRATEGY}")

        if not inputs.readiness.ready:
            return RelativeStrengthSprintReport(
                strategy_key=candidate.strategy.canonical,
                status=SprintStatus.BLOCKED,
                reasons=inputs.readiness.reasons or ("DATA_NOT_READY",),
            )

        controls = self._controls.select(
            candidate,
            inputs.universe,
            sector_etf=inputs.sector_etf,
            seed_namespace=inputs.seed_namespace,
        )
        control_counts = {row.kind.value: int(row.available) for row in controls}
        control_symbols = {row.kind.value: row.symbol for row in controls}

        forward_returns: dict[str, float | None] = {}
        strategy_return = self._measure_return(
            candidate.symbol,
            candidate.as_of,
            candidate.proposed_entry,
            inputs.bars_by_symbol,
            inputs.horizon,
        )
        forward_returns["strategy"] = strategy_return

        for control in controls:
            value: float | None = None
            if control.available and control.symbol is not None:
                first = self._first_rth_bar(
                    control.symbol,
                    candidate.as_of,
                    inputs.bars_by_symbol,
                )
                if first is not None:
                    value = self._measure_return(
                        control.symbol,
                        candidate.as_of,
                        first.open,
                        inputs.bars_by_symbol,
                        inputs.horizon,
                    )
            forward_returns[control.kind.value] = value

        attribution = None
        reasons: list[str] = ["FULL_VALIDATION_STAGES_PENDING"]
        needed = (
            strategy_return,
            forward_returns.get(ControlKind.NEXT_OPEN.value),
            forward_returns.get(ControlKind.SECTOR_ETF.value),
            forward_returns.get(ControlKind.SPY.value),
        )
        if all(value is not None for value in needed):
            attribution = self._attribution.attribute(
                strategy_return=float(strategy_return),
                next_open_return=float(forward_returns[ControlKind.NEXT_OPEN.value]),
                sector_return=float(forward_returns[ControlKind.SECTOR_ETF.value]),
                market_return=float(forward_returns[ControlKind.SPY.value]),
            )
        else:
            reasons.append("ATTRIBUTION_INPUT_MISSING")

        trial = ResearchTrial.build(
            campaign_id="morning_alpha_v1",
            strategy_key=candidate.strategy.canonical,
            control_version="controls@1.0.0",
            trigger_version="raw_forward@1.0.0",
            exit_version=f"forward_{inputs.horizon.value}@1.0.0",
            ablation_kind="full",
            parameter_fingerprint="sha256:relative-strength-v1-frozen",
            cost_bps=0,
            data_manifest_hash=inputs.data_manifest_hash,
            sample_start=inputs.sample_start,
            sample_end=inputs.sample_end,
            status=TrialStatus.COMPLETED,
            sample_size=1,
        )
        self.ledger.append(trial)

        return RelativeStrengthSprintReport(
            strategy_key=candidate.strategy.canonical,
            status=SprintStatus.INSUFFICIENT_DATA,
            control_counts=control_counts,
            control_symbols=control_symbols,
            forward_returns=forward_returns,
            attribution=attribution,
            trial_ids=(trial.trial_id,),
            reasons=tuple(reasons),
        )

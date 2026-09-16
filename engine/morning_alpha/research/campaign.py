from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from morning_alpha.models import StrategyKey
from morning_alpha.research.trigger_lab import TriggerKind


PRE_REGISTERED_STRATEGIES: tuple[StrategyKey, ...] = (
    StrategyKey(strategy_id="relative_strength_breakout", version="1.0.0"),
    StrategyKey(strategy_id="sector_rotation", version="1.0.0"),
    StrategyKey(strategy_id="post_earnings_drift", version="1.0.0"),
    StrategyKey(strategy_id="momentum_breakout", version="1.0.0"),
    StrategyKey(strategy_id="pullback_continuation", version="1.0.0"),
    StrategyKey(strategy_id="gap_continuation", version="1.0.0"),
)

PRE_REGISTERED_TRIGGERS: tuple[TriggerKind, ...] = tuple(TriggerKind)
PRE_REGISTERED_COST_BPS: tuple[int, ...] = (0, 2, 5, 10, 20)


class ResearchCampaignSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    campaign_id: str = "morning_alpha_v1"
    strategies: tuple[StrategyKey, ...] = PRE_REGISTERED_STRATEGIES
    triggers: tuple[TriggerKind, ...] = PRE_REGISTERED_TRIGGERS
    cost_bps: tuple[int, ...] = PRE_REGISTERED_COST_BPS
    min_historical_trades: int = Field(default=200, gt=0)
    require_oos: bool = True
    require_wfo: bool = True
    require_monte_carlo: bool = True
    require_regime_stability: bool = True
    require_gate_v2: bool = True

    @model_validator(mode="after")
    def validate_campaign(self) -> "ResearchCampaignSpec":
        if len(set(key.canonical for key in self.strategies)) != len(self.strategies):
            raise ValueError("strategy versions must be unique within a campaign")
        if len(set(self.cost_bps)) != len(self.cost_bps):
            raise ValueError("cost_bps must be unique")
        return self


class DataReadinessReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    ready: bool
    root: str
    file_count: int
    symbols: tuple[str, ...]
    earliest_timestamp: datetime | None = None
    latest_timestamp: datetime | None = None
    reasons: tuple[str, ...] = ()


def inspect_research_files(root: str | Path) -> DataReadinessReport:
    """Check file-stage readiness without inventing historical coverage."""
    path = Path(root)
    files = sorted(path.glob("bars/*.parquet")) if path.exists() else []
    symbols = tuple(sorted(file.stem for file in files))
    reasons: list[str] = []
    if not path.exists():
        reasons.append("DATA_ROOT_MISSING")
    if not files:
        reasons.append("NO_BAR_FILES")
    return DataReadinessReport(
        ready=not reasons,
        root=str(path),
        file_count=len(files),
        symbols=symbols,
        reasons=tuple(reasons),
    )


def require_research_ready(report: DataReadinessReport) -> None:
    if not report.ready:
        detail = ",".join(report.reasons) or "UNKNOWN"
        raise RuntimeError(f"Morning Alpha research data not ready: {detail}")

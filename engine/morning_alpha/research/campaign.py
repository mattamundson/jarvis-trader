from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

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


class ResearchArtifactKind(StrEnum):
    DAILY_BARS = "daily_bars"
    INTRADAY_BARS = "intraday_bars"
    UNIVERSE_MEMBERSHIP = "universe_membership"
    DELISTED_SYMBOLS = "delisted_symbols"
    CORPORATE_ACTIONS = "corporate_actions"
    SECTOR_HISTORY = "sector_history"
    EARNINGS_EVENTS = "earnings_events"
    MACRO_CONTEXT = "macro_context"
    PREMARKET_BARS = "premarket_bars"


class ResearchArtifactReceipt(BaseModel):
    """Immutable provenance receipt binding one research evidence artifact to bytes on disk."""

    model_config = ConfigDict(frozen=True)

    kind: ResearchArtifactKind
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    provider: str = Field(min_length=1)
    row_count: int = Field(ge=0)
    symbol_count: int = Field(ge=0)
    earliest_timestamp: datetime | None = None
    latest_timestamp: datetime | None = None
    point_in_time: bool = False

    @model_validator(mode="after")
    def validate_receipt(self) -> "ResearchArtifactReceipt":
        pure = PurePosixPath(self.path.replace("\\", "/"))
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError("artifact receipt path must be relative and cannot escape the research root")
        for field_name in ("earliest_timestamp", "latest_timestamp"):
            value = getattr(self, field_name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{field_name} must be timezone-aware")
        if (
            self.earliest_timestamp
            and self.latest_timestamp
            and self.earliest_timestamp > self.latest_timestamp
        ):
            raise ValueError("artifact earliest_timestamp cannot exceed latest_timestamp")
        return self


_REQUIRED_ARTIFACT_KINDS: tuple[ResearchArtifactKind, ...] = tuple(ResearchArtifactKind)


def _version_at_least(version: str, minimum: tuple[int, int, int]) -> bool:
    try:
        parts = tuple(int(part) for part in version.split(".")[:3])
    except ValueError:
        return False
    return parts >= minimum if len(parts) == 3 else False


def _artifact_flag(receipts: tuple[ResearchArtifactReceipt, ...], kind: ResearchArtifactKind) -> bool:
    return any(receipt.kind is kind for receipt in receipts)


def build_manifest_from_receipts(
    receipts: list[ResearchArtifactReceipt] | tuple[ResearchArtifactReceipt, ...],
    *,
    generated_at: datetime,
) -> "ResearchDataManifest":
    """Build v1.1 manifest assertions from artifact receipts instead of hand-edited booleans."""

    ordered = tuple(receipts)
    providers = tuple(sorted({receipt.provider for receipt in ordered}))
    by_kind = {receipt.kind: receipt for receipt in ordered}
    daily = by_kind.get(ResearchArtifactKind.DAILY_BARS)
    intraday = by_kind.get(ResearchArtifactKind.INTRADAY_BARS)
    universe = by_kind.get(ResearchArtifactKind.UNIVERSE_MEMBERSHIP)

    return ResearchDataManifest(
        manifest_version="1.1.0",
        generated_at=generated_at,
        providers=providers,
        daily_symbol_count=daily.symbol_count if daily else 0,
        intraday_symbol_count=intraday.symbol_count if intraday else 0,
        earliest_daily_timestamp=daily.earliest_timestamp if daily else None,
        latest_daily_timestamp=daily.latest_timestamp if daily else None,
        earliest_intraday_timestamp=intraday.earliest_timestamp if intraday else None,
        latest_intraday_timestamp=intraday.latest_timestamp if intraday else None,
        point_in_time_universe=bool(universe and universe.point_in_time),
        delisted_symbols=_artifact_flag(ordered, ResearchArtifactKind.DELISTED_SYMBOLS),
        corporate_actions=_artifact_flag(ordered, ResearchArtifactKind.CORPORATE_ACTIONS),
        sector_history=_artifact_flag(ordered, ResearchArtifactKind.SECTOR_HISTORY),
        earnings_events=_artifact_flag(ordered, ResearchArtifactKind.EARNINGS_EVENTS),
        macro_context=_artifact_flag(ordered, ResearchArtifactKind.MACRO_CONTEXT),
        source_lineage=bool(ordered) and all(r.provider and r.sha256 for r in ordered),
        premarket_bars=_artifact_flag(ordered, ResearchArtifactKind.PREMARKET_BARS),
        artifacts=ordered,
    )


class ResearchCampaignSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    campaign_id: str = "morning_alpha_v1"
    strategies: tuple[StrategyKey, ...] = PRE_REGISTERED_STRATEGIES
    triggers: tuple[TriggerKind, ...] = PRE_REGISTERED_TRIGGERS
    cost_bps: tuple[int, ...] = PRE_REGISTERED_COST_BPS
    min_historical_trades: int = Field(default=200, gt=0)
    min_daily_symbols: int = Field(default=500, gt=0)
    min_intraday_symbols: int = Field(default=100, gt=0)
    min_history_years: int = Field(default=8, gt=0)
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


class ResearchDataManifest(BaseModel):
    """Explicit evidence that a local research dataset is fit for the v1 campaign.

    This manifest is intentionally declarative. It does not make a provider trustworthy;
    it records the coverage assertions that ingestion/validation tooling must prove and
    preserves them alongside the dataset for later audit.
    """

    model_config = ConfigDict(frozen=True)

    manifest_version: str = "1.0.0"
    generated_at: datetime
    providers: tuple[str, ...] = ()
    daily_symbol_count: int = Field(ge=0)
    intraday_symbol_count: int = Field(ge=0)
    earliest_daily_timestamp: datetime | None = None
    latest_daily_timestamp: datetime | None = None
    earliest_intraday_timestamp: datetime | None = None
    latest_intraday_timestamp: datetime | None = None
    point_in_time_universe: bool = False
    delisted_symbols: bool = False
    corporate_actions: bool = False
    sector_history: bool = False
    earnings_events: bool = False
    macro_context: bool = False
    source_lineage: bool = False
    premarket_bars: bool = False
    artifacts: tuple[ResearchArtifactReceipt, ...] = ()

    @model_validator(mode="after")
    def validate_timestamps(self) -> "ResearchDataManifest":
        timestamp_fields = (
            "generated_at",
            "earliest_daily_timestamp",
            "latest_daily_timestamp",
            "earliest_intraday_timestamp",
            "latest_intraday_timestamp",
        )
        for field_name in timestamp_fields:
            value = getattr(self, field_name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{field_name} must be timezone-aware")
        if (
            self.earliest_daily_timestamp
            and self.latest_daily_timestamp
            and self.earliest_daily_timestamp > self.latest_daily_timestamp
        ):
            raise ValueError("earliest_daily_timestamp cannot exceed latest_daily_timestamp")
        if (
            self.earliest_intraday_timestamp
            and self.latest_intraday_timestamp
            and self.earliest_intraday_timestamp > self.latest_intraday_timestamp
        ):
            raise ValueError("earliest_intraday_timestamp cannot exceed latest_intraday_timestamp")
        return self


class DataReadinessReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    ready: bool
    file_stage_ready: bool = False
    manifest_present: bool = False
    root: str
    file_count: int
    symbols: tuple[str, ...]
    providers: tuple[str, ...] = ()
    daily_symbol_count: int = 0
    intraday_symbol_count: int = 0
    earliest_timestamp: datetime | None = None
    latest_timestamp: datetime | None = None
    earliest_intraday_timestamp: datetime | None = None
    latest_intraday_timestamp: datetime | None = None
    reasons: tuple[str, ...] = ()


def _history_span_ok(
    earliest: datetime | None,
    latest: datetime | None,
    *,
    min_years: int,
) -> bool:
    if earliest is None or latest is None:
        return False
    return latest - earliest >= timedelta(days=365 * min_years)


def inspect_research_files(
    root: str | Path,
    *,
    spec: ResearchCampaignSpec | None = None,
) -> DataReadinessReport:
    """Validate file presence plus the evidence manifest required for honest research.

    The prior implementation only checked for ``bars/*.parquet``. That is useful as a
    file-stage smoke test but is insufficient to certify a survivorship-safe, point-in-time
    research corpus. ``ready`` now means that the dataset also carries an explicit manifest
    satisfying the pre-registered campaign coverage contract.
    """

    campaign = spec or ResearchCampaignSpec()
    path = Path(root)
    files = sorted(path.glob("bars/**/*.parquet")) if path.exists() else []
    if path.exists() and not files:
        # ``Path.glob('bars/**/*.parquet')`` is recursive on current Python versions, but
        # include the direct pattern explicitly for clarity/portability.
        files = sorted(path.glob("bars/*.parquet"))
    symbols = tuple(sorted({file.stem for file in files}))
    manifest_path = path / "research_manifest.json"

    reasons: list[str] = []
    if not path.exists():
        reasons.append("DATA_ROOT_MISSING")
    if not files:
        reasons.append("NO_BAR_FILES")

    manifest: ResearchDataManifest | None = None
    if not manifest_path.exists():
        reasons.append("MANIFEST_MISSING")
    else:
        try:
            manifest = ResearchDataManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError, ValueError):
            reasons.append("MANIFEST_INVALID")

    if manifest is not None:
        if not manifest.providers:
            reasons.append("PROVIDER_LINEAGE_EMPTY")
        if manifest.daily_symbol_count < campaign.min_daily_symbols:
            reasons.append("DAILY_SYMBOL_COVERAGE_LOW")
        if manifest.intraday_symbol_count < campaign.min_intraday_symbols:
            reasons.append("INTRADAY_SYMBOL_COVERAGE_LOW")
        if not _history_span_ok(
            manifest.earliest_daily_timestamp,
            manifest.latest_daily_timestamp,
            min_years=campaign.min_history_years,
        ):
            reasons.append("DAILY_HISTORY_SPAN_TOO_SHORT")
        if manifest.earliest_intraday_timestamp is None or manifest.latest_intraday_timestamp is None:
            reasons.append("INTRADAY_TIMESTAMP_COVERAGE_MISSING")

        required_flags = (
            ("point_in_time_universe", "POINT_IN_TIME_UNIVERSE_MISSING"),
            ("delisted_symbols", "DELISTED_SYMBOLS_MISSING"),
            ("corporate_actions", "CORPORATE_ACTIONS_MISSING"),
            ("sector_history", "SECTOR_HISTORY_MISSING"),
            ("earnings_events", "EARNINGS_EVENTS_MISSING"),
            ("macro_context", "MACRO_CONTEXT_MISSING"),
            ("source_lineage", "SOURCE_LINEAGE_MISSING"),
            ("premarket_bars", "PREMARKET_BARS_MISSING"),
        )
        for attr, reason in required_flags:
            if not getattr(manifest, attr):
                reasons.append(reason)

        if _version_at_least(manifest.manifest_version, (1, 1, 0)):
            receipts_by_kind = {receipt.kind: receipt for receipt in manifest.artifacts}
            for kind in _REQUIRED_ARTIFACT_KINDS:
                if kind not in receipts_by_kind:
                    reasons.append(f"ARTIFACT_KIND_MISSING:{kind.value}")

            for receipt in manifest.artifacts:
                artifact_path = path / receipt.path
                if not artifact_path.is_file():
                    reasons.append(f"ARTIFACT_FILE_MISSING:{receipt.path}")
                    continue
                actual_hash = sha256(artifact_path.read_bytes()).hexdigest()
                if actual_hash.lower() != receipt.sha256.lower():
                    reasons.append(f"ARTIFACT_HASH_MISMATCH:{receipt.path}")

            universe_receipt = receipts_by_kind.get(ResearchArtifactKind.UNIVERSE_MEMBERSHIP)
            if universe_receipt is not None and not universe_receipt.point_in_time:
                reasons.append("UNIVERSE_RECEIPT_NOT_POINT_IN_TIME")

    return DataReadinessReport(
        ready=not reasons,
        file_stage_ready=bool(files),
        manifest_present=manifest_path.exists(),
        root=str(path),
        file_count=len(files),
        symbols=symbols,
        providers=manifest.providers if manifest else (),
        daily_symbol_count=manifest.daily_symbol_count if manifest else 0,
        intraday_symbol_count=manifest.intraday_symbol_count if manifest else 0,
        earliest_timestamp=manifest.earliest_daily_timestamp if manifest else None,
        latest_timestamp=manifest.latest_daily_timestamp if manifest else None,
        earliest_intraday_timestamp=(
            manifest.earliest_intraday_timestamp if manifest else None
        ),
        latest_intraday_timestamp=manifest.latest_intraday_timestamp if manifest else None,
        reasons=tuple(reasons),
    )


def require_research_ready(report: DataReadinessReport) -> None:
    if not report.ready:
        detail = ",".join(report.reasons) or "UNKNOWN"
        raise RuntimeError(f"Morning Alpha research data not ready: {detail}")
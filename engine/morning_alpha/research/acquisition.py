from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from morning_alpha.research.campaign import ResearchArtifactKind


class AcquisitionSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = Field(min_length=1)
    product: str = Field(min_length=1)
    url: str = Field(min_length=1)
    capabilities: tuple[str, ...] = ()
    point_in_time: bool = False
    role: str = "primary"


class ArtifactAcquisitionRequirement(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: ResearchArtifactKind
    required_fields: tuple[str, ...]
    sources: tuple[AcquisitionSource, ...]
    notes: str = ""


class ResearchAcquisitionPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    plan_version: str = "1.0.0"
    artifacts: tuple[ArtifactAcquisitionRequirement, ...]


_DATABENTO_SECURITY_MASTER = AcquisitionSource(
    provider="Databento Reference",
    product="Point-in-time Security Master",
    url="https://databento.com/docs/schemas-and-data-formats/security-master",
    capabilities=(
        "ts_record",
        "ts_effective",
        "listed_and_delisted",
        "listing_status",
        "listing_date",
        "delisting_date",
        "gics",
        "sic",
        "naics",
        "stable_identifiers",
    ),
    point_in_time=True,
)

_DATABENTO_CORPORATE_ACTIONS = AcquisitionSource(
    provider="Databento Reference",
    product="Point-in-time Corporate Actions",
    url="https://databento.com/docs/venues-and-datasets/corporate-actions",
    capabilities=("ts_record", "event_unique_id", "effective_date", "pit_history"),
    point_in_time=True,
)

_MASSIVE_STOCKS = AcquisitionSource(
    provider="Massive",
    product="U.S. Stocks historical aggregates/trades",
    url="https://massive.com/docs/rest/stocks/overview",
    capabilities=(
        "daily_ohlcv",
        "intraday_ohlcv",
        "tick_trades",
        "premarket",
        "regular_session",
        "after_hours",
        "history_since_2003",
    ),
)

_ZACKS_EARNINGS = AcquisitionSource(
    provider="Zacks Data",
    product="Historical EPS & Sales Surprises",
    url="https://www.zackspro.com/historical.asp",
    capabilities=(
        "report_date",
        "entry_date",
        "actual_eps",
        "consensus_on_report_date",
        "surprise_pct",
        "actual_sales",
        "sales_consensus",
        "estimate_revisions",
    ),
    point_in_time=True,
)

_FINNHUB_EARNINGS = AcquisitionSource(
    provider="Finnhub",
    product="Earnings calendar",
    url="https://finnhub.io/",
    capabilities=("historical_earnings_dates", "earnings_calendar"),
    point_in_time=False,
    role="cross_check",
)

_FRED_MACRO = AcquisitionSource(
    provider="FRED",
    product="Official/redistributed daily macro series",
    url="https://fred.stlouisfed.org/",
    capabilities=("DGS10", "WTI_daily", "VIXCLS"),
    point_in_time=False,
)

_CBOE_VIX = AcquisitionSource(
    provider="Cboe",
    product="VIX historical index data",
    url="https://www.cboe.com/tradable-products/vix/vix-historical-data",
    capabilities=("VIX_daily",),
    point_in_time=False,
    role="authoritative_cross_check",
)

_FED_CALENDAR = AcquisitionSource(
    provider="Federal Reserve",
    product="FOMC meeting calendar",
    url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    capabilities=("scheduled_fomc_dates", "policy_statement_dates"),
    point_in_time=True,
)

_BLS_CALENDAR = AcquisitionSource(
    provider="U.S. Bureau of Labor Statistics",
    product="Official release calendar",
    url="https://www.bls.gov/schedule/",
    capabilities=("cpi_release_dates", "employment_release_dates", "release_times"),
    point_in_time=True,
)


RESEARCH_ACQUISITION_PLAN_V1: tuple[ArtifactAcquisitionRequirement, ...] = (
    ArtifactAcquisitionRequirement(
        kind=ResearchArtifactKind.DAILY_BARS,
        required_fields=("symbol", "timestamp", "open", "high", "low", "close", "volume"),
        sources=(_MASSIVE_STOCKS,),
        notes="Store raw/unadjusted market history plus separate corporate-action evidence so adjustment policy remains reproducible.",
    ),
    ArtifactAcquisitionRequirement(
        kind=ResearchArtifactKind.INTRADAY_BARS,
        required_fields=(
            "symbol", "timestamp", "open", "high", "low", "close", "volume", "session"
        ),
        sources=(_MASSIVE_STOCKS,),
        notes="5-minute-or-better coverage is required for the ORB, retest and VWAP trigger laboratory.",
    ),
    ArtifactAcquisitionRequirement(
        kind=ResearchArtifactKind.UNIVERSE_MEMBERSHIP,
        required_fields=(
            "stable_id", "symbol", "ts_record", "ts_effective", "listing_status",
            "listing_date", "delisting_date", "primary_exchange", "security_type"
        ),
        sources=(_DATABENTO_SECURITY_MASTER,),
        notes="Build membership snapshots from effective-time records, never from today's surviving symbols.",
    ),
    ArtifactAcquisitionRequirement(
        kind=ResearchArtifactKind.DELISTED_SYMBOLS,
        required_fields=("stable_id", "symbol", "ts_record", "ts_effective", "delisting_date", "listing_status"),
        sources=(_DATABENTO_SECURITY_MASTER,),
    ),
    ArtifactAcquisitionRequirement(
        kind=ResearchArtifactKind.CORPORATE_ACTIONS,
        required_fields=("stable_id", "event_unique_id", "event_type", "ts_record", "effective_date"),
        sources=(_DATABENTO_CORPORATE_ACTIONS,),
        notes="Retain PIT revisions and adjustment factors separately from raw market bars.",
    ),
    ArtifactAcquisitionRequirement(
        kind=ResearchArtifactKind.SECTOR_HISTORY,
        required_fields=("stable_id", "ts_record", "ts_effective", "gics", "sic", "naics"),
        sources=(_DATABENTO_SECURITY_MASTER,),
        notes="Sector/industry classification must be reconstructed from PIT records rather than current classifications.",
    ),
    ArtifactAcquisitionRequirement(
        kind=ResearchArtifactKind.EARNINGS_EVENTS,
        required_fields=(
            "symbol", "report_date", "entry_date", "fiscal_period", "actual_eps",
            "consensus_on_report_date", "eps_surprise_pct", "actual_revenue", "revenue_consensus"
        ),
        sources=(_ZACKS_EARNINGS, _FINNHUB_EARNINGS),
        notes="PEAD research requires the consensus known on the report date; a calendar-only source is insufficient.",
    ),
    ArtifactAcquisitionRequirement(
        kind=ResearchArtifactKind.MACRO_CONTEXT,
        required_fields=(
            "timestamp", "vix", "dgs10", "wti", "scheduled_event_type", "scheduled_event_timestamp"
        ),
        sources=(_FRED_MACRO, _CBOE_VIX, _FED_CALENDAR, _BLS_CALENDAR),
        notes="Use official release calendars for FOMC/CPI/jobs event risk; market series alone cannot reconstruct scheduled-event state.",
    ),
    ArtifactAcquisitionRequirement(
        kind=ResearchArtifactKind.PREMARKET_BARS,
        required_fields=("symbol", "timestamp", "open", "high", "low", "close", "volume", "session"),
        sources=(_MASSIVE_STOCKS,),
        notes="Session normalization must distinguish premarket from RTH and after-hours.",
    ),
)

RESEARCH_ACQUISITION_PLAN = ResearchAcquisitionPlan(artifacts=RESEARCH_ACQUISITION_PLAN_V1)


def acquisition_requirement_for(kind: ResearchArtifactKind) -> ArtifactAcquisitionRequirement:
    for requirement in RESEARCH_ACQUISITION_PLAN_V1:
        if requirement.kind is kind:
            return requirement
    raise KeyError(kind)


def preferred_source_for(kind: ResearchArtifactKind) -> AcquisitionSource:
    return acquisition_requirement_for(kind).sources[0]

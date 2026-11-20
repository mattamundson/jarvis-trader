from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Sequence

from pydantic import BaseModel, ConfigDict, Field

from morning_alpha.config import MorningAlphaConfig
from morning_alpha.journal import InMemorySignalJournal, SignalJournal
from morning_alpha.models import InstrumentSnapshot, MarketRegime, SetupCandidate, TradePlan
from morning_alpha.portfolio import PortfolioHeatEngine, PortfolioHeatResult
from morning_alpha.providers.protocols import MarketDataProvider
from morning_alpha.risk import TradeConstructor, TradeRejection
from morning_alpha.sectors import SectorScore
from morning_alpha.setups import SetupContext, SetupDetector
from morning_alpha.universe import UniverseRecord, evaluate_eligibility


class ScanStatus(StrEnum):
    QUALIFIED = "QUALIFIED"
    NO_TRADE = "NO_TRADE"


class ScanRejection(BaseModel):
    model_config = ConfigDict(frozen=True)
    symbol: str
    stage: str
    reason: str


class ScanResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    as_of: object
    status: ScanStatus
    regime: MarketRegime | None = None
    sector_scores: tuple[SectorScore, ...] = ()
    eligible_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    candidates: tuple[SetupCandidate, ...] = ()
    rejections: tuple[ScanRejection, ...] = ()
    qualified_plans: tuple[TradePlan, ...] = ()
    portfolio_decision: PortfolioHeatResult


ContextBuilder = Callable[[InstrumentSnapshot], SetupContext]
RegimeSupplier = Callable[[object], MarketRegime | None]
SectorSupplier = Callable[[object], Sequence[SectorScore]]
UniverseRecordBuilder = Callable[[InstrumentSnapshot, object], UniverseRecord]


@dataclass
class MorningAlphaService:
    provider: MarketDataProvider
    detectors: Sequence[SetupDetector]
    context_builder: ContextBuilder
    config: MorningAlphaConfig = MorningAlphaConfig()
    journal: SignalJournal = InMemorySignalJournal()
    regime_supplier: RegimeSupplier | None = None
    sector_supplier: SectorSupplier | None = None
    universe_record_builder: UniverseRecordBuilder | None = None

    def __post_init__(self) -> None:
        self.trade_constructor = TradeConstructor(self.config)
        self.heat_engine = PortfolioHeatEngine(self.config)

    def _universe_record(self, snapshot: InstrumentSnapshot, as_of) -> UniverseRecord:
        if self.universe_record_builder:
            return self.universe_record_builder(snapshot, as_of)
        bars = self.provider.bars(snapshot.symbol, as_of=as_of, limit=1)
        market_timestamp = bars[-1].timestamp if bars else snapshot.ingested_at
        return UniverseRecord(
            symbol=snapshot.symbol,
            price=snapshot.price,
            avg_daily_shares_20d=snapshot.avg_daily_shares_20d or 0.0,
            avg_dollar_volume_20d=snapshot.avg_dollar_volume_20d or 0.0,
            is_leveraged_etf=False,
            effective_from=market_timestamp,
            market_timestamp=market_timestamp,
        )

    def scan(self, *, as_of, symbols: Sequence[str]) -> ScanResult:
        regime = self.regime_supplier(as_of) if self.regime_supplier else None
        sectors = tuple(self.sector_supplier(as_of)) if self.sector_supplier else ()
        sector_rank = {row.symbol: row.rank for row in sectors}

        eligible_count = 0
        candidates: list[SetupCandidate] = []
        plans: list[tuple[SetupCandidate, TradePlan]] = []
        rejections: list[ScanRejection] = []

        for symbol in symbols:
            try:
                snapshot = self.provider.instrument_snapshot(symbol, as_of=as_of)
            except KeyError:
                rejections.append(
                    ScanRejection(symbol=symbol, stage="data", reason="missing_snapshot")
                )
                continue

            decision = evaluate_eligibility(
                self._universe_record(snapshot, as_of), as_of=as_of, config=self.config
            )
            if not decision.eligible:
                rejections.append(
                    ScanRejection(symbol=symbol, stage="universe", reason=decision.reason.value)
                )
                continue
            eligible_count += 1

            context = self.context_builder(snapshot)
            if snapshot.sector and snapshot.sector in sector_rank and hasattr(context, "sector_rank"):
                context = context.model_copy(update={"sector_rank": sector_rank[snapshot.sector]})

            for detector in self.detectors:
                candidate = detector.evaluate(snapshot, context)
                if candidate is None:
                    continue
                candidates.append(candidate)
                candidate_id = self.journal.append_candidate(
                    candidate,
                    recorded_at=as_of,
                    provider_lineage={"market_data_source": snapshot.source},
                )
                built = self.trade_constructor.build(
                    candidate, account_equity=self.config.account_equity
                )
                if isinstance(built, TradeRejection):
                    self.journal.append_rejection(candidate_id, built, recorded_at=as_of)
                    rejections.append(
                        ScanRejection(
                            symbol=symbol,
                            stage="trade_construction",
                            reason=built.reason.value,
                        )
                    )
                    continue
                self.journal.append_plan(candidate_id, built, recorded_at=as_of)
                plans.append((candidate, built))

        selected: list[TradePlan] = []
        for _, plan in sorted(plans, key=lambda item: (-item[1].expected_r, item[1].symbol)):
            trial = selected + [plan]
            decision = self.heat_engine.evaluate(trial)
            if decision.accepted:
                selected.append(plan)
            else:
                rejections.append(
                    ScanRejection(
                        symbol=plan.symbol,
                        stage="portfolio_heat",
                        reason="; ".join(v.reason.value for v in decision.violations),
                    )
                )

        portfolio_decision = self.heat_engine.evaluate(selected)
        status = ScanStatus.QUALIFIED if selected else ScanStatus.NO_TRADE
        return ScanResult(
            as_of=as_of,
            status=status,
            regime=regime,
            sector_scores=sectors,
            eligible_count=eligible_count,
            candidate_count=len(candidates),
            candidates=tuple(candidates),
            rejections=tuple(rejections),
            qualified_plans=tuple(selected),
            portfolio_decision=portfolio_decision,
        )

from datetime import UTC, datetime, timedelta

from morning_alpha.models import MarketBar, Session, SetupCandidate, StrategyKey
from morning_alpha.providers import FakeMarketDataProvider, ParquetHistoricalProvider
from morning_alpha.service import MorningAlphaService, ScanStatus

AS_OF = datetime(2026, 9, 15, 13, 0, tzinfo=UTC)


def bars():
    rows = []
    for i in range(20):
        ts = AS_OF - timedelta(days=19 - i)
        price = 100 + i * 0.5
        rows.append(
            MarketBar(
                symbol="XYZ",
                timestamp=ts,
                open=price - 0.2,
                high=price + 0.4,
                low=price - 0.5,
                close=price,
                volume=1_000_000,
                session=Session.RTH,
                source="fixture",
                ingested_at=ts,
            )
        )
    return rows


class Detector:
    strategy = StrategyKey(strategy_id="parity", version="1.0.0")

    def evaluate(self, snapshot, context):
        return SetupCandidate(
            symbol=snapshot.symbol,
            strategy=self.strategy,
            as_of=snapshot.as_of,
            side="long",
            setup_type="parity",
            thesis_code="P",
            proposed_entry=context.entry,
            proposed_stop=context.stop,
            sector=snapshot.sector,
            theme="parity",
        )

    def explain_features(self, snapshot, context):
        return {}


class Context:
    def __init__(self, entry, stop):
        self.entry = entry
        self.stop = stop


def context_builder(snapshot):
    return Context(entry=snapshot.price + 0.5, stop=snapshot.price - 1.5)


class FakeCursorResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class FakeConnection:
    def __init__(self, source_rows):
        self.source_rows = source_rows

    def execute(self, sql, params):
        if "SELECT DISTINCT symbol" in sql:
            return FakeCursorResult([("XYZ",)])
        _, symbol, as_of, limit = params
        eligible = [b for b in self.source_rows if b.symbol == symbol and b.timestamp <= as_of]
        eligible = sorted(eligible, key=lambda b: b.timestamp, reverse=True)[:limit]
        return FakeCursorResult(
            [
                (
                    b.symbol,
                    b.timestamp,
                    b.open,
                    b.high,
                    b.low,
                    b.close,
                    b.volume,
                    b.session.value,
                    b.source,
                    b.ingested_at,
                )
                for b in eligible
            ]
        )


def make_services():
    source = bars()
    fake = FakeMarketDataProvider({"XYZ": source})
    hist = ParquetHistoricalProvider(
        data_dir="/unused", connection_factory=lambda: FakeConnection(source)
    )
    kwargs = dict(detectors=[Detector()], context_builder=context_builder)
    return MorningAlphaService(provider=fake, **kwargs), MorningAlphaService(
        provider=hist, **kwargs
    )


def test_live_and_historical_provider_paths_produce_identical_candidate_and_plan():
    live, historical = make_services()
    a = live.scan(as_of=AS_OF, symbols=["XYZ"])
    b = historical.scan(as_of=AS_OF, symbols=["XYZ"])
    assert a.status is ScanStatus.QUALIFIED
    assert b.status is ScanStatus.QUALIFIED
    assert [x.model_dump(mode="json") for x in a.candidates] == [
        x.model_dump(mode="json") for x in b.candidates
    ]
    assert [x.model_dump(mode="json") for x in a.qualified_plans] == [
        x.model_dump(mode="json") for x in b.qualified_plans
    ]


def test_no_trade_is_success_not_exception():
    source = bars()
    service = MorningAlphaService(
        provider=FakeMarketDataProvider({"XYZ": source}),
        detectors=[],
        context_builder=context_builder,
    )
    result = service.scan(as_of=AS_OF, symbols=["XYZ"])
    assert result.status is ScanStatus.NO_TRADE
    assert result.qualified_plans == ()


def test_heat_gate_can_reduce_multiple_valid_plans_deterministically():
    source = bars()
    service = MorningAlphaService(
        provider=FakeMarketDataProvider({"XYZ": source}),
        detectors=[Detector(), Detector()],
        context_builder=context_builder,
    )
    result = service.scan(as_of=AS_OF, symbols=["XYZ"])
    assert len(result.candidates) == 2
    assert result.portfolio_decision.accepted is True

from datetime import UTC, datetime, timedelta

from morning_alpha.audit import OutcomeAuditor
from morning_alpha.models import MarketBar, Session, SetupCandidate, StrategyKey
from morning_alpha.providers import FakeMarketDataProvider, ParquetHistoricalProvider
from morning_alpha.service import MorningAlphaService

AS_OF = datetime(2026, 9, 15, 13, 0, tzinfo=UTC)


class Detector:
    strategy = StrategyKey(strategy_id="golden", version="1.0.0")

    def evaluate(self, snapshot, context):
        return SetupCandidate(
            symbol=snapshot.symbol,
            strategy=self.strategy,
            as_of=snapshot.as_of,
            side="long",
            setup_type="golden",
            thesis_code="G",
            proposed_entry=snapshot.price + 1,
            proposed_stop=snapshot.price - 1,
            theme="golden",
        )

    def explain_features(self, snapshot, context):
        return {}


class Context:
    pass


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class Conn:
    def __init__(self, source):
        self.source = source

    def execute(self, sql, params):
        if "DISTINCT symbol" in sql:
            return Result([("XYZ",)])
        _, symbol, as_of, limit = params
        xs = sorted(
            [b for b in self.source if b.symbol == symbol and b.timestamp <= as_of],
            key=lambda b: b.timestamp,
            reverse=True,
        )[:limit]
        return Result(
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
                for b in xs
            ]
        )


def source_bars():
    xs = []
    for i in range(20):
        ts = AS_OF - timedelta(days=19 - i)
        p = 100 + i * 0.5
        xs.append(
            MarketBar(
                symbol="XYZ",
                timestamp=ts,
                open=p,
                high=p + 0.5,
                low=p - 0.5,
                close=p,
                volume=1_000_000,
                session=Session.RTH,
                source="golden",
                ingested_at=ts,
            )
        )
    return xs


def test_golden_replay_is_deterministic_and_provider_parity_safe():
    source = source_bars()
    fake = FakeMarketDataProvider({"XYZ": source})
    historical = ParquetHistoricalProvider(
        data_dir="/unused", connection_factory=lambda: Conn(source)
    )
    kwargs = dict(detectors=[Detector()], context_builder=lambda snapshot: Context())
    a = MorningAlphaService(provider=fake, **kwargs).scan(as_of=AS_OF, symbols=["XYZ"])
    b = MorningAlphaService(provider=historical, **kwargs).scan(as_of=AS_OF, symbols=["XYZ"])
    assert a.model_dump(mode="json")["qualified_plans"] == b.model_dump(mode="json")[
        "qualified_plans"
    ]
    assert a.model_dump(mode="json")["candidates"] == b.model_dump(mode="json")["candidates"]

    plan = a.qualified_plans[0]
    next_bar = MarketBar(
        symbol="XYZ",
        timestamp=AS_OF + timedelta(minutes=1),
        open=plan.entry,
        high=plan.entry + 3 * plan.risk_per_share,
        low=plan.entry - 0.25 * plan.risk_per_share,
        close=plan.entry + 2.5 * plan.risk_per_share,
        volume=2_000_000,
        session=Session.RTH,
        source="golden",
        ingested_at=AS_OF + timedelta(minutes=1),
    )
    outcome = OutcomeAuditor().audit(plan, [next_bar])
    assert outcome.mfe_r == 3
    assert outcome.mae_r == -0.25
    assert outcome.reached_2r is True

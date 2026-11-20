from datetime import UTC, datetime, timedelta

from morning_alpha.config import MorningAlphaConfig
from morning_alpha.models import MarketBar, Session
from morning_alpha.research.campaign import DataReadinessReport
from morning_alpha.research.feature_builder import HistoricalFeatureBuilder
from morning_alpha.research.population import HistoricalCandidatePopulationBuilder, HistoricalUniverseMember
from morning_alpha.setups.relative_strength_breakout import RelativeStrengthBreakout


def _bars(symbol, start, count, *, base, slope, volume=1_500_000):
    rows = []
    day = start
    i = 0
    while len(rows) < count:
        if day.weekday() < 5:
            close = base + i * slope
            rows.append(MarketBar(symbol=symbol,timestamp=day.replace(hour=20),open=close - 0.2,high=close + 0.6,low=close - 0.6,close=close,volume=volume,session=Session.RTH,source="fixture",ingested_at=day.replace(hour=20, minute=1)))
            i += 1
        day += timedelta(days=1)
    return rows


def _fixture():
    start = datetime(2023, 6, 1, tzinfo=UTC)
    spy = _bars("SPY", start, 252, base=400, slope=0.25)
    xlk = _bars("XLK", start, 252, base=180, slope=0.30)
    decision = spy[-1].timestamp.replace(hour=13) + timedelta(days=1)
    while decision.weekday() >= 5:
        decision += timedelta(days=1)
    ready = DataReadinessReport(ready=True,file_stage_ready=True,manifest_present=True,root="fixture",file_count=1,symbols=("AAA",),reasons=())
    return start, spy, xlk, decision, ready


def _member(stable_id, symbol, decision, **overrides):
    data = dict(stable_security_id=stable_id,symbol=symbol,sector="Technology",sector_etf="XLK",listing_timestamp=decision - timedelta(days=1000),delisting_timestamp=None)
    data.update(overrides)
    return HistoricalUniverseMember(**data)


def test_population_builder_filters_future_listing_and_post_delisting_membership():
    start, spy, xlk, decision, ready = _fixture()
    active = _member("SEC-A", "AAA", decision)
    future = _member("SEC-F", "FFF", decision, listing_timestamp=decision + timedelta(days=1))
    delisted = _member("SEC-D", "DDD", decision, delisting_timestamp=decision - timedelta(days=1))
    result = HistoricalCandidatePopulationBuilder().build_session(readiness=ready,campaign_id="morning_alpha_v1",decision_timestamp=decision,data_manifest_hash="d" * 64,universe=(active, future, delisted),bars_by_symbol={"AAA": _bars("AAA", start, 252, base=100, slope=0.55)},spy_bars=spy,sector_bars_by_etf={"XLK": xlk})
    assert result.input_universe_count == 1
    assert {o.stable_security_id for o in result.observations} == {"SEC-A"}


def test_population_builder_uses_exact_detector_output():
    start, spy, xlk, decision, ready = _fixture()
    member = _member("SEC-A", "AAA", decision)
    stock = _bars("AAA", start, 252, base=100, slope=0.65)
    feature = HistoricalFeatureBuilder().build(stable_security_id="SEC-A",symbol="AAA",sector="Technology",sector_etf="XLK",decision_timestamp=decision,data_manifest_hash="d" * 64,stock_bars=stock,spy_bars=spy,sector_bars=xlk)
    direct = RelativeStrengthBreakout().evaluate(feature.to_instrument_snapshot(), feature.to_setup_context())
    result = HistoricalCandidatePopulationBuilder().build_session(readiness=ready,campaign_id="morning_alpha_v1",decision_timestamp=decision,data_manifest_hash="d" * 64,universe=(member,),bars_by_symbol={"AAA": stock},spy_bars=spy,sector_bars_by_etf={"XLK": xlk})
    assert direct is not None
    assert result.observations[0].detector_candidate is not None
    assert result.observations[0].detector_candidate.model_dump(mode="json") == direct.model_dump(mode="json")


def test_population_builder_rejection_accounting_reconciles_exactly():
    start, spy, xlk, decision, ready = _fixture()
    universe = (_member("SEC-Q", "QUAL", decision),_member("SEC-L", "LOWVOL", decision),_member("SEC-H", "SHORT", decision),_member("SEC-R", "REJECT", decision))
    bars = {"QUAL": _bars("QUAL", start, 252, base=100, slope=0.70),"LOWVOL": _bars("LOWVOL", start, 252, base=100, slope=0.70, volume=1_000),"SHORT": _bars("SHORT", start, 100, base=100, slope=0.70),"REJECT": _bars("REJECT", start, 252, base=100, slope=0.10)}
    result = HistoricalCandidatePopulationBuilder(config=MorningAlphaConfig()).build_session(readiness=ready,campaign_id="morning_alpha_v1",decision_timestamp=decision,data_manifest_hash="d" * 64,universe=universe,bars_by_symbol=bars,spy_bars=spy,sector_bars_by_etf={"XLK": xlk})
    assert result.input_universe_count == 4
    assert result.qualified_count == 1
    assert result.rejected_count == 3
    assert result.rejection_counts == {"LIQUIDITY_REJECTED": 1,"INSUFFICIENT_HISTORY": 1,"DETECTOR_REJECTED": 1}
    assert sum(result.rejection_counts.values()) + result.qualified_count == result.input_universe_count


def test_population_builder_is_deterministic_for_unchanged_inputs():
    start, spy, xlk, decision, ready = _fixture()
    member = _member("SEC-A", "AAA", decision)
    kwargs = dict(readiness=ready,campaign_id="morning_alpha_v1",decision_timestamp=decision,data_manifest_hash="d" * 64,universe=(member,),bars_by_symbol={"AAA": _bars("AAA", start, 252, base=100, slope=0.65)},spy_bars=spy,sector_bars_by_etf={"XLK": xlk})
    builder = HistoricalCandidatePopulationBuilder()
    first = builder.build_session(**kwargs)
    second = builder.build_session(**kwargs)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")

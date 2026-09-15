from datetime import UTC, datetime, timedelta

import pytest

from morning_alpha.models import InstrumentSnapshot, MarketBar, Session, SetupCandidate, StrategyKey
from morning_alpha.research import (
    DEFAULT_TRIGGERS,
    HistoricalSimulator,
    TriggerDefinition,
    TriggerKind,
    TriggerLab,
    bars_at_or_before,
    compute_strategy_metrics,
)

AS_OF = datetime(2026, 9, 15, 13, 0, tzinfo=UTC)
RTH_OPEN = datetime(2026, 9, 15, 13, 30, tzinfo=UTC)


def bar(ts, o, h, l, c, volume=1000, session=Session.RTH):
    return MarketBar(
        symbol="XYZ",
        timestamp=ts,
        open=o,
        high=h,
        low=l,
        close=c,
        volume=volume,
        session=session,
        source="fixture",
        ingested_at=ts,
    )


def candidate():
    return SetupCandidate(
        symbol="XYZ",
        strategy=StrategyKey(strategy_id="test", version="1.0.0"),
        as_of=AS_OF,
        side="long",
        setup_type="test",
        thesis_code="T",
        proposed_entry=100,
        proposed_stop=98,
        sector="XLK",
    )


def test_all_eight_trigger_variants_are_versioned():
    assert len(DEFAULT_TRIGGERS) == 8
    assert {x.kind for x in DEFAULT_TRIGGERS} == set(TriggerKind)
    assert all(x.version == "1.0.0" for x in DEFAULT_TRIGGERS)


def test_orb_5m_is_not_active_during_formation_window():
    bars = [
        bar(
            RTH_OPEN + timedelta(minutes=i),
            99 + i / 10,
            100 + i / 10,
            98.5,
            99.5 + i / 10,
        )
        for i in range(7)
    ]
    signal = TriggerLab().signal(TriggerDefinition(TriggerKind.ORB_5M), bars)
    assert signal is not None
    assert signal.active_from_timestamp == RTH_OPEN + timedelta(minutes=5)
    assert signal.entry == pytest.approx(max(x.high for x in bars[:5]))


def test_premarket_high_uses_only_premarket_bars():
    bars = [
        bar(RTH_OPEN - timedelta(minutes=10), 97, 99, 96, 98, session=Session.PREMARKET),
        bar(RTH_OPEN - timedelta(minutes=5), 98, 101, 98, 100, session=Session.PREMARKET),
        bar(RTH_OPEN, 100, 105, 99, 104),
    ]
    signal = TriggerLab().signal(TriggerDefinition(TriggerKind.PREMARKET_HIGH), bars)
    assert signal is not None
    assert signal.entry == 101


def test_breakout_retest_requires_break_then_hold_retest():
    bars = [
        bar(RTH_OPEN, 99, 101, 99, 100.5),
        bar(RTH_OPEN + timedelta(minutes=1), 100.5, 101.2, 99.8, 100.2),
    ]
    signal = TriggerLab().signal(
        TriggerDefinition(TriggerKind.BREAKOUT_RETEST), bars, prior_day_high=100
    )
    assert signal is not None
    assert signal.active_from_index == 1
    assert signal.entry == 100


def test_future_bar_is_excluded_from_historical_feature_window():
    today = bar(AS_OF - timedelta(minutes=1), 99, 100, 98, 99)
    tomorrow = bar(AS_OF + timedelta(days=1), 99, 500, 98, 400)
    base = bars_at_or_before([today], AS_OF)
    with_future = bars_at_or_before([today, tomorrow], AS_OF)
    assert [b.high for b in base] == [100]
    assert [b.high for b in with_future] == [100]


def test_trigger_lab_reuses_trade_constructor_and_auditor():
    bars = [
        bar(RTH_OPEN, 99, 100.5, 99, 100.2),
        bar(RTH_OPEN + timedelta(minutes=1), 100.2, 104.2, 99.5, 103.8),
    ]
    plan, outcome = TriggerLab().evaluate(
        candidate(),
        bars,
        TriggerDefinition(TriggerKind.PRIOR_DAY_HIGH),
        prior_day_high=100,
        account_equity=3000,
    )
    assert plan is not None
    assert outcome is not None
    assert outcome.reached_2r is True


def test_metrics_include_cost_sensitivity():
    bars = [
        bar(RTH_OPEN, 99, 100.5, 99, 100.2),
        bar(RTH_OPEN + timedelta(minutes=1), 100.2, 104.2, 99.5, 103.8),
    ]
    plan, outcome = TriggerLab().evaluate(
        candidate(),
        bars,
        TriggerDefinition(TriggerKind.PRIOR_DAY_HIGH),
        prior_day_high=100,
        account_equity=3000,
    )
    metrics = compute_strategy_metrics([outcome], [plan])
    assert metrics.n == 1
    assert metrics.expectancy_r is not None
    assert set(metrics.cost_sensitivity_r) == {0, 2, 5, 10, 20}
    assert metrics.cost_sensitivity_r[20] < metrics.cost_sensitivity_r[0]


def test_historical_simulator_rejects_naive_snapshot_time():
    snap = InstrumentSnapshot(
        symbol="XYZ",
        as_of=datetime(2026, 9, 15, 13, 0),
        price=100,
        source="fixture",
        ingested_at=AS_OF,
    )

    class Detector:
        strategy = StrategyKey(strategy_id="x", version="1")

        def evaluate(self, snapshot, context):
            return None

        def explain_features(self, snapshot, context):
            return {}

    class Context:
        catalyst = None
        catalysts = ()

    with pytest.raises(ValueError, match="timezone-aware"):
        HistoricalSimulator().detect(Detector(), snap, Context())

from datetime import UTC, datetime, timedelta

import pytest

from morning_alpha.models import MarketBar, Session, StrategyKey, TradePlan
from morning_alpha.research.excursions import ExcursionEngine, ExcursionHorizon

ENTRY_TS = datetime(2026, 9, 15, 14, 0, tzinfo=UTC)


def plan(side: str = "long") -> TradePlan:
    if side == "long":
        entry, stop = 100.0, 98.0
        targets = (102.0, 104.0, 106.0, 108.0)
    else:
        entry, stop = 100.0, 102.0
        targets = (98.0, 96.0, 94.0, 92.0)
    return TradePlan(
        symbol="XYZ",
        strategy=StrategyKey(strategy_id="relative_strength_breakout", version="1.0.0"),
        as_of=ENTRY_TS,
        side=side,
        entry=entry,
        stop=stop,
        targets=targets,
        risk_per_share=2.0,
        account_equity=3000,
        risk_fraction=0.005,
        shares=7,
        max_dollar_risk=14.0,
        expected_r=4.0,
    )


def bar(minutes: int, low: float, high: float, *, day_offset: int = 0) -> MarketBar:
    ts = ENTRY_TS + timedelta(days=day_offset, minutes=minutes)
    close = (low + high) / 2
    return MarketBar(
        symbol="XYZ",
        timestamp=ts,
        open=close,
        high=high,
        low=low,
        close=close,
        volume=1_000_000,
        session=Session.RTH,
        source="fixture",
        ingested_at=ts,
    )


def test_pre_entry_extremes_are_ignored():
    bars = [bar(-5, 50, 150), bar(5, 99, 101), bar(25, 98.5, 104)]
    curve = ExcursionEngine().measure(plan(), ENTRY_TS, bars, (ExcursionHorizon.MIN_30,))
    obs = curve.observations[0]

    assert obs.mfe_r == pytest.approx(2.0)
    assert obs.mae_r == pytest.approx(-0.75)


def test_future_bar_after_horizon_does_not_change_30m_excursion():
    base = [bar(5, 99, 101), bar(25, 98.5, 104)]
    extended = base + [bar(35, 60, 180)]
    engine = ExcursionEngine()

    first = engine.measure(plan(), ENTRY_TS, base, (ExcursionHorizon.MIN_30,))
    second = engine.measure(plan(), ENTRY_TS, extended, (ExcursionHorizon.MIN_30,))

    assert first == second


def test_short_side_excursion_math_is_symmetric():
    bars = [bar(10, 96, 101), bar(20, 94, 103)]
    obs = ExcursionEngine().measure(
        plan("short"), ENTRY_TS, bars, (ExcursionHorizon.MIN_30,)
    ).observations[0]

    assert obs.mfe_r == pytest.approx(3.0)
    assert obs.mae_r == pytest.approx(-1.5)


def test_eod_curve_uses_same_trading_date_only():
    bars = [bar(30, 99, 103), bar(180, 97, 106), bar(0, 80, 140, day_offset=1)]
    obs = ExcursionEngine().measure(plan(), ENTRY_TS, bars, (ExcursionHorizon.EOD,)).observations[0]

    assert obs.mfe_r == pytest.approx(3.0)
    assert obs.mae_r == pytest.approx(-1.5)
    assert obs.end_timestamp == ENTRY_TS + timedelta(minutes=180)


def test_day_1_curve_includes_entry_day_and_first_future_trading_day():
    bars = [
        bar(60, 99, 103),
        bar(0, 97, 106, day_offset=1),
        bar(180, 96, 108, day_offset=1),
        bar(180, 70, 150, day_offset=2),
    ]
    obs = ExcursionEngine().measure(plan(), ENTRY_TS, bars, (ExcursionHorizon.DAY_1,)).observations[0]

    assert obs.mfe_r == pytest.approx(4.0)
    assert obs.mae_r == pytest.approx(-2.0)
    assert obs.end_timestamp == ENTRY_TS + timedelta(days=1, minutes=180)


def test_missing_horizon_is_explicitly_unavailable():
    obs = ExcursionEngine().measure(plan(), ENTRY_TS, [], (ExcursionHorizon.MIN_60,)).observations[0]
    assert obs.available is False
    assert obs.mfe_r is None
    assert obs.mae_r is None
    assert obs.reason == "NO_ELIGIBLE_BARS"

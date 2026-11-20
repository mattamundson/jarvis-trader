from datetime import UTC, datetime, timedelta

import pytest

from morning_alpha.models import MarketBar, Session
from morning_alpha.research.forward_returns import ForwardHorizon, ForwardReturnEngine

DECISION = datetime(2026, 9, 15, 14, 0, tzinfo=UTC)


def bar(minutes: int, close: float, *, day_offset: int = 0) -> MarketBar:
    ts = DECISION + timedelta(days=day_offset, minutes=minutes)
    return MarketBar(
        symbol="XYZ",
        timestamp=ts,
        open=close - 0.2,
        high=close + 0.4,
        low=close - 0.4,
        close=close,
        volume=1_000_000,
        session=Session.RTH,
        source="fixture",
        ingested_at=ts,
    )


def test_30_minute_horizon_uses_latest_bar_at_or_before_boundary_only():
    bars = [bar(5, 101), bar(25, 103), bar(35, 150)]
    obs = ForwardReturnEngine().measure(
        "XYZ", DECISION, 100.0, bars, (ForwardHorizon.MIN_30,)
    )[0]

    assert obs.available is True
    assert obs.end_timestamp == DECISION + timedelta(minutes=25)
    assert obs.end_price == 103
    assert obs.simple_return == pytest.approx(0.03)


def test_adding_future_rows_does_not_change_earlier_horizon():
    base = [bar(5, 101), bar(25, 103)]
    extended = base + [bar(180, 500), bar(0, 900, day_offset=1)]
    engine = ForwardReturnEngine()

    first = engine.measure("XYZ", DECISION, 100.0, base, (ForwardHorizon.MIN_30,))[0]
    second = engine.measure("XYZ", DECISION, 100.0, extended, (ForwardHorizon.MIN_30,))[0]

    assert first == second


def test_eod_uses_last_same_session_date_bar():
    bars = [bar(30, 101), bar(120, 104), bar(0, 120, day_offset=1)]
    obs = ForwardReturnEngine().measure(
        "XYZ", DECISION, 100.0, bars, (ForwardHorizon.EOD,)
    )[0]

    assert obs.end_timestamp == DECISION + timedelta(minutes=120)
    assert obs.simple_return == pytest.approx(0.04)


def test_day_1_uses_last_bar_of_next_distinct_trading_date():
    bars = [
        bar(60, 101),
        bar(0, 102, day_offset=1),
        bar(240, 106, day_offset=1),
        bar(240, 130, day_offset=2),
    ]
    obs = ForwardReturnEngine().measure(
        "XYZ", DECISION, 100.0, bars, (ForwardHorizon.DAY_1,)
    )[0]

    assert obs.end_timestamp == DECISION + timedelta(days=1, minutes=240)
    assert obs.end_price == 106


def test_day_2_uses_second_future_trading_date_not_calendar_interpolation():
    bars = [
        bar(0, 103, day_offset=1),
        bar(180, 104, day_offset=1),
        bar(0, 107, day_offset=3),
        bar(180, 109, day_offset=3),
    ]
    obs = ForwardReturnEngine().measure(
        "XYZ", DECISION, 100.0, bars, (ForwardHorizon.DAY_2,)
    )[0]

    assert obs.end_timestamp == DECISION + timedelta(days=3, minutes=180)
    assert obs.end_price == 109


def test_missing_endpoint_is_explicitly_unavailable():
    obs = ForwardReturnEngine().measure(
        "XYZ", DECISION, 100.0, [], (ForwardHorizon.MIN_60,)
    )[0]

    assert obs.available is False
    assert obs.end_timestamp is None
    assert obs.simple_return is None
    assert obs.reason == "NO_ELIGIBLE_ENDPOINT"


def test_bars_at_or_before_decision_are_not_forward_endpoints():
    before = bar(-5, 999)
    obs = ForwardReturnEngine().measure(
        "XYZ", DECISION, 100.0, [before], (ForwardHorizon.MIN_30,)
    )[0]
    assert obs.available is False

from datetime import UTC, datetime

import pytest

from morning_alpha.regime import MarketRegimeEngine, RegimeInputs

AS_OF = datetime(2026, 9, 15, 13, 0, tzinfo=UTC)


def inputs(**overrides):
    values = dict(
        as_of=AS_OF,
        spy_close=110,
        spy_ema8=108,
        spy_ema21=105,
        spy_ema34=100,
        qqq_close=210,
        qqq_ema8=208,
        qqq_ema21=205,
        qqq_ema34=200,
        iwm_return_20d=0.04,
        spy_return_20d=0.03,
        vix=16,
        breadth_score=0.3,
        ten_year_yield_change_5d=-0.05,
        crude_return_5d=0.02,
        scheduled_event_risk=False,
    )
    values.update(overrides)
    return RegimeInputs(**values)


def test_trending_bull_regime():
    result = MarketRegimeEngine().evaluate(inputs())
    assert result.spy_trend == "TRENDING_BULL"
    assert result.risk_state == "TRENDING_BULL"
    assert result.iwm_relative_strength == pytest.approx(0.01)


def test_risk_off_regime_from_bearish_index_alignment():
    result = MarketRegimeEngine().evaluate(
        inputs(
            spy_close=90,
            spy_ema8=92,
            spy_ema21=95,
            spy_ema34=100,
            qqq_close=180,
            qqq_ema8=185,
            qqq_ema21=190,
            qqq_ema34=200,
            breadth_score=-0.4,
        )
    )
    assert result.spy_trend == "TRENDING_BEAR"
    assert result.qqq_trend == "TRENDING_BEAR"
    assert result.risk_state == "RISK_OFF"


def test_trending_bear_is_distinct_from_risk_off():
    result = MarketRegimeEngine().evaluate(
        inputs(
            spy_close=90,
            spy_ema8=92,
            spy_ema21=95,
            spy_ema34=100,
            qqq_close=180,
            qqq_ema8=185,
            qqq_ema21=190,
            qqq_ema34=200,
            breadth_score=-0.1,
        )
    )
    assert result.risk_state == "TRENDING_BEAR"


def test_volatile_regime_overrides_trend():
    result = MarketRegimeEngine().evaluate(inputs(vix=35))
    assert result.vix_bucket == "CRISIS"
    assert result.risk_state == "VOLATILE"


def test_event_risk_has_highest_precedence():
    result = MarketRegimeEngine().evaluate(inputs(vix=35, scheduled_event_risk=True))
    assert result.scheduled_event_risk is True
    assert result.risk_state == "EVENT_RISK"

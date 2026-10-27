from datetime import UTC, datetime, timedelta

from morning_alpha.config import MorningAlphaConfig
from morning_alpha.universe.eligibility import (
    EligibilityReason,
    UniverseRecord,
    evaluate_eligibility,
)

AS_OF = datetime(2026, 9, 15, 13, 0, tzinfo=UTC)


def record(**overrides):
    values = dict(
        symbol="XYZ",
        price=50.0,
        avg_daily_shares_20d=1_000_000,
        avg_dollar_volume_20d=75_000_000.0,
        is_leveraged_etf=False,
        effective_from=AS_OF - timedelta(days=365),
        effective_to=None,
        market_timestamp=AS_OF - timedelta(minutes=1),
    )
    values.update(overrides)
    return UniverseRecord(**values)


def test_eligible_record_is_accepted():
    decision = evaluate_eligibility(record(), as_of=AS_OF, config=MorningAlphaConfig())
    assert decision.eligible is True
    assert decision.reason is EligibilityReason.ELIGIBLE


def test_price_floor_rejection_is_explicit():
    decision = evaluate_eligibility(record(price=9.99), as_of=AS_OF, config=MorningAlphaConfig())
    assert decision.reason is EligibilityReason.PRICE_TOO_LOW


def test_adv_floor_rejection_is_explicit():
    decision = evaluate_eligibility(record(avg_daily_shares_20d=749_999), as_of=AS_OF, config=MorningAlphaConfig())
    assert decision.reason is EligibilityReason.ADV_TOO_LOW


def test_dollar_volume_floor_rejection_is_explicit():
    decision = evaluate_eligibility(record(avg_dollar_volume_20d=49_999_999), as_of=AS_OF, config=MorningAlphaConfig())
    assert decision.reason is EligibilityReason.DOLLAR_VOLUME_TOO_LOW


def test_leveraged_etf_is_rejected():
    decision = evaluate_eligibility(record(is_leveraged_etf=True), as_of=AS_OF, config=MorningAlphaConfig())
    assert decision.reason is EligibilityReason.LEVERAGED_ETF


def test_stale_market_record_is_rejected():
    decision = evaluate_eligibility(
        record(market_timestamp=AS_OF - timedelta(days=3)),
        as_of=AS_OF,
        config=MorningAlphaConfig(),
        max_staleness=timedelta(days=1),
    )
    assert decision.reason is EligibilityReason.STALE


def test_future_market_timestamp_is_rejected_as_point_in_time_violation():
    decision = evaluate_eligibility(
        record(market_timestamp=AS_OF + timedelta(seconds=1)),
        as_of=AS_OF,
        config=MorningAlphaConfig(),
    )
    assert decision.reason is EligibilityReason.FUTURE_DATA


def test_inactive_historical_membership_is_rejected():
    decision = evaluate_eligibility(
        record(effective_to=AS_OF),
        as_of=AS_OF,
        config=MorningAlphaConfig(),
    )
    assert decision.reason is EligibilityReason.NOT_ACTIVE_AS_OF

from datetime import UTC, datetime

import pytest

from morning_alpha.models import SetupCandidate, StrategyKey, TradePlan
from morning_alpha.risk import TradeConstructor, TradeRejection, TradeRejectionReason

AS_OF = datetime(2026, 9, 15, 13, 0, tzinfo=UTC)


def candidate(entry=100.0, stop=98.0, *, obstacle=None, side="long"):
    return SetupCandidate(
        symbol="XYZ",
        strategy=StrategyKey(strategy_id="relative_strength_breakout", version="1.0.0"),
        as_of=AS_OF,
        side=side,
        setup_type="relative_strength_breakout",
        thesis_code="RSB_V1",
        proposed_entry=entry,
        proposed_stop=stop,
        nearby_obstacle=obstacle,
        sector="XLK",
        theme="ai_infrastructure",
    )


def test_3000_account_at_half_percent_risk_sizes_integer_shares():
    result = TradeConstructor().build(candidate(), account_equity=3000)
    assert isinstance(result, TradePlan)
    assert result.shares == 7
    assert result.max_dollar_risk == 14.0
    assert result.risk_fraction == 0.005


def test_requested_risk_is_capped_at_one_percent():
    result = TradeConstructor().build(
        candidate(), account_equity=3000, requested_risk_fraction=0.02
    )
    assert isinstance(result, TradePlan)
    assert result.risk_fraction == 0.01
    assert result.shares == 15
    assert result.max_dollar_risk == 30.0


def test_capital_constraint_can_reduce_risk_sizing():
    result = TradeConstructor().build(candidate(entry=1000, stop=999), account_equity=3000)
    assert isinstance(result, TradePlan)
    assert result.shares == 3
    assert result.max_dollar_risk == 3


def test_zero_share_is_rejected():
    result = TradeConstructor().build(candidate(entry=3000, stop=2900), account_equity=3000)
    assert isinstance(result, TradeRejection)
    assert result.reason is TradeRejectionReason.ZERO_SHARES


def test_nearby_resistance_below_2r_rejects_trade():
    result = TradeConstructor().build(candidate(obstacle=103.0), account_equity=3000)
    assert isinstance(result, TradeRejection)
    assert result.reason is TradeRejectionReason.INSUFFICIENT_REWARD


def test_verified_obstacle_at_2r_is_accepted_and_caps_expected_r():
    result = TradeConstructor().build(candidate(), account_equity=3000, obstacles=[104.0])
    assert isinstance(result, TradePlan)
    assert result.expected_r == pytest.approx(2.0)
    assert result.targets == pytest.approx((102.0, 104.0, 106.0, 108.0))


def test_price_discovery_without_obstacle_allows_4r_ladder():
    result = TradeConstructor().build(candidate(obstacle=None), account_equity=3000)
    assert isinstance(result, TradePlan)
    assert result.expected_r == 4.0


def test_short_targets_and_obstacle_are_inverted():
    result = TradeConstructor().build(
        candidate(entry=100, stop=102, obstacle=None, side="short"),
        account_equity=3000,
        obstacles=[96],
    )
    assert isinstance(result, TradePlan)
    assert result.expected_r == 2.0
    assert result.targets == pytest.approx((98.0, 96.0, 94.0, 92.0))

from datetime import datetime, timedelta, timezone

from morning_alpha.research.execution_replay import (
    ExecutionIntent,
    ExecutionQuote,
    ExecutionReplayStatus,
    OrderSide,
    replay_execution,
)

TS = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)


def q(seconds, bid, ask, bid_size=1000, ask_size=1000):
    return ExecutionQuote(
        timestamp=TS + timedelta(seconds=seconds),
        bid=bid,
        ask=ask,
        bid_size=bid_size,
        ask_size=ask_size,
        source="fixture",
    )


def intent(**updates):
    base = dict(
        candidate_id="C1",
        side=OrderSide.BUY,
        quantity=100,
        trigger_timestamp=TS,
        reference_price=100.0,
        stop_price=99.0,
        risk_per_share=1.0,
        max_delay_seconds=60,
        max_participation_fraction=1.0,
        commission_per_share=0.01,
        impact_bps=0.0,
    )
    base.update(updates)
    return ExecutionIntent(**base)


def test_full_fill_crosses_ask_and_records_shortfall_spread_and_commission():
    result = replay_execution(intent(), (q(0, 99.9, 100.1),))
    assert result.status is ExecutionReplayStatus.FILLED
    assert result.filled_quantity == 100
    assert result.fill_ratio == 1.0
    assert result.average_entry_price == 100.1
    assert result.implementation_shortfall_per_share == 0.1
    assert result.commission_cost == 1.0
    assert result.spread_crossing_cost > 0


def test_partial_fill_is_capped_by_displayed_size_participation_and_remainder_is_explicit():
    i = intent(quantity=100, max_participation_fraction=0.5, max_delay_seconds=10)
    result = replay_execution(
        i,
        (
            q(0, 99.9, 100.1, ask_size=50),
            q(5, 99.95, 100.15, ask_size=50),
        ),
    )
    assert result.status is ExecutionReplayStatus.PARTIAL_FILL
    assert result.filled_quantity == 50
    assert result.unfilled_quantity == 50
    assert result.fill_ratio == 0.5


def test_delay_uses_first_quote_at_or_after_delayed_execution_time():
    result = replay_execution(
        intent(),
        (q(0, 99.9, 100.1), q(30, 100.4, 100.5)),
        delay_seconds=30,
    )
    assert result.average_entry_price == 100.5
    assert result.delay_seconds == 30
    assert result.implementation_shortfall_per_share == 0.5


def test_positive_impact_bps_worsens_entry_separately_from_spread():
    result = replay_execution(intent(impact_bps=10), (q(0, 99.9, 100.1),))
    assert result.average_entry_price > 100.1
    assert result.impact_cost > 0
    assert result.spread_crossing_cost > 0


def test_gap_through_stop_fills_at_first_executable_bid_not_stop_price():
    result = replay_execution(
        intent(),
        (q(0, 99.9, 100.1),),
        stop_quotes=(q(20, 98.5, 98.7),),
        stop_trigger_timestamp=TS + timedelta(seconds=20),
    )
    assert result.stop_fill_price == 98.5
    assert result.realized_r is not None
    assert result.realized_r < -1.0


def test_missing_quote_evidence_fails_closed():
    result = replay_execution(intent(), ())
    assert result.status is ExecutionReplayStatus.UNVERIFIED_EXECUTION
    assert result.average_entry_price is None
    assert result.realized_r is None


def test_quotes_outside_maximum_delay_do_not_receive_fantasy_fill():
    result = replay_execution(intent(max_delay_seconds=10), (q(30, 100.0, 100.2),))
    assert result.status is ExecutionReplayStatus.UNVERIFIED_EXECUTION
    assert result.filled_quantity == 0


def test_profitable_theoretical_target_can_become_non_positive_after_real_entry_and_exit():
    i = intent(target_price=101.0, max_delay_seconds=60)
    result = replay_execution(
        i,
        (q(30, 100.7, 100.8),),
        delay_seconds=30,
        exit_quotes=(q(40, 100.5, 100.7),),
        exit_trigger_timestamp=TS + timedelta(seconds=40),
    )
    assert result.theoretical_exit_r == 1.0
    assert result.realized_r is not None
    assert result.realized_r <= 0.0

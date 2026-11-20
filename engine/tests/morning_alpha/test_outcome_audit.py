from datetime import UTC, datetime, timedelta

import pytest

from morning_alpha.audit import OutcomeAuditor, ScorecardBuilder
from morning_alpha.models import MarketBar, OutcomeClassification, Session, StrategyKey, TradePlan

AS_OF = datetime(2026, 9, 15, 13, 0, tzinfo=UTC)


def plan(*, entry=100.0, stop=98.0, side="long") -> TradePlan:
    risk = abs(entry - stop)
    direction = 1 if side == "long" else -1
    return TradePlan(
        symbol="XYZ",
        strategy=StrategyKey(strategy_id="test", version="1.0.0"),
        as_of=AS_OF,
        side=side,
        entry=entry,
        stop=stop,
        targets=tuple(entry + direction * r * risk for r in (1, 2, 3, 4)),
        risk_per_share=risk,
        account_equity=3000,
        risk_fraction=0.005,
        shares=7,
        max_dollar_risk=7 * risk,
        expected_r=4.0,
    )


def bar(minutes, o, h, l, c):
    ts = AS_OF + timedelta(minutes=minutes)
    return MarketBar(
        symbol="XYZ",
        timestamp=ts,
        open=o,
        high=h,
        low=l,
        close=c,
        volume=1000,
        session=Session.RTH,
        source="fixture",
        ingested_at=ts,
    )


def test_trigger_never_fires_then_price_falls_is_filtered_loser():
    result = OutcomeAuditor().audit(plan(), [bar(1, 99, 99.5, 97, 97.5)])
    assert result.triggered is False
    assert result.classification is OutcomeClassification.FILTERED_LOSER


def test_trigger_never_fires_then_price_rallies_is_filtered_winner():
    result = OutcomeAuditor().audit(plan(), [bar(1, 95, 99.5, 94.5, 99)])
    assert result.triggered is False
    assert result.classification is OutcomeClassification.FILTERED_WINNER


def test_mfe_mae_begin_only_after_actual_trigger_bar():
    bars = [
        bar(1, 95, 99, 90, 98),
        bar(2, 99, 100.5, 99, 100.2),
        bar(3, 100.2, 103, 99.5, 102.5),
    ]
    result = OutcomeAuditor().audit(plan(), bars)
    assert result.triggered is True
    assert result.mae_r == pytest.approx(-0.5)
    assert result.mfe_r == pytest.approx(1.5)
    assert result.classification is OutcomeClassification.OPEN


def test_trigger_fires_then_later_stop_before_1r_is_loss():
    bars = [
        bar(1, 99.5, 100.5, 99.2, 100.1),
        bar(2, 100.1, 101, 97.5, 98),
    ]
    result = OutcomeAuditor().audit(plan(), bars)
    assert result.classification is OutcomeClassification.LOSS
    assert result.stop_hit is True
    assert result.reached_1r is False


def test_trigger_reaches_2r_without_stop_is_win():
    bars = [
        bar(1, 99.5, 100.5, 99.2, 100.1),
        bar(2, 100.1, 104.2, 99.5, 103.8),
    ]
    result = OutcomeAuditor().audit(plan(), bars)
    assert result.classification is OutcomeClassification.WIN
    assert result.reached_1r is True
    assert result.reached_2r is True
    assert result.stop_hit is False


def test_same_bar_stop_and_target_is_unverified():
    bars = [bar(1, 99.5, 104.5, 97.5, 101)]
    result = OutcomeAuditor().audit(plan(), bars)
    assert result.triggered is True
    assert result.classification is OutcomeClassification.UNVERIFIED
    assert result.stop_hit is None


def test_positive_close_below_1r_is_open_with_marked_close_r():
    bars = [
        bar(1, 99.5, 100.5, 99.2, 100.1),
        bar(2, 100.1, 101.5, 99.5, 101),
    ]
    result = OutcomeAuditor().audit(plan(), bars)
    assert result.classification is OutcomeClassification.OPEN
    assert result.close_r == pytest.approx(0.5)


def test_scorecard_counts_and_rates():
    auditor = OutcomeAuditor()
    outcomes = [
        auditor.audit(plan(), [bar(1, 99.5, 100.5, 99.2, 100.1), bar(2, 100.1, 104.2, 99.5, 103.8)]),
        auditor.audit(plan(), [bar(1, 99, 99.5, 97, 97.5)]),
        auditor.audit(plan(), [bar(1, 95, 99.5, 94.5, 99)]),
    ]
    score = ScorecardBuilder().build(outcomes)
    assert score.total_candidates == 3
    assert score.triggers_fired == 1
    assert score.wins == 1
    assert score.filtered_losers == 1
    assert score.filtered_winners == 1
    assert score.trigger_rate == pytest.approx(1 / 3)
    assert score.filter_protection_rate == pytest.approx(0.5)
    assert score.missed_opportunity_rate == pytest.approx(0.5)

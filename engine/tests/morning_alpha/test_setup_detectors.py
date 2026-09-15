from datetime import UTC, datetime, timedelta

import pytest

from morning_alpha.models import CatalystSnapshot, InstrumentSnapshot
from morning_alpha.setups import (
    GapContinuation,
    MomentumBreakout,
    PostEarningsDrift,
    PullbackContinuation,
    RelativeStrengthBreakout,
    SectorRotation,
    SetupContext,
)

NOW = datetime(2026, 9, 15, 13, 0, tzinfo=UTC)


def snapshot(price: float = 100.0) -> InstrumentSnapshot:
    return InstrumentSnapshot(
        symbol="XYZ",
        as_of=NOW,
        price=price,
        previous_close=98.0,
        avg_daily_shares_20d=1_000_000,
        avg_dollar_volume_20d=100_000_000,
        high_52w=101.0,
        sector="XLK",
        source="fixture",
        ingested_at=NOW,
    )


def test_all_detectors_are_versioned_and_deterministic_interfaces():
    detectors = [
        RelativeStrengthBreakout(),
        MomentumBreakout(),
        PullbackContinuation(),
        PostEarningsDrift(),
        SectorRotation(),
        GapContinuation(),
    ]
    for detector in detectors:
        assert detector.strategy.version == "1.0.0"
        assert callable(detector.evaluate)
        assert callable(detector.explain_features)


def test_relative_strength_qualifies_and_persists_features():
    context = SetupContext(
        returns_20d=0.20,
        spy_return_20d=0.05,
        sector_return_20d=0.08,
        sma20=95,
        sma50=90,
        atr14=2,
        prior_high=100.5,
        prior_low=96,
        high_252d=101,
    )
    result = RelativeStrengthBreakout().evaluate(snapshot(), context)
    assert result is not None
    assert result.proposed_entry == pytest.approx(100.56)
    assert result.features["beats_spy"] is True


def test_momentum_requires_top_quintile():
    context = SetupContext(
        return_percentile_20d=79,
        sma20=95,
        sma50=90,
        relative_volume=2,
        high_20d=101,
        prior_low=96,
        atr14=2,
    )
    detector = MomentumBreakout()
    assert detector.evaluate(snapshot(), context) is None
    assert detector.evaluate(snapshot(), context.model_copy(update={"return_percentile_20d": 80})) is not None


def test_pullback_requires_ema_zone_and_50sma_hold():
    context = SetupContext(
        sma20=96,
        sma50=90,
        ema8=98,
        ema21=96,
        atr14=2,
        pullback_low=96.5,
        prior_bar_high=99,
    )
    detector = PullbackContinuation()
    assert detector.evaluate(snapshot(), context) is not None
    assert detector.evaluate(snapshot(), context.model_copy(update={"pullback_low": 89})) is None


def test_pead_requires_verified_point_in_time_earnings_catalyst():
    catalyst = CatalystSnapshot(
        symbol="XYZ",
        as_of=NOW,
        catalyst_type="earnings",
        headline="earnings beat",
        published_at=NOW - timedelta(minutes=5),
        verified=True,
    )
    context = SetupContext(
        catalyst=catalyst,
        eps_surprise_pct=0.10,
        revenue_surprise_pct=0.05,
        gap_pct=0.08,
        gap_retention=0.80,
        relative_volume=2.0,
        prior_high=105,
        gap_low=99,
        atr14=2,
    )
    detector = PostEarningsDrift()
    assert detector.evaluate(snapshot(104), context) is not None
    bad = context.model_copy(update={"catalyst": catalyst.model_copy(update={"verified": False})})
    assert detector.evaluate(snapshot(104), bad) is None


def test_sector_rotation_requires_top_quartile_and_relative_strength():
    context = SetupContext(
        sector_rank=3,
        sector_count=11,
        returns_20d=0.20,
        spy_return_20d=0.05,
        sector_return_20d=0.10,
        sma20=95,
        sma50=90,
        prior_high=101,
        prior_low=96,
        atr14=2,
    )
    detector = SectorRotation()
    assert detector.evaluate(snapshot(), context) is not None
    assert detector.evaluate(snapshot(), context.model_copy(update={"sector_rank": 4})) is None


def test_gap_continuation_requires_retention_and_volume():
    context = SetupContext(
        gap_pct=0.05,
        gap_retention=0.70,
        relative_volume=1.80,
        prior_high=105,
        prior_close=98,
        atr14=2,
    )
    detector = GapContinuation()
    assert detector.evaluate(snapshot(104), context) is not None
    assert detector.evaluate(snapshot(104), context.model_copy(update={"gap_retention": 0.30})) is None

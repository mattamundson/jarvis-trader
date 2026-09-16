from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from morning_alpha.research.paper_forward import PaperForwardRegistry, PaperSignal, compare_forward_to_historical

NY = ZoneInfo('America/New_York')
TS = datetime(2026, 1, 5, 9, tzinfo=NY)


def _signal(i=1):
    return PaperSignal.create(
        strategy_key='relative_strength_breakout@1.0.0',
        generated_at=TS,
        symbol=f'S{i}',
        entry=100.0,
        stop=98.0,
        targets=(102.0, 104.0),
        feature_hash='a' * 64,
        regime='bull',
        expected_cost_r=0.05,
        expected_slippage_r=0.03,
    )


def test_signal_hash_is_deterministic_and_record_is_frozen():
    a = _signal()
    b = _signal()
    assert a.signal_hash == b.signal_hash
    with pytest.raises(Exception):
        a.entry = 101.0


def test_outcome_is_separate_and_does_not_mutate_signal_levels():
    registry = PaperForwardRegistry()
    sig = _signal()
    registry.append_signal(sig)
    registry.append_outcome(signal_hash=sig.signal_hash, realized_r=1.2, actual_slippage_r=0.07, filled=True)
    stored = registry.signals[0]
    assert stored.entry == 100.0
    assert stored.stop == 98.0
    assert registry.outcomes[0].signal_hash == sig.signal_hash
    assert not hasattr(registry.outcomes[0], 'entry')


def test_duplicate_signal_or_outcome_is_rejected():
    registry = PaperForwardRegistry()
    sig = _signal()
    registry.append_signal(sig)
    with pytest.raises(ValueError, match='DUPLICATE_PAPER_SIGNAL'):
        registry.append_signal(sig)
    registry.append_outcome(signal_hash=sig.signal_hash, realized_r=0.5, actual_slippage_r=0.02, filled=True)
    with pytest.raises(ValueError, match='DUPLICATE_PAPER_OUTCOME'):
        registry.append_outcome(signal_hash=sig.signal_hash, realized_r=0.1, actual_slippage_r=0.01, filled=True)


def test_forward_comparison_requires_minimum_sample_and_reports_execution_drift():
    registry = PaperForwardRegistry()
    for i in range(1, 6):
        sig = _signal(i)
        registry.append_signal(sig)
        registry.append_outcome(signal_hash=sig.signal_hash, realized_r=0.2 * i, actual_slippage_r=0.04, filled=i != 5)
    small = compare_forward_to_historical(registry, historical_expectancy_r=0.7, min_outcomes=10)
    assert small.status == 'insufficient_data'
    complete = compare_forward_to_historical(registry, historical_expectancy_r=0.7, min_outcomes=5)
    assert complete.status == 'complete'
    assert complete.outcome_count == 5
    assert complete.fill_rate == 0.8
    assert complete.average_actual_slippage_r == 0.04
    assert complete.expectancy_delta_r == pytest.approx(complete.paper_expectancy_r - 0.7)

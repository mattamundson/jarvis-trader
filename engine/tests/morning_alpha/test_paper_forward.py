from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from morning_alpha.research.paper_forward import PaperForwardRegistry,PaperSignal,compare_forward_to_historical
NY=ZoneInfo("America/New_York"); TS=datetime(2026,1,5,9,tzinfo=NY)
def _signal(i=1): return PaperSignal.create(strategy_key="relative_strength_breakout@1.0.0",generated_at=TS,symbol=f"S{i}",entry=100.,stop=98.,targets=(102.,104.),feature_hash="a"*64,regime="bull",expected_cost_r=.05,expected_slippage_r=.03)
def test_signal_hash_deterministic_and_frozen():
    a=_signal(); b=_signal(); assert a.signal_hash==b.signal_hash
    with pytest.raises(Exception): a.entry=101
def test_outcome_separate_and_does_not_mutate_signal():
    r=PaperForwardRegistry(); s=_signal(); r.append_signal(s); r.append_outcome(signal_hash=s.signal_hash,realized_r=1.2,actual_slippage_r=.07,filled=True); assert r.signals[0].entry==100 and not hasattr(r.outcomes[0],"entry")
def test_duplicates_rejected():
    r=PaperForwardRegistry(); s=_signal(); r.append_signal(s)
    with pytest.raises(ValueError,match="DUPLICATE_PAPER_SIGNAL"): r.append_signal(s)
    r.append_outcome(signal_hash=s.signal_hash,realized_r=.5,actual_slippage_r=.02,filled=True)
    with pytest.raises(ValueError,match="DUPLICATE_PAPER_OUTCOME"): r.append_outcome(signal_hash=s.signal_hash,realized_r=.1,actual_slippage_r=.01,filled=True)
def test_forward_comparison_minimum_sample_and_execution_drift():
    r=PaperForwardRegistry()
    for i in range(1,6):
        s=_signal(i); r.append_signal(s); r.append_outcome(signal_hash=s.signal_hash,realized_r=.2*i,actual_slippage_r=.04,filled=i!=5)
    assert compare_forward_to_historical(r,historical_expectancy_r=.7,min_outcomes=10).status=="insufficient_data"
    c=compare_forward_to_historical(r,historical_expectancy_r=.7,min_outcomes=5); assert c.status=="complete" and c.fill_rate==.8 and c.average_actual_slippage_r==.04 and c.expectancy_delta_r==pytest.approx(c.paper_expectancy_r-.7)

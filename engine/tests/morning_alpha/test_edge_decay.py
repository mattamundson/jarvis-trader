from morning_alpha.research.edge_decay import EdgeDecayMonitor,EdgeMonitorSpec,EdgeState

def _monitor(): return EdgeDecayMonitor(EdgeMonitorSpec(version="1.0.0",min_samples=20,watch_expectancy_fraction=.60,degraded_expectancy_r=0,halt_expectancy_r=-.20,slippage_watch_multiple=1.5,slippage_degraded_multiple=2,recovery_expectancy_fraction=.85))

def test_single_loss_cannot_change_state_before_minimum():
    r=_monitor().evaluate(previous_state=EdgeState.NORMAL,recent_returns_r=(-3,),recent_slippage_r=(.2,),historical_expectancy_r=.4,modeled_slippage_r=.05); assert r.state is EdgeState.NORMAL and r.reason=="INSUFFICIENT_SAMPLE_NO_TRANSITION"

def test_healthy_sample_remains_normal():
    r=_monitor().evaluate(previous_state=EdgeState.NORMAL,recent_returns_r=tuple([.4]*25),recent_slippage_r=tuple([.05]*25),historical_expectancy_r=.4,modeled_slippage_r=.05); assert r.state is EdgeState.NORMAL

def test_gradual_decay_watch_degraded_halted():
    m=_monitor(); w=m.evaluate(previous_state=EdgeState.NORMAL,recent_returns_r=tuple([.2]*25),recent_slippage_r=tuple([.05]*25),historical_expectancy_r=.4,modeled_slippage_r=.05); assert w.state is EdgeState.WATCH; d=m.evaluate(previous_state=EdgeState.WATCH,recent_returns_r=tuple([-.05]*25),recent_slippage_r=tuple([.05]*25),historical_expectancy_r=.4,modeled_slippage_r=.05); assert d.state is EdgeState.DEGRADED; h=m.evaluate(previous_state=EdgeState.DEGRADED,recent_returns_r=tuple([-.3]*25),recent_slippage_r=tuple([.05]*25),historical_expectancy_r=.4,modeled_slippage_r=.05); assert h.state is EdgeState.HALTED

def test_slippage_drift_can_degrade():
    r=_monitor().evaluate(previous_state=EdgeState.NORMAL,recent_returns_r=tuple([.4]*25),recent_slippage_r=tuple([.11]*25),historical_expectancy_r=.4,modeled_slippage_r=.05); assert r.state is EdgeState.DEGRADED and "SLIPPAGE" in r.reason

def test_halted_sticky_without_revalidation():
    m=_monitor(); healthy=dict(recent_returns_r=tuple([.5]*30),recent_slippage_r=tuple([.04]*30),historical_expectancy_r=.4,modeled_slippage_r=.05); stuck=m.evaluate(previous_state=EdgeState.HALTED,**healthy); assert stuck.state is EdgeState.HALTED and stuck.reason=="REVALIDATION_REQUIRED"; recovered=m.evaluate(previous_state=EdgeState.HALTED,revalidation_approved=True,**healthy); assert recovered.state is EdgeState.NORMAL

from morning_alpha.research.edge_decay import EdgeDecayMonitor, EdgeMonitorSpec, EdgeState


def _monitor():
    return EdgeDecayMonitor(
        EdgeMonitorSpec(
            version='1.0.0',
            min_samples=20,
            watch_expectancy_fraction=0.60,
            degraded_expectancy_r=0.0,
            halt_expectancy_r=-0.20,
            slippage_watch_multiple=1.5,
            slippage_degraded_multiple=2.0,
            recovery_expectancy_fraction=0.85,
        )
    )


def test_single_loss_cannot_change_state_before_minimum_sample():
    result = _monitor().evaluate(
        previous_state=EdgeState.NORMAL,
        recent_returns_r=(-3.0,),
        recent_slippage_r=(0.2,),
        historical_expectancy_r=0.4,
        modeled_slippage_r=0.05,
    )
    assert result.state is EdgeState.NORMAL
    assert result.reason == 'INSUFFICIENT_SAMPLE_NO_TRANSITION'


def test_healthy_sample_remains_normal():
    result = _monitor().evaluate(
        previous_state=EdgeState.NORMAL,
        recent_returns_r=tuple([0.4] * 25),
        recent_slippage_r=tuple([0.05] * 25),
        historical_expectancy_r=0.4,
        modeled_slippage_r=0.05,
    )
    assert result.state is EdgeState.NORMAL


def test_gradual_expectancy_decay_transitions_watch_then_degraded_then_halted():
    monitor = _monitor()
    watch = monitor.evaluate(previous_state=EdgeState.NORMAL, recent_returns_r=tuple([0.20]*25), recent_slippage_r=tuple([0.05]*25), historical_expectancy_r=0.4, modeled_slippage_r=0.05)
    assert watch.state is EdgeState.WATCH
    degraded = monitor.evaluate(previous_state=EdgeState.WATCH, recent_returns_r=tuple([-0.05]*25), recent_slippage_r=tuple([0.05]*25), historical_expectancy_r=0.4, modeled_slippage_r=0.05)
    assert degraded.state is EdgeState.DEGRADED
    halted = monitor.evaluate(previous_state=EdgeState.DEGRADED, recent_returns_r=tuple([-0.30]*25), recent_slippage_r=tuple([0.05]*25), historical_expectancy_r=0.4, modeled_slippage_r=0.05)
    assert halted.state is EdgeState.HALTED


def test_slippage_drift_can_degrade_even_when_expectancy_is_healthy():
    result = _monitor().evaluate(
        previous_state=EdgeState.NORMAL,
        recent_returns_r=tuple([0.4] * 25),
        recent_slippage_r=tuple([0.11] * 25),
        historical_expectancy_r=0.4,
        modeled_slippage_r=0.05,
    )
    assert result.state is EdgeState.DEGRADED
    assert 'SLIPPAGE' in result.reason


def test_halted_is_sticky_without_explicit_revalidation():
    monitor = _monitor()
    healthy = dict(
        recent_returns_r=tuple([0.5] * 30),
        recent_slippage_r=tuple([0.04] * 30),
        historical_expectancy_r=0.4,
        modeled_slippage_r=0.05,
    )
    stuck = monitor.evaluate(previous_state=EdgeState.HALTED, **healthy)
    assert stuck.state is EdgeState.HALTED
    assert stuck.reason == 'REVALIDATION_REQUIRED'
    recovered = monitor.evaluate(previous_state=EdgeState.HALTED, revalidation_approved=True, **healthy)
    assert recovered.state is EdgeState.NORMAL

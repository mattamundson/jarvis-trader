from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from morning_alpha.research.edge_decay import EdgeDecayMonitor, EdgeMonitorSpec, EdgeState
from morning_alpha.research.gate_v2_adapter import EvidenceGatedGateV2, MorningAlphaGateV2, MorningAlphaResearchRun, ValidationPrerequisite
from morning_alpha.research.monte_carlo import MonteCarloObservation, MonteCarloSpec, run_cluster_monte_carlo
from morning_alpha.research.multiple_testing import VariantReturnSeries, cscv_pbo, reality_check
from morning_alpha.research.oos import LockedOOSEvaluator, OOSLockSpec
from morning_alpha.research.paper_forward import PaperForwardRegistry, PaperSignal, compare_forward_to_historical
from morning_alpha.research.regime_robustness import StructuralObservation, analyze_dimension
from morning_alpha.research.replication import ReplicationCandidate, ReplicationDataset, compare_replication
from morning_alpha.research.walk_forward import WalkForwardRecord, WalkForwardRunner, WalkForwardSpec

NY = ZoneInfo('America/New_York')


def test_soundness_chain_preserves_separate_evidence_states_without_auto_promotion():
    # L6: lock and evaluate exact identity.
    lock = OOSLockSpec(
        campaign_id='c', strategy_key='relative_strength_breakout@1.0.0', parameter_hash='a'*64,
        trigger_version='t1', exit_version='e1', data_manifest_hash='b'*64,
        candidate_population_hash='c'*64, trial_ledger_hash='d'*64, trial_count=25,
        development_start=date(2018,1,1), development_end=date(2021,12,31),
        validation_start=date(2022,1,1), validation_end=date(2023,12,31),
        oos_start=date(2024,1,1), oos_end=date(2025,12,31), purge_sessions=20,
        embargo_sessions=20, code_commit='abc', locked_at=datetime(2023,12,1,9,tzinfo=NY),
    ).seal()
    oos = LockedOOSEvaluator(lock).evaluate(lock.identity, lambda: {'expectancy_r': 0.22, 'n': 210})
    assert oos.metrics['expectancy_r'] > 0

    # L7: walk-forward contains positive and negative folds; evidence is not perfect by construction.
    start = date(2020,1,1)
    records = tuple(WalkForwardRecord(observation_id=f'r{i}', trading_date=start+timedelta(days=i), payload={'x':i}) for i in range(30))
    wfo = WalkForwardRunner(WalkForwardSpec(train_sessions=10,test_sessions=5,step_sessions=5,purge_sessions=1,embargo_sessions=1)).run(
        records, lambda rows: {'p': 1}, lambda rows, p: {'expectancy_r': 0.1 if rows[0].payload['x'] < 20 else -0.05}
    )
    assert len(wfo.folds) >= 3

    # L8: regime report explicitly retains a weak bucket.
    structural = tuple(
        StructuralObservation(observation_id=f's{i}', edge=edge, dimensions={'regime': regime})
        for i, (edge, regime) in enumerate([(0.4,'bull'),(0.3,'bull'),(0.1,'neutral'),(0.0,'neutral'),(-0.2,'bear'),(-0.1,'bear')])
    )
    regime = analyze_dimension(structural, dimension='regime', min_bucket_n=2)
    assert regime.worst_bucket == 'bear'

    # L9: cluster Monte Carlo exposes non-zero drawdown risk.
    mc_rows = tuple(MonteCarloObservation(observation_id=f'm{i}', trading_date=start+timedelta(days=i//2), return_r=r) for i, r in enumerate([0.4,-0.1,0.3,0.2,-0.4,0.1]))
    mc = run_cluster_monte_carlo(mc_rows, MonteCarloSpec(n_paths=300, seed=1, loss_thresholds_r=(-0.5,)))
    assert mc.p95_max_drawdown_r >= 0

    # L10: canonical adapter is invoked only after L6-L9 prerequisites are complete.
    gate_calls = []
    base_gate = MorningAlphaGateV2(gate_fn=lambda *args: gate_calls.append(args) or {'verdict':'PASS','passed_via':'core','reasons':[]}, normal_min_trades=200)
    run = MorningAlphaResearchRun('relative_strength_breakout@1.0.0',200,tuple([0.1]*200),({'w':1},),5,{'pf':1.3},{'10bps':{'pf':1.2}})
    prereq = tuple(ValidationPrerequisite(level=f'L{i}',status='complete',identity_hash='f'*64) for i in range(6,10))
    gate = EvidenceGatedGateV2(base_gate).evaluate(run, prereq)
    assert gate.gate_verdict == 'PASS' and len(gate_calls) == 1

    # L11: paper evidence remains separate and can differ from historical expectancy.
    registry = PaperForwardRegistry()
    for i in range(5):
        sig = PaperSignal.create(strategy_key=run.strategy_key,generated_at=datetime(2026,1,5+i,9,tzinfo=NY),symbol=f'P{i}',entry=100,stop=98,targets=(102,),feature_hash='1'*64,regime='bull',expected_cost_r=0.05,expected_slippage_r=0.03)
        registry.append_signal(sig)
        registry.append_outcome(signal_hash=sig.signal_hash, realized_r=0.15, actual_slippage_r=0.04, filled=True)
    forward = compare_forward_to_historical(registry,historical_expectancy_r=0.22,min_outcomes=5)
    assert forward.status == 'complete' and forward.expectancy_delta_r < 0

    # L12: multiple-testing evidence is reported separately from Gate-v2.
    variants = (
        VariantReturnSeries(variant_id='v1', returns=tuple([0.12]*40)),
        VariantReturnSeries(variant_id='v2', returns=tuple([0.01,-0.01]*20)),
        VariantReturnSeries(variant_id='v3', returns=tuple([-0.03]*40)),
    )
    assert 0 <= cscv_pbo(variants, partitions=8).pbo <= 1
    assert 0 <= reality_check(variants,n_bootstrap=200,block_length=4,seed=1).p_value <= 1

    # L13: independent replication is an evidence comparison, not an automatic veto/pass.
    primary = ReplicationDataset(provider='A',lineage_hash='a'*64,candidates=(ReplicationCandidate(candidate_id='x',features={'rs':.2},triggered=True,outcome_r=.3),))
    secondary = ReplicationDataset(provider='B',lineage_hash='b'*64,candidates=(ReplicationCandidate(candidate_id='x',features={'rs':.21},triggered=True,outcome_r=.25),))
    replication = compare_replication(primary,secondary)
    assert replication.status == 'complete' and replication.expectancy_delta_r < 0

    # L14: healthy forward evidence can still move to WATCH if it decays materially.
    monitor = EdgeDecayMonitor(EdgeMonitorSpec(version='1',min_samples=5,watch_expectancy_fraction=.75,degraded_expectancy_r=0,halt_expectancy_r=-.2,slippage_watch_multiple=1.5,slippage_degraded_multiple=2,recovery_expectancy_fraction=.9))
    decay = monitor.evaluate(previous_state=EdgeState.NORMAL,recent_returns_r=tuple([.1]*5),recent_slippage_r=tuple([.03]*5),historical_expectancy_r=.22,modeled_slippage_r=.03)
    assert decay.state is EdgeState.WATCH

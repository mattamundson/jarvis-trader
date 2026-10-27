from morning_alpha.research.gate_v2_adapter import (
    EvidenceGatedGateV2,
    MorningAlphaGateV2,
    MorningAlphaResearchRun,
    ValidationPrerequisite,
)


def _run():
    return MorningAlphaResearchRun(
        strategy_key='relative_strength_breakout@1.0.0',
        total_historical_trades=200,
        trade_returns_r=tuple([0.1] * 200),
        oos_results=({'x': 1},),
        n_grid_combos=5,
        fixed_params_metrics={'pf': 1.3},
        cost_sweep_metrics={'10bps': {'pf': 1.2}},
    )


def _evidence(status='complete', identity='a' * 64):
    return tuple(ValidationPrerequisite(level=f'L{i}', status=status, identity_hash=identity) for i in range(6, 10))


def test_gate_v2_is_not_invoked_when_l6_l9_evidence_missing():
    calls = []
    base = MorningAlphaGateV2(gate_fn=lambda *args: calls.append(args) or {'verdict':'PASS'}, normal_min_trades=200)
    verdict = EvidenceGatedGateV2(base).evaluate(_run(), _evidence()[:-1])
    assert verdict.gate_invoked is False
    assert 'L9' in ' '.join(verdict.reasons)
    assert calls == []


def test_gate_v2_is_not_invoked_when_evidence_is_incomplete():
    calls = []
    rows = list(_evidence())
    rows[2] = rows[2].model_copy(update={'status':'insufficient_data'})
    base = MorningAlphaGateV2(gate_fn=lambda *args: calls.append(args) or {'verdict':'PASS'}, normal_min_trades=200)
    verdict = EvidenceGatedGateV2(base).evaluate(_run(), tuple(rows))
    assert verdict.gate_invoked is False
    assert calls == []


def test_gate_v2_rejects_mixed_validation_identity():
    calls = []
    rows = list(_evidence())
    rows[-1] = rows[-1].model_copy(update={'identity_hash':'b' * 64})
    base = MorningAlphaGateV2(gate_fn=lambda *args: calls.append(args) or {'verdict':'PASS'}, normal_min_trades=200)
    verdict = EvidenceGatedGateV2(base).evaluate(_run(), tuple(rows))
    assert verdict.gate_invoked is False
    assert 'identity' in ' '.join(verdict.reasons).lower()
    assert calls == []


def test_gate_v2_delegates_to_canonical_adapter_when_l6_l9_complete():
    calls = []
    base = MorningAlphaGateV2(
        gate_fn=lambda oos, combos, fixed, cost: calls.append((oos, combos, fixed, cost)) or {'verdict':'PASS','passed_via':'core','reasons':[]},
        normal_min_trades=200,
    )
    verdict = EvidenceGatedGateV2(base).evaluate(_run(), _evidence())
    assert verdict.gate_invoked is True
    assert verdict.gate_verdict == 'PASS'
    assert len(calls) == 1

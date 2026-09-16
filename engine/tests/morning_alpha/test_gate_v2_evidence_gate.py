from morning_alpha.research.gate_v2_adapter import EvidenceGatedGateV2,MorningAlphaGateV2,MorningAlphaResearchRun,ValidationPrerequisite

def _run():
    return MorningAlphaResearchRun(strategy_key="relative_strength_breakout@1.0.0",total_historical_trades=200,trade_returns_r=tuple([.1]*200),oos_results=({"x":1},),n_grid_combos=5,fixed_params_metrics={"pf":1.3},cost_sweep_metrics={"10bps":{"pf":1.2}})

def _evidence(status="complete",identity="a"*64): return tuple(ValidationPrerequisite(level=f"L{i}",status=status,identity_hash=identity) for i in range(6,10))

def test_missing_l6_l9_blocks_gate():
    calls=[]; v=EvidenceGatedGateV2(MorningAlphaGateV2(gate_fn=lambda *a:calls.append(a) or {"verdict":"PASS"},normal_min_trades=200)).evaluate(_run(),_evidence()[:-1]); assert not v.gate_invoked; assert calls==[]; assert "L9" in " ".join(v.reasons)

def test_incomplete_evidence_blocks_gate():
    calls=[]; rows=list(_evidence()); rows[2]=rows[2].model_copy(update={"status":"insufficient_data"}); v=EvidenceGatedGateV2(MorningAlphaGateV2(gate_fn=lambda *a:calls.append(a) or {"verdict":"PASS"},normal_min_trades=200)).evaluate(_run(),tuple(rows)); assert not v.gate_invoked and calls==[]

def test_mixed_identity_blocks_gate():
    calls=[]; rows=list(_evidence()); rows[-1]=rows[-1].model_copy(update={"identity_hash":"b"*64}); v=EvidenceGatedGateV2(MorningAlphaGateV2(gate_fn=lambda *a:calls.append(a) or {"verdict":"PASS"},normal_min_trades=200)).evaluate(_run(),tuple(rows)); assert not v.gate_invoked; assert "identity" in " ".join(v.reasons).lower(); assert calls==[]

def test_complete_evidence_delegates_once():
    calls=[]; base=MorningAlphaGateV2(gate_fn=lambda o,c,f,s:calls.append((o,c,f,s)) or {"verdict":"PASS","passed_via":"core","reasons":[]},normal_min_trades=200); v=EvidenceGatedGateV2(base).evaluate(_run(),_evidence()); assert v.gate_invoked and v.gate_verdict=="PASS" and len(calls)==1

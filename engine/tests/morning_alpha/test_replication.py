from morning_alpha.research.replication import ReplicationCandidate,ReplicationDataset,ShadowComparisonJournal,compare_replication

def _dataset(provider,lineage,tweak=0.0):
    return ReplicationDataset(provider=provider,lineage_hash=lineage,candidates=(ReplicationCandidate(candidate_id="a",features={"rs":.20+tweak,"atr":2.0},triggered=True,outcome_r=1.0+tweak),ReplicationCandidate(candidate_id="b",features={"rs":.10+tweak,"atr":1.5},triggered=False,outcome_r=-.2+tweak),ReplicationCandidate(candidate_id="c",features={"rs":.15+tweak,"atr":1.8},triggered=True,outcome_r=.5+tweak)))

def test_requires_independent_lineage():
    r=compare_replication(_dataset("A","a"*64),_dataset("A","a"*64)); assert r.status=="invalid" and "INDEPENDENT_LINEAGE_REQUIRED" in r.reasons

def test_reports_overlap_feature_trigger_and_expectancy_deltas():
    r=compare_replication(_dataset("A","a"*64),_dataset("B","b"*64,.01)); assert r.status=="complete" and r.candidate_overlap_rate==1 and r.trigger_disagreement_rate==0 and r.feature_mean_absolute_delta["rs"]>0 and r.expectancy_delta_r!=0

def test_reports_missing_candidates_and_divergence():
    p=_dataset("A","a"*64); s=ReplicationDataset(provider="B",lineage_hash="b"*64,candidates=(ReplicationCandidate(candidate_id="a",features={"rs":.2,"atr":2.0},triggered=False,outcome_r=1),ReplicationCandidate(candidate_id="d",features={"rs":.3,"atr":2.2},triggered=True,outcome_r=.4))); r=compare_replication(p,s); assert r.candidate_overlap_rate<1 and r.missing_from_secondary==("b","c") and r.missing_from_primary==("d",) and r.trigger_disagreement_rate==1

def test_shadow_journal_records_divergence():
    j=ShadowComparisonJournal(); e=j.append(primary_signal_hash="a"*64,shadow_signal_hash="b"*64,same_decision=False,reason="TRIGGER_DIVERGENCE"); assert j.events==(e,)

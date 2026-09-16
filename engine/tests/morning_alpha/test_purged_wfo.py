from datetime import date,timedelta
from morning_alpha.research.walk_forward import WalkForwardRecord,WalkForwardRunner,WalkForwardSpec

def _records(n=30):
    start=date(2024,1,1); return tuple(WalkForwardRecord(observation_id=f"r{i}",trading_date=start+timedelta(days=i),payload={"x":i}) for i in range(n))

def test_wfo_purges_train_tail_and_embargoes_test_head():
    first=WalkForwardRunner(WalkForwardSpec(train_sessions=10,test_sessions=5,step_sessions=5,purge_sessions=2,embargo_sessions=1)).folds(_records(25))[0]
    assert [r.payload["x"] for r in first.train_records]==list(range(8)); assert [r.payload["x"] for r in first.test_records]==[11,12,13,14]
    assert first.purged_train_ids==("r8","r9"); assert first.embargoed_test_ids==("r10",)

def test_selector_and_evaluator_are_fold_separated():
    runner=WalkForwardRunner(WalkForwardSpec(train_sessions=8,test_sessions=4,step_sessions=4,purge_sessions=1,embargo_sessions=1))
    summary=runner.run(_records(20),lambda rows:{"threshold":max(r.payload["x"] for r in rows)},lambda rows,p:{"n":len(rows),"first":rows[0].payload["x"],"p":p["threshold"]})
    for fold in summary.folds:
        assert set(r.observation_id for r in fold.train_records).isdisjoint(r.observation_id for r in fold.test_records)
        assert fold.selected_params["threshold"]<fold.test_records[0].payload["x"]

def test_overlapping_test_windows_not_double_counted():
    runner=WalkForwardRunner(WalkForwardSpec(train_sessions=8,test_sessions=6,step_sessions=3,purge_sessions=1,embargo_sessions=0))
    s=runner.run(_records(25),lambda rows:{"p":1},lambda rows,p:{"n":len(rows)})
    raw=[r.observation_id for f in s.folds for r in f.test_records]
    assert len(raw)>len(set(raw)); assert s.unique_test_observation_ids==tuple(dict.fromkeys(raw))

def test_fold_hash_is_deterministic():
    runner=WalkForwardRunner(WalkForwardSpec(train_sessions=8,test_sessions=4,step_sessions=4,purge_sessions=1,embargo_sessions=0))
    one=runner.run(_records(20),lambda rows:{"p":7},lambda rows,p:{"n":len(rows)}); two=runner.run(_records(20),lambda rows:{"p":7},lambda rows,p:{"n":len(rows)})
    assert [f.fold_hash for f in one.folds]==[f.fold_hash for f in two.folds]; assert all(len(f.parameter_hash)==64 for f in one.folds)

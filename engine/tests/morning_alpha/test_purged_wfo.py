from datetime import date, timedelta

from morning_alpha.research.walk_forward import WalkForwardRecord, WalkForwardRunner, WalkForwardSpec


def _records(n=30):
    start = date(2024, 1, 1)
    return tuple(WalkForwardRecord(observation_id=f'r{i}', trading_date=start + timedelta(days=i), payload={'x': i}) for i in range(n))


def test_wfo_purges_train_tail_and_embargoes_test_head():
    spec = WalkForwardSpec(train_sessions=10, test_sessions=5, step_sessions=5, purge_sessions=2, embargo_sessions=1)
    folds = WalkForwardRunner(spec).folds(_records(25))
    first = folds[0]
    assert len(first.train_records) == 8
    assert [r.payload['x'] for r in first.train_records] == list(range(8))
    assert len(first.test_records) == 4
    assert [r.payload['x'] for r in first.test_records] == [11, 12, 13, 14]
    assert first.purged_train_ids == ('r8', 'r9')
    assert first.embargoed_test_ids == ('r10',)


def test_selector_receives_train_only_and_evaluator_receives_test_only():
    seen_train = []
    seen_test = []
    spec = WalkForwardSpec(train_sessions=8, test_sessions=4, step_sessions=4, purge_sessions=1, embargo_sessions=1)
    runner = WalkForwardRunner(spec)

    def selector(rows):
        seen_train.extend(r.observation_id for r in rows)
        return {'threshold': max(r.payload['x'] for r in rows)}

    def evaluator(rows, params):
        seen_test.extend(r.observation_id for r in rows)
        assert params['threshold'] < min(r.payload['x'] for r in rows)
        return {'expectancy': 0.1, 'n': len(rows)}

    summary = runner.run(_records(20), selector, evaluator)
    assert summary.folds
    assert set(seen_train).isdisjoint(set(seen_test)) is False  # same record may be train in a later fold
    for fold in summary.folds:
        assert set(r.observation_id for r in fold.train_records).isdisjoint(
            r.observation_id for r in fold.test_records
        )


def test_overlapping_test_windows_are_not_double_counted_in_aggregate_ids():
    spec = WalkForwardSpec(train_sessions=8, test_sessions=6, step_sessions=3, purge_sessions=1, embargo_sessions=0)
    runner = WalkForwardRunner(spec)
    summary = runner.run(
        _records(25),
        lambda rows: {'p': 1},
        lambda rows, params: {'expectancy': 0.2, 'n': len(rows)},
    )
    raw_test_ids = [r.observation_id for fold in summary.folds for r in fold.test_records]
    assert len(raw_test_ids) > len(set(raw_test_ids))
    assert summary.unique_test_observation_ids == tuple(dict.fromkeys(raw_test_ids))


def test_fold_hash_is_deterministic_and_parameter_identity_is_persisted():
    spec = WalkForwardSpec(train_sessions=8, test_sessions=4, step_sessions=4, purge_sessions=1, embargo_sessions=0)
    runner = WalkForwardRunner(spec)
    one = runner.run(_records(20), lambda rows: {'p': 7}, lambda rows, p: {'n': len(rows)})
    two = runner.run(_records(20), lambda rows: {'p': 7}, lambda rows, p: {'n': len(rows)})
    assert [f.fold_hash for f in one.folds] == [f.fold_hash for f in two.folds]
    assert all(len(f.parameter_hash) == 64 for f in one.folds)

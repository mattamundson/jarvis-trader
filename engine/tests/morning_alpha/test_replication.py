from morning_alpha.research.replication import ReplicationCandidate, ReplicationDataset, ShadowComparisonJournal, compare_replication


def _dataset(provider, lineage, tweak=0.0):
    return ReplicationDataset(
        provider=provider,
        lineage_hash=lineage,
        candidates=(
            ReplicationCandidate(candidate_id='a', features={'rs':0.20+tweak,'atr':2.0}, triggered=True, outcome_r=1.0+tweak),
            ReplicationCandidate(candidate_id='b', features={'rs':0.10+tweak,'atr':1.5}, triggered=False, outcome_r=-0.2+tweak),
            ReplicationCandidate(candidate_id='c', features={'rs':0.15+tweak,'atr':1.8}, triggered=True, outcome_r=0.5+tweak),
        ),
    )


def test_replication_requires_independent_provider_lineage():
    primary = _dataset('ProviderA','a'*64)
    same = _dataset('ProviderA','a'*64)
    report = compare_replication(primary, same)
    assert report.status == 'invalid'
    assert 'INDEPENDENT_LINEAGE_REQUIRED' in report.reasons


def test_replication_reports_overlap_feature_trigger_and_expectancy_deltas():
    primary = _dataset('ProviderA','a'*64)
    secondary = _dataset('ProviderB','b'*64, tweak=0.01)
    report = compare_replication(primary, secondary)
    assert report.status == 'complete'
    assert report.candidate_overlap_rate == 1.0
    assert report.trigger_disagreement_rate == 0.0
    assert report.feature_mean_absolute_delta['rs'] > 0
    assert report.expectancy_delta_r != 0


def test_replication_exposes_missing_candidates_and_trigger_divergence():
    primary = _dataset('ProviderA','a'*64)
    secondary = ReplicationDataset(
        provider='ProviderB', lineage_hash='b'*64,
        candidates=(
            ReplicationCandidate(candidate_id='a', features={'rs':0.2,'atr':2.0}, triggered=False, outcome_r=1.0),
            ReplicationCandidate(candidate_id='d', features={'rs':0.3,'atr':2.2}, triggered=True, outcome_r=0.4),
        ),
    )
    report = compare_replication(primary, secondary)
    assert report.candidate_overlap_rate < 1
    assert report.missing_from_secondary == ('b','c')
    assert report.missing_from_primary == ('d',)
    assert report.trigger_disagreement_rate == 1.0


def test_shadow_journal_records_divergence_without_mutating_prior_event():
    journal = ShadowComparisonJournal()
    event = journal.append(primary_signal_hash='a'*64, shadow_signal_hash='b'*64, same_decision=False, reason='TRIGGER_DIVERGENCE')
    assert event.reason == 'TRIGGER_DIVERGENCE'
    assert journal.events == (event,)

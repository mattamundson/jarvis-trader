from datetime import UTC, datetime, timedelta

from morning_alpha.journal import InMemorySignalJournal
from morning_alpha.models import (
    OutcomeClassification,
    SetupCandidate,
    SignalOutcome,
    StrategyKey,
    TradePlan,
)

NOW = datetime(2026, 9, 15, 13, 0, tzinfo=UTC)


def candidate():
    return SetupCandidate(
        symbol="XYZ",
        strategy=StrategyKey(strategy_id="rs", version="1.0.0"),
        as_of=NOW,
        side="long",
        setup_type="relative_strength_breakout",
        thesis_code="RSB_V1",
        proposed_entry=100,
        proposed_stop=98,
        nearby_obstacle=108,
        sector="XLK",
        theme="software",
    )


def plan():
    return TradePlan(
        symbol="XYZ",
        strategy=StrategyKey(strategy_id="rs", version="1.0.0"),
        as_of=NOW,
        side="long",
        entry=100,
        stop=98,
        targets=(102, 104, 106, 108),
        risk_per_share=2,
        account_equity=3000,
        risk_fraction=0.005,
        shares=7,
        max_dollar_risk=14,
        expected_r=4,
        sector="XLK",
        theme="software",
    )


def test_candidate_is_retrieved_exactly_as_recorded():
    journal = InMemorySignalJournal()
    original = candidate()
    cid = journal.append_candidate(
        original,
        recorded_at=NOW,
        provider_lineage={"market": "alpaca", "as_of": NOW.isoformat()},
    )
    record = journal.get_candidate(cid)
    assert record.payload == original.model_dump(mode="json")
    assert record.provider_lineage["market"] == "alpaca"
    assert ("rs", "1.0.0") in journal.strategy_versions


def test_plan_and_outcome_append_without_mutating_original_candidate_levels():
    journal = InMemorySignalJournal()
    cid = journal.append_candidate(candidate(), recorded_at=NOW)
    journal.append_plan(cid, plan(), recorded_at=NOW + timedelta(minutes=1))
    outcome = SignalOutcome(
        symbol="XYZ",
        strategy=StrategyKey(strategy_id="rs", version="1.0.0"),
        signal_as_of=NOW,
        evaluated_as_of=NOW + timedelta(days=1),
        triggered=True,
        classification=OutcomeClassification.WIN,
        entry_price=100,
        mfe_r=2.2,
        mae_r=-0.25,
        close_r=1.4,
        stop_hit=False,
        reached_1r=True,
        reached_2r=True,
        reached_3r=False,
        reached_4r=False,
    )
    journal.append_outcome(cid, outcome, recorded_at=NOW + timedelta(days=1))
    record = journal.get_candidate(cid)
    assert record.payload["proposed_entry"] == 100
    assert record.payload["proposed_stop"] == 98
    assert [e.event_type for e in journal.events(cid)] == ["trade_plan", "outcome"]


def test_returned_record_is_defensive_copy():
    journal = InMemorySignalJournal()
    cid = journal.append_candidate(
        candidate(), recorded_at=NOW, provider_lineage={"nested": {"x": 1}}
    )
    first = journal.get_candidate(cid)
    first.payload["symbol"] = "MUTATED"
    first.provider_lineage["nested"]["x"] = 999
    second = journal.get_candidate(cid)
    assert second.payload["symbol"] == "XYZ"
    assert second.provider_lineage["nested"]["x"] == 1


def test_unknown_candidate_cannot_receive_event():
    from uuid import uuid4

    journal = InMemorySignalJournal()
    try:
        journal.append_plan(uuid4(), plan(), recorded_at=NOW)
    except KeyError:
        pass
    else:
        raise AssertionError("unknown candidate must be rejected")


def test_recorded_at_must_be_timezone_aware():
    journal = InMemorySignalJournal()
    naive = datetime(2026, 9, 15, 13, 0)
    try:
        journal.append_candidate(candidate(), recorded_at=naive)
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("naive timestamps must be rejected")

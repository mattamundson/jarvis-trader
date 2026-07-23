from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from es_research.contracts import (
    AggressorSide,
    ExperimentRun,
    ExperimentStatus,
    SimulationLevel,
    SimulationResult,
    StrategyCandidate,
    TradeEvent,
)
from es_research.hashing import sha256_hash
from es_research.manifests.models import DataManifest, SourceFileRecord

UTC_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def test_timezone_validation_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        TradeEvent(
            event_timestamp=datetime(2026, 1, 1),
            instrument_id="ESH6",
            symbol="/ES",
            price=Decimal("1"),
            quantity=Decimal("1"),
            aggressor_side=AggressorSide.BUY,
            sequence_number=1,
            venue="CME",
        )


def test_json_round_trip() -> None:
    event = TradeEvent(
        event_timestamp=UTC_TIME,
        instrument_id="ESH6",
        symbol="/ES",
        price=Decimal("5000.25"),
        quantity=Decimal("1"),
        aggressor_side=AggressorSide.BUY,
        sequence_number=1,
        venue="CME",
    )
    assert TradeEvent.model_validate_json(event.model_dump_json()) == event


def test_deterministic_hashing_and_equivalent_dicts() -> None:
    assert sha256_hash({"b": 2, "a": {"x": 1}}) == sha256_hash({"a": {"x": 1}, "b": 2})


def test_modified_configuration_changes_hash() -> None:
    assert sha256_hash({"seed": 1}) != sha256_hash({"seed": 2})


def test_invalid_monetary_values() -> None:
    with pytest.raises(ValidationError, match="non-negative"):
        TradeEvent(
            event_timestamp=UTC_TIME,
            instrument_id="ESH6",
            symbol="/ES",
            price=Decimal("-1"),
            quantity=Decimal("1"),
            aggressor_side=AggressorSide.SELL,
            sequence_number=1,
            venue="CME",
        )


def test_duckdb_registry_initialization(tmp_path) -> None:  # type: ignore[no-untyped-def]
    duckdb = pytest.importorskip("duckdb")
    assert duckdb is not None
    from es_research.registry.repository import DuckDBExperimentRegistry

    db = tmp_path / "registry.duckdb"
    registry = DuckDBExperimentRegistry(db)
    registry.initialize()
    registry.initialize()
    assert db.exists()


def _candidate() -> StrategyCandidate:
    definition = {"name": "demo"}
    return StrategyCandidate(
        candidate_id=sha256_hash(definition),
        canonical_strategy_definition=definition,
        strategy_hash=sha256_hash(definition),
        parameter_values={"x": 1},
        feature_version="v1",
        creation_timestamp=UTC_TIME,
    )


def test_experiment_insertion_and_retrieval(tmp_path) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("duckdb")
    from es_research.registry.repository import DuckDBExperimentRegistry

    registry = DuckDBExperimentRegistry(tmp_path / "registry.duckdb")
    candidate = _candidate()
    experiment = ExperimentRun(
        experiment_id="exp-1",
        strategy_hash=candidate.strategy_hash,
        data_manifest_hash="manifest",
        feature_version="v1",
        code_commit="abc",
        configuration_hash="cfg",
        cost_model_version="cost",
        simulation_level=SimulationLevel.SCREENING,
        start_timestamp=UTC_TIME,
        random_seed=1,
        status=ExperimentStatus.PENDING,
    )
    registry.upsert_candidate(candidate)
    registry.insert_experiment(experiment)
    assert registry.get_candidate(candidate.candidate_id) == candidate
    assert registry.get_experiment("exp-1") == experiment


def test_duplicate_candidate_handling(tmp_path) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("duckdb")
    from es_research.registry.repository import DuckDBExperimentRegistry

    registry = DuckDBExperimentRegistry(tmp_path / "registry.duckdb")
    candidate = _candidate()
    registry.upsert_candidate(candidate)
    registry.upsert_candidate(candidate)
    assert registry.get_candidate(candidate.candidate_id) == candidate


def test_simulation_result_rejects_invalid_drawdown() -> None:
    with pytest.raises(ValidationError, match="non-negative"):
        SimulationResult(
            experiment_id="e",
            candidate_id="c",
            gross_pnl=Decimal("0"),
            net_pnl=Decimal("0"),
            trade_count=0,
            turnover=Decimal("0"),
            maximum_drawdown=Decimal("-1"),
            sharpe_ratio=Decimal("0"),
            win_rate=Decimal("0"),
            average_trade=Decimal("0"),
            result_timestamp=UTC_TIME,
        )


def test_manifest_hash() -> None:
    manifest = DataManifest(
        source_files=(
            SourceFileRecord(
                path="x", sha256="abc", row_count=1, min_timestamp=UTC_TIME, max_timestamp=UTC_TIME
            ),
        ),
        schema_version="v1",
        generation_timestamp=UTC_TIME,
        code_commit="abc",
    )
    assert len(manifest.manifest_hash) == 64

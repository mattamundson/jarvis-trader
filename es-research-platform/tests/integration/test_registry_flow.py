from __future__ import annotations

import pytest

from es_research.demo import build_synthetic_objects


def test_full_registry_flow(tmp_path) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("duckdb")
    from es_research.registry.repository import DuckDBExperimentRegistry

    registry = DuckDBExperimentRegistry(tmp_path / "flow.duckdb")
    manifest, candidate, experiment, result = build_synthetic_objects()
    manifest_hash = registry.insert_manifest(manifest)
    registry.upsert_candidate(candidate)
    registry.insert_experiment(experiment)
    registry.insert_result(result)
    assert registry.get_manifest(manifest_hash) == manifest
    assert registry.get_candidate(candidate.candidate_id) == candidate
    assert registry.get_experiment(experiment.experiment_id) == experiment
    assert registry.get_result(experiment.experiment_id, candidate.candidate_id) == result
    assert experiment.data_manifest_hash == manifest_hash
    assert result.experiment_id == experiment.experiment_id


def test_reproducibility_values_survive_database_deletion(tmp_path) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("duckdb")
    from es_research.demo import run_reproducibility_demo

    first_db = tmp_path / "first.duckdb"
    second_db = tmp_path / "second.duckdb"
    first_values = run_reproducibility_demo(first_db)
    first_db.unlink()
    second_values = run_reproducibility_demo(second_db)
    assert first_values == second_values

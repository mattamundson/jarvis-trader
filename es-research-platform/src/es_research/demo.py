from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from es_research.contracts import (
    ExperimentRun,
    ExperimentStatus,
    SimulationLevel,
    SimulationResult,
    StrategyCandidate,
)
from es_research.hashing import sha256_hash
from es_research.manifests.models import DataManifest, SourceFileRecord
from es_research.registry.repository import DuckDBExperimentRegistry

FIXED_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def build_synthetic_objects() -> tuple[
    DataManifest, StrategyCandidate, ExperimentRun, SimulationResult
]:
    strategy_definition = {"name": "phase1_identity", "rules": [{"if": "demo", "then": "record"}]}
    strategy_hash = sha256_hash(strategy_definition)
    manifest = DataManifest(
        source_files=(
            SourceFileRecord(
                path="synthetic/demo.jsonl",
                sha256=sha256_hash({"demo": 1}),
                row_count=2,
                min_timestamp=FIXED_TIME,
                max_timestamp=FIXED_TIME,
            ),
        ),
        schema_version="phase1.v1",
        generation_timestamp=FIXED_TIME,
        code_commit="demo-commit",
    )
    config_hash = sha256_hash({"registry": "demo", "seed": 7})
    candidate_id = sha256_hash({"strategy_hash": strategy_hash, "parameters": {"lookback": 1}})
    experiment_id = sha256_hash(
        {
            "strategy_hash": strategy_hash,
            "manifest_hash": manifest.manifest_hash,
            "configuration_hash": config_hash,
            "seed": 7,
        }
    )
    candidate = StrategyCandidate(
        candidate_id=candidate_id,
        canonical_strategy_definition=strategy_definition,
        strategy_hash=strategy_hash,
        parameter_values={"lookback": 1},
        feature_version="demo.v1",
        creation_timestamp=FIXED_TIME,
    )
    experiment = ExperimentRun(
        experiment_id=experiment_id,
        strategy_hash=strategy_hash,
        data_manifest_hash=manifest.manifest_hash,
        feature_version="demo.v1",
        code_commit="demo-commit",
        configuration_hash=config_hash,
        cost_model_version="zero_cost.v1",
        simulation_level=SimulationLevel.SCREENING,
        start_timestamp=FIXED_TIME,
        end_timestamp=FIXED_TIME,
        random_seed=7,
        status=ExperimentStatus.COMPLETED,
    )
    result = SimulationResult(
        experiment_id=experiment_id,
        candidate_id=candidate_id,
        gross_pnl=Decimal("0"),
        net_pnl=Decimal("0"),
        trade_count=0,
        turnover=Decimal("0"),
        maximum_drawdown=Decimal("0"),
        sharpe_ratio=Decimal("0"),
        win_rate=Decimal("0"),
        average_trade=Decimal("0"),
        result_timestamp=FIXED_TIME,
    )
    return manifest, candidate, experiment, result


def run_reproducibility_demo(path: Path) -> dict[str, str]:
    first = build_synthetic_objects()
    second = build_synthetic_objects()
    if [first[0].manifest_hash, first[1].candidate_id, first[2].experiment_id] != [
        second[0].manifest_hash,
        second[1].candidate_id,
        second[2].experiment_id,
    ]:
        raise RuntimeError("reproducibility demo produced mismatched deterministic identifiers")
    registry = DuckDBExperimentRegistry(path)
    registry.initialize()
    manifest, candidate, experiment, result = first
    registry.insert_manifest(manifest)
    registry.upsert_candidate(candidate)
    if registry.get_experiment(experiment.experiment_id) is None:
        registry.insert_experiment(experiment)
    if registry.get_result(result.experiment_id, result.candidate_id) is None:
        registry.insert_result(result)
    return {
        "manifest_hash": manifest.manifest_hash,
        "candidate_id": candidate.candidate_id,
        "experiment_id": experiment.experiment_id,
    }

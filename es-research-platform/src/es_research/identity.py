"""Deterministic identity helpers for research artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from es_research.contracts import (
    ExperimentRun,
    ExperimentStatus,
    SimulationLevel,
    StrategyCandidate,
)
from es_research.hashing import sha256_hash


def strategy_hash(strategy_definition: dict[str, Any]) -> str:
    """Hash a canonical strategy definition."""
    return sha256_hash(strategy_definition)


def candidate_id(
    strategy_hash_value: str, parameter_values: dict[str, int | float | str | bool]
) -> str:
    """Create a stable candidate identifier from a strategy hash and parameter values."""
    return sha256_hash({"strategy_hash": strategy_hash_value, "parameters": parameter_values})


def experiment_id(
    *,
    strategy_hash_value: str,
    data_manifest_hash: str,
    configuration_hash: str,
    random_seed: int,
) -> str:
    """Create a stable experiment identifier from the identity-defining inputs."""
    return sha256_hash(
        {
            "strategy_hash": strategy_hash_value,
            "manifest_hash": data_manifest_hash,
            "configuration_hash": configuration_hash,
            "seed": random_seed,
        }
    )


def build_candidate(
    *,
    canonical_strategy_definition: dict[str, Any],
    parameter_values: dict[str, int | float | str | bool],
    feature_version: str,
    creation_timestamp: datetime,
) -> StrategyCandidate:
    """Build a candidate with deterministic strategy hash and candidate ID."""
    strategy_hash_value = strategy_hash(canonical_strategy_definition)
    return StrategyCandidate(
        candidate_id=candidate_id(strategy_hash_value, parameter_values),
        canonical_strategy_definition=canonical_strategy_definition,
        strategy_hash=strategy_hash_value,
        parameter_values=parameter_values,
        feature_version=feature_version,
        creation_timestamp=creation_timestamp,
    )


def build_experiment(
    *,
    strategy_hash_value: str,
    data_manifest_hash: str,
    feature_version: str,
    code_commit: str,
    configuration_hash: str,
    cost_model_version: str,
    simulation_level: SimulationLevel,
    start_timestamp: datetime,
    end_timestamp: datetime | None,
    random_seed: int,
    status: ExperimentStatus,
) -> ExperimentRun:
    """Build an experiment with a deterministic ID from reproducibility inputs."""
    return ExperimentRun(
        experiment_id=experiment_id(
            strategy_hash_value=strategy_hash_value,
            data_manifest_hash=data_manifest_hash,
            configuration_hash=configuration_hash,
            random_seed=random_seed,
        ),
        strategy_hash=strategy_hash_value,
        data_manifest_hash=data_manifest_hash,
        feature_version=feature_version,
        code_commit=code_commit,
        configuration_hash=configuration_hash,
        cost_model_version=cost_model_version,
        simulation_level=simulation_level,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        random_seed=random_seed,
        status=status,
    )

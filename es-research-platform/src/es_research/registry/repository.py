"""DuckDB-backed experiment registry with repository interfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import duckdb
from es_research.contracts import ExperimentRun, SimulationResult, StrategyCandidate
from es_research.manifests.models import DataManifest


class ExperimentRegistry(Protocol):
    def initialize(self) -> None: ...
    def upsert_candidate(self, candidate: StrategyCandidate) -> None: ...
    def insert_experiment(self, experiment: ExperimentRun) -> None: ...
    def insert_manifest(self, manifest: DataManifest) -> str: ...
    def insert_result(self, result: SimulationResult) -> None: ...
    def get_candidate(self, candidate_id: str) -> StrategyCandidate | None: ...
    def get_experiment(self, experiment_id: str) -> ExperimentRun | None: ...
    def get_result(self, experiment_id: str, candidate_id: str) -> SimulationResult | None: ...
    def get_manifest(self, manifest_hash: str) -> DataManifest | None: ...


class DuckDBExperimentRegistry:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.path))

    def initialize(self) -> None:
        with self._connect() as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR PRIMARY KEY)"
            )
            con.execute("INSERT OR IGNORE INTO schema_migrations VALUES ('phase1.v1')")
            con.execute(
                """CREATE TABLE IF NOT EXISTS candidates (
                    candidate_id VARCHAR PRIMARY KEY,
                    payload JSON NOT NULL
                )"""
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id VARCHAR PRIMARY KEY,
                    payload JSON NOT NULL
                )"""
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS simulation_results (
                    experiment_id VARCHAR NOT NULL,
                    candidate_id VARCHAR NOT NULL,
                    payload JSON NOT NULL,
                    PRIMARY KEY (experiment_id, candidate_id)
                )"""
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS manifests (
                    manifest_hash VARCHAR PRIMARY KEY,
                    payload JSON NOT NULL
                )"""
            )

    def upsert_candidate(self, candidate: StrategyCandidate) -> None:
        self.initialize()
        with self._connect() as con:
            con.execute(
                "INSERT OR IGNORE INTO candidates VALUES (?, ?)",
                [candidate.candidate_id, candidate.model_dump_json()],
            )

    def insert_experiment(self, experiment: ExperimentRun) -> None:
        self.initialize()
        with self._connect() as con:
            con.execute(
                "INSERT INTO experiments VALUES (?, ?)",
                [experiment.experiment_id, experiment.model_dump_json()],
            )

    def insert_manifest(self, manifest: DataManifest) -> str:
        self.initialize()
        manifest_hash = manifest.manifest_hash
        with self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO manifests VALUES (?, ?)",
                [manifest_hash, manifest.model_dump_json()],
            )
        return manifest_hash

    def insert_result(self, result: SimulationResult) -> None:
        self.initialize()
        with self._connect() as con:
            con.execute(
                "INSERT INTO simulation_results VALUES (?, ?, ?)",
                [result.experiment_id, result.candidate_id, result.model_dump_json()],
            )

    def _fetch_payload(self, table: str, where: str, params: list[str]) -> str | None:
        with self._connect() as con:
            row = con.execute(f"SELECT payload FROM {table} WHERE {where}", params).fetchone()
        return None if row is None else str(row[0])

    def get_candidate(self, candidate_id: str) -> StrategyCandidate | None:
        payload = self._fetch_payload("candidates", "candidate_id = ?", [candidate_id])
        return None if payload is None else StrategyCandidate.model_validate_json(payload)

    def get_experiment(self, experiment_id: str) -> ExperimentRun | None:
        payload = self._fetch_payload("experiments", "experiment_id = ?", [experiment_id])
        return None if payload is None else ExperimentRun.model_validate_json(payload)

    def get_result(self, experiment_id: str, candidate_id: str) -> SimulationResult | None:
        payload = self._fetch_payload(
            "simulation_results",
            "experiment_id = ? AND candidate_id = ?",
            [experiment_id, candidate_id],
        )
        return None if payload is None else SimulationResult.model_validate_json(payload)

    def get_manifest(self, manifest_hash: str) -> DataManifest | None:
        payload = self._fetch_payload("manifests", "manifest_hash = ?", [manifest_hash])
        return None if payload is None else DataManifest.model_validate_json(payload)

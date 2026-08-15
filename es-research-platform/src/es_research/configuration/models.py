from __future__ import annotations

from pathlib import Path

from pydantic import Field

from es_research.contracts import ContractModel
from es_research.hashing import sha256_hash


class RegistrySettings(ContractModel):
    path: Path = Path("data/registry/experiments.duckdb")


class ResearchConfiguration(ContractModel):
    registry: RegistrySettings = Field(default_factory=RegistrySettings)
    schema_version: str = "phase1.v1"
    cost_model_version: str = "zero_cost.v1"

    @property
    def configuration_hash(self) -> str:
        return sha256_hash(self)

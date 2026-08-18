"""Reproducibility manifest models."""

from __future__ import annotations

from datetime import datetime

from pydantic import field_validator

from es_research.contracts import ContractModel, require_utc
from es_research.hashing import sha256_hash


class SourceFileRecord(ContractModel):
    path: str
    sha256: str
    row_count: int
    min_timestamp: datetime
    max_timestamp: datetime

    _timestamps = field_validator("min_timestamp", "max_timestamp")(require_utc)


class DataManifest(ContractModel):
    source_files: tuple[SourceFileRecord, ...]
    schema_version: str
    generation_timestamp: datetime
    code_commit: str

    _generation_timestamp_utc = field_validator("generation_timestamp")(require_utc)

    @property
    def manifest_hash(self) -> str:
        return sha256_hash(self)

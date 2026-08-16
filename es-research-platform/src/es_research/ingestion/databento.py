"""Immutable Databento DBN bronze ingestion.

The adapter deliberately stores the vendor response before interpretation. Tests
inject a fake client, while production callers can pass ``databento.Historical``.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from es_research.contracts import require_utc


class DatabentoResponse(Protocol):
    def to_file(self, path: str) -> None: ...


class DatabentoTimeseries(Protocol):
    def get_range(self, **kwargs: object) -> DatabentoResponse: ...


class DatabentoHistoricalClient(Protocol):
    timeseries: DatabentoTimeseries


@dataclass(frozen=True)
class DatabentoRequest:
    dataset: str
    schema: str
    symbols: tuple[str, ...]
    start: datetime
    end: datetime
    stype_in: str = "parent"

    def __post_init__(self) -> None:
        start = require_utc(self.start)
        end = require_utc(self.end)
        if end <= start:
            raise ValueError("Databento request end must be after start")
        if not self.symbols:
            raise ValueError("Databento request requires at least one symbol")


@dataclass(frozen=True)
class BronzeArtifact:
    data_path: Path
    metadata_path: Path
    sha256: str
    byte_count: int


def ingest_databento_dbn(
    client: DatabentoHistoricalClient,
    request: DatabentoRequest,
    destination: Path,
) -> BronzeArtifact:
    """Download one DBN response atomically and refuse to mutate existing bronze data."""
    if destination.exists() or destination.with_suffix(destination.suffix + ".json").exists():
        raise FileExistsError(f"immutable bronze artifact already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    metadata_path = destination.with_suffix(destination.suffix + ".json")
    if temporary.exists():
        temporary.unlink()

    response = client.timeseries.get_range(
        dataset=request.dataset,
        schema=request.schema,
        symbols=list(request.symbols),
        stype_in=request.stype_in,
        start=require_utc(request.start).isoformat(),
        end=require_utc(request.end).isoformat(),
        encoding="dbn",
        compression="zstd",
    )
    response.to_file(str(temporary))
    if not temporary.is_file() or temporary.stat().st_size == 0:
        temporary.unlink(missing_ok=True)
        raise ValueError("Databento returned an empty bronze artifact")

    digest = _file_sha256(temporary)
    byte_count = temporary.stat().st_size
    os.replace(temporary, destination)
    metadata = {
        "byte_count": byte_count,
        "dataset": request.dataset,
        "end": require_utc(request.end).isoformat(),
        "schema": request.schema,
        "sha256": digest,
        "start": require_utc(request.start).isoformat(),
        "stype_in": request.stype_in,
        "symbols": list(request.symbols),
    }
    metadata_path.write_text(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return BronzeArtifact(destination, metadata_path, digest, byte_count)


def verify_bronze_artifact(artifact: BronzeArtifact) -> None:
    """Fail if an immutable bronze artifact no longer matches its recorded digest."""
    if not artifact.data_path.is_file():
        raise FileNotFoundError(f"bronze artifact does not exist: {artifact.data_path}")
    if artifact.data_path.stat().st_size != artifact.byte_count:
        raise ValueError("bronze artifact byte count changed")
    if _file_sha256(artifact.data_path) != artifact.sha256:
        raise ValueError("bronze artifact SHA-256 changed")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

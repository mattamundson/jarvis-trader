"""Deterministic cataloging of ThinkScript research sources.

Cataloging preserves provenance only. It does not treat a chart study as an
executable strategy, a validated Python port, or evidence of profitability.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from es_research.hashing import sha256_hash


@dataclass(frozen=True)
class ThinkScriptSource:
    source_id: str
    files: tuple[str, ...]
    file_hashes: tuple[str, ...]
    docs: str
    docs_hash: str
    status: str
    layer: int
    layer_name: str
    python_counterpart: str | None
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ThinkScriptCatalog:
    registry_version: int
    registry_generated: str
    registry_sha256: str
    source_count: int
    duplicate_count: int
    sources: tuple[ThinkScriptSource, ...]
    catalog_hash: str


def build_thinkscript_catalog(source_dir: Path) -> ThinkScriptCatalog:
    """Validate registry references and return a location-independent source catalog."""
    registry_path = source_dir / "registry.yaml"
    if not registry_path.is_file():
        raise FileNotFoundError(f"ThinkScript registry does not exist: {registry_path}")
    payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("ThinkScript registry must be a YAML object")
    scripts = payload.get("scripts")
    duplicates = payload.get("duplicates_to_skip", [])
    if not isinstance(scripts, list) or not scripts:
        raise ValueError("ThinkScript registry must contain a non-empty scripts list")
    if not isinstance(duplicates, list) or not all(isinstance(item, str) for item in duplicates):
        raise ValueError("duplicates_to_skip must be a list of paths")
    _validate_paths(source_dir, tuple(duplicates), "duplicate")

    sources = tuple(
        sorted((_parse_source(source_dir, item) for item in scripts), key=lambda x: x.source_id)
    )
    source_ids = [source.source_id for source in sources]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("ThinkScript registry contains duplicate source IDs")
    registry_version = int(payload.get("version", 0))
    registry_generated = str(payload.get("generated", ""))
    registry_sha256 = _file_sha256(registry_path)
    identity = {
        "duplicate_count": len(duplicates),
        "registry_generated": registry_generated,
        "registry_sha256": registry_sha256,
        "registry_version": registry_version,
        "sources": tuple(asdict(source) for source in sources),
    }
    return ThinkScriptCatalog(
        registry_version=registry_version,
        registry_generated=registry_generated,
        registry_sha256=registry_sha256,
        source_count=len(sources),
        duplicate_count=len(duplicates),
        sources=sources,
        catalog_hash=sha256_hash(identity),
    )


def write_thinkscript_catalog(catalog: ThinkScriptCatalog, path: Path) -> None:
    """Write canonical catalog JSON without embedding machine-specific paths."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(catalog), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )


def _parse_source(source_dir: Path, item: object) -> ThinkScriptSource:
    if not isinstance(item, dict):
        raise ValueError("each ThinkScript registry entry must be an object")
    source_id = _required_string(item, "id")
    raw_files = item.get("file")
    if isinstance(raw_files, str):
        files = (raw_files,)
    elif (
        isinstance(raw_files, list)
        and raw_files
        and all(isinstance(path, str) for path in raw_files)
    ):
        files = tuple(raw_files)
    else:
        raise ValueError(f"ThinkScript source {source_id!r} requires one or more files")
    _validate_paths(source_dir, files, f"source {source_id!r}")
    docs = _required_string(item, "docs")
    _validate_paths(source_dir, (docs,), f"documentation for {source_id!r}")
    parameters = item.get("tos_inputs", {})
    if not isinstance(parameters, dict):
        raise ValueError(f"ThinkScript source {source_id!r} tos_inputs must be an object")
    python_counterpart = item.get("python_counterpart")
    if python_counterpart is not None and not isinstance(python_counterpart, str):
        raise ValueError(f"ThinkScript source {source_id!r} has invalid python_counterpart")
    return ThinkScriptSource(
        source_id=source_id,
        files=files,
        file_hashes=tuple(_file_sha256(source_dir / path) for path in files),
        docs=docs,
        docs_hash=_file_sha256(source_dir / docs),
        status=_required_string(item, "status"),
        layer=int(item.get("layer", 0)),
        layer_name=_required_string(item, "layer_name"),
        python_counterpart=python_counterpart,
        parameters=dict(parameters),
    )


def _required_string(item: dict[str, Any], name: str) -> str:
    value = item.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"ThinkScript registry field {name!r} must be a non-empty string")
    return value.strip()


def _validate_paths(source_dir: Path, paths: tuple[str, ...], description: str) -> None:
    root = source_dir.resolve()
    for relative in paths:
        candidate = (source_dir / relative).resolve()
        if not candidate.is_relative_to(root):
            raise ValueError(f"{description} path escapes source directory: {relative}")
        if not candidate.is_file():
            raise FileNotFoundError(f"{description} file does not exist: {relative}")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

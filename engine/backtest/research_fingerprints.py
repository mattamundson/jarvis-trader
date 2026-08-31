"""Deterministic fingerprints for reproducible JARVIS research trials."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


class ResearchFingerprintError(ValueError):
    """Raised when a reproducible fingerprint cannot be produced."""


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    file_path = Path(path)
    if not file_path.is_file():
        raise ResearchFingerprintError(f"not a file: {file_path}")
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def dataframe_fingerprint(frame: pd.DataFrame, *, include_index: bool = True) -> str:
    """Fingerprint dataframe schema, order, index metadata, and values.

    ``pandas.util.hash_pandas_object`` supplies stable per-row value hashes; the
    SHA-256 wrapper also commits to column order/names/dtypes and index metadata.
    Row order is intentionally significant for time-series research.
    """
    if not isinstance(frame, pd.DataFrame):
        raise ResearchFingerprintError("frame must be a pandas DataFrame")

    metadata = {
        "columns": [str(column) for column in frame.columns],
        "dtypes": [str(dtype) for dtype in frame.dtypes],
        "index_type": type(frame.index).__name__,
        "index_name": str(frame.index.name),
        "index_dtype": str(frame.index.dtype),
        "index_tz": str(getattr(frame.index, "tz", None)),
        "shape": list(frame.shape),
        "include_index": include_index,
    }
    digest = hashlib.sha256(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    try:
        row_hashes = pd.util.hash_pandas_object(frame, index=include_index).to_numpy()
    except (TypeError, ValueError) as exc:
        raise ResearchFingerprintError("dataframe contains unhashable/noncanonical values") from exc
    digest.update(row_hashes.tobytes())
    return digest.hexdigest()


def manifest_fingerprint(
    paths: Iterable[str | Path],
    *,
    root: str | Path | None = None,
) -> str:
    """Fingerprint a set of files independent of caller-supplied path order."""
    root_path = Path(root).resolve() if root is not None else None
    entries: list[tuple[str, str]] = []
    for raw_path in paths:
        path = Path(raw_path).resolve()
        if not path.is_file():
            raise ResearchFingerprintError(f"not a file: {path}")
        if root_path is not None:
            try:
                label = path.relative_to(root_path).as_posix()
            except ValueError as exc:
                raise ResearchFingerprintError(f"file outside root: {path}") from exc
        else:
            label = path.as_posix()
        entries.append((label, sha256_file(path)))

    if not entries:
        raise ResearchFingerprintError("manifest must contain at least one file")
    canonical = json.dumps(sorted(entries), separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def research_context_fingerprint(
    *,
    data_fingerprint: str,
    registry_fingerprint: str,
    code_commit: str,
    configuration: dict[str, Any],
) -> str:
    """Fingerprint the reproducibility-critical context surrounding a trial."""
    for name, value in (
        ("data_fingerprint", data_fingerprint),
        ("registry_fingerprint", registry_fingerprint),
        ("code_commit", code_commit),
    ):
        if not str(value).strip():
            raise ResearchFingerprintError(f"{name} must be non-empty")
    payload = {
        "data_fingerprint": data_fingerprint,
        "registry_fingerprint": registry_fingerprint,
        "code_commit": code_commit,
        "configuration": configuration,
    }
    try:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ResearchFingerprintError("configuration must be JSON-serializable") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

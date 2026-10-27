"""Fail-closed guard for retired research families.

This module is analysis-only. It has no runtime config, broker, signal-routing,
risk, or order-management imports.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path(__file__).with_name("negative_results_registry.json")


class RetiredResearchError(ValueError):
    """Raised when a rejected family is reused without a complete new freeze."""


@dataclass(frozen=True)
class ReopenAuthorization:
    candidate_id: str
    preregistration_id: str
    material_change: str
    locked_evaluation_window_id: str


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    retired = payload.get("retired_results")
    if payload.get("schema_version") != "1.0.0" or not isinstance(retired, list):
        raise ValueError("invalid negative-result registry schema")
    ids = [row.get("candidate_id") for row in retired]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("negative-result candidate ids must be unique and non-empty")
    if any(row.get("verdict") != "REJECT" for row in retired):
        raise ValueError("negative-result registry may contain only REJECT verdicts")
    return payload


def retired_result(candidate_id: str, path: Path = REGISTRY_PATH) -> dict[str, Any] | None:
    for row in load_registry(path)["retired_results"]:
        if row["candidate_id"] == candidate_id:
            return row
    return None


def assert_reopen_allowed(
    candidate_id: str,
    *,
    preregistration_id: str | None = None,
    material_change: str | None = None,
    locked_evaluation_window_id: str | None = None,
    reuses_rejected_oos_for_optimization: bool = False,
    path: Path = REGISTRY_PATH,
) -> ReopenAuthorization | None:
    """Fail closed when a rejected candidate is silently resurrected.

    Unknown candidates are not blocked by this registry. A known retired candidate
    requires all four independent reopening conditions from the durable contract.
    """
    row = retired_result(candidate_id, path)
    if row is None:
        return None

    missing = [
        field
        for field, value in (
            ("preregistration_id", preregistration_id),
            ("material_change", material_change),
            ("locked_evaluation_window_id", locked_evaluation_window_id),
        )
        if not value or not value.strip()
    ]
    if missing:
        raise RetiredResearchError(
            f"{candidate_id} is retired; missing reopening evidence: {', '.join(missing)}"
        )
    if reuses_rejected_oos_for_optimization:
        raise RetiredResearchError(
            f"{candidate_id} is retired; its rejected OOS window cannot be reused for optimization"
        )

    return ReopenAuthorization(
        candidate_id=candidate_id,
        preregistration_id=preregistration_id.strip(),
        material_change=material_change.strip(),
        locked_evaluation_window_id=locked_evaluation_window_id.strip(),
    )

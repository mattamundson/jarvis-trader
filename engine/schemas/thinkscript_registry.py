"""Pydantic models for the ThinkScript registry endpoint."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# "ported"/"orphan"/"deprecated"/"reference_only" describe migration lineage
# (ThinkScript -> Python port history). "active"/"experimental" describe the
# reverse direction: JARVIS-authored TOS scripts mirroring already-live Python
# engine logic (jarvis-suite/*), where python_counterpart is the canonical
# source of truth and the .ts file is a chart-side view of it.
ScriptStatus = Literal["ported", "orphan", "deprecated", "reference_only", "active", "experimental"]
Panel = Literal["upper", "lower"]


class ScriptRegistryEntry(BaseModel):
    id: str
    file: str | list[str] = Field(description="Single .ts file or list for consolidated entries")
    docs: str
    author: str
    layer: int = Field(ge=0, le=5, description="0 = supporting, 1-5 = JARVIS layers")
    layer_name: str
    status: ScriptStatus
    python_counterpart: str | None = None
    panel: Panel | None = None
    jarvis_signals: list[str] = Field(default_factory=list)
    tos_inputs: dict[str, object] = Field(default_factory=dict)


class ScriptRegistry(BaseModel):
    version: int
    generated: str
    source_of_truth: dict[str, str]
    duplicates_to_skip: list[str]
    scripts: list[ScriptRegistryEntry]


class ScriptWithDocs(BaseModel):
    entry: ScriptRegistryEntry
    doc_markdown: str

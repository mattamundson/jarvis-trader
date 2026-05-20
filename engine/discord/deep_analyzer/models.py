"""Pydantic v2 result types for deep_analyzer."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ArtifactType(StrEnum):
    TEXT = "text"
    URL = "url"
    X_POST = "x_post"
    IMAGE = "image"
    AUDIO = "audio"
    DOCUMENT = "document"


class LLMUsage(BaseModel):
    model_config = ConfigDict(frozen=True)
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class AnalysisResult(BaseModel):
    """A single artifact's analysis output. Persisted to discord_analyses."""

    model_config = ConfigDict(frozen=True)

    bookmark_id: str
    artifact_type: ArtifactType
    summary: str
    structured: dict[str, Any] = Field(default_factory=dict)
    model_used: str
    usage: LLMUsage
    cost_usd: float
    vault_path: str | None = None
    gbrain_chunk_ids: list[str] = Field(default_factory=list)
    error_text: str | None = None

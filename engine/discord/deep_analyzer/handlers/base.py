"""Handler protocol for artifact-specific analyzers."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..models import AnalysisResult


@runtime_checkable
class Handler(Protocol):
    """All handlers expose the same async entry point.

    The runner passes the row dict (from discord_bookmarks) and gets back
    a fully-formed AnalysisResult (or raises on permanent failure).
    """

    async def analyze(self, row: dict[str, Any]) -> AnalysisResult: ...

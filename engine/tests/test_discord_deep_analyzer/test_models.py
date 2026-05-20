"""Tests for deep_analyzer.models."""

import pytest
from pydantic import ValidationError

from discord.deep_analyzer.models import AnalysisResult, ArtifactType, LLMUsage


def test_analysis_result_minimal_construction():
    r = AnalysisResult(
        bookmark_id="m1",
        artifact_type=ArtifactType.TEXT,
        summary="hi",
        structured={},
        model_used="gemini-2.5-flash",
        usage=LLMUsage(input_tokens=10, output_tokens=5),
        cost_usd=0.0001,
    )
    assert r.bookmark_id == "m1"
    assert r.artifact_type == "text"


def test_artifact_type_rejects_unknown():
    with pytest.raises(ValidationError):
        AnalysisResult(
            bookmark_id="m1",
            artifact_type="unknown",  # type: ignore[arg-type]
            summary="x",
            structured={},
            model_used="m",
            usage=LLMUsage(input_tokens=0, output_tokens=0),
            cost_usd=0,
        )


def test_llm_usage_total_tokens():
    u = LLMUsage(input_tokens=10, output_tokens=20)
    assert u.total_tokens == 30

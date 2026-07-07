"""Regression: every vault writer resolves its root through the single canonical
resolver (vault.paths.vault_root), which honours JARVIS_VAULT_ROOT.

Guards the F2 fix — the deep_analyzer writers previously fell back to their own
duplicated ``~/my-vault`` constants and silently ignored JARVIS_VAULT_ROOT, so
setting the override moved the /vault jobs but left bookmark/digest pages behind
in a different root (path fragmentation). These assert the override now flows
through to the actual write.
"""

from __future__ import annotations

from pathlib import Path

from discord.deep_analyzer.models import AnalysisResult, ArtifactType, LLMUsage
from discord.deep_analyzer.vault import write_page
from vault.paths import vault_root


def _result() -> AnalysisResult:
    return AnalysisResult(
        bookmark_id="bm123",
        artifact_type=ArtifactType.X_POST,
        summary="test tweet",
        structured={"tickers": ["MES"]},
        model_used="test",
        usage=LLMUsage(input_tokens=1, output_tokens=1),
        cost_usd=0.0,
    )


def test_deep_analyzer_vault_honours_jarvis_vault_root(monkeypatch, tmp_path):
    override = tmp_path / "unified-vault"
    monkeypatch.setenv("JARVIS_VAULT_ROOT", str(override))

    # resolver sees the override
    assert vault_root() == override

    # write_page with no explicit root must fall back to the canonical resolver
    path = write_page(
        result=_result(),
        posted_at="2026-06-01T12:00:00Z",
        slug_source="test tweet",
        discord_url="https://discord.example/x",
    )

    assert override in path.parents, f"{path} not under override {override}"
    assert path.exists() and path.read_text(encoding="utf-8")
    # and NOT under the old duplicated default
    assert Path.home() / "my-vault" not in path.parents


def test_explicit_root_arg_still_wins(tmp_path):
    """An explicit vault_root arg overrides the resolver (unchanged behaviour)."""
    explicit = tmp_path / "explicit"
    path = write_page(
        result=_result(),
        posted_at="2026-06-01T12:00:00Z",
        slug_source="test tweet",
        discord_url="https://discord.example/x",
        vault_root=explicit,
    )
    assert explicit in path.parents

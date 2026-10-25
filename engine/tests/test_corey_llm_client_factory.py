"""
Tests for build_default_llm_client — the standalone-surface LLM client factory.

Why this exists: the MCP server, the `discord.cli --trigger-commentary` refresh,
and corey_compare construct CoreyCommentaryProcessor with NO llm_client, so they
fell through to a raw httpx POST against api.anthropic.com. When that account's
credit was exhausted (2026-06-29), every standalone Corey session-bias extraction
silently degraded to data_quality='none' — while the live engine, which routes
through JarvisLLMClient's Vertex/Gemini/OpenAI failover chain, stayed healthy.

build_default_llm_client() gives the standalone surfaces the same resilient
client. Contract:
  - returns a JarvisLLMClient anchored at engine/data/llm_costs.db (next to the
    Corey commentary DB), so the cost ledger isn't scattered by cwd; and
  - returns None (never raises) if the client can't be built, so callers degrade
    to the existing direct-POST path instead of crashing.
"""

from __future__ import annotations

import os

import discord.commentary_processor as cp


def test_build_default_llm_client_anchors_cost_db_next_to_commentary_db(monkeypatch):
    """The client's cost DB lives beside the passed commentary DB, named llm_costs.db."""
    captured = {}

    class FakeClient:
        def __init__(self, api_key=None, db_path=None):
            captured["api_key"] = api_key
            captured["db_path"] = db_path

    monkeypatch.setattr("llm.client.JarvisLLMClient", FakeClient)

    client = cp.build_default_llm_client(os.path.join("X:", "engine", "data", "jarvis_trader.db"))

    assert isinstance(client, FakeClient)
    assert os.path.basename(captured["db_path"]) == "llm_costs.db"
    # Anchored in the SAME directory as the commentary DB, not cwd-relative.
    assert os.path.dirname(captured["db_path"]) == os.path.join("X:", "engine", "data")


def test_build_default_llm_client_degrades_to_none_on_construction_error(monkeypatch):
    """A construction failure returns None (caller falls back to direct POST), never raises."""

    def boom(*args, **kwargs):
        raise RuntimeError("no LLM providers reachable")

    monkeypatch.setattr("llm.client.JarvisLLMClient", boom)

    assert cp.build_default_llm_client() is None


def test_build_default_llm_client_passes_anthropic_key_from_env(monkeypatch):
    """The Anthropic key is sourced from env so the client's failover chain can use it."""
    captured = {}

    class FakeClient:
        def __init__(self, api_key=None, db_path=None):
            captured["api_key"] = api_key

    monkeypatch.setattr("llm.client.JarvisLLMClient", FakeClient)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sentinel-key")

    cp.build_default_llm_client()

    assert captured["api_key"] == "sentinel-key"


def test_build_default_llm_client_resolves_when_run_as_engine_package():
    """Package-qualified callers (``python -m engine.discord.cli`` from the repo root,
    as Jarvis-DiscordAutoImport runs it) must still get a client.

    Regression: engine/ is not on sys.path in that invocation, so the bare
    ``from llm.client import ...`` raised ModuleNotFoundError, the factory returned
    None, and every scheduled Corey extraction fell back to the direct Anthropic
    POST (dead credit) -> data_quality='none' since 2026-10-02.
    """
    import subprocess
    import sys

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    probe = (
        "from engine.discord.commentary_processor import build_default_llm_client; "
        "c = build_default_llm_client(); "
        "print(type(c).__name__)"
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "JarvisLLMClient", result.stderr

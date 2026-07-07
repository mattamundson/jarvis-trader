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

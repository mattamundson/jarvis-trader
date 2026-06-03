"""Unit tests for the Vertex-aware Anthropic client factory.

These tests patch the anthropic SDK client classes, so they verify provider
dispatch + model-id translation logic WITHOUT any GCP/ADC credentials or
network access — they run green before the Vertex auth gate is satisfied.
"""

import anthropic
import pytest

from llm import provider_factory as pf

# --- provider dispatch ------------------------------------------------------

def test_ollama_returns_none(monkeypatch):
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", "ollama")
    assert pf.get_anthropic_client(api_key="ignored") is None


def test_direct_anthropic_uses_api_key(monkeypatch):
    captured = {}

    class FakeDirect:
        def __init__(self, api_key=None):
            captured["api_key"] = api_key

    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeDirect)
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", "anthropic")

    client = pf.get_anthropic_client(api_key="sk-test-123")
    assert isinstance(client, FakeDirect)
    assert captured["api_key"] == "sk-test-123"


def test_vertex_client_uses_project_and_region(monkeypatch):
    captured = {}

    class FakeVertex:
        def __init__(self, project_id=None, region=None):
            captured["project_id"] = project_id
            captured["region"] = region

    monkeypatch.setattr(anthropic, "AsyncAnthropicVertex", FakeVertex)
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", "vertex")
    monkeypatch.setenv("ANTHROPIC_VERTEX_PROJECT_ID", "proj-explicit")
    monkeypatch.setenv("ANTHROPIC_VERTEX_REGION", "us-east5")

    client = pf.get_anthropic_client(api_key="should-be-ignored")
    assert isinstance(client, FakeVertex)
    assert captured["project_id"] == "proj-explicit"
    assert captured["region"] == "us-east5"


def test_explicit_provider_arg_overrides_env(monkeypatch):
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", "ollama")
    assert pf.resolve_provider("VERTEX") == "vertex"
    assert pf.is_vertex_enabled("vertex") is True
    assert pf.is_vertex_enabled("anthropic") is False


# --- project / region defaults ---------------------------------------------

def test_vertex_defaults_when_env_unset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_VERTEX_PROJECT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("ANTHROPIC_VERTEX_REGION", raising=False)
    assert pf.get_vertex_project() == "jarvis-trading-493009"
    # Claude on Vertex must default to us-east5, NOT the Gemini region.
    assert pf.get_vertex_region() == "us-east5"


def test_google_cloud_project_fallback(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_VERTEX_PROJECT_ID", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj-from-gcp-env")
    assert pf.get_vertex_project() == "proj-from-gcp-env"


# --- model-id translation ---------------------------------------------------

def test_model_translation_default_map(monkeypatch):
    monkeypatch.delenv("JARVIS_VERTEX_MODEL_MAP", raising=False)
    # Verified against the live Vertex Model Garden catalog 2026-06-03.
    assert pf.to_vertex_model_id("claude-sonnet-4-6") == "claude-sonnet-4-6@default"
    assert pf.to_vertex_model_id("claude-haiku-4-5-20251001") == "claude-haiku-4-5@20251001"
    assert pf.to_vertex_model_id("claude-opus-4-8") == "claude-opus-4-8@default"


def test_model_translation_passthrough_on_unknown(monkeypatch):
    monkeypatch.delenv("JARVIS_VERTEX_MODEL_MAP", raising=False)
    # Unmapped model is returned verbatim -> surfaces an explicit Vertex 404
    # rather than silently substituting a different model.
    assert pf.to_vertex_model_id("some-future-model") == "some-future-model"


def test_model_translation_env_override_wins(monkeypatch):
    monkeypatch.setenv(
        "JARVIS_VERTEX_MODEL_MAP",
        "claude-sonnet-4-6=claude-sonnet-4-5@99999999,foo=bar@1",
    )
    assert pf.to_vertex_model_id("claude-sonnet-4-6") == "claude-sonnet-4-5@99999999"
    assert pf.to_vertex_model_id("foo") == "bar@1"


def test_model_translation_empty_input(monkeypatch):
    assert pf.to_vertex_model_id("") == ""


def test_env_map_parser_skips_malformed(monkeypatch):
    monkeypatch.setenv("JARVIS_VERTEX_MODEL_MAP", "  , bad-entry , a=b , =c , d= ")
    # Only "a=b" is well-formed.
    assert pf.to_vertex_model_id("a") == "b"
    assert pf.to_vertex_model_id("d") == "d"  # blank value -> ignored -> passthrough

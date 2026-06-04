"""
Smoke tests locking in the Vertex-routing default-off invariants and guarding
the constructor-regression class that reddened the integration branch.

The vertex branch had briefly made JarvisLLMClient.__init__(api_key) a REQUIRED
positional arg; vision_analyst's `JarvisLLMClient()` fallback and ~40 fixtures
then raised TypeError. test_vertex_routing.py exercises the transport but always
passes api_key=..., so it would NOT have caught that regression. These tests
construct with NO api_key and assert the provider dispatch stays off-by-default
without any GCP credentials or network access.
"""

from __future__ import annotations

from types import SimpleNamespace

import anthropic
import pytest

from llm import JarvisLLMClient
from llm import provider_factory as pf


@pytest.fixture
def temp_db(tmp_path):
    return str(tmp_path / "llm_costs.db")


# ── Regression guard: no-arg api_key must still construct ──────────────────────

def test_client_constructs_without_api_key_argument(monkeypatch, temp_db):
    # The exact regression: JarvisLLMClient() with no api_key must not raise.
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda api_key=None: SimpleNamespace())
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", "anthropic")
    # No api_key passed — only db_path, to keep the cost DB out of the real tree.
    client = JarvisLLMClient(db_path=temp_db)
    assert client.provider == "anthropic"
    assert client.client is not None


def test_ollama_default_provider_needs_no_sdk_client(monkeypatch, temp_db):
    # With the provider unset, resolve_provider defaults to ollama → no SDK
    # client is built and no api_key is required.
    monkeypatch.delenv("JARVIS_LLM_PROVIDER", raising=False)
    client = JarvisLLMClient(db_path=temp_db)
    assert client.provider == "ollama"
    assert client.client is None


# ── Default-off invariants: no vertex/shadow/failover/gemini-vertex by default ─

def test_vertex_features_all_off_by_default(monkeypatch, temp_db):
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda api_key=None: SimpleNamespace())
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", "anthropic")
    for flag in (
        "JARVIS_LLM_VERTEX_SHADOW",
        "JARVIS_LLM_VERTEX_FAILOVER",
        "JARVIS_GEMINI_USE_VERTEX",
    ):
        monkeypatch.delenv(flag, raising=False)

    client = JarvisLLMClient(api_key="k", db_path=temp_db)
    assert client.vertex_shadow_enabled is False
    assert client.vertex_failover_enabled is False
    assert client.gemini_use_vertex is False
    assert client._shadow_vertex_client is None
    assert client._aux_vertex_client is None


# ── provider_factory dispatch ─────────────────────────────────────────────────

def test_resolve_provider_defaults_to_ollama(monkeypatch):
    monkeypatch.delenv("JARVIS_LLM_PROVIDER", raising=False)
    assert pf.resolve_provider() == "ollama"
    assert pf.resolve_provider("Vertex") == "vertex"  # normalized


def test_is_vertex_enabled_only_when_flag_set(monkeypatch):
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", "anthropic")
    assert pf.is_vertex_enabled() is False
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", "vertex")
    assert pf.is_vertex_enabled() is True


def test_get_anthropic_client_dispatch(monkeypatch):
    built = {}

    class FakeDirect:
        def __init__(self, api_key=None):
            built["kind"] = "direct"

    class FakeVertex:
        def __init__(self, project_id=None, region=None):
            built["kind"] = "vertex"

    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeDirect)
    monkeypatch.setattr(anthropic, "AsyncAnthropicVertex", FakeVertex)

    # ollama → no SDK client at all
    assert pf.get_anthropic_client(provider="ollama") is None
    # direct → AsyncAnthropic
    assert isinstance(pf.get_anthropic_client(provider="anthropic"), FakeDirect)
    # vertex → AsyncAnthropicVertex (only when explicitly selected)
    monkeypatch.setenv("ANTHROPIC_VERTEX_PROJECT_ID", "p")
    assert isinstance(pf.get_anthropic_client(provider="vertex"), FakeVertex)

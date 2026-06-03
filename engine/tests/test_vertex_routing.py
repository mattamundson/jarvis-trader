"""Task 3 tests: Vertex routing + shadow mode in JarvisLLMClient.

All Anthropic/Vertex SDK classes are monkeypatched, so these verify the
provider dispatch, model-id translation, and shadow A/B wiring WITHOUT any GCP
credentials or network access. pytest runs in asyncio auto mode, so async tests
need no explicit marker.
"""

from types import SimpleNamespace

import anthropic
import pytest

from llm import JarvisLLMClient


@pytest.fixture
def temp_db(tmp_path):
    return str(tmp_path / "llm_costs.db")


def _resp(text, in_tok=3, out_tok=4):
    return SimpleNamespace(
        usage=SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok),
        content=[SimpleNamespace(text=text)],
    )


def test_vertex_provider_builds_vertex_client(monkeypatch, temp_db):
    captured = {}

    class FakeVertex:
        def __init__(self, project_id=None, region=None):
            captured["project_id"] = project_id
            captured["region"] = region

    monkeypatch.setattr(anthropic, "AsyncAnthropicVertex", FakeVertex)
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", "vertex")
    monkeypatch.setenv("ANTHROPIC_VERTEX_PROJECT_ID", "proj-x")
    monkeypatch.setenv("ANTHROPIC_VERTEX_REGION", "us-east5")

    client = JarvisLLMClient(api_key="unused-on-vertex", db_path=temp_db)
    assert isinstance(client.client, FakeVertex)
    assert captured["project_id"] == "proj-x"
    assert captured["region"] == "us-east5"


async def test_call_with_retry_translates_model_for_vertex(monkeypatch, temp_db):
    captured = {}

    class FakeMessages:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return _resp("ok")

    class FakeVertex:
        def __init__(self, project_id=None, region=None):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "AsyncAnthropicVertex", FakeVertex)
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", "vertex")
    monkeypatch.delenv("JARVIS_VERTEX_MODEL_MAP", raising=False)

    client = JarvisLLMClient(api_key="unused", db_path=temp_db)
    await client._call_with_retry(
        model="claude-sonnet-4-6",
        system="s",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=16,
        temperature=0.5,
        agent_name="t",
    )
    # The wire call must use the translated Vertex @-pinned id.
    assert captured["model"] == "claude-sonnet-4-5@20250929"
    await client.close()


async def test_no_translation_for_direct_provider(monkeypatch, temp_db):
    captured = {}

    class FakeMessages:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return _resp("ok")

    class FakeDirect:
        def __init__(self, api_key=None):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeDirect)
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", "anthropic")

    client = JarvisLLMClient(api_key="k", db_path=temp_db)
    await client._call_with_retry(
        model="claude-sonnet-4-6",
        system="s",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=16,
        temperature=0.5,
        agent_name="t",
    )
    # Direct path is untouched — the alias goes out verbatim.
    assert captured["model"] == "claude-sonnet-4-6"
    await client.close()


def test_shadow_disabled_when_provider_is_vertex(monkeypatch, temp_db):
    class FakeVertex:
        def __init__(self, project_id=None, region=None):
            self.messages = SimpleNamespace()

    monkeypatch.setattr(anthropic, "AsyncAnthropicVertex", FakeVertex)
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", "vertex")
    monkeypatch.setenv("JARVIS_LLM_VERTEX_SHADOW", "1")

    client = JarvisLLMClient(api_key="x", db_path=temp_db)
    # Shadow makes no sense when vertex is already primary.
    assert client.vertex_shadow_enabled is False
    assert client._shadow_vertex_client is None


async def test_shadow_mode_fires_translated_vertex_call(monkeypatch, temp_db):
    primary_calls = {}
    shadow_calls = {}

    class FakeDirectMessages:
        async def create(self, **kwargs):
            primary_calls.update(kwargs)
            return _resp("primary-answer")

    class FakeDirect:
        def __init__(self, api_key=None):
            self.messages = FakeDirectMessages()

    class FakeVertexMessages:
        async def create(self, **kwargs):
            shadow_calls.update(kwargs)
            return _resp("shadow-answer")

    class FakeVertex:
        def __init__(self, project_id=None, region=None):
            self.messages = FakeVertexMessages()

    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeDirect)
    monkeypatch.setattr(anthropic, "AsyncAnthropicVertex", FakeVertex)
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("JARVIS_LLM_VERTEX_SHADOW", "1")
    monkeypatch.delenv("JARVIS_VERTEX_MODEL_MAP", raising=False)
    # Ensure the Gemini-primary branch is inert so the direct path runs.
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # Disable the module-level TokenProxy cache so the call hits the real path
    # (the cache is a singleton shared across tests and would short-circuit).
    monkeypatch.setattr("llm.client._TOKEN_PROXY_AVAILABLE", False)

    client = JarvisLLMClient(api_key="k", db_path=temp_db)
    assert client.vertex_shadow_enabled is True
    assert client._shadow_vertex_client is not None

    result = await client.call(
        model="claude-sonnet-4-6",
        system="s",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=16,
        agent_name="trader",  # decision agent — not a Gemini-primary agent
        temperature=0.5,
        compact=False,
    )
    # Primary result is the direct one, unaffected by the shadow.
    assert result.success is True
    assert result.content == "primary-answer"

    # Let the fire-and-forget shadow task complete.
    import asyncio

    await asyncio.sleep(0.05)
    assert shadow_calls.get("model") == "claude-sonnet-4-5@20250929"
    assert client.vertex_shadow_count == 1
    await client.close()


# --- Task 5: Vertex failover on credit-exhaustion ---------------------------

def test_failover_disabled_by_default(monkeypatch, temp_db):
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda api_key=None: SimpleNamespace())
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("JARVIS_LLM_VERTEX_FAILOVER", raising=False)
    monkeypatch.delenv("JARVIS_LLM_VERTEX_SHADOW", raising=False)

    client = JarvisLLMClient(api_key="k", db_path=temp_db)
    # Off by default (gated-flip): no aux Vertex client is even built.
    assert client.vertex_failover_enabled is False
    assert client._aux_vertex_client is None


async def test_credit_exhaustion_fails_over_to_vertex(monkeypatch, temp_db):
    vertex_calls = {}

    class FakeDirectMessages:
        async def create(self, **kwargs):
            raise Exception("Your credit balance is too low to access the Anthropic API")

    class FakeDirect:
        def __init__(self, api_key=None):
            self.messages = FakeDirectMessages()

    class FakeVertexMessages:
        async def create(self, **kwargs):
            vertex_calls.update(kwargs)
            return _resp("vertex-rescue")

    class FakeVertex:
        def __init__(self, project_id=None, region=None):
            self.messages = FakeVertexMessages()

    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeDirect)
    monkeypatch.setattr(anthropic, "AsyncAnthropicVertex", FakeVertex)
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("JARVIS_LLM_VERTEX_FAILOVER", "1")
    monkeypatch.setenv("JARVIS_LLM_VERTEX_SHADOW", "0")
    monkeypatch.delenv("JARVIS_VERTEX_MODEL_MAP", raising=False)
    # Disable the Gemini fallback so we prove the VERTEX path served the call.
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # Disable the module-level TokenProxy cache so the call hits the real path.
    monkeypatch.setattr("llm.client._TOKEN_PROXY_AVAILABLE", False)

    client = JarvisLLMClient(api_key="k", db_path=temp_db)
    assert client.vertex_failover_enabled is True

    result = await client.call(
        model="claude-sonnet-4-6",
        system="s",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=16,
        agent_name="trader",
        temperature=0.5,
        compact=False,
    )
    # Direct path was credit-exhausted; Vertex rescued the call transparently.
    assert result.success is True
    assert result.content == "vertex-rescue"
    # Cost/logging stay keyed on the direct alias, not the Vertex id.
    assert result.model == "claude-sonnet-4-6"
    # The wire call used the translated Vertex @-pinned id.
    assert vertex_calls.get("model") == "claude-sonnet-4-5@20250929"
    assert client.vertex_failover_count == 1
    await client.close()


# --- Task 6: Gemini-on-Vertex for the analyst tier --------------------------

async def test_analyst_routes_to_vertex_gemini(monkeypatch, temp_db):
    from google import genai

    captured = {}

    class FakeModels:
        def generate_content(self, model=None, contents=None, config=None):
            captured["model"] = model
            captured["contents"] = contents
            return SimpleNamespace(
                text="gemini-vertex-answer",
                usage_metadata=SimpleNamespace(
                    prompt_token_count=11, candidates_token_count=22
                ),
            )

    class FakeGenaiClient:
        def __init__(self, vertexai=None, project=None, location=None):
            captured["vertexai"] = vertexai
            captured["project"] = project
            captured["location"] = location
            self.models = FakeModels()

    monkeypatch.setattr(genai, "Client", FakeGenaiClient)
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda api_key=None: SimpleNamespace())
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("JARVIS_GEMINI_USE_VERTEX", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj-g")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    monkeypatch.setattr("llm.client._TOKEN_PROXY_AVAILABLE", False)
    # No AI-Studio key — Vertex Gemini must work without it.
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    client = JarvisLLMClient(api_key="k", db_path=temp_db)
    assert client.gemini_use_vertex is True
    # Vertex Gemini counts as "gemini available" even with no AI-Studio key.
    assert client.gemini_enabled is True

    result = await client.call(
        model="claude-sonnet-4-6",
        system="sys",
        messages=[{"role": "user", "content": "analyze"}],
        max_tokens=32,
        agent_name="news_analyst",  # a GEMINI_PRIMARY_AGENT
        temperature=0.3,
        compact=False,
    )
    assert result.success is True
    assert result.content == "gemini-vertex-answer"
    assert result.model == "gemini-2.5-flash"  # GOOGLE_FAILOVER_MAP[sonnet]
    assert result.input_tokens == 11 and result.output_tokens == 22
    # Confirm it went through the Vertex genai client, not the AI-Studio endpoint.
    assert captured["vertexai"] is True
    assert captured["project"] == "proj-g"
    assert captured["location"] == "us-central1"
    assert captured["model"] == "gemini-2.5-flash"
    await client.close()

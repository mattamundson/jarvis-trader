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

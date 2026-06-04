"""
Test suite for the Claude-on-Vertex transport in JarvisLLMClient.

Covers (Phase 3.5, 2026-06-03):
- Flag OFF (default): use_vertex False, client is the direct AsyncAnthropic,
  and the wire-point model name is unchanged (byte-identical to pre-Vertex).
- Flag ON: use_vertex True, client is AsyncAnthropicVertex (mocked to avoid ADC).
- JARVIS_VERTEX_MODEL_MAP parsing (direct -> Vertex publisher @version IDs).
- Wire-point translation: with Vertex active, _call_with_retry sends the mapped
  model to messages.create while cost/logging keep the direct name.
"""

from unittest.mock import AsyncMock, MagicMock

import anthropic
import pytest

from llm import JarvisLLMClient


def _make_client(tmp_path, monkeypatch, **env):
    """Construct a JarvisLLMClient with a clean Vertex-relevant env."""
    # Default the provider to anthropic so the Vertex branch is reachable;
    # individual tests override via env kwargs.
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", env.pop("JARVIS_LLM_PROVIDER", "anthropic"))
    for key in (
        "JARVIS_CLAUDE_USE_VERTEX",
        "JARVIS_VERTEX_MODEL_MAP",
        "ANTHROPIC_VERTEX_PROJECT_ID",
        "ANTHROPIC_VERTEX_REGION",
        "JARVIS_LLM_VERTEX_FAILOVER",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, val in env.items():
        monkeypatch.setenv(key, val)
    db_path = str(tmp_path / "vertex_costs.db")
    return JarvisLLMClient(api_key="test-key-12345", db_path=db_path)


class TestVertexFlagOff:
    """Default behavior must be unchanged when the flag is absent/false."""

    def test_flag_absent_uses_direct_anthropic(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        assert client.use_vertex is False
        assert isinstance(client.client, anthropic.AsyncAnthropic)
        assert not isinstance(client.client, anthropic.AsyncAnthropicVertex)

    def test_flag_false_uses_direct_anthropic(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch, JARVIS_CLAUDE_USE_VERTEX="false")
        assert client.use_vertex is False
        assert isinstance(client.client, anthropic.AsyncAnthropic)

    def test_ollama_provider_never_uses_vertex(self, tmp_path, monkeypatch):
        client = _make_client(
            tmp_path,
            monkeypatch,
            JARVIS_LLM_PROVIDER="ollama",
            JARVIS_CLAUDE_USE_VERTEX="1",
        )
        assert client.use_vertex is False
        assert client.client is None


class TestVertexFlagOn:
    """Flag ON routes through AsyncAnthropicVertex (mocked to avoid ADC)."""

    def test_flag_on_builds_vertex_client(self, tmp_path, monkeypatch):
        sentinel = MagicMock(name="AsyncAnthropicVertexInstance")
        fake_ctor = MagicMock(return_value=sentinel)
        monkeypatch.setattr(anthropic, "AsyncAnthropicVertex", fake_ctor)

        client = _make_client(
            tmp_path,
            monkeypatch,
            JARVIS_CLAUDE_USE_VERTEX="1",
            ANTHROPIC_VERTEX_PROJECT_ID="jarvis-trading-493009",
            ANTHROPIC_VERTEX_REGION="us-east5",
        )

        assert client.use_vertex is True
        assert client.client is sentinel
        fake_ctor.assert_called_once_with(
            project_id="jarvis-trading-493009", region="us-east5"
        )

    def test_flag_on_without_project_omits_kwargs(self, tmp_path, monkeypatch):
        fake_ctor = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(anthropic, "AsyncAnthropicVertex", fake_ctor)

        _make_client(tmp_path, monkeypatch, JARVIS_CLAUDE_USE_VERTEX="1")

        # No project/region env -> rely on ADC defaults, pass no kwargs.
        fake_ctor.assert_called_once_with()


class TestVertexModelMap:
    """JARVIS_VERTEX_MODEL_MAP parses direct->Vertex IDs; bad entries skipped."""

    def test_map_parsing(self, tmp_path, monkeypatch):
        fake_ctor = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(anthropic, "AsyncAnthropicVertex", fake_ctor)
        client = _make_client(
            tmp_path,
            monkeypatch,
            JARVIS_CLAUDE_USE_VERTEX="1",
            JARVIS_VERTEX_MODEL_MAP=(
                "claude-sonnet-4-6=claude-sonnet-4-5@20250929,"
                "claude-haiku-4-5-20251001=claude-haiku-4-5@20251001,"
                "garbage-no-eq,"
                "  =skipme"
            ),
        )
        assert client.vertex_model_map == {
            "claude-sonnet-4-6": "claude-sonnet-4-5@20250929",
            "claude-haiku-4-5-20251001": "claude-haiku-4-5@20251001",
        }

    def test_map_empty_by_default(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        assert client.vertex_model_map == {}


class TestWirePointTranslation:
    """_call_with_retry sends the mapped model only when Vertex is active."""

    @pytest.mark.asyncio
    async def test_translates_model_when_vertex_on(self, tmp_path, monkeypatch):
        fake_ctor = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(anthropic, "AsyncAnthropicVertex", fake_ctor)
        client = _make_client(
            tmp_path,
            monkeypatch,
            JARVIS_CLAUDE_USE_VERTEX="1",
            JARVIS_VERTEX_MODEL_MAP="claude-sonnet-4-6=claude-sonnet-4-5@20250929",
        )
        create = AsyncMock(return_value=MagicMock())
        client.client = MagicMock()
        client.client.messages.create = create

        await client._call_with_retry(
            model="claude-sonnet-4-6",
            system="s",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=8,
            temperature=0.3,
            agent_name="test",
        )

        assert create.await_count == 1
        assert create.await_args.kwargs["model"] == "claude-sonnet-4-5@20250929"

    @pytest.mark.asyncio
    async def test_unmapped_model_passes_through_on_vertex(self, tmp_path, monkeypatch):
        fake_ctor = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(anthropic, "AsyncAnthropicVertex", fake_ctor)
        client = _make_client(tmp_path, monkeypatch, JARVIS_CLAUDE_USE_VERTEX="1")
        create = AsyncMock(return_value=MagicMock())
        client.client = MagicMock()
        client.client.messages.create = create

        await client._call_with_retry(
            model="claude-opus-4-8",
            system="s",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=8,
            temperature=0.3,
            agent_name="test",
        )

        assert create.await_args.kwargs["model"] == "claude-opus-4-8"

    @pytest.mark.asyncio
    async def test_no_translation_when_vertex_off(self, tmp_path, monkeypatch):
        # Even if a map is set, an OFF flag must not translate.
        client = _make_client(
            tmp_path,
            monkeypatch,
            JARVIS_VERTEX_MODEL_MAP="claude-sonnet-4-6=claude-sonnet-4-5@20250929",
        )
        assert client.use_vertex is False
        create = AsyncMock(return_value=MagicMock())
        client.client = MagicMock()
        client.client.messages.create = create

        await client._call_with_retry(
            model="claude-sonnet-4-6",
            system="s",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=8,
            temperature=0.3,
            agent_name="test",
        )

        assert create.await_args.kwargs["model"] == "claude-sonnet-4-6"


class TestVertexFailover:
    """Phase 3.5 credit-exhaustion failover (JARVIS_LLM_VERTEX_FAILOVER).

    Default OFF; when armed it builds a SECOND Vertex client while the primary
    transport stays direct AsyncAnthropic. Off/ollama/Vertex-primary all leave
    it disarmed.
    """

    def test_failover_off_by_default(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        assert client.vertex_failover_enabled is False
        assert client._failover_vertex_client is None
        assert client.vertex_failover_count == 0
        # Primary transport is unchanged (direct Anthropic).
        assert isinstance(client.client, anthropic.AsyncAnthropic)

    def test_failover_flag_false_stays_disarmed(self, tmp_path, monkeypatch):
        client = _make_client(
            tmp_path, monkeypatch, JARVIS_LLM_VERTEX_FAILOVER="false"
        )
        assert client.vertex_failover_enabled is False
        assert client._failover_vertex_client is None

    def test_failover_on_builds_aux_client_primary_stays_direct(
        self, tmp_path, monkeypatch
    ):
        sentinel = MagicMock(name="AsyncAnthropicVertexFailover")
        fake_ctor = MagicMock(return_value=sentinel)
        monkeypatch.setattr(anthropic, "AsyncAnthropicVertex", fake_ctor)

        client = _make_client(
            tmp_path,
            monkeypatch,
            JARVIS_LLM_VERTEX_FAILOVER="1",
            ANTHROPIC_VERTEX_PROJECT_ID="jarvis-trading-493009",
            ANTHROPIC_VERTEX_REGION="us-east5",
        )

        # Primary is still the direct API; failover is a SEPARATE Vertex client.
        assert client.use_vertex is False
        assert isinstance(client.client, anthropic.AsyncAnthropic)
        assert client.vertex_failover_enabled is True
        assert client._failover_vertex_client is sentinel
        fake_ctor.assert_called_once_with(
            project_id="jarvis-trading-493009", region="us-east5"
        )

    def test_failover_not_armed_when_vertex_is_primary(self, tmp_path, monkeypatch):
        # Vertex-primary already routes everything through Vertex; a second
        # failover client would be redundant, so it must stay disarmed.
        fake_ctor = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(anthropic, "AsyncAnthropicVertex", fake_ctor)
        client = _make_client(
            tmp_path,
            monkeypatch,
            JARVIS_CLAUDE_USE_VERTEX="1",
            JARVIS_LLM_VERTEX_FAILOVER="1",
        )
        assert client.use_vertex is True
        assert client.vertex_failover_enabled is False
        assert client._failover_vertex_client is None

    def test_failover_disabled_for_ollama(self, tmp_path, monkeypatch):
        client = _make_client(
            tmp_path,
            monkeypatch,
            JARVIS_LLM_PROVIDER="ollama",
            JARVIS_LLM_VERTEX_FAILOVER="1",
        )
        assert client.vertex_failover_enabled is False
        assert client._failover_vertex_client is None

    @pytest.mark.asyncio
    async def test_call_vertex_failover_translates_model(self, tmp_path, monkeypatch):
        fake_ctor = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(anthropic, "AsyncAnthropicVertex", fake_ctor)
        client = _make_client(
            tmp_path,
            monkeypatch,
            JARVIS_LLM_VERTEX_FAILOVER="1",
            JARVIS_VERTEX_MODEL_MAP="claude-sonnet-4-6=claude-sonnet-4-5@20250929",
        )
        create = AsyncMock(return_value=MagicMock())
        client._failover_vertex_client = MagicMock()
        client._failover_vertex_client.messages.create = create

        await client._call_vertex_failover(
            "claude-sonnet-4-6",
            "s",
            [{"role": "user", "content": "hi"}],
            8,
            0.3,
        )

        assert create.await_count == 1
        # Alias is translated to the Vertex publisher id for the wire call.
        assert create.await_args.kwargs["model"] == "claude-sonnet-4-5@20250929"
        assert create.await_args.kwargs["temperature"] == 0.3

    @pytest.mark.asyncio
    async def test_call_vertex_failover_unmapped_passes_through(
        self, tmp_path, monkeypatch
    ):
        fake_ctor = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(anthropic, "AsyncAnthropicVertex", fake_ctor)
        client = _make_client(
            tmp_path, monkeypatch, JARVIS_LLM_VERTEX_FAILOVER="1"
        )
        create = AsyncMock(return_value=MagicMock())
        client._failover_vertex_client = MagicMock()
        client._failover_vertex_client.messages.create = create

        await client._call_vertex_failover(
            "claude-opus-4-8",
            "s",
            [{"role": "user", "content": "hi"}],
            8,
            0.3,
        )

        assert create.await_args.kwargs["model"] == "claude-opus-4-8"

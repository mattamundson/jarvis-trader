"""
Tests for engine/discord/personal_mcp_server.py — the live-REST personal Discord MCP.

Mocks `_discord_get` / `_discord_post` to isolate tool logic from the network,
matching the pattern used in test_discord_bookmark_mcp.py for the DCE-ingested
companion MCP.
"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _bot_token_env(monkeypatch):
    """Ensure a stable bot token so `_auth_headers` does not raise."""
    monkeypatch.setenv("DISCORD_PERSONAL_BOT_TOKEN", "test-token-fixture")


@pytest.fixture
def sample_message():
    """Discord REST message payload — minimal but covers every `_format_message` field."""
    return {
        "id": "1500000000000000001",
        "timestamp": "2026-05-21T15:00:00.000000+00:00",
        "edited_timestamp": None,
        "author": {"id": "1234567890", "username": "amoszn"},
        "content": "Test message with a link https://x.com/foo",
        "attachments": [
            {
                "url": "https://cdn.discordapp.com/attachments/x/y/img.png",
                "filename": "img.png",
                "content_type": "image/png",
                "size": 12345,
            }
        ],
        "embeds": [
            {"title": "Title", "description": "Desc", "url": "https://e.com", "type": "rich"}
        ],
        "referenced_message": {"id": "1499000000000000000"},
        "pinned": False,
    }


# ── _format_message — pure function ───────────────────────────────────────────


def test_format_message_shape(sample_message):
    from discord.personal_mcp_server import _format_message

    out = _format_message(sample_message)
    assert out["id"] == "1500000000000000001"
    assert out["author_name"] == "amoszn"
    assert out["author_id"] == "1234567890"
    assert out["content"].startswith("Test message")
    assert len(out["attachments"]) == 1
    assert out["attachments"][0]["filename"] == "img.png"
    assert len(out["embeds"]) == 1
    assert out["embeds"][0]["title"] == "Title"
    assert out["referenced_message_id"] == "1499000000000000000"
    assert out["pinned"] is False


def test_format_message_handles_missing_optional_fields():
    """Author absent, no attachments, no embeds — must not raise."""
    from discord.personal_mcp_server import _format_message

    out = _format_message({"id": "1", "content": "x"})
    assert out["id"] == "1"
    assert out["author_name"] is None
    assert out["author_id"] is None
    assert out["attachments"] == []
    assert out["embeds"] == []
    assert out["referenced_message_id"] is None
    assert out["pinned"] is False


# ── list_recent_messages ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_recent_messages_success(sample_message):
    from discord import personal_mcp_server as mod

    with patch.object(mod, "_discord_get", new=AsyncMock(return_value=[sample_message])):
        result = await mod.list_recent_messages(limit=5)

    assert len(result) == 1
    assert result[0]["id"] == "1500000000000000001"


@pytest.mark.asyncio
async def test_list_recent_messages_limit_clamped_to_100():
    from discord import personal_mcp_server as mod

    mock_get = AsyncMock(return_value=[])
    with patch.object(mod, "_discord_get", new=mock_get):
        await mod.list_recent_messages(limit=999)

    call_args = mock_get.call_args
    assert call_args.kwargs["params"]["limit"] == 100


@pytest.mark.asyncio
async def test_list_recent_messages_limit_floor_is_one():
    from discord import personal_mcp_server as mod

    mock_get = AsyncMock(return_value=[])
    with patch.object(mod, "_discord_get", new=mock_get):
        await mod.list_recent_messages(limit=0)

    assert mock_get.call_args.kwargs["params"]["limit"] == 1


@pytest.mark.asyncio
async def test_list_recent_messages_api_failure_returns_empty():
    from discord import personal_mcp_server as mod

    mock_get = AsyncMock(side_effect=RuntimeError("Discord GET failed: 401"))
    with patch.object(mod, "_discord_get", new=mock_get):
        result = await mod.list_recent_messages(limit=5)

    assert result == []


@pytest.mark.asyncio
async def test_list_recent_messages_non_list_payload_returns_empty():
    """Defensive: if Discord ever returns a non-list, the tool must not crash."""
    from discord import personal_mcp_server as mod

    with patch.object(mod, "_discord_get", new=AsyncMock(return_value={"unexpected": "shape"})):
        result = await mod.list_recent_messages(limit=5)

    assert result == []


# ── get_message_by_id ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_message_by_id_success(sample_message):
    from discord import personal_mcp_server as mod

    with patch.object(mod, "_discord_get", new=AsyncMock(return_value=sample_message)):
        result = await mod.get_message_by_id("1500000000000000001")

    assert result["id"] == "1500000000000000001"
    assert result["author_name"] == "amoszn"


@pytest.mark.asyncio
async def test_get_message_by_id_not_found_returns_empty_dict():
    from discord import personal_mcp_server as mod

    mock_get = AsyncMock(side_effect=RuntimeError("Discord GET failed: 404 Unknown Message"))
    with patch.object(mod, "_discord_get", new=mock_get):
        result = await mod.get_message_by_id("nonexistent")

    assert result == {}


# ── search_personal_channel ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_personal_channel_filters_by_substring(sample_message):
    from discord import personal_mcp_server as mod

    msgs = [
        sample_message,
        {**sample_message, "id": "2", "content": "no match here"},
        {**sample_message, "id": "3", "content": "another link mentioned"},
    ]
    with patch.object(mod, "_discord_get", new=AsyncMock(return_value=msgs)):
        result = await mod.search_personal_channel(query="link", limit=10)

    assert len(result) == 2
    assert {m["id"] for m in result} == {"1500000000000000001", "3"}


@pytest.mark.asyncio
async def test_search_personal_channel_case_insensitive(sample_message):
    from discord import personal_mcp_server as mod

    msgs = [{**sample_message, "id": "1", "content": "LINK in upper case"}]
    with patch.object(mod, "_discord_get", new=AsyncMock(return_value=msgs)):
        result = await mod.search_personal_channel(query="link", limit=10)

    assert len(result) == 1


@pytest.mark.asyncio
async def test_search_personal_channel_empty_query_returns_empty():
    from discord import personal_mcp_server as mod

    result = await mod.search_personal_channel(query="", limit=10)
    assert result == []


@pytest.mark.asyncio
async def test_search_personal_channel_limit_caps_results(sample_message):
    from discord import personal_mcp_server as mod

    msgs = [{**sample_message, "id": str(i), "content": "link"} for i in range(10)]
    with patch.object(mod, "_discord_get", new=AsyncMock(return_value=msgs)):
        result = await mod.search_personal_channel(query="link", limit=3)

    assert len(result) == 3


# ── post_to_personal_channel ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_to_personal_channel_success(sample_message):
    from discord import personal_mcp_server as mod

    posted = {**sample_message, "content": "hello world"}
    with patch.object(mod, "_discord_post", new=AsyncMock(return_value=posted)):
        result = await mod.post_to_personal_channel(content="hello world")

    assert result["content"] == "hello world"
    assert "error" not in result


@pytest.mark.asyncio
async def test_post_to_personal_channel_empty_content_returns_error():
    from discord import personal_mcp_server as mod

    result = await mod.post_to_personal_channel(content="")
    assert "error" in result


@pytest.mark.asyncio
async def test_post_to_personal_channel_whitespace_only_returns_error():
    from discord import personal_mcp_server as mod

    result = await mod.post_to_personal_channel(content="   \n\t  ")
    assert "error" in result


@pytest.mark.asyncio
async def test_post_to_personal_channel_too_long_returns_error():
    from discord import personal_mcp_server as mod

    result = await mod.post_to_personal_channel(content="x" * 2001)
    assert "error" in result
    assert "2000" in result["error"]


@pytest.mark.asyncio
async def test_post_to_personal_channel_api_error_returns_error_dict():
    from discord import personal_mcp_server as mod

    mock_post = AsyncMock(side_effect=RuntimeError("Discord POST failed: 403 Missing Permissions"))
    with patch.object(mod, "_discord_post", new=mock_post):
        result = await mod.post_to_personal_channel(content="hello")

    assert "error" in result
    assert "403" in result["error"]


# ── get_channel_info ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_channel_info_success():
    from discord import personal_mcp_server as mod

    payload = {"id": "1490851279180660819", "name": "general", "type": 0, "topic": "Amo's channel"}
    with patch.object(mod, "_discord_get", new=AsyncMock(return_value=payload)):
        result = await mod.get_channel_info()

    assert result["name"] == "general"
    assert result["type"] == 0
    assert result["topic"] == "Amo's channel"
    assert result["permissions_ok"] is True
    assert result["error"] is None


@pytest.mark.asyncio
async def test_get_channel_info_api_error_surfaces_in_error_field():
    """The channel-perms gap (403) must be reported cleanly, not raised."""
    from discord import personal_mcp_server as mod

    mock_get = AsyncMock(side_effect=RuntimeError("Discord GET failed: 403 Missing Access"))
    with patch.object(mod, "_discord_get", new=mock_get):
        result = await mod.get_channel_info()

    assert result["permissions_ok"] is False
    assert "403" in result["error"]


# ── _auth_headers — token absence edge case ──────────────────────────────────


def test_auth_headers_raises_when_token_missing(monkeypatch):
    monkeypatch.delenv("DISCORD_PERSONAL_BOT_TOKEN", raising=False)
    from discord import personal_mcp_server as mod

    with pytest.raises(RuntimeError, match="DISCORD_PERSONAL_BOT_TOKEN not set"):
        mod._auth_headers()

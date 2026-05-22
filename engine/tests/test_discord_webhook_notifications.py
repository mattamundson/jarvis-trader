"""
Tests for engine/notifications/discord_webhook.py

Covers:
  - test_no_op_when_webhook_unset: env unset → no HTTP call attempted
  - test_posts_candidate_with_embed_shape: env set + mock httpx → POST with expected JSON
  - test_webhook_failure_logged_not_raised: httpx raises → returns None + WARNING in caplog
  - test_approval_result_posts_correctly: approved action → correct embed posted
  - test_rejection_includes_reason_in_message: rejection reason appears in embed fields
  - test_result_no_op_when_webhook_unset: result function also skips when env not set
  - test_candidate_expiry_ttl_display: expires_at parsed to human-readable TTL string
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure the engine root is on sys.path for direct import
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_httpx_client(status_code: int = 204):
    """Return a context-manager-compatible async mock for httpx.AsyncClient."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.text = ""

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_resp)
    return mock_client


def _basic_candidate(candidate_id: int = 17) -> dict:
    return {
        "id": candidate_id,
        "symbol": "MCL",
        "direction": "LONG",
        "confidence": 0.72,
        "expires_at": "2026-05-21T18:42:00+00:00",
        "ttl_seconds": 1800,
    }


# ---------------------------------------------------------------------------
# post_approval_candidate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_op_when_webhook_unset(monkeypatch, caplog):
    """When JARVIS_DISCORD_APPROVAL_WEBHOOK is not set, no HTTP call is made."""
    monkeypatch.delenv("JARVIS_DISCORD_APPROVAL_WEBHOOK", raising=False)

    mock_client = _make_mock_httpx_client()

    with patch("httpx.AsyncClient", return_value=mock_client):
        # Import fresh after monkeypatch so env reads are current
        from notifications import discord_webhook

        await discord_webhook.post_approval_candidate(_basic_candidate())

    mock_client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_posts_candidate_with_embed_shape(monkeypatch):
    """When env is set, POST is called with the correct embed structure."""
    monkeypatch.setenv("JARVIS_DISCORD_APPROVAL_WEBHOOK", "https://discord.example/hook/123/abc")

    mock_client = _make_mock_httpx_client(status_code=204)

    with patch("httpx.AsyncClient", return_value=mock_client):
        from notifications import discord_webhook

        await discord_webhook.post_approval_candidate(_basic_candidate(17))

    mock_client.post.assert_awaited_once()
    _url, kwargs = mock_client.post.call_args.args[0], mock_client.post.call_args.kwargs
    payload = (
        kwargs.get("json") or mock_client.post.call_args.args[1]
        if len(mock_client.post.call_args.args) > 1
        else kwargs["json"]
    )

    # Verify top-level shape
    assert "embeds" in payload
    assert len(payload["embeds"]) == 1
    embed = payload["embeds"][0]

    # Title must mention the candidate ID
    assert "17" in embed["title"]

    # Required embed keys
    assert "color" in embed
    assert "fields" in embed
    assert "timestamp" in embed
    assert "footer" in embed

    # Field names must include key trade details
    field_names = {f["name"] for f in embed["fields"]}
    assert "Symbol" in field_names
    assert "Direction" in field_names
    assert "Confidence" in field_names


@pytest.mark.asyncio
async def test_webhook_failure_logged_not_raised(monkeypatch, caplog):
    """When httpx raises, post_approval_candidate returns None and logs a WARNING."""
    monkeypatch.setenv("JARVIS_DISCORD_APPROVAL_WEBHOOK", "https://discord.example/hook/fail")

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=Exception("connection refused"))

    import logging

    with patch("httpx.AsyncClient", return_value=mock_client):
        with caplog.at_level(logging.WARNING, logger="notifications.discord_webhook"):
            from notifications import discord_webhook

            result = await discord_webhook.post_approval_candidate(_basic_candidate())

    # Must return None without raising
    assert result is None
    # A warning must have been logged somewhere (either from _post or the outer except)
    assert any(
        "discord_webhook" in r.name or "WARNING" in r.levelname or r.levelno >= logging.WARNING
        for r in caplog.records
    ), "Expected at least one WARNING-level log entry"


# ---------------------------------------------------------------------------
# post_approval_result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_result_posts_correctly(monkeypatch):
    """post_approval_result with action='approved' posts embed with approved title."""
    monkeypatch.setenv("JARVIS_DISCORD_APPROVAL_WEBHOOK", "https://discord.example/hook/results")

    mock_client = _make_mock_httpx_client(status_code=200)

    with patch("httpx.AsyncClient", return_value=mock_client):
        from notifications import discord_webhook

        await discord_webhook.post_approval_result(
            17,
            "approved",
            order_id="INV-12345",
            symbol="MCL",
            direction="LONG",
        )

    mock_client.post.assert_awaited_once()
    payload = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args.args[1]

    embed = payload["embeds"][0]
    assert "17" in embed["title"]
    assert "approved" in embed["title"].lower() or "Approved" in embed["description"]

    # order_id must appear in a field
    field_values = " ".join(f["value"] for f in embed.get("fields", []))
    assert "INV-12345" in field_values


@pytest.mark.asyncio
async def test_rejection_includes_reason_in_message(monkeypatch):
    """post_approval_result with action='rejected' includes the reason in the embed."""
    monkeypatch.setenv("JARVIS_DISCORD_APPROVAL_WEBHOOK", "https://discord.example/hook/reject")

    mock_client = _make_mock_httpx_client(status_code=204)

    with patch("httpx.AsyncClient", return_value=mock_client):
        from notifications import discord_webhook

        await discord_webhook.post_approval_result(
            42,
            "rejected",
            notes="too close to resistance",
            symbol="MNQ",
            direction="SHORT",
        )

    mock_client.post.assert_awaited_once()
    payload = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args.args[1]

    embed = payload["embeds"][0]
    assert "42" in embed["title"]
    assert "rejected" in embed["title"].lower() or "Rejected" in embed.get("description", "")

    # Rejection reason must surface somewhere in the embed
    field_values = " ".join(f["value"] for f in embed.get("fields", []))
    assert "too close to resistance" in field_values


@pytest.mark.asyncio
async def test_result_no_op_when_webhook_unset(monkeypatch):
    """post_approval_result is a no-op when the env var is not set."""
    monkeypatch.delenv("JARVIS_DISCORD_APPROVAL_WEBHOOK", raising=False)

    mock_client = _make_mock_httpx_client()

    with patch("httpx.AsyncClient", return_value=mock_client):
        from notifications import discord_webhook

        await discord_webhook.post_approval_result(99, "expired")

    mock_client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_candidate_expiry_ttl_display(monkeypatch):
    """expires_at in the future parses to a human-readable 'X min remaining' string."""
    monkeypatch.setenv("JARVIS_DISCORD_APPROVAL_WEBHOOK", "https://discord.example/hook/ttl")

    from datetime import datetime as _dt
    from datetime import timedelta, timezone

    future = (_dt.now(timezone.utc) + timedelta(minutes=25)).isoformat()
    candidate = _basic_candidate()
    candidate["expires_at"] = future
    candidate["ttl_seconds"] = 1500  # 25 min

    mock_client = _make_mock_httpx_client()

    with patch("httpx.AsyncClient", return_value=mock_client):
        from notifications import discord_webhook

        await discord_webhook.post_approval_candidate(candidate)

    mock_client.post.assert_awaited_once()
    payload = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args.args[1]
    embed = payload["embeds"][0]

    # The Expires field must mention 'min'
    expires_field = next((f for f in embed.get("fields", []) if f.get("name") == "Expires"), None)
    assert expires_field is not None, "Expected an 'Expires' field in the embed"
    assert (
        "min" in expires_field["value"]
    ), f"Expected 'min' in TTL field, got: {expires_field['value']}"

"""
Tests for engine/discord/reaction_watcher.py

Uses mocks for all Discord gateway and engine HTTP calls — no live connections.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

# ---------------------------------------------------------------------------
# Helpers to build fake Discord event payloads
# ---------------------------------------------------------------------------

BOT_USER_ID = "111111111111111111"
AUTHORIZED_USER_ID = "222222222222222222"
OTHER_USER_ID = "333333333333333333"
PERSONAL_CHANNEL_ID = "1490851279180660819"
OTHER_CHANNEL_ID = "9999999999999999999"
MESSAGE_ID = "444444444444444444"
CANDIDATE_ID = 17

APPROVAL_MESSAGE_CONTENT = f"New trade candidate (ID {CANDIDATE_ID}) — MCL LONG @ 72.50"
NON_CANDIDATE_MESSAGE_CONTENT = "Just a normal chat message, no candidate here."


def _reaction_event(
    user_id: str = AUTHORIZED_USER_ID,
    channel_id: str = PERSONAL_CHANNEL_ID,
    message_id: str = MESSAGE_ID,
    emoji_name: str = "✅",  # ✅
) -> dict:
    return {
        "user_id": user_id,
        "channel_id": channel_id,
        "message_id": message_id,
        "emoji": {"name": emoji_name, "id": None},
    }


def _discord_message(
    author_id: str = BOT_USER_ID,
    content: str = APPROVAL_MESSAGE_CONTENT,
) -> dict:
    return {
        "id": MESSAGE_ID,
        "author": {"id": author_id, "username": "JARVIS"},
        "content": content,
    }


# ---------------------------------------------------------------------------
# Module-level env patching helpers
# ---------------------------------------------------------------------------


def _env_with_both(**extra):
    return {
        "DISCORD_PERSONAL_BOT_TOKEN": "Bot-test-token",
        "DISCORD_PERSONAL_USER_ID": AUTHORIZED_USER_ID,
        "API_KEY": "test-api-key",
        **extra,
    }


def _env_no_token(**extra):
    return {
        "DISCORD_PERSONAL_USER_ID": AUTHORIZED_USER_ID,
        "API_KEY": "test-api-key",
        **extra,
    }


def _env_no_user_id(**extra):
    return {
        "DISCORD_PERSONAL_BOT_TOKEN": "Bot-test-token",
        "API_KEY": "test-api-key",
        **extra,
    }


# ---------------------------------------------------------------------------
# Shared helper: aiohttp context-manager mock
# ---------------------------------------------------------------------------


def _make_resp_cm(json_data: dict, status: int = 200) -> MagicMock:
    """
    Build a MagicMock that behaves as an async context manager returning a
    fake aiohttp response. Compatible with ``async with session.get(...) as r``.
    """
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data)
    resp.text = AsyncMock(return_value="")
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


def _make_mock_session(author_id: str = BOT_USER_ID, content: str = APPROVAL_MESSAGE_CONTENT):
    """
    Build a mock aiohttp.ClientSession where .get() returns a context manager
    (not a coroutine) — this is how aiohttp's API actually works.
    """
    resp = _make_resp_cm(json_data=_discord_message(author_id=author_id, content=content))
    mock_session = MagicMock()
    # session.get(url, ...) returns the context manager directly (synchronously)
    mock_session.get = MagicMock(return_value=resp)
    mock_session.post = MagicMock(return_value=_make_resp_cm({}))
    return mock_session


# ---------------------------------------------------------------------------
# 1. test_disabled_without_token
# ---------------------------------------------------------------------------


def test_disabled_without_token():
    """is_reaction_watcher_enabled() returns False when token is absent."""
    with patch.dict("os.environ", _env_no_token(), clear=True):
        from discord.reaction_watcher import is_reaction_watcher_enabled

        assert is_reaction_watcher_enabled() is False


# ---------------------------------------------------------------------------
# 2. test_disabled_without_user_id
# ---------------------------------------------------------------------------


def test_disabled_without_user_id():
    """is_reaction_watcher_enabled() returns False when user_id is absent (security gate)."""
    with patch.dict("os.environ", _env_no_user_id(), clear=True):
        from discord.reaction_watcher import is_reaction_watcher_enabled

        assert is_reaction_watcher_enabled() is False


# ---------------------------------------------------------------------------
# 3. test_reaction_from_wrong_user_ignored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reaction_from_wrong_user_ignored():
    """Reactions from users other than DISCORD_PERSONAL_USER_ID are silently ignored."""
    with patch.dict("os.environ", _env_with_both(), clear=True):
        from discord.reaction_watcher import _handle_reaction

        mock_session = _make_mock_session()
        with patch("discord.reaction_watcher._call_engine", new_callable=AsyncMock) as mock_engine:
            event = _reaction_event(user_id=OTHER_USER_ID)
            await _handle_reaction(mock_session, event, BOT_USER_ID)
            mock_engine.assert_not_called()


# ---------------------------------------------------------------------------
# 4. test_reaction_on_non_bot_message_ignored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reaction_on_non_bot_message_ignored():
    """Reactions on messages authored by someone other than the bot are ignored."""
    with patch.dict("os.environ", _env_with_both(), clear=True):
        from discord.reaction_watcher import _handle_reaction

        mock_session = _make_mock_session(author_id="some_human_user_99")

        with patch("discord.reaction_watcher._call_engine", new_callable=AsyncMock) as mock_engine:
            event = _reaction_event(user_id=AUTHORIZED_USER_ID)
            await _handle_reaction(mock_session, event, BOT_USER_ID)
            mock_engine.assert_not_called()


# ---------------------------------------------------------------------------
# Shared helper for emoji dispatch tests (5-7)
# ---------------------------------------------------------------------------


async def _run_emoji_test(
    emoji_name: str,
    engine_response: dict | None = None,
) -> dict:
    """
    Run _handle_reaction with a given emoji on a valid bot-authored candidate
    message. Returns the kwargs captured from _call_engine.
    """
    with patch.dict("os.environ", _env_with_both(), clear=True):
        from discord.reaction_watcher import _handle_reaction

        mock_session = _make_mock_session()
        captured: dict = {}

        async def fake_call_engine(session, method, path, params=None, json_body=None):
            # Only capture the approval/reject/extend call, not any other call
            if method != "GET":
                captured["method"] = method
                captured["path"] = path
                captured["params"] = params
                captured["json_body"] = json_body
            return engine_response or {"_http_status": 200}

        with (
            patch("discord.reaction_watcher._call_engine", side_effect=fake_call_engine),
            patch("discord.reaction_watcher._post_message", new_callable=AsyncMock),
        ):
            event = _reaction_event(emoji_name=emoji_name)
            await _handle_reaction(mock_session, event, BOT_USER_ID)

        return captured


# ---------------------------------------------------------------------------
# 5. test_check_emoji_approve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_emoji_approve():
    """✅ reaction on a bot-posted candidate ID 17 calls /approvals/17/approve."""
    captured = await _run_emoji_test(
        emoji_name="✅",  # ✅
        engine_response={
            "_http_status": 200,
            "symbol": "MCL",
            "direction": "LONG",
            "order_id": "paper-001",
        },
    )
    assert captured.get("method") == "POST"
    assert captured.get("path") == f"/approvals/{CANDIDATE_ID}/approve"


# ---------------------------------------------------------------------------
# 6. test_check_emoji_reject
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_emoji_reject():
    """❌ reaction on a bot-posted candidate ID 17 calls /approvals/17/reject."""
    captured = await _run_emoji_test(
        emoji_name="❌",  # ❌
        engine_response={"_http_status": 200, "status": "rejected"},
    )
    assert captured.get("method") == "POST"
    assert captured.get("path") == f"/approvals/{CANDIDATE_ID}/reject"
    assert (captured.get("json_body") or {}).get("reason") is not None


# ---------------------------------------------------------------------------
# 7. test_check_emoji_extend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_emoji_extend():
    """⏸ reaction on a bot-posted candidate ID 17 calls /approvals/17/extend with minutes=30."""
    captured = await _run_emoji_test(
        emoji_name="⏸",  # ⏸
        engine_response={
            "_http_status": 200,
            "status": "extended",
            "expires_at": "2026-05-21T12:00:00+00:00",
        },
    )
    assert captured.get("method") == "POST"
    assert captured.get("path") == f"/approvals/{CANDIDATE_ID}/extend"
    assert (captured.get("params") or {}).get("minutes") == "30"


# ---------------------------------------------------------------------------
# 8. test_engine_call_failure_replies_in_channel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_engine_call_failure_replies_in_channel():
    """When the engine returns an error status, a failure message is posted to the channel."""
    with patch.dict("os.environ", _env_with_both(), clear=True):
        from discord.reaction_watcher import _handle_reaction

        mock_session = _make_mock_session()
        posted_messages: list[str] = []

        async def fake_post_message(session, channel_id, content):
            posted_messages.append(content)

        async def fake_engine_failure(session, method, path, params=None, json_body=None):
            return {"_http_status": 409, "detail": "kill switch active"}

        with (
            patch("discord.reaction_watcher._call_engine", side_effect=fake_engine_failure),
            patch(
                "discord.reaction_watcher._post_message",
                side_effect=fake_post_message,
            ),
        ):
            event = _reaction_event(emoji_name="✅")  # ✅
            await _handle_reaction(mock_session, event, BOT_USER_ID)

        assert len(posted_messages) == 1
        assert "FAILED" in posted_messages[0] or "409" in posted_messages[0]


# ---------------------------------------------------------------------------
# Extra: _extract_candidate_id
# ---------------------------------------------------------------------------


def test_extract_candidate_id_parses_standard_format():
    from discord.reaction_watcher import _extract_candidate_id

    assert _extract_candidate_id("New trade candidate (ID 17) — MCL LONG") == 17


def test_extract_candidate_id_returns_none_for_no_match():
    from discord.reaction_watcher import _extract_candidate_id

    assert _extract_candidate_id("Just a normal message") is None


# ---------------------------------------------------------------------------
# Extra: reconnect backoff must not reset before authentication succeeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backoff_grows_when_gateway_rejects_identify_before_ready():
    """
    Regression test: a WebSocket connect that gets IDENTIFY-rejected and closed
    before READY must NOT reset the reconnect backoff to the 2s floor.

    Previously, backoff was reset immediately after the raw ws_connect() call
    succeeded — before the gateway ever authenticated. A bad token/intents
    config (or any close-before-READY) then spun the reconnect loop at the 2s
    floor forever instead of backing off exponentially (2, 4, 8, ...).
    """
    from discord import reaction_watcher

    backoff_sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        if seconds > 10:
            # Heartbeat-loop sleep (41.25s) — not part of the reconnect backoff
            # under test. Cancel it immediately so it can't interleave.
            raise asyncio.CancelledError()
        backoff_sleep_calls.append(seconds)
        if len(backoff_sleep_calls) >= 3:
            raise asyncio.CancelledError()

    class FakeWS:
        close_code = 4004  # Discord: Authentication failed (non-resumable)

        def __init__(self) -> None:
            self._msgs = [
                MagicMock(
                    type=aiohttp.WSMsgType.TEXT,
                    data=json.dumps({"op": 10, "d": {"heartbeat_interval": 41250}}),
                ),
                MagicMock(type=aiohttp.WSMsgType.CLOSE, data=None),
            ]

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._msgs:
                raise StopAsyncIteration
            return self._msgs.pop(0)

        async def send_str(self, _s: str) -> None:
            return None

    class FakeWSConnectCM:
        async def __aenter__(self):
            return FakeWS()

        async def __aexit__(self, *_a):
            return False

    class FakeClientSession:
        def ws_connect(self, *_a, **_kw):
            return FakeWSConnectCM()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

    with (
        patch.dict("os.environ", _env_with_both(), clear=True),
        patch("asyncio.sleep", side_effect=fake_sleep),
        patch("aiohttp.ClientSession", return_value=FakeClientSession()),
    ):
        await reaction_watcher.watch_approval_reactions()

    assert backoff_sleep_calls == [2, 4, 8]


@pytest.mark.asyncio
async def test_stream_end_with_no_close_frame_logs_warning(caplog):
    """
    2026-08-15 incident: when the gateway's async-for iterator simply ends
    (connection dropped with no CLOSE/CLOSING/ERROR frame at all — the
    exact failure mode observed live, 14,632 times in one session), this
    previously logged nothing. A `for...else` on the message loop now logs
    a WARNING so this termination path is distinguishable from a healthy
    idle session in the logs.
    """
    import logging

    from discord import reaction_watcher

    class FakeWS:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    with caplog.at_level(logging.WARNING, logger="discord.reaction_watcher"):
        session_id, last_seq, should_resume = await reaction_watcher._gateway_session(
            FakeWS(), MagicMock(), None, None
        )

    assert session_id is None
    assert any(
        "gateway stream ended with no close frame" in r.message for r in caplog.records
    )

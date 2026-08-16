"""
Tests for engine/discord/reaction_watcher.py

Uses mocks for all Discord gateway and engine HTTP calls — no live connections.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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
# watch_approval_reactions(): reconnect backoff on a WS-connects-but-never-
# authenticates failure (2026-08-15 incident -- 14,632 reconnects over 7.5h,
# every ~2s, never escalating).
# ---------------------------------------------------------------------------


class _FakeWSMsg:
    def __init__(self, type_, data):
        self.type = type_
        self.data = data


class _FakeWS:
    """An aiohttp-shaped websocket that yields HELLO, then the connection
    drops with no further message and no CLOSE/CLOSING/ERROR frame -- the
    exact 'async for msg in ws' silent-termination shape observed in prod
    (IDENTIFY sent, then nothing logged, no READY, ever)."""

    def __init__(self, messages):
        self._messages = messages
        self.close_code = None

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for m in self._messages:
            yield m

    async def send_str(self, _s):
        return None


class _FakeWSConnectCM:
    def __init__(self, ws):
        self._ws = ws

    async def __aenter__(self):
        return self._ws

    async def __aexit__(self, *_a):
        return False


class _FakeHttpSession:
    def __init__(self, ws_factory):
        self._ws_factory = ws_factory

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    def ws_connect(self, _url, **_kw):
        return _FakeWSConnectCM(self._ws_factory())


@pytest.mark.asyncio
async def test_backoff_escalates_when_ws_connects_but_never_reaches_ready(monkeypatch):
    """The module docstring promises 'connection drops trigger exponential
    back-off (2, 4, 8, 16, 32, 60s cap)'. It doesn't, for this failure shape:
    the outer loop resets backoff to the INITIAL value as soon as the raw
    WebSocket handshake succeeds -- before IDENTIFY is even acknowledged --
    so a connect-then-silently-die cycle (auth never completes, no CLOSE
    frame) loops forever at the 2s floor instead of escalating."""
    import json as _json

    import aiohttp

    from discord import reaction_watcher as rw

    monkeypatch.setattr(rw, "_get_bot_token", lambda: "fake-token")
    monkeypatch.setattr(rw, "_get_channel_id", lambda: "chan")
    monkeypatch.setattr(rw, "_get_personal_user_id", lambda: "user")

    enabled_calls = {"n": 0}

    def _enabled():
        enabled_calls["n"] += 1
        return enabled_calls["n"] <= 5  # let 5 reconnect cycles run, then exit

    monkeypatch.setattr(rw, "is_reaction_watcher_enabled", _enabled)

    def _hello_then_silence():
        hello = _FakeWSMsg(
            aiohttp.WSMsgType.TEXT,
            _json.dumps({"op": rw.OP_HELLO, "d": {"heartbeat_interval": 41250}}),
        )
        return _FakeWS([hello])  # generator ends here -- no READY, no CLOSE

    monkeypatch.setattr(
        rw.aiohttp, "ClientSession", lambda: _FakeHttpSession(_hello_then_silence)
    )

    sleeps: list[float] = []

    async def _fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(rw.asyncio, "sleep", _fake_sleep)

    await rw.watch_approval_reactions()

    # Current (buggy) behavior would record every sleep as 2.0 (the initial
    # backoff, reset on every successful raw-socket connect). A correct
    # exponential backoff must escalate across repeated auth failures.
    assert sleeps[0] == pytest.approx(rw._INITIAL_BACKOFF_SECONDS)
    assert sleeps[-1] > sleeps[0], (
        f"backoff never escalated across {len(sleeps)} consecutive "
        f"never-reached-READY cycles: {sleeps}"
    )
    assert sleeps == sorted(sleeps), f"backoff must be monotonically non-decreasing: {sleeps}"


@pytest.mark.asyncio
async def test_backoff_still_resets_after_a_session_reaches_ready(monkeypatch):
    """Guards against a fix that satisfies the escalation test by simply never
    resetting backoff at all -- a session that genuinely authenticates (READY)
    and later drops must still reconnect quickly, not inherit an escalated
    backoff from before it was healthy."""
    import json as _json

    import aiohttp

    from discord import reaction_watcher as rw

    monkeypatch.setattr(rw, "_get_bot_token", lambda: "fake-token")
    monkeypatch.setattr(rw, "_get_channel_id", lambda: "chan")
    monkeypatch.setattr(rw, "_get_personal_user_id", lambda: "user")

    enabled_calls = {"n": 0}

    def _enabled():
        enabled_calls["n"] += 1
        # +1 for the startup check at line ~609 before the reconnect loop
        # even begins its first iteration.
        return enabled_calls["n"] <= 4

    monkeypatch.setattr(rw, "is_reaction_watcher_enabled", _enabled)

    cycle = {"n": 0}

    def _ws_factory():
        cycle["n"] += 1
        hello = _FakeWSMsg(
            aiohttp.WSMsgType.TEXT,
            _json.dumps({"op": rw.OP_HELLO, "d": {"heartbeat_interval": 41250}}),
        )
        if cycle["n"] <= 2:
            # First two cycles: silently die before READY (as above).
            return _FakeWS([hello])
        # Third cycle: genuinely reaches READY, then drops.
        ready = _FakeWSMsg(
            aiohttp.WSMsgType.TEXT,
            _json.dumps({
                "op": rw.OP_DISPATCH, "t": "READY", "s": 1,
                "d": {"session_id": "sess-abc", "user": {"id": "999"}},
            }),
        )
        return _FakeWS([hello, ready])

    monkeypatch.setattr(rw.aiohttp, "ClientSession", lambda: _FakeHttpSession(_ws_factory))

    sleeps: list[float] = []

    async def _fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(rw.asyncio, "sleep", _fake_sleep)

    await rw.watch_approval_reactions()

    # Cycle 1 fails pre-READY -> sleeps[0] at the floor. Cycle 2 fails
    # pre-READY again -> must have escalated past the floor (same bug as
    # above). Cycle 3 reaches READY -> its post-drop sleep must be back at
    # the floor, not a further-escalated value.
    assert sleeps[0] == pytest.approx(rw._INITIAL_BACKOFF_SECONDS)
    assert sleeps[1] > sleeps[0]
    assert sleeps[2] == pytest.approx(rw._INITIAL_BACKOFF_SECONDS), (
        f"backoff didn't reset after a session reached READY: {sleeps}"
    )

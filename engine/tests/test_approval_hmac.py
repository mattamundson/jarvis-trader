"""
§6.2 — HMAC forged-reaction protection tests.

Covers:
  1. _sign_candidate_id generates a deterministic, non-None token when key is set
  2. _verify_approval_hmac: correct token → True; wrong token → False; key absent → True
  3. _handle_reaction rejects a forged reaction (key set, message has no/wrong HMAC)
  4. _handle_reaction still extracts candidate ID from embed title (backward compat)
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Constants shared across tests
# ---------------------------------------------------------------------------

_HMAC_KEY = "test-jarvis-hmac-secret"
BOT_USER_ID = "111111111111111111"
AUTHORIZED_USER_ID = "222222222222222222"
CHANNEL_ID = "1490851279180660819"
MESSAGE_ID = "444444444444444444"
CANDIDATE_ID = 42


def _env(**extra):
    return {
        "DISCORD_PERSONAL_BOT_TOKEN": "Bot-test-token",
        "DISCORD_PERSONAL_USER_ID": AUTHORIZED_USER_ID,
        "API_KEY": "test-api-key",
        **extra,
    }


def _make_resp_cm(json_data: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data)
    resp.text = AsyncMock(return_value="")
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


def _reaction_event(emoji: str = "✅") -> dict:
    return {
        "user_id": AUTHORIZED_USER_ID,
        "channel_id": CHANNEL_ID,
        "message_id": MESSAGE_ID,
        "emoji": {"name": emoji, "id": None},
    }


# ---------------------------------------------------------------------------
# 1. sign roundtrip — pure unit
# ---------------------------------------------------------------------------


def test_sign_returns_token_when_key_set(monkeypatch):
    monkeypatch.setenv("JARVIS_APPROVAL_HMAC_KEY", _HMAC_KEY)
    from notifications.discord_webhook import _sign_candidate_id

    token = _sign_candidate_id(CANDIDATE_ID)
    assert token is not None
    assert len(token) == 16
    assert all(c in "0123456789abcdef" for c in token)


def test_sign_returns_none_when_key_absent(monkeypatch):
    monkeypatch.delenv("JARVIS_APPROVAL_HMAC_KEY", raising=False)
    from notifications.discord_webhook import _sign_candidate_id

    assert _sign_candidate_id(CANDIDATE_ID) is None


def test_sign_is_deterministic(monkeypatch):
    monkeypatch.setenv("JARVIS_APPROVAL_HMAC_KEY", _HMAC_KEY)
    from notifications.discord_webhook import _sign_candidate_id

    assert _sign_candidate_id(CANDIDATE_ID) == _sign_candidate_id(CANDIDATE_ID)


# ---------------------------------------------------------------------------
# 2. verify — pure unit
# ---------------------------------------------------------------------------


def test_verify_passes_correct_token(monkeypatch):
    monkeypatch.setenv("JARVIS_APPROVAL_HMAC_KEY", _HMAC_KEY)
    from discord.reaction_watcher import _verify_approval_hmac
    from notifications.discord_webhook import _sign_candidate_id

    token = _sign_candidate_id(CANDIDATE_ID)
    assert _verify_approval_hmac(CANDIDATE_ID, token) is True


def test_verify_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("JARVIS_APPROVAL_HMAC_KEY", _HMAC_KEY)
    from discord.reaction_watcher import _verify_approval_hmac

    assert _verify_approval_hmac(CANDIDATE_ID, "deadbeef00000000") is False


def test_verify_rejects_empty_token(monkeypatch):
    monkeypatch.setenv("JARVIS_APPROVAL_HMAC_KEY", _HMAC_KEY)
    from discord.reaction_watcher import _verify_approval_hmac

    assert _verify_approval_hmac(CANDIDATE_ID, "") is False


def test_verify_rejects_wrong_candidate_id(monkeypatch):
    monkeypatch.setenv("JARVIS_APPROVAL_HMAC_KEY", _HMAC_KEY)
    from discord.reaction_watcher import _verify_approval_hmac
    from notifications.discord_webhook import _sign_candidate_id

    token = _sign_candidate_id(CANDIDATE_ID)
    assert _verify_approval_hmac(CANDIDATE_ID + 1, token) is False


def test_verify_passes_when_no_key(monkeypatch):
    """When key is not configured, HMAC check is skipped — backward compat."""
    monkeypatch.delenv("JARVIS_APPROVAL_HMAC_KEY", raising=False)
    from discord.reaction_watcher import _verify_approval_hmac

    assert _verify_approval_hmac(CANDIDATE_ID, "") is True
    assert _verify_approval_hmac(CANDIDATE_ID, "garbage") is True


# ---------------------------------------------------------------------------
# 3. _handle_reaction rejects forged reaction when key is set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_reaction_rejects_missing_hmac(monkeypatch):
    """When key is configured, a message with no auth: token is rejected before engine call."""
    env = _env(JARVIS_APPROVAL_HMAC_KEY=_HMAC_KEY)
    with patch.dict("os.environ", env, clear=True):
        from discord.reaction_watcher import _handle_reaction

        # Message has candidate ID but no HMAC token (forged / old-style)
        forged_msg = {
            "id": MESSAGE_ID,
            "author": {"id": BOT_USER_ID},
            "content": f"approval candidate (ID {CANDIDATE_ID})",
        }
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=_make_resp_cm(forged_msg))
        mock_session.post = MagicMock(return_value=_make_resp_cm({}))

        with patch("discord.reaction_watcher._call_engine", new_callable=AsyncMock) as mock_engine:
            await _handle_reaction(mock_session, _reaction_event(), BOT_USER_ID)
            mock_engine.assert_not_called()


@pytest.mark.asyncio
async def test_handle_reaction_rejects_wrong_hmac(monkeypatch):
    """A message with a bad HMAC token is rejected."""
    env = _env(JARVIS_APPROVAL_HMAC_KEY=_HMAC_KEY)
    with patch.dict("os.environ", env, clear=True):
        from discord.reaction_watcher import _handle_reaction

        bad_msg = {
            "id": MESSAGE_ID,
            "author": {"id": BOT_USER_ID},
            "content": f"approval candidate (ID {CANDIDATE_ID}) | auth:deadbeef00000000",
        }
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=_make_resp_cm(bad_msg))
        mock_session.post = MagicMock(return_value=_make_resp_cm({}))

        with patch("discord.reaction_watcher._call_engine", new_callable=AsyncMock) as mock_engine:
            await _handle_reaction(mock_session, _reaction_event(), BOT_USER_ID)
            mock_engine.assert_not_called()


@pytest.mark.asyncio
async def test_handle_reaction_passes_valid_hmac(monkeypatch):
    """A message with a correct HMAC token reaches the engine."""
    import hashlib
    import hmac as _hmac

    token = _hmac.new(_HMAC_KEY.encode(), str(CANDIDATE_ID).encode(), hashlib.sha256).hexdigest()[
        :16
    ]
    env = _env(JARVIS_APPROVAL_HMAC_KEY=_HMAC_KEY)
    with patch.dict("os.environ", env, clear=True):
        from discord.reaction_watcher import _handle_reaction

        signed_msg = {
            "id": MESSAGE_ID,
            "author": {"id": BOT_USER_ID},
            "content": f"approval candidate (ID {CANDIDATE_ID}) | auth:{token}",
        }
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=_make_resp_cm(signed_msg))
        mock_session.post = MagicMock(return_value=_make_resp_cm({}))

        with patch(
            "discord.reaction_watcher._call_engine",
            new_callable=AsyncMock,
            return_value={
                "_http_status": 200,
                "symbol": "MCL",
                "direction": "LONG",
                "order_id": "9",
            },
        ) as mock_engine:
            await _handle_reaction(mock_session, _reaction_event(), BOT_USER_ID)
            mock_engine.assert_called_once()


# ---------------------------------------------------------------------------
# 4. Embed title fallback (backward compat with no-content messages)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_title_fallback_no_key(monkeypatch):
    """When no key is set, candidate ID in embed title triggers approval (backward compat)."""
    env = _env()  # no JARVIS_APPROVAL_HMAC_KEY
    with patch.dict("os.environ", env, clear=True):
        from discord.reaction_watcher import _handle_reaction

        embed_msg = {
            "id": MESSAGE_ID,
            "author": {"id": BOT_USER_ID},
            "content": "",  # empty — old-style webhook embed
            "embeds": [{"title": f"New trade candidate (ID {CANDIDATE_ID})"}],
        }
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=_make_resp_cm(embed_msg))
        mock_session.post = MagicMock(return_value=_make_resp_cm({}))

        with patch(
            "discord.reaction_watcher._call_engine",
            new_callable=AsyncMock,
            return_value={
                "_http_status": 200,
                "symbol": "MCL",
                "direction": "LONG",
                "order_id": "9",
            },
        ) as mock_engine:
            await _handle_reaction(mock_session, _reaction_event(), BOT_USER_ID)
            mock_engine.assert_called_once()

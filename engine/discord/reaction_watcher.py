"""
Discord Reaction Watcher — approval/reject/extend via emoji reactions.

Listens on the Discord gateway for MESSAGE_REACTION_ADD events on the personal
channel. When Matt reacts to a bot-posted approval-candidate message:

  ✅  → POST /approvals/{id}/approve
  ❌  → POST /approvals/{id}/reject
  ⏸  → POST /approvals/{id}/extend?minutes=30

Default-OFF: both DISCORD_PERSONAL_BOT_TOKEN and DISCORD_PERSONAL_USER_ID must
be set in engine/.env for the watcher to start. Missing either env var causes
is_reaction_watcher_enabled() to return False and watch_approval_reactions() to
return immediately without connecting.

Gateway implementation uses raw aiohttp WebSocket (no discord.py dependency) to
match the pattern in engine/discord/personal_mcp_server.py. The minimal gateway
subset used here:

  HELLO (op=10)   → extract heartbeat_interval, start heartbeat loop
  IDENTIFY (op=2) → authenticate with intents bitmask
  HEARTBEAT (op=1) → sent every heartbeat_interval ms
  HEARTBEAT_ACK (op=11) → confirm gateway alive
  DISPATCH (op=0) → handle MESSAGE_REACTION_ADD events
  RESUME (op=6)   → reconnect with last session_id + seq after disconnect

Intents bitmask (decimal 1537):
  GUILDS (1) | GUILD_MESSAGES (512) | GUILD_MESSAGE_REACTIONS (1024) = 1537

  (No MESSAGE_CONTENT -- not needed and not requested; see GATEWAY_INTENTS.)

Security: only reactions from DISCORD_PERSONAL_USER_ID are acted upon. All
others are silently ignored and logged at DEBUG. The bot also verifies the
target message was authored by itself (bot user ID from the IDENTIFY READY
event) — this prevents acting on reactions to third-party messages.

Resilience: connection drops trigger exponential back-off (2, 4, 8, 16, 32, 60 s
cap). The watcher never raises into the engine lifespan; all exceptions are
caught and retried.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac as _hmac_module
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

import aiohttp

# Ensure engine root on sys.path when invoked directly.
_ENGINE_ROOT = str(Path(__file__).resolve().parent.parent)
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DISCORD_GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"
DISCORD_API_BASE = "https://discord.com/api/v10"
REQUEST_TIMEOUT_SECONDS = 15

# Gateway opcodes
OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RESUME = 6
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

# Gateway intents: GUILDS | GUILD_MESSAGES | GUILD_MESSAGE_REACTIONS
#
# 2026-08-16: two corrections found while root-causing a persistent IDENTIFY
# failure (live diagnostic: Discord closes with code 4004 "Authentication
# failed" -- an invalid bot token, not an intents problem, but both bugs
# below were real and worth fixing regardless).
#
# MESSAGE_CONTENT (privileged, 32768) removed: this listener only ever
# dispatches on READY/RESUMED/MESSAGE_REACTION_ADD (see _gateway_session
# below), none of which carry or require message content over the gateway --
# the approval-message text is fetched separately via Discord REST
# (_handle_reaction -> GET .../messages/{id}), unaffected by gateway intents.
# Requesting an unused privileged intent only adds a Developer Portal
# dependency (must be explicitly toggled on) for zero functional benefit.
#
# GUILD_MESSAGE_REACTIONS corrected from 8192 to 1024: PERSONAL_CHANNEL_ID
# lives inside a guild (personal_mcp_server.py's DEFAULT_GUILD_ID), not a DM,
# so the intent needed is GUILD_MESSAGE_REACTIONS (bit 10, 1024). The prior
# value (8192, bit 13) is actually Discord's DIRECT_MESSAGE_REACTIONS --
# mislabeled in this comment, and would never have delivered
# MESSAGE_REACTION_ADD events for this guild channel even on a healthy
# connection.
GATEWAY_INTENTS = 1 | 512 | 1024  # 1537

# Personal channel (same constant as personal_mcp_server.py)
PERSONAL_CHANNEL_ID = "1490851279180660819"

# Emoji → action mapping
EMOJI_APPROVE = "✅"  # ✅
EMOJI_REJECT = "❌"  # ❌
EMOJI_EXTEND = "⏸"  # ⏸

# Regex to extract candidate ID from bot-posted approval messages.
# Matches patterns like "New trade candidate (ID 17)" or "approval candidate (id 17)"
_CANDIDATE_ID_RE = re.compile(r"(?:candidate|approval)[^(]*\((?:ID\s*)?(\d+)\)", re.IGNORECASE)

# Regex to extract HMAC token embedded by discord_webhook.post_approval_candidate.
# Matches "auth:<16-char-hex>" appended by _sign_candidate_id.
_HMAC_TOKEN_RE = re.compile(r"auth:([0-9a-f]+)", re.IGNORECASE)

# Back-off caps
_MAX_BACKOFF_SECONDS = 60
_INITIAL_BACKOFF_SECONDS = 2


# ---------------------------------------------------------------------------
# Env helpers
# ---------------------------------------------------------------------------


def _get_bot_token() -> str | None:
    return os.getenv("DISCORD_PERSONAL_BOT_TOKEN")


def _get_personal_user_id() -> str | None:
    return os.getenv("DISCORD_PERSONAL_USER_ID")


def _get_engine_api_key() -> str | None:
    """Read API_KEY from env — used for X-API-Key header on engine calls."""
    return os.getenv("API_KEY")


def _get_channel_id() -> str:
    return os.getenv("DISCORD_PERSONAL_CHANNEL_ID", PERSONAL_CHANNEL_ID)


def _get_engine_base_url() -> str:
    return os.getenv("ENGINE_BASE_URL", "http://127.0.0.1:8010")


# ---------------------------------------------------------------------------
# HMAC helpers — §6.2 forged-reaction protection
# ---------------------------------------------------------------------------


def _get_hmac_key_bytes() -> bytes | None:
    """Return the signing key bytes from JARVIS_APPROVAL_HMAC_KEY, or None if not set."""
    raw = os.getenv("JARVIS_APPROVAL_HMAC_KEY", "").strip()
    return raw.encode() if raw else None


def _extract_approval_hmac(content: str) -> str | None:
    """Extract the 'auth:<token>' HMAC token from a message content string, or None."""
    m = _HMAC_TOKEN_RE.search(content)
    return m.group(1) if m else None


def _verify_approval_hmac(candidate_id: int, token: str) -> bool:
    """
    Verify the HMAC token for the given candidate ID.

    Returns True when:
      - JARVIS_APPROVAL_HMAC_KEY is not set (key absent → skip check, backward compat)
      - Key is set AND token matches the expected HMAC-SHA256[:16] of str(candidate_id)

    Returns False when:
      - Key is set but token is wrong, empty, or missing
    """
    key = _get_hmac_key_bytes()
    if key is None:
        return True  # HMAC not configured — allow all (backward compat)
    expected = _hmac_module.new(key, str(candidate_id).encode(), hashlib.sha256).hexdigest()[:16]
    return _hmac_module.compare_digest(expected, (token or "").lower())


def is_reaction_watcher_enabled() -> bool:
    """
    Return True only when both DISCORD_PERSONAL_BOT_TOKEN and
    DISCORD_PERSONAL_USER_ID are set and non-empty.

    Called fresh on every reconnect attempt so that .env changes take effect
    without an engine restart.
    """
    return bool(_get_bot_token()) and bool(_get_personal_user_id())


# ---------------------------------------------------------------------------
# Discord REST helpers (for posting result feedback to the channel)
# ---------------------------------------------------------------------------


def _auth_headers() -> dict[str, str]:
    token = _get_bot_token()
    if not token:
        raise RuntimeError("DISCORD_PERSONAL_BOT_TOKEN not configured")
    return {
        "Authorization": f"Bot {token}",
        "User-Agent": "DiscordBot (https://github.com/mattamundson/jarvis-trader, 1.0)",
        "Content-Type": "application/json",
    }


async def _post_message(session: aiohttp.ClientSession, channel_id: str, content: str) -> None:
    """Best-effort: post a text message to a channel. Never raises."""
    if len(content) > 2000:
        content = content[:1997] + "..."
    try:
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
        async with session.post(
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
            headers=_auth_headers(),
            json={"content": content},
            timeout=timeout,
        ) as resp:
            if resp.status >= 400:
                text = await resp.text()
                logger.warning(
                    "reaction_watcher: Discord channel post failed %s: %s",
                    resp.status,
                    text[:200],
                )
    except Exception as exc:
        logger.warning("reaction_watcher: post_message failed (non-fatal): %s", exc)


async def _call_engine(
    session: aiohttp.ClientSession,
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Call the local engine API. Returns the JSON response dict or a synthetic
    error dict if the call fails. Never raises.
    """
    api_key = _get_engine_api_key()
    headers = {"X-API-Key": api_key or "", "Content-Type": "application/json"}
    base_url = _get_engine_base_url()
    url = f"{base_url}{path}"
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    try:
        async with session.request(
            method,
            url,
            headers=headers,
            params=params,
            json=json_body,
            timeout=timeout,
        ) as resp:
            text = await resp.text()
            try:
                data = json.loads(text) if text else {}
            except json.JSONDecodeError:
                data = {"raw": text}
            data["_http_status"] = resp.status
            return data
    except Exception as exc:
        logger.warning("reaction_watcher: engine call %s %s failed: %s", method, path, exc)
        return {"error": str(exc), "_http_status": 0}


# ---------------------------------------------------------------------------
# Candidate ID extraction
# ---------------------------------------------------------------------------


def _extract_candidate_id(content: str) -> int | None:
    """Return the candidate ID embedded in a bot-posted approval message, or None."""
    m = _CANDIDATE_ID_RE.search(content)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
# Reaction handler
# ---------------------------------------------------------------------------


async def _handle_reaction(
    session: aiohttp.ClientSession,
    event: dict[str, Any],
    bot_user_id: str,
) -> None:
    """
    Process a single MESSAGE_REACTION_ADD event.

    Security checks (in order):
      1. Reactor user_id must match DISCORD_PERSONAL_USER_ID — ignore all others.
      2. The reacted-to message must be in the personal channel.
      3. The reacted-to message must have been authored by the bot itself.
      4. The message content must contain a parseable candidate ID.
      5. The emoji must be ✅, ❌, or ⏸.
    """
    channel_id = _get_channel_id()
    authorized_user_id = _get_personal_user_id()

    # --- Security gate 1: authorized reactor only ---
    reactor_id = str(event.get("user_id", ""))
    if reactor_id != authorized_user_id:
        logger.debug(
            "reaction_watcher: ignoring reaction from user_id=%s (not authorized)", reactor_id
        )
        return

    # --- Channel filter ---
    event_channel_id = str(event.get("channel_id", ""))
    if event_channel_id != channel_id:
        logger.debug(
            "reaction_watcher: ignoring reaction in channel %s (not personal channel)",
            event_channel_id,
        )
        return

    # --- Identify the emoji ---
    emoji_data = event.get("emoji") or {}
    emoji_name = emoji_data.get("name", "")

    if emoji_name not in (EMOJI_APPROVE, EMOJI_REJECT, EMOJI_EXTEND):
        logger.debug("reaction_watcher: ignoring unrecognized emoji %r", emoji_name)
        return

    # --- Fetch the message from Discord REST to check authorship + extract ID ---
    message_id = str(event.get("message_id", ""))
    msg_data: dict[str, Any] = {}
    try:
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
        async with session.get(
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}",
            headers=_auth_headers(),
            timeout=timeout,
        ) as resp:
            if resp.status == 200:
                msg_data = await resp.json(content_type=None)
            else:
                text = await resp.text()
                logger.warning(
                    "reaction_watcher: could not fetch message %s: %s %s",
                    message_id,
                    resp.status,
                    text[:200],
                )
                return
    except Exception as exc:
        logger.warning("reaction_watcher: message fetch failed: %s", exc)
        return

    # --- Security gate 2: bot-authored message only ---
    msg_author_id = str((msg_data.get("author") or {}).get("id", ""))
    if msg_author_id != bot_user_id:
        logger.debug(
            "reaction_watcher: ignoring reaction on message authored by %s (not the bot)",
            msg_author_id,
        )
        return

    # --- Extract candidate ID from message content (preferred) or embed title (fallback) ---
    # The content field carries the HMAC token; embed title is a backward-compat fallback
    # for pre-HMAC messages (those won't pass HMAC check when key is configured).
    content = msg_data.get("content", "")
    candidate_id = _extract_candidate_id(content)

    if candidate_id is None:
        for embed in msg_data.get("embeds") or []:
            title = embed.get("title") or ""
            candidate_id = _extract_candidate_id(title)
            if candidate_id is not None:
                break

    if candidate_id is None:
        logger.info(
            "reaction_watcher: bot-authored message %s has no parseable candidate ID "
            "(emoji=%s, content=%r)",
            message_id,
            emoji_name,
            content[:120],
        )
        return

    # --- HMAC verification (§6.2) ---
    # Reject reactions to messages that lack a valid HMAC token when key is configured.
    # This closes the forged-reaction attack: even bot-authored messages must carry a
    # token that only the engine (holding JARVIS_APPROVAL_HMAC_KEY) could have produced.
    hmac_token = _extract_approval_hmac(content)
    if not _verify_approval_hmac(candidate_id, hmac_token or ""):
        logger.warning(
            "reaction_watcher: HMAC verification FAILED for candidate %d (message=%s) — "
            "reaction rejected as potentially forged",
            candidate_id,
            message_id,
        )
        return

    logger.info(
        "reaction_watcher: %s reaction from user %s → candidate %d",
        emoji_name,
        reactor_id,
        candidate_id,
    )

    # --- Dispatch to engine ---
    if emoji_name == EMOJI_APPROVE:
        result = await _call_engine(session, "POST", f"/approvals/{candidate_id}/approve")
        status = result.get("_http_status", 0)
        if status == 200:
            sym = result.get("symbol", "?")
            direction = result.get("direction", "?")
            order_id = result.get("order_id", "?")
            reply = (
                f"APPROVED — candidate {candidate_id} ({sym} {direction}) "
                f"submitted as paper order. order_id={order_id}"
            )
        else:
            detail = result.get("detail") or result.get("error") or "unknown error"
            reply = f"Approval FAILED for candidate {candidate_id}: HTTP {status} — {detail}"

    elif emoji_name == EMOJI_REJECT:
        result = await _call_engine(
            session,
            "POST",
            f"/approvals/{candidate_id}/reject",
            json_body={"reason": "Discord reaction ❌"},
        )
        status = result.get("_http_status", 0)
        if status == 200:
            reply = f"REJECTED — candidate {candidate_id} has been rejected."
        else:
            detail = result.get("detail") or result.get("error") or "unknown error"
            reply = f"Rejection FAILED for candidate {candidate_id}: HTTP {status} — {detail}"

    else:  # EMOJI_EXTEND (⏸)
        result = await _call_engine(
            session,
            "POST",
            f"/approvals/{candidate_id}/extend",
            params={"minutes": "30"},
        )
        status = result.get("_http_status", 0)
        if status == 200:
            new_expiry = result.get("expires_at", "?")
            reply = (
                f"EXTENDED — candidate {candidate_id} TTL extended by 30 minutes "
                f"(new expiry: {new_expiry})"
            )
        else:
            detail = result.get("detail") or result.get("error") or "unknown error"
            reply = f"Extend FAILED for candidate {candidate_id}: HTTP {status} — {detail}"

    await _post_message(session, channel_id, reply)


# ---------------------------------------------------------------------------
# Gateway loop
# ---------------------------------------------------------------------------


async def _gateway_session(
    ws: aiohttp.ClientWebSocketResponse,
    session: aiohttp.ClientSession,
    resume_session_id: str | None,
    resume_seq: int | None,
) -> tuple[str | None, int | None, bool]:
    """
    Run one connected gateway session.

    Returns (session_id, last_seq, should_resume) so the caller can decide
    whether to RESUME or re-IDENTIFY on the next connection.
    """
    heartbeat_interval: float = 41.25  # seconds, updated from HELLO
    heartbeat_task: asyncio.Task | None = None
    session_id: str | None = resume_session_id
    last_seq: int | None = resume_seq
    bot_user_id: str | None = None
    should_resume = False

    async def _heartbeat_loop(interval_s: float) -> None:
        while True:
            await asyncio.sleep(interval_s)
            hb = json.dumps({"op": OP_HEARTBEAT, "d": last_seq})
            try:
                await ws.send_str(hb)
                logger.debug("reaction_watcher: sent HEARTBEAT (seq=%s)", last_seq)
            except Exception as exc:
                logger.warning("reaction_watcher: heartbeat send failed: %s", exc)
                return

    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            payload = json.loads(msg.data)
            op: int = payload.get("op", -1)
            data: Any = payload.get("d")
            event_type: str | None = payload.get("t")
            seq: int | None = payload.get("s")

            if seq is not None:
                last_seq = seq

            if op == OP_HELLO:
                # Start heartbeat loop
                heartbeat_interval = (data or {}).get("heartbeat_interval", 41250) / 1000.0
                heartbeat_task = asyncio.create_task(_heartbeat_loop(heartbeat_interval))

                # Send IDENTIFY or RESUME
                token = _get_bot_token() or ""
                if resume_session_id and resume_seq is not None:
                    resume_payload = {
                        "op": OP_RESUME,
                        "d": {
                            "token": token,
                            "session_id": resume_session_id,
                            "seq": resume_seq,
                        },
                    }
                    await ws.send_str(json.dumps(resume_payload))
                    logger.info("reaction_watcher: sent RESUME (session=%s)", resume_session_id)
                else:
                    identify_payload = {
                        "op": OP_IDENTIFY,
                        "d": {
                            "token": token,
                            "intents": GATEWAY_INTENTS,
                            "properties": {
                                "os": "windows",
                                "browser": "jarvis-trader",
                                "device": "jarvis-trader",
                            },
                        },
                    }
                    await ws.send_str(json.dumps(identify_payload))
                    logger.info("reaction_watcher: sent IDENTIFY (intents=%d)", GATEWAY_INTENTS)

            elif op == OP_HEARTBEAT_ACK:
                logger.debug("reaction_watcher: HEARTBEAT_ACK received")

            elif op == OP_DISPATCH:
                if event_type == "READY":
                    session_id = (data or {}).get("session_id")
                    bot_user_id = str(((data or {}).get("user") or {}).get("id", ""))
                    logger.info(
                        "reaction_watcher: READY (session=%s, bot_user_id=%s)",
                        session_id,
                        bot_user_id,
                    )

                elif event_type == "RESUMED":
                    logger.info("reaction_watcher: RESUMED successfully")

                elif event_type == "MESSAGE_REACTION_ADD":
                    if bot_user_id is None:
                        logger.warning(
                            "reaction_watcher: bot_user_id not yet known — ignoring reaction"
                        )
                        continue
                    try:
                        await _handle_reaction(session, data or {}, bot_user_id)
                    except Exception as exc:
                        logger.error(
                            "reaction_watcher: _handle_reaction raised (non-fatal): %s",
                            exc,
                            exc_info=True,
                        )

            elif op == OP_HEARTBEAT:
                # Server requests immediate heartbeat
                hb = json.dumps({"op": OP_HEARTBEAT, "d": last_seq})
                try:
                    await ws.send_str(hb)
                except Exception as _hb_exc:
                    logger.warning("reaction_watcher: server-requested heartbeat failed: %s", _hb_exc)
                    return session_id, last_seq, True

        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING):
            logger.warning(
                "reaction_watcher: gateway closed (code=%s data=%s)",
                ws.close_code,
                msg.data,
            )
            should_resume = ws.close_code not in (4004, 4010, 4011, 4012, 4013, 4014)
            break

        elif msg.type == aiohttp.WSMsgType.ERROR:
            logger.warning("reaction_watcher: gateway websocket error: %s", msg.data)
            should_resume = True
            break

    else:
        # 2026-08-15 incident: the async-for ended by exhausting the iterator
        # (connection dropped with no CLOSE/CLOSING/ERROR frame at all) --
        # previously silent, so an extended run of these looked identical in
        # the log to a healthy idle session. `for...else` skips this when a
        # `break` fired one of the branches above, which already log their
        # own reason.
        logger.warning(
            "reaction_watcher: gateway stream ended with no close frame "
            "(session_id=%s, ready_this_cycle=%s)",
            session_id, session_id is not None,
        )

    if heartbeat_task is not None and not heartbeat_task.done():
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

    return session_id, last_seq, should_resume


async def watch_approval_reactions() -> None:
    """
    Entry point: long-running gateway watcher.

    Starts only if is_reaction_watcher_enabled() returns True. On disconnect,
    backs off exponentially and reconnects. Never raises into the caller.

    Wire this into the FastAPI lifespan via asyncio.create_task().
    """
    if not is_reaction_watcher_enabled():
        logger.info(
            "reaction_watcher: disabled — DISCORD_PERSONAL_BOT_TOKEN or "
            "DISCORD_PERSONAL_USER_ID not set in .env"
        )
        return

    logger.info(
        "reaction_watcher: starting (channel=%s, authorized_user=%s)",
        _get_channel_id(),
        _get_personal_user_id(),
    )

    backoff = _INITIAL_BACKOFF_SECONDS
    resume_session_id: str | None = None
    resume_seq: int | None = None

    while True:
        # Re-check enabled on every reconnect so .env changes take effect
        if not is_reaction_watcher_enabled():
            logger.info("reaction_watcher: disabled at runtime — exiting loop")
            return

        try:
            async with aiohttp.ClientSession() as http_session:
                gateway_url = DISCORD_GATEWAY_URL if not resume_session_id else DISCORD_GATEWAY_URL
                async with http_session.ws_connect(
                    gateway_url,
                    heartbeat=None,  # We manage heartbeats manually
                    timeout=30,
                    compress=0,
                ) as ws:
                    logger.info("reaction_watcher: WebSocket connected")
                    resume_session_id, resume_seq, should_resume = await _gateway_session(
                        ws, http_session, resume_session_id, resume_seq
                    )
                    if resume_session_id is not None:
                        # Only reset backoff once the gateway actually authenticated
                        # (READY/RESUMED set session_id). A raw TCP/TLS connect that
                        # gets IDENTIFY-rejected and closed immediately must NOT reset
                        # backoff, or a bad token/intents config spins the reconnect
                        # loop at the 2s floor forever instead of backing off.
                        backoff = _INITIAL_BACKOFF_SECONDS
                    if not should_resume:
                        # Non-resumable close code — clear resume state and re-identify
                        resume_session_id = None
                        resume_seq = None

        except asyncio.CancelledError:
            logger.info("reaction_watcher: task cancelled — shutting down")
            return
        except Exception as exc:
            logger.error("reaction_watcher: unexpected error: %s", exc, exc_info=True)

        logger.info("reaction_watcher: reconnecting in %ds...", backoff)
        try:
            await asyncio.sleep(backoff)
        except asyncio.CancelledError:
            logger.info("reaction_watcher: sleep cancelled — shutting down")
            return

        backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)

"""
Personal Discord MCP Server — LIVE access to a single channel via Discord REST.

Companion to mcp_server.py (which reads DCE-ingested SQLite rows on ~24h lag).
This server bypasses the nightly DCE pipeline by hitting Discord's REST API
directly with a bot token scoped to one channel — currently Amo's personal
channel 1490851279180660819 in guild 1490851278601982165.

Tools (all hit Discord REST live):
  list_recent_messages       Latest N messages from the channel
  get_message_by_id          Single message by snowflake ID
  search_personal_channel    Substring filter over recent history
  post_to_personal_channel   Write a new message (token must have Send Messages)
  get_channel_info           Channel metadata (sanity check + permissions)

Run as MCP server:
  python engine/discord/personal_mcp_server.py

Required env (engine/.env):
  DISCORD_PERSONAL_BOT_TOKEN   Bot token from https://discord.com/developers/applications
                               Must have MESSAGE CONTENT INTENT enabled.
  DISCORD_PERSONAL_CHANNEL_ID  Target channel snowflake (default: 1490851279180660819)
  DISCORD_PERSONAL_GUILD_ID    Target guild snowflake (default: 1490851278601982165)
                               Currently informational only; not used for routing.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

# Match mcp_server.py: when invoked as a script by Claude Code's MCP launcher,
# sys.path only contains this file's dir, so sibling-package imports fail.
# Add engine/ root to sys.path.
_ENGINE_ROOT = str(Path(__file__).resolve().parent.parent)
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

# Load engine/.env so DISCORD_PERSONAL_BOT_TOKEN is available regardless of
# the parent process env.
try:
    from dotenv import load_dotenv  # type: ignore  # noqa: E402

    _ENV_PATH = Path(_ENGINE_ROOT) / ".env"
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH)
except ImportError:
    pass

import aiohttp  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_CHANNEL_ID = "1490851279180660819"
DEFAULT_GUILD_ID = "1490851278601982165"
DISCORD_API_BASE = "https://discord.com/api/v10"
REQUEST_TIMEOUT_SECONDS = 15
DEFAULT_MESSAGE_LIMIT = 20
MAX_MESSAGE_LIMIT = 100  # Discord REST cap per request


def _get_token() -> str | None:
    """Read bot token from env. Returns None if absent (graceful degradation)."""
    return os.getenv("DISCORD_PERSONAL_BOT_TOKEN")


def _get_channel_id() -> str:
    return os.getenv("DISCORD_PERSONAL_CHANNEL_ID", DEFAULT_CHANNEL_ID)


def _get_guild_id() -> str:
    return os.getenv("DISCORD_PERSONAL_GUILD_ID", DEFAULT_GUILD_ID)


def _auth_headers() -> dict[str, str]:
    token = _get_token()
    if not token:
        raise RuntimeError(
            "DISCORD_PERSONAL_BOT_TOKEN not set in engine/.env — "
            "create a bot at https://discord.com/developers/applications, "
            "drop the token, then restart the MCP server."
        )
    # Discord requires the `DiscordBot (url, version)` UA format at the edge
    # (Cloudflare WAF). Generic UAs get a misleading 403 + code 40333
    # "internal network error". Verified 2026-05-21 — PowerShell default UA
    # was blocked guild-wide; the format below works.
    return {
        "Authorization": f"Bot {token}",
        "User-Agent": "DiscordBot (https://github.com/mattamundson/jarvis-trader, 1.0)",
        "Content-Type": "application/json",
    }


def _format_message(msg: dict[str, Any]) -> dict[str, Any]:
    """Trim Discord's verbose message payload to the fields useful in chat."""
    author = msg.get("author") or {}
    return {
        "id": msg.get("id"),
        "timestamp": msg.get("timestamp"),
        "edited_timestamp": msg.get("edited_timestamp"),
        "author_id": author.get("id"),
        "author_name": author.get("username"),
        "content": msg.get("content", ""),
        "attachments": [
            {
                "url": a.get("url"),
                "filename": a.get("filename"),
                "content_type": a.get("content_type"),
                "size": a.get("size"),
            }
            for a in (msg.get("attachments") or [])
        ],
        "embeds": [
            {
                "title": e.get("title"),
                "description": e.get("description"),
                "url": e.get("url"),
                "type": e.get("type"),
            }
            for e in (msg.get("embeds") or [])
        ],
        "referenced_message_id": (msg.get("referenced_message") or {}).get("id"),
        "pinned": msg.get("pinned", False),
    }


# ---------------------------------------------------------------------------
# REST helpers
# ---------------------------------------------------------------------------


async def _discord_get(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET against Discord REST. Raises on non-2xx; caller handles."""
    headers = _auth_headers()
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(f"{DISCORD_API_BASE}{path}", headers=headers, params=params) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"Discord GET {path} failed: {resp.status} {text[:300]}")
            return await resp.json(content_type=None) if text else None


async def _discord_post(path: str, payload: dict[str, Any]) -> Any:
    """POST against Discord REST. Raises on non-2xx; caller handles."""
    headers = _auth_headers()
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(f"{DISCORD_API_BASE}{path}", headers=headers, json=payload) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"Discord POST {path} failed: {resp.status} {text[:300]}")
            return await resp.json(content_type=None) if text else None


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("discord-personal")


@mcp.tool()
async def list_recent_messages(limit: int = DEFAULT_MESSAGE_LIMIT) -> list[dict[str, Any]]:
    """Fetch the latest messages from the personal Discord channel.

    Args:
      limit: number of messages to return (1-100). Defaults to 20.

    Returns:
      List of message dicts with id, timestamp, author_name, content,
      attachments, embeds, referenced_message_id, pinned. Newest first.
    """
    clamped = max(1, min(int(limit), MAX_MESSAGE_LIMIT))
    channel_id = _get_channel_id()
    try:
        raw = await _discord_get(f"/channels/{channel_id}/messages", params={"limit": clamped})
    except Exception as exc:
        logger.warning("list_recent_messages failed: %s", exc)
        return []
    if not isinstance(raw, list):
        return []
    return [_format_message(m) for m in raw]


@mcp.tool()
async def get_message_by_id(message_id: str) -> dict[str, Any]:
    """Fetch a single message by its Discord snowflake ID.

    Args:
      message_id: Discord message snowflake (numeric string).

    Returns:
      Message dict (same shape as list_recent_messages entries) or empty dict
      if not found / not in the personal channel.
    """
    channel_id = _get_channel_id()
    try:
        raw = await _discord_get(f"/channels/{channel_id}/messages/{message_id}")
    except Exception as exc:
        logger.warning("get_message_by_id(%s) failed: %s", message_id, exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    return _format_message(raw)


@mcp.tool()
async def search_personal_channel(
    query: str, limit: int = DEFAULT_MESSAGE_LIMIT, scan: int = 100
) -> list[dict[str, Any]]:
    """Substring-match against recent messages in the personal channel.

    Discord REST does not expose channel-scoped search to bots; this fetches
    the last `scan` messages and filters client-side. For deeper searches use
    the DCE-ingested bookmark tools in discord-jarvis MCP.

    Args:
      query: case-insensitive substring to match against message content.
      limit: max matches to return (1-100). Defaults to 20.
      scan: how many recent messages to scan over. 1-100. Defaults to 100.

    Returns:
      Up to `limit` matching messages, newest first.
    """
    q = (query or "").strip().lower()
    if not q:
        return []
    clamped_limit = max(1, min(int(limit), MAX_MESSAGE_LIMIT))
    clamped_scan = max(1, min(int(scan), MAX_MESSAGE_LIMIT))
    channel_id = _get_channel_id()
    try:
        raw = await _discord_get(f"/channels/{channel_id}/messages", params={"limit": clamped_scan})
    except Exception as exc:
        logger.warning("search_personal_channel failed: %s", exc)
        return []
    if not isinstance(raw, list):
        return []
    matches: list[dict[str, Any]] = []
    for m in raw:
        content = (m.get("content") or "").lower()
        if q in content:
            matches.append(_format_message(m))
            if len(matches) >= clamped_limit:
                break
    return matches


@mcp.tool()
async def post_to_personal_channel(content: str) -> dict[str, Any]:
    """Post a new message to the personal channel.

    Args:
      content: message text (1-2000 chars per Discord limit).

    Returns:
      Posted message dict, or {"error": "..."} on failure.
    """
    text = (content or "").strip()
    if not text:
        return {"error": "content cannot be empty"}
    if len(text) > 2000:
        return {"error": f"content too long ({len(text)} > 2000 chars)"}
    channel_id = _get_channel_id()
    try:
        raw = await _discord_post(f"/channels/{channel_id}/messages", payload={"content": text})
    except Exception as exc:
        logger.warning("post_to_personal_channel failed: %s", exc)
        return {"error": str(exc)}
    if not isinstance(raw, dict):
        return {"error": "unexpected response shape"}
    return _format_message(raw)


@mcp.tool()
async def get_channel_info() -> dict[str, Any]:
    """Return channel metadata and configured scope. Useful as a sanity check
    that the bot has been invited to the guild and can see the channel.

    Returns:
      {"channel_id", "guild_id", "name", "type", "topic",
       "permissions_ok": bool, "error": str|None}
    """
    channel_id = _get_channel_id()
    guild_id = _get_guild_id()
    result: dict[str, Any] = {
        "channel_id": channel_id,
        "guild_id": guild_id,
        "name": None,
        "type": None,
        "topic": None,
        "permissions_ok": False,
        "error": None,
    }
    try:
        raw = await _discord_get(f"/channels/{channel_id}")
    except Exception as exc:
        result["error"] = str(exc)
        return result
    if not isinstance(raw, dict):
        result["error"] = "unexpected channel payload shape"
        return result
    result["name"] = raw.get("name")
    result["type"] = raw.get("type")
    result["topic"] = raw.get("topic")
    result["permissions_ok"] = True
    return result


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("PERSONAL_MCP_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger.info(
        "discord-personal MCP starting (channel=%s, guild=%s, token=%s)",
        _get_channel_id(),
        _get_guild_id(),
        "set" if _get_token() else "MISSING",
    )
    mcp.run()

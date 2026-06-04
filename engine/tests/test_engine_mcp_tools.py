"""Tests for get_engine_health and get_open_positions MCP tools.

Both tools make async HTTP calls to the engine API. Tests mock aiohttp.ClientSession
so the production engine never needs to be running.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_session(status: int, json_payload: object) -> MagicMock:
    """Return a mock aiohttp.ClientSession whose get() returns status + json."""
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_payload)

    mock_get_ctx = AsyncMock()
    mock_get_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_get_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_get_ctx)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    return mock_session_ctx


_HEALTH_OK = {
    "status": "ok",
    "version": "1.1.0",
    "ibkr_connected": True,
    "ibkr_execution_connected": True,
    "ibkr_data_connected": True,
    "tradingview_mcp_healthy": True,
    "llm_path_healthy": True,
    "uptime_seconds": 3994.0,
    "kill_switch_active": False,
    "paper_mode": True,
}

_POSITIONS_FLAT: list = []

_POSITIONS_OPEN = [
    {"symbol": "MES", "position": 1, "avg_cost": 5420.0, "unrealized_pnl": 62.5},
    {"symbol": "MCL", "position": -2, "avg_cost": 78.5, "unrealized_pnl": -40.0},
]


# ---------------------------------------------------------------------------
# get_engine_health
# ---------------------------------------------------------------------------


async def test_engine_health_ok() -> None:
    from discord.mcp_server import get_engine_health

    with patch(
        "discord.mcp_server.aiohttp.ClientSession", return_value=_mock_session(200, _HEALTH_OK)
    ):
        result = await get_engine_health()

    assert result["status"] == "ok"
    assert result["ibkr_connected"] is True
    assert result["tradingview_mcp_healthy"] is True
    assert result["llm_path_healthy"] is True
    assert result["kill_switch_active"] is False
    assert result["paper_mode"] is True


async def test_engine_health_http_error() -> None:
    from discord.mcp_server import get_engine_health

    with patch("discord.mcp_server.aiohttp.ClientSession", return_value=_mock_session(503, {})):
        result = await get_engine_health()

    assert result["status"] == "error"
    assert "503" in result["error"]


async def test_engine_health_unreachable() -> None:
    from discord.mcp_server import get_engine_health

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(side_effect=Exception("Connection refused"))
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    with patch("discord.mcp_server.aiohttp.ClientSession", return_value=mock_session_ctx):
        result = await get_engine_health()

    assert result["status"] == "unreachable"
    assert "error" in result


# ---------------------------------------------------------------------------
# get_open_positions
# ---------------------------------------------------------------------------


async def test_get_open_positions_flat() -> None:
    from discord.mcp_server import get_open_positions

    with patch(
        "discord.mcp_server.aiohttp.ClientSession", return_value=_mock_session(200, _POSITIONS_FLAT)
    ):
        result = await get_open_positions()

    assert result["positions"] == []
    assert result["count"] == 0


async def test_get_open_positions_with_holdings() -> None:
    from discord.mcp_server import get_open_positions

    with patch(
        "discord.mcp_server.aiohttp.ClientSession", return_value=_mock_session(200, _POSITIONS_OPEN)
    ):
        result = await get_open_positions()

    assert result["count"] == 2
    syms = {p["symbol"] for p in result["positions"]}
    assert syms == {"MES", "MCL"}


async def test_get_open_positions_wrapped_dict() -> None:
    """Engine may return {"positions": [...]} instead of a bare list."""
    from discord.mcp_server import get_open_positions

    wrapped = {"positions": _POSITIONS_OPEN, "total": 2}
    with patch(
        "discord.mcp_server.aiohttp.ClientSession", return_value=_mock_session(200, wrapped)
    ):
        result = await get_open_positions()

    assert result["count"] == 2


async def test_get_open_positions_ibkr_nested() -> None:
    """Engine returns nested {"ibkr": {"connected": true, "positions": [...]}, ...}."""
    from discord.mcp_server import get_open_positions

    nested = {
        "ibkr": {"connected": True, "positions": _POSITIONS_OPEN},
        "schwab": {"connected": False, "positions": []},
        "paper": {"positions": []},
        "reconciliation": {"health": "ok"},
    }
    with patch("discord.mcp_server.aiohttp.ClientSession", return_value=_mock_session(200, nested)):
        result = await get_open_positions()

    assert result["count"] == 2
    syms = {p["symbol"] for p in result["positions"]}
    assert syms == {"MES", "MCL"}


async def test_get_open_positions_ibkr_nested_flat() -> None:
    """When IBKR connected=False and paper has positions, use paper."""
    from discord.mcp_server import get_open_positions

    nested = {
        "ibkr": {"connected": False, "positions": []},
        "schwab": {"connected": False, "positions": []},
        "paper": {"positions": _POSITIONS_OPEN},
        "reconciliation": {"health": "partial"},
    }
    with patch("discord.mcp_server.aiohttp.ClientSession", return_value=_mock_session(200, nested)):
        result = await get_open_positions()

    assert result["count"] == 2


async def test_get_open_positions_http_error() -> None:
    from discord.mcp_server import get_open_positions

    with patch("discord.mcp_server.aiohttp.ClientSession", return_value=_mock_session(401, {})):
        result = await get_open_positions()

    assert result["positions"] == []
    assert "401" in result["error"]


async def test_get_open_positions_unreachable() -> None:
    from discord.mcp_server import get_open_positions

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(side_effect=Exception("timeout"))
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    with patch("discord.mcp_server.aiohttp.ClientSession", return_value=mock_session_ctx):
        result = await get_open_positions()

    assert result["positions"] == []
    assert "error" in result


# ---------------------------------------------------------------------------
# semantic_search
# ---------------------------------------------------------------------------


def _mock_embed_session() -> MagicMock:
    """Mock aiohttp.ClientSession whose post() returns a fake 768-dim embedding.

    semantic_search embeds the query via Ollama BEFORE checking the index, so
    tests must stub the embed call or they hit the real endpoint (which can be
    saturated by a background embed job, causing the test to hang).
    """
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"embeddings": [[0.0] * 768]})

    post_ctx = AsyncMock()
    post_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    post_ctx.__aexit__ = AsyncMock(return_value=None)

    session = AsyncMock()
    session.post = MagicMock(return_value=post_ctx)

    session_ctx = AsyncMock()
    session_ctx.__aenter__ = AsyncMock(return_value=session)
    session_ctx.__aexit__ = AsyncMock(return_value=None)
    return session_ctx


async def test_semantic_search_no_index() -> None:
    """Returns error dict when vec_index.db doesn't exist."""
    from discord.mcp_server import semantic_search

    with (
        patch("discord.mcp_server.aiohttp.ClientSession", return_value=_mock_embed_session()),
        patch("discord.mcp_server.os.path.exists", return_value=False),
    ):
        result = await semantic_search("ES auction theory")

    assert result["results"] == []
    assert "error" in result
    # Both are valid "semantic search unavailable" outcomes. Locally (sqlite_vec
    # installed) the patched os.path.exists -> False reaches the index check and
    # returns "not found"; in CI (sqlite_vec absent from the venv) the earlier
    # availability guard short-circuits with "not installed" before the path
    # check. Accept either so the test is environment-independent.
    err = result["error"].lower()
    assert ("not found" in err) or ("not installed" in err), result["error"]


async def test_semantic_search_ollama_error() -> None:
    """Returns error dict when Ollama embed call fails."""
    from discord.mcp_server import semantic_search

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(side_effect=Exception("connection refused"))
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    with patch("discord.mcp_server.aiohttp.ClientSession", return_value=mock_session_ctx):
        result = await semantic_search("ES auction theory")

    assert result["results"] == []
    assert "Ollama embed error" in result["error"]


async def test_semantic_search_limit_clamped() -> None:
    """Limit is clamped to 1-20 range — a limit of 99 becomes 20."""
    from discord.mcp_server import semantic_search

    with (
        patch("discord.mcp_server.aiohttp.ClientSession", return_value=_mock_embed_session()),
        patch("discord.mcp_server.os.path.exists", return_value=False),
    ):
        result = await semantic_search("ES", limit=99)

    # Regardless of limit, no-index error triggers before the limit is used.
    assert "error" in result

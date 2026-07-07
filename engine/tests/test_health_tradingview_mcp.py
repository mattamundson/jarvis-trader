"""Tests for the two-stage TradingView MCP health probe in health_router.

Stage 1: socket port check (0.5s timeout) — fast fail if TV Desktop not running.
Stage 2: CDP HTTP probe — only reached if port 9222 is listening.

Return shape: (healthy: bool, details: str | None, status: str)
where status in {not_running, connecting, healthy, degraded}.
"""
from __future__ import annotations

import socket
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from routers import health_router


@pytest.fixture(autouse=True)
def _reset_tv_health_cache():
    """Start every test with an empty cache so state doesn't leak between tests."""
    health_router._tv_mcp_health_cache.update(
        checked_at=0.0, healthy=False, details="not yet probed", status="connecting",
    )
    yield


def _fake_socket(connect_result: int = 0):
    """Return a mock socket.socket where connect_ex returns connect_result."""
    sock = MagicMock()
    sock.connect_ex.return_value = connect_result
    sock.__enter__ = lambda s: s
    sock.__exit__ = lambda s, *a: None
    return sock


def _fake_urlopen_response(status: int = 200):
    resp = MagicMock()
    resp.status = status
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda self, *a: None
    return resp


def _patch_socket(connect_result: int):
    """Patch socket.socket constructor so connect_ex returns connect_result."""
    return patch(
        "routers.health_router.socket.socket",
        return_value=_fake_socket(connect_result),
    )


# ── port-check stage ─────────────────────────────────────────────────────────

def test_port_not_listening_returns_not_running():
    with _patch_socket(connect_result=111):  # ECONNREFUSED
        healthy, details, status = health_router._check_tradingview_mcp_health()
    assert healthy is False
    assert status == "not_running"
    assert "port 9222 not listening" in details


def test_port_not_listening_skips_cdp_probe():
    with _patch_socket(connect_result=111) as mock_sock:
        with patch("routers.health_router.urllib.request.urlopen") as mock_urlopen:
            health_router._check_tradingview_mcp_health()
    mock_urlopen.assert_not_called()


# ── CDP probe stage ───────────────────────────────────────────────────────────

def test_cdp_200_returns_healthy():
    with _patch_socket(connect_result=0):
        with patch("routers.health_router.urllib.request.urlopen",
                   return_value=_fake_urlopen_response(200)):
            healthy, details, status = health_router._check_tradingview_mcp_health()
    assert healthy is True
    assert details is None
    assert status == "healthy"


def test_cdp_url_error_returns_connecting():
    err = urllib.error.URLError("Connection refused")
    with _patch_socket(connect_result=0):
        with patch("routers.health_router.urllib.request.urlopen", side_effect=err):
            healthy, details, status = health_router._check_tradingview_mcp_health()
    assert healthy is False
    assert status == "connecting"
    assert "CDP port 9222 unreachable" in details


def test_cdp_non200_returns_degraded():
    with _patch_socket(connect_result=0):
        with patch("routers.health_router.urllib.request.urlopen",
                   return_value=_fake_urlopen_response(500)):
            healthy, details, status = health_router._check_tradingview_mcp_health()
    assert healthy is False
    assert status == "degraded"
    assert "HTTP 500" in details


def test_cdp_unexpected_exception_returns_connecting():
    with _patch_socket(connect_result=0):
        with patch("routers.health_router.urllib.request.urlopen",
                   side_effect=RuntimeError("boom")):
            healthy, details, status = health_router._check_tradingview_mcp_health()
    assert healthy is False
    assert status == "connecting"
    assert "boom" in details


# ── cache behaviour ───────────────────────────────────────────────────────────

def test_cache_short_circuits_second_call():
    with _patch_socket(connect_result=0):
        with patch("routers.health_router.urllib.request.urlopen",
                   return_value=_fake_urlopen_response(200)) as mock_urlopen:
            health_router._check_tradingview_mcp_health()
            health_router._check_tradingview_mcp_health()
            health_router._check_tradingview_mcp_health()
    assert mock_urlopen.call_count == 1


def test_cache_re_probes_after_ttl_expires():
    with _patch_socket(connect_result=0):
        with patch("routers.health_router.urllib.request.urlopen",
                   return_value=_fake_urlopen_response(200)) as mock_urlopen:
            health_router._check_tradingview_mcp_health()
            assert mock_urlopen.call_count == 1
            health_router._tv_mcp_health_cache["checked_at"] -= 31.0
            health_router._check_tradingview_mcp_health()
            assert mock_urlopen.call_count == 2


def test_cache_stores_status_healthy():
    with _patch_socket(connect_result=0):
        with patch("routers.health_router.urllib.request.urlopen",
                   return_value=_fake_urlopen_response(200)):
            health_router._check_tradingview_mcp_health()
    assert health_router._tv_mcp_health_cache["status"] == "healthy"


def test_cache_stores_status_not_running():
    with _patch_socket(connect_result=111):
        health_router._check_tradingview_mcp_health()
    assert health_router._tv_mcp_health_cache["status"] == "not_running"


def test_cache_returns_stored_status_on_hit():
    """Cache hit must return all three fields including status."""
    health_router._tv_mcp_health_cache.update(
        checked_at=1e18,  # far future — will never expire
        healthy=True,
        details=None,
        status="healthy",
    )
    healthy, details, status = health_router._check_tradingview_mcp_health()
    assert healthy is True
    assert status == "healthy"

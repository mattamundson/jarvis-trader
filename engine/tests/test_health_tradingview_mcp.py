"""Roadmap P0.6 — TradingView MCP healthcheck in /health.

Unit tests for `_check_tradingview_mcp_health` in `routers.health_router`.
Covers: CDP up, CDP unreachable, CDP non-200, timeout, and cache TTL.

The helper probes `http://127.0.0.1:9222/json/version` which TradingView
Desktop exposes when launched with `--remote-debugging-port=9222`. Failure
modes we care about:
  * TV Desktop not running → ConnectionRefused
  * TV launched without CDP flag → port simply not bound (same symptom)
  * TV responding but with non-200 (rare; suggests a browser conflict)

The 30s cache is load-bearing: `/health` is polled by the dashboard every
few seconds and we don't want to hammer CDP.
"""
from __future__ import annotations

import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from routers import health_router


@pytest.fixture(autouse=True)
def _reset_tv_health_cache():
    """Start every test with an empty cache so state doesn't leak between tests."""
    health_router._tv_mcp_health_cache.update(
        checked_at=0.0, healthy=False, details="not yet probed",
    )
    yield


def _fake_urlopen_response(status: int = 200):
    """Build a context-manager-capable mock matching urlopen's interface."""
    resp = MagicMock()
    resp.status = status
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda self, *a: None
    return resp


def test_cdp_reachable_returns_healthy_true():
    with patch("routers.health_router.urllib.request.urlopen",
               return_value=_fake_urlopen_response(200)):
        healthy, details = health_router._check_tradingview_mcp_health()
    assert healthy is True
    assert details is None


def test_cdp_unreachable_returns_healthy_false_with_details():
    err = urllib.error.URLError("Connection refused")
    with patch("routers.health_router.urllib.request.urlopen", side_effect=err):
        healthy, details = health_router._check_tradingview_mcp_health()
    assert healthy is False
    assert details is not None
    assert "CDP port 9222 unreachable" in details


def test_cdp_non200_returns_healthy_false():
    with patch("routers.health_router.urllib.request.urlopen",
               return_value=_fake_urlopen_response(500)):
        healthy, details = health_router._check_tradingview_mcp_health()
    assert healthy is False
    assert details is not None
    assert "HTTP 500" in details


def test_cdp_unexpected_exception_captured():
    with patch("routers.health_router.urllib.request.urlopen",
               side_effect=RuntimeError("boom")):
        healthy, details = health_router._check_tradingview_mcp_health()
    assert healthy is False
    assert details is not None
    assert "boom" in details


def test_cache_short_circuits_second_call():
    """Second call within TTL should NOT re-probe. Saves CDP from flood at /health rate."""
    with patch("routers.health_router.urllib.request.urlopen",
               return_value=_fake_urlopen_response(200)) as mock_urlopen:
        health_router._check_tradingview_mcp_health()  # first call — probes
        health_router._check_tradingview_mcp_health()  # second call — cached
        health_router._check_tradingview_mcp_health()  # third call — cached
    assert mock_urlopen.call_count == 1


def test_cache_re_probes_after_ttl_expires(monkeypatch):
    """Jump the monotonic clock past 30s; next call re-probes."""
    with patch("routers.health_router.urllib.request.urlopen",
               return_value=_fake_urlopen_response(200)) as mock_urlopen:
        health_router._check_tradingview_mcp_health()
        assert mock_urlopen.call_count == 1

        # Fast-forward past the 30s TTL by overwriting the cache's checked_at.
        health_router._tv_mcp_health_cache["checked_at"] -= 31.0

        health_router._check_tradingview_mcp_health()
        assert mock_urlopen.call_count == 2

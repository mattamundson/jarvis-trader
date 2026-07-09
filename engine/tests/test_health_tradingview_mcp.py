"""Tests for the two-stage TradingView MCP health probe in health_router.

Stage 1: socket port check (0.5s timeout) — fast fail if TV Desktop not running.
Stage 2: CDP HTTP probe — only reached if port 9222 is listening.

Return shape: (healthy: bool, details: str | None, status: str)
where status in {not_running, connecting, healthy, degraded}.

SOTA P1.6: a transient post-port-open failure within _TV_MCP_GRACE_TTL_SEC of a
real success is masked behind the last-known-good result (grace cache), so a
single missed CDP probe doesn't flip top-line /health. `not_running` is never
masked — it's a steady, expected condition and always reports immediately.
"""
from __future__ import annotations

import asyncio
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
    health_router._tv_mcp_last_good.update(at=0.0, details=None)
    health_router._tv_mcp_refresher_task = None
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


# ── grace-cache masking (P1.6 flap fix) ────────────────────────────────────────
#
# "TV Desktop not installed" (not_running) must stay steady/expected and never be
# masked. "CDP transiently unreachable" (connecting/degraded after a real success)
# must NOT flip top-line health within the grace window — that's the flap this
# story fixes.

def test_transient_failure_within_grace_is_masked_as_healthy():
    """A real success followed by one transient blip stays reported healthy."""
    with _patch_socket(connect_result=0):
        with patch(
            "routers.health_router.urllib.request.urlopen",
            return_value=_fake_urlopen_response(200),
        ):
            health_router._check_tradingview_mcp_health()  # real success -> last_good set

        # Force a re-probe (bypass the 30s poll cache) but stay inside grace.
        health_router._tv_mcp_health_cache["checked_at"] -= 31.0
        err = urllib.error.URLError("Connection refused")
        with patch("routers.health_router.urllib.request.urlopen", side_effect=err):
            healthy, details, status = health_router._check_tradingview_mcp_health()

    assert healthy is True
    assert status == "healthy"
    assert "masked by grace cache" in details
    assert "Connection refused" in details


def test_transient_failure_outside_grace_reports_unhealthy():
    """Once the grace window has fully elapsed, a real outage is reported."""
    with _patch_socket(connect_result=0):
        with patch(
            "routers.health_router.urllib.request.urlopen",
            return_value=_fake_urlopen_response(200),
        ):
            health_router._check_tradingview_mcp_health()  # real success -> last_good set

        # Push both the poll cache AND the last-good grace window into the past.
        health_router._tv_mcp_health_cache["checked_at"] -= 31.0
        health_router._tv_mcp_last_good["at"] -= (health_router._TV_MCP_GRACE_TTL_SEC + 1.0)
        err = urllib.error.URLError("Connection refused")
        with patch("routers.health_router.urllib.request.urlopen", side_effect=err):
            healthy, details, status = health_router._check_tradingview_mcp_health()

    assert healthy is False
    assert status == "connecting"
    assert "masked by grace cache" not in details


def test_first_ever_transient_failure_is_not_masked():
    """No prior success exists (cold start) -- nothing to mask a blip behind."""
    with _patch_socket(connect_result=0):
        err = urllib.error.URLError("Connection refused")
        with patch("routers.health_router.urllib.request.urlopen", side_effect=err):
            healthy, details, status = health_router._check_tradingview_mcp_health()

    assert healthy is False
    assert status == "connecting"


def test_not_running_is_never_masked_even_inside_grace():
    """TV Desktop closing right after a success must report not_running immediately."""
    with _patch_socket(connect_result=0):
        with patch(
            "routers.health_router.urllib.request.urlopen",
            return_value=_fake_urlopen_response(200),
        ):
            health_router._check_tradingview_mcp_health()  # real success -> last_good set

    health_router._tv_mcp_health_cache["checked_at"] -= 31.0
    with _patch_socket(connect_result=111):  # port closed -- TV Desktop was shut down
        healthy, details, status = health_router._check_tradingview_mcp_health()

    assert healthy is False
    assert status == "not_running"


def test_not_running_clears_grace_memory():
    """A steady not_running state must reset last_good so a future relaunch's own
    startup blips aren't compared against a long-dead prior session."""
    with _patch_socket(connect_result=0):
        with patch(
            "routers.health_router.urllib.request.urlopen",
            return_value=_fake_urlopen_response(200),
        ):
            health_router._check_tradingview_mcp_health()
    assert health_router._tv_mcp_last_good["at"] > 0.0

    health_router._tv_mcp_health_cache["checked_at"] -= 31.0
    with _patch_socket(connect_result=111):
        health_router._check_tradingview_mcp_health()

    assert health_router._tv_mcp_last_good["at"] == 0.0


def test_repeated_not_running_polls_stay_steady_not_running():
    """Simulates the steady 'TV Desktop not installed' state across many polls --
    must never oscillate into healthy/connecting."""
    statuses = []
    with _patch_socket(connect_result=111):
        for _ in range(5):
            health_router._tv_mcp_health_cache["checked_at"] -= 31.0
            _, _, status = health_router._check_tradingview_mcp_health()
            statuses.append(status)

    assert statuses == ["not_running"] * 5


# ── background refresher ────────────────────────────────────────────────────────

async def _cancel_and_await(task: "asyncio.Task") -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_ensure_background_refresher_starts_task_from_running_loop():
    assert health_router._tv_mcp_refresher_task is None
    health_router._ensure_tv_mcp_background_refresher()
    try:
        assert health_router._tv_mcp_refresher_task is not None
        assert isinstance(health_router._tv_mcp_refresher_task, asyncio.Task)
        assert not health_router._tv_mcp_refresher_task.done()
    finally:
        await _cancel_and_await(health_router._tv_mcp_refresher_task)


@pytest.mark.asyncio
async def test_ensure_background_refresher_is_idempotent():
    health_router._ensure_tv_mcp_background_refresher()
    first_task = health_router._tv_mcp_refresher_task
    health_router._ensure_tv_mcp_background_refresher()
    try:
        assert health_router._tv_mcp_refresher_task is first_task
    finally:
        await _cancel_and_await(first_task)


def test_ensure_background_refresher_noop_without_running_loop():
    """Called from a sync context (no running event loop) -- must not raise."""
    health_router._ensure_tv_mcp_background_refresher()
    assert health_router._tv_mcp_refresher_task is None


@pytest.mark.asyncio
async def test_background_refresh_loop_updates_cache_without_blocking_caller():
    with _patch_socket(connect_result=0):
        with patch(
            "routers.health_router.urllib.request.urlopen",
            return_value=_fake_urlopen_response(200),
        ):
            task = asyncio.create_task(health_router._tv_mcp_background_refresh_loop())
            try:
                await asyncio.sleep(0.05)
                assert health_router._tv_mcp_health_cache["status"] == "healthy"
            finally:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

"""Tests for the /health single-flight snapshot cache (resilience under load spikes).

`_health_cached` wraps `_health_inner` so that a burst of concurrent /health
requests (the dashboard polls it many times per second) collapses to at most one
blocking recompute per TTL window — preventing the event-loop pileup that lets a
warm 20ms call spike to 5-12s under machine contention. These tests pin the
single-flight, TTL, and cold-start semantics without needing a live server.
"""

from __future__ import annotations

import asyncio

import pytest

from routers import health_router


@pytest.fixture(autouse=True)
def _reset_snapshot():
    """Clear the snapshot cache so cross-test state doesn't leak."""
    health_router._health_snapshot.update(computed_at=0.0, payload=None)
    yield
    health_router._health_snapshot.update(computed_at=0.0, payload=None)


def _install_counting_inner(monkeypatch, delay: float = 0.05):
    """Replace _health_inner with an async stub that counts calls and yields."""
    calls = {"n": 0}

    async def _fake_inner() -> dict:
        calls["n"] += 1
        # Yield so concurrent callers all reach the cache-check/lock before the
        # first compute finishes — exercises the single-flight path.
        await asyncio.sleep(delay)
        return {"status": "ok", "compute_id": calls["n"]}

    monkeypatch.setattr(health_router, "_health_inner", _fake_inner)
    return calls


def test_concurrent_burst_computes_once(monkeypatch):
    """A storm of concurrent callers within one TTL window → exactly one compute."""
    monkeypatch.setattr(health_router, "_HEALTH_SNAPSHOT_TTL_SEC", 1.0)
    calls = _install_counting_inner(monkeypatch)

    async def _run():
        return await asyncio.gather(*[health_router._health_cached() for _ in range(20)])

    results = asyncio.run(_run())

    assert calls["n"] == 1, "single-flight: 20 concurrent callers must share one compute"
    # Every caller gets the same shared payload.
    assert all(r["compute_id"] == 1 for r in results)


def test_second_call_within_ttl_uses_cache(monkeypatch):
    """A follow-up call inside the TTL returns the cached payload, no recompute."""
    monkeypatch.setattr(health_router, "_HEALTH_SNAPSHOT_TTL_SEC", 5.0)
    calls = _install_counting_inner(monkeypatch, delay=0.0)

    async def _run():
        first = await health_router._health_cached()
        second = await health_router._health_cached()
        return first, second

    first, second = asyncio.run(_run())
    assert calls["n"] == 1
    assert first is second  # same cached object handed back


def test_ttl_zero_always_recomputes(monkeypatch):
    """TTL<=0 disables the cache — each call is live (for callers needing truth)."""
    monkeypatch.setattr(health_router, "_HEALTH_SNAPSHOT_TTL_SEC", 0.0)
    calls = _install_counting_inner(monkeypatch, delay=0.0)

    async def _run():
        await health_router._health_cached()
        await health_router._health_cached()
        await health_router._health_cached()

    asyncio.run(_run())
    assert calls["n"] == 3


def test_cold_first_call_is_live(monkeypatch):
    """The first call after boot (empty cache) always computes — keeps
    port_guardian readiness truthful rather than serving a stale/None snapshot."""
    monkeypatch.setattr(health_router, "_HEALTH_SNAPSHOT_TTL_SEC", 5.0)
    calls = _install_counting_inner(monkeypatch, delay=0.0)

    result = asyncio.run(health_router._health_cached())
    assert calls["n"] == 1
    assert result["status"] == "ok"


def test_stale_snapshot_triggers_recompute(monkeypatch):
    """A snapshot older than the TTL is recomputed on the next call."""
    monkeypatch.setattr(health_router, "_HEALTH_SNAPSHOT_TTL_SEC", 1.0)
    calls = _install_counting_inner(monkeypatch, delay=0.0)

    async def _run():
        await health_router._health_cached()  # compute #1
        # Force the snapshot to look old without sleeping the wall clock.
        health_router._health_snapshot["computed_at"] -= 10.0
        await health_router._health_cached()  # must recompute → #2

    asyncio.run(_run())
    assert calls["n"] == 2

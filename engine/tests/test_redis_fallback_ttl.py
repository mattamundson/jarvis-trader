"""
Regression tests for the in-memory fallback cache's TTL handling.

Bug: cache.redis_client's in-memory fallback (used whenever Redis is down, or
whenever a single Redis call transiently fails) stored raw values with no
expiry at all. Any TTL passed by a caller (signal_cache's 30-min signal cache,
alert_cooldown's 2-hour cooldown, feature_store's 5-min indicator cache) was
silently dropped in fallback mode, so a stale signal — or a muted alert —
could live forever instead of expiring on schedule. See task: "fix
signal-cache staleness bug (never-expiring cache)".
"""

import time

import pytest

from cache import redis_client


@pytest.fixture(autouse=True)
def _reset_fallback_state():
    """Isolate each test's fallback cache and force fallback mode."""
    redis_client._fallback_cache.clear()
    prev_enabled = redis_client._redis_enabled
    prev_client = redis_client._redis_client
    redis_client._redis_enabled = False
    redis_client._redis_client = None
    yield
    redis_client._fallback_cache.clear()
    redis_client._redis_enabled = prev_enabled
    redis_client._redis_client = prev_client


@pytest.mark.asyncio
async def test_fallback_entry_expires_after_ttl(monkeypatch):
    """A fallback entry must become unreadable once its TTL elapses."""
    fake_now = [1_000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_now[0])

    await redis_client.set("jarvis:signal:MES", "cached-signal", ttl_seconds=1800)
    assert await redis_client.get("jarvis:signal:MES") == "cached-signal"
    assert await redis_client.exists("jarvis:signal:MES") is True

    # Advance past the TTL.
    fake_now[0] += 1801

    assert await redis_client.get("jarvis:signal:MES") is None
    assert await redis_client.exists("jarvis:signal:MES") is False


@pytest.mark.asyncio
async def test_fallback_entry_still_valid_before_ttl(monkeypatch):
    """An entry must remain readable right up until its TTL elapses."""
    fake_now = [1_000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_now[0])

    await redis_client.set("jarvis:cooldown:whatsapp:MES", "1", ttl_seconds=7200)
    fake_now[0] += 7199

    assert await redis_client.get("jarvis:cooldown:whatsapp:MES") == "1"
    assert await redis_client.exists("jarvis:cooldown:whatsapp:MES") is True


@pytest.mark.asyncio
async def test_expired_fallback_entry_is_evicted_not_just_hidden():
    """An expired read must actually remove the dead entry, not leak memory forever."""
    await redis_client.set("jarvis:indicators:MES:5m", "{}", ttl_seconds=1)
    # Wait past a 1-second TTL using the real clock (fast, no need to mock).
    time.sleep(1.05)

    assert await redis_client.get("jarvis:indicators:MES:5m") is None
    assert "jarvis:indicators:MES:5m" not in redis_client._fallback_cache


@pytest.mark.asyncio
async def test_redis_setex_exception_still_expires_in_fallback(monkeypatch):
    """
    The sneakiest instance of the bug: Redis reports enabled, but a single
    setex() call throws (transient network blip). The old code fell back to
    a bare, permanent dict write even though Redis was "up" — so a cooldown
    or signal cache entry written during a momentary Redis hiccup would never
    expire until process restart. The fallback write must still carry the
    caller's TTL.
    """

    class _ExplodingRedis:
        async def setex(self, *_args, **_kwargs):
            raise ConnectionError("simulated transient Redis failure")

    redis_client._redis_enabled = True
    redis_client._redis_client = _ExplodingRedis()

    fake_now = [2_000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_now[0])

    ok = await redis_client.set("jarvis:signal:MGC", "cached-signal", ttl_seconds=1800)
    assert ok is True
    assert await redis_client.get("jarvis:signal:MGC") == "cached-signal"

    fake_now[0] += 1801
    assert await redis_client.get("jarvis:signal:MGC") is None


@pytest.mark.asyncio
async def test_fallback_entry_with_no_ttl_never_expires():
    """Explicitly TTL-less entries (ttl_seconds=None) are still allowed to persist."""
    await redis_client.set("jarvis:permanent:marker", "1", ttl_seconds=None)
    time.sleep(0.05)
    assert await redis_client.get("jarvis:permanent:marker") == "1"

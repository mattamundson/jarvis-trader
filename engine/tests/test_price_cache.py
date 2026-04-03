"""
Test price caching and Polygon rate limit handling.
"""

import asyncio
from functools import partial

import pytest

from data.price_cache import PriceCache, retry_with_backoff


@pytest.mark.asyncio
async def test_price_cache_set_and_get():
    """Test basic cache set and get."""
    cache = PriceCache(ttl_seconds=60)
    test_data = {
        "symbol": "MES",
        "last_price": 5500.0,
        "prev_close": 5490.0,
        "change_pct": 0.0018,
    }

    await cache.set("MES", test_data)
    result = await cache.get("MES")

    assert result is not None
    assert result["symbol"] == "MES"
    assert result["last_price"] == 5500.0


@pytest.mark.asyncio
async def test_price_cache_miss():
    """Test cache miss returns None."""
    cache = PriceCache(ttl_seconds=60)
    result = await cache.get("NONEXISTENT")
    assert result is None


@pytest.mark.asyncio
async def test_price_cache_expired():
    """Test cache expiration after TTL."""
    cache = PriceCache(ttl_seconds=0.1)  # 100ms TTL
    test_data = {"symbol": "MES", "last_price": 5500.0}

    await cache.set("MES", test_data)
    result = await cache.get("MES")
    assert result is not None

    # Wait for TTL to expire
    await asyncio.sleep(0.15)
    result = await cache.get("MES")
    assert result is None


@pytest.mark.asyncio
async def test_price_cache_get_expired_fallback():
    """Test fallback to expired cache when requested."""
    cache = PriceCache(ttl_seconds=0.1)
    test_data = {"symbol": "MES", "last_price": 5500.0}

    await cache.set("MES", test_data)
    await asyncio.sleep(0.15)

    # get() returns None (expired)
    result = await cache.get("MES")
    assert result is None

    # get_expired() returns data even when expired
    result = await cache.get_expired("MES")
    assert result is not None
    assert result["symbol"] == "MES"


@pytest.mark.asyncio
async def test_retry_with_backoff_success():
    """Test retry succeeds on first try."""
    cache = PriceCache(ttl_seconds=60)

    call_count = 0

    async def fetch_fn(symbol):
        nonlocal call_count
        call_count += 1
        return {"symbol": symbol, "price": 100.0}

    fetch_bound = partial(fetch_fn, "TEST")
    result = await retry_with_backoff(fetch_bound, "TEST", cache)

    assert result is not None
    assert result["symbol"] == "TEST"
    assert call_count == 1

    # Verify data was cached
    cached = await cache.get("TEST")
    assert cached is not None


@pytest.mark.asyncio
async def test_retry_with_backoff_rate_limit_429():
    """Test 429 error returns expired cache if available."""
    cache = PriceCache(ttl_seconds=0.1)

    # Pre-populate cache with old data
    old_data = {"symbol": "TEST", "price": 99.0}
    await cache.set("TEST", old_data)
    await asyncio.sleep(0.15)  # Expire cache

    call_count = 0

    async def fetch_fn_429(symbol):
        nonlocal call_count
        call_count += 1
        raise Exception("429: Too Many Requests")

    fetch_bound = partial(fetch_fn_429, "TEST")
    result = await retry_with_backoff(fetch_bound, "TEST", cache)

    # Should return expired cache instead of None
    assert result is not None
    assert result["symbol"] == "TEST"
    assert result["price"] == 99.0
    assert call_count == 1  # Should stop after first 429, not retry


@pytest.mark.asyncio
async def test_retry_with_backoff_transient_error():
    """Test retry on transient error (not 429)."""
    cache = PriceCache(ttl_seconds=60)

    call_count = 0

    async def fetch_fn_transient(symbol):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise Exception("Connection timeout")
        return {"symbol": symbol, "price": 100.0}

    fetch_bound = partial(fetch_fn_transient, "TEST")
    result = await retry_with_backoff(
        fetch_bound, "TEST", cache, max_retries=3, retry_delays=[0.01, 0.01, 0.01]
    )

    assert result is not None
    assert result["symbol"] == "TEST"
    assert call_count == 2  # Failed once, succeeded on retry


@pytest.mark.asyncio
async def test_cache_clear():
    """Test cache clear."""
    cache = PriceCache(ttl_seconds=60)

    await cache.set("MES", {"symbol": "MES", "price": 5500.0})
    await cache.set("MNQ", {"symbol": "MNQ", "price": 18000.0})

    # Clear single symbol
    await cache.clear("MES")
    assert await cache.get("MES") is None
    assert await cache.get("MNQ") is not None

    # Clear all
    await cache.clear()
    assert await cache.get("MNQ") is None

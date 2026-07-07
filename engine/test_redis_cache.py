"""
Test script to verify Redis caching and alert cooldown integration.

Run with: python test_redis_cache.py
"""

import asyncio


async def test_redis_init():
    """Test Redis initialization and fallback."""
    print("\n" + "=" * 60)
    print("TEST 1: Redis Initialization")
    print("=" * 60)

    from cache import close_redis, get_redis_client, init_redis

    redis_url = "redis://localhost:6379"
    print(f"Initializing Redis: {redis_url}")

    success = await init_redis(redis_url)
    client = get_redis_client()

    if success:
        print("✅ Redis connected successfully")
        print(f"   Client: {client}")
    else:
        print("⚠️  Redis unavailable — using in-memory fallback")
        print("   (This is normal if Redis server is not running)")

    await close_redis()
    print("✅ Redis closed gracefully\n")


async def test_signal_cache():
    """Test signal caching."""
    print("=" * 60)
    print("TEST 2: Signal Caching (Pipeline Results)")
    print("=" * 60)

    from cache import (
        cache_signal,
        close_redis,
        get_cache_stats,
        get_cached_signal,
        init_redis,
        should_use_cache,
    )

    await init_redis("redis://localhost:6379")

    # Create a mock pipeline result
    pipeline_result = {
        "symbol": "MES",
        "final_action": "buy",
        "final_quantity": 2,
        "analyst_reports": {"technical": {"regime": "UPTREND", "trend": "UP"}},
        "confidence": 0.85,
        "summary": "Test signal",
    }

    print("\nCaching signal for MES...")
    success = await cache_signal("MES", pipeline_result)
    print(f"✅ Signal cached: {success}")

    print("\nRetrieving cached signal...")
    should_use = await should_use_cache("MES")
    print(f"✅ Should use cache: {should_use}")

    cached = await get_cached_signal("MES")
    if cached:
        print("✅ Retrieved cached signal:")
        print(f"   Symbol: {cached['symbol']}")
        print(f"   Action: {cached['final_action']}")
        print(f"   Quantity: {cached['final_quantity']}")

    stats = get_cache_stats()
    print("\n✅ Cache Statistics:")
    print(f"   Hits: {stats['cache_hits']}")
    print(f"   Misses: {stats['cache_misses']}")
    print(f"   Total: {stats['total_accesses']}")
    print(f"   Hit Rate: {stats['hit_rate_percent']}%\n")

    await close_redis()


async def test_alert_cooldown():
    """Test alert cooldown tracking."""
    print("=" * 60)
    print("TEST 3: Alert Cooldown (WhatsApp Rate Limiting)")
    print("=" * 60)

    from cache import clear_cooldown, close_redis, init_redis, is_on_cooldown, set_cooldown

    await init_redis("redis://localhost:6379")

    symbol = "MES"
    channel = "whatsapp"

    print(f"\nChecking cooldown for {symbol}/{channel}...")
    active = await is_on_cooldown(symbol, channel)
    print(f"✅ Cooldown active (before set): {active}")

    print("\nSetting 2-hour cooldown...")
    success = await set_cooldown(symbol, channel, seconds=7200)
    print(f"✅ Cooldown set: {success}")

    print("\nChecking cooldown again...")
    active = await is_on_cooldown(symbol, channel)
    print(f"✅ Cooldown active (after set): {active}")

    print("\nClearing cooldown...")
    success = await clear_cooldown(symbol, channel)
    print(f"✅ Cooldown cleared: {success}")

    print("\nChecking cooldown after clear...")
    active = await is_on_cooldown(symbol, channel)
    print(f"✅ Cooldown active (after clear): {active}\n")

    await close_redis()


async def test_indicator_cache():
    """Test indicator caching."""
    print("=" * 60)
    print("TEST 4: Indicator Cache (Technical Analysis)")
    print("=" * 60)

    from cache import close_redis, get_indicators, init_redis, store_indicators

    await init_redis("redis://localhost:6379")

    symbol = "MES"
    timeframe = "5m"
    indicators = {
        "rsi": 65.5,
        "macd": 0.25,
        "bb_upper": 4525.50,
        "bb_lower": 4485.25,
        "atr": 15.0,
    }

    print(f"\nStoring indicators for {symbol}/{timeframe}...")
    success = await store_indicators(symbol, timeframe, indicators)
    print(f"✅ Indicators stored: {success}")

    print("\nRetrieving indicators...")
    cached_indicators = await get_indicators(symbol, timeframe)
    if cached_indicators:
        print("✅ Retrieved indicators:")
        for key, val in cached_indicators.items():
            print(f"   {key}: {val}")

    print()
    await close_redis()


async def test_graceful_fallback():
    """Test graceful fallback to in-memory cache."""
    print("=" * 60)
    print("TEST 5: Graceful Fallback (Invalid Redis URL)")
    print("=" * 60)

    from cache import cache_signal, close_redis, get_cached_signal, init_redis

    # Try to connect to invalid Redis URL
    print("\nTrying to connect to invalid URL...")
    success = await init_redis("redis://localhost:9999")  # Invalid port

    if not success:
        print("✅ Gracefully fell back to in-memory cache")

        # Verify fallback works
        print("\nTesting cache operations on fallback...")

        result = {"symbol": "MES", "action": "hold"}
        await cache_signal("MES", result)
        print("✅ Cached signal in fallback")

        cached = await get_cached_signal("MES")
        print(f"✅ Retrieved signal from fallback: {cached}")
    else:
        print("⚠️  Redis connected (expected fallback, but got real connection)")

    await close_redis()
    print()


async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("JARVIS TRADER — Redis Cache Integration Tests")
    print("=" * 60)

    try:
        # Test 1: Initialization
        await test_redis_init()

        # Test 2: Signal Cache
        await test_signal_cache()

        # Test 3: Alert Cooldown
        await test_alert_cooldown()

        # Test 4: Indicator Cache
        await test_indicator_cache()

        # Test 5: Fallback
        await test_graceful_fallback()

        print("=" * 60)
        print("✅ ALL TESTS COMPLETED")
        print("=" * 60)
        print("\nNote: Some tests may show graceful fallback if Redis is not running.")
        print(
            "      This is expected behavior — the system continues working with in-memory cache."
        )

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())

# JARVIS TRADER — Redis Caching & Alert Cooldown Integration

## Overview

Redis caching has been fully integrated into JARVIS TRADER to:
1. Cache pipeline signals (30-min TTL) — avoid redundant LLM calls when regime unchanged
2. Track alert cooldowns (2-hour TTL) — prevent WhatsApp alert spam
3. Cache technical indicators (5-min TTL) — avoid recalculating expensive indicators
4. Graceful fallback to in-memory dict if Redis unavailable

## Architecture

### Cache Layers

#### 1. Signal Cache (`cache/signal_cache.py`)
- **Purpose**: Cache complete pipeline results to avoid re-running full analysis
- **Key Format**: `jarvis:signal:{symbol}`
- **TTL**: 30 minutes (1800 seconds)
- **Hit Condition**:
  - Cached signal exists and hasn't expired
  - Market regime unchanged (optional validation)
- **Savings**: Skips all 5 pipeline stages (analysts, debate, trader, risk, fund)

#### 2. Alert Cooldown (`cache/alert_cooldown.py`)
- **Purpose**: Rate-limit WhatsApp alerts per symbol
- **Key Format**: `jarvis:cooldown:{channel}:{symbol}`
- **TTL**: 2 hours (7200 seconds)
- **Channels**: `whatsapp`, `email`, `discord` (extensible)
- **Usage**: Before sending alert, check if cooldown active

#### 3. Feature Store / Indicator Cache (`cache/feature_store.py`)
- **Purpose**: Cache pre-computed technical indicators
- **Key Format**: `jarvis:indicators:{symbol}:{timeframe}`
- **TTL**: 5 minutes (300 seconds)
- **Use Case**: Avoid pandas-ta recalculation if bars haven't changed

### Redis Client (`cache/redis_client.py`)

**Graceful Degradation**:
```python
# If Redis unavailable, automatically falls back to in-memory dict
# System continues operating without Redis — no crashes
init_redis(redis_url)  # Returns True if connected, False if using fallback
```

**Features**:
- Async Redis connection pool with connection reuse
- Socket keepalive and health checks (30s interval)
- Automatic fallback to in-memory cache if Redis down
- Cache statistics tracking (hits/misses)

## Integration Points

### 1. Main Server Startup (`main.py`)

**Initialization**:
```python
# In lifespan startup
redis_ready = await init_redis(settings.REDIS_URL)
if redis_ready:
    logger.info("✅ Redis initialized for caching")
else:
    logger.warning("⚠️  Redis unavailable — using in-memory fallback")
```

**Shutdown**:
```python
# In lifespan teardown
await close_redis()
```

### 2. Pipeline Signal Caching (`agents/pipeline.py`)

**Before analysis** (check cache):
```python
if _CACHE_AVAILABLE:
    if await should_use_cache(symbol):
        cached = await get_cached_signal(symbol)
        if cached:
            logger.info(f"{symbol} cache hit — skipping full pipeline")
            return cached  # Early return saves LLM calls
```

**After analysis** (store result):
```python
if _CACHE_AVAILABLE:
    await cache_signal(symbol, pipeline_result)
```

### 3. WhatsApp Alert Cooldown (`main.py`)

**Scheduler** (run_watchlist_analysis):
```python
cooldown_active = await is_on_cooldown(symbol, channel="whatsapp")
if notifier.enabled and not cooldown_active:
    sent = await notifier.send(msg)
    if sent:
        await set_cooldown(symbol, channel="whatsapp", seconds=7200)
        logger.info(f"Alert sent + 2h cooldown")
```

**Manual Trigger** (trigger_scan_now):
```python
# Same cooldown logic as scheduler
```

### 4. Cache Status Endpoint (`main.py`)

**Endpoint**: `GET /cache/status`

**Response**:
```json
{
  "redis_connected": true,
  "redis_url": "redis://localhost:6379",
  "cache_layers": {
    "signal_cache": {
      "description": "30-min TTL for complete pipeline results",
      "key_prefix": "jarvis:signal:*",
      "ttl_seconds": 1800
    },
    "alert_cooldown": {
      "description": "2-hour TTL for WhatsApp alert rate limiting",
      "key_prefix": "jarvis:cooldown:*",
      "ttl_seconds": 7200
    },
    "indicator_cache": {
      "description": "5-min TTL for pre-computed technical indicators",
      "key_prefix": "jarvis:indicators:*",
      "ttl_seconds": 300
    }
  },
  "statistics": {
    "cache_hits": 42,
    "cache_misses": 8,
    "total_accesses": 50,
    "hit_rate_percent": 84.0
  },
  "status": "operational",
  "note": "If Redis unavailable, caching uses non-persistent in-memory dict..."
}
```

## Configuration

### Environment Variables

```bash
# In .env
REDIS_URL=redis://localhost:6379   # Default — can be overridden
```

### Default TTLs

| Layer | TTL | Use Case |
|-------|-----|----------|
| Signal Cache | 30 min | Avoid re-analyzing same regime |
| Alert Cooldown | 2 hours | Prevent alert spam |
| Indicators | 5 min | Fast lookup if bars unchanged |

## Graceful Fallback Behavior

### If Redis Unavailable

1. **Startup**: Logs warning but continues (non-blocking init)
2. **Operation**: Uses in-memory dict fallback (same API)
3. **On Restart**: In-memory cache is cleared (non-persistent)
4. **No Crashes**: System never crashes due to Redis failure

### Example Log Output

```
[INFO] ✅ Redis initialized for caching (TTL: signals=30m, cooldown=2h, indicators=5m)
[INFO] ✅ JARVIS TRADER ready. Dashboard: http://localhost:3010

# Or if Redis down:
[WARNING] ⚠️  Redis unavailable — using in-memory fallback cache (non-persistent)
[INFO] ✅ JARVIS TRADER ready. Dashboard: http://localhost:3010
```

## Cache Hit Examples

### Scenario 1: Market Regime Unchanged

```
Time 09:30 → Run pipeline for MES → Cache result
Time 10:00 → Run pipeline for MES → Cache HIT (regime unchanged) → Return cached result in <10ms
           → Saves: All 10 agents + debate + risk/fund manager (millions of tokens)
```

### Scenario 2: Alert Already Sent

```
Time 09:45 → MES signal = "BUY" → WhatsApp alert sent → Set 2h cooldown
Time 10:15 → MES signal = "BUY" again → Cooldown ACTIVE → Alert suppressed
           → Prevents: Alert spam to Matt
```

### Scenario 3: Indicator Reuse

```
Time 09:31 → Request bars for MES → Calculate 50 indicators → Cache (5 min)
Time 09:33 → Request bars for MES again → Indicator CACHE HIT → Reuse cached values
           → Saves: 0.5 seconds of pandas-ta computation
```

## Performance Impact

### Cache Hits (Best Case)
- Pipeline: <10ms (Redis lookup)
- Previous: 15-20 seconds (full LLM analysis)
- **Savings: 99.9% latency, millions of tokens**

### Cache Misses (No Penalty)
- Same latency as Redis was unavailable
- Redis operations are async (non-blocking)
- Fallback dict has minimal overhead

### Network Overhead
- Async connection pooling reuses connections
- Single key lookup: ~1-5ms over network
- Batch operations: Can use MGET for multiple keys

## Testing Cache

### 1. Check Cache Status

```bash
curl http://localhost:8010/cache/status
```

### 2. Verify Redis Connection

```bash
# From shell
redis-cli ping  # Should return "PONG"
```

### 3. Monitor Cache Hits/Misses

Watch the `/cache/status` endpoint for increasing `hit_rate_percent`.

### 4. Test Alert Cooldown

```bash
# First trigger
curl -X POST http://localhost:8010/scan
# WhatsApp alert sent + cooldown set

# Immediate second trigger
curl -X POST http://localhost:8010/scan
# Alert suppressed (cooldown active)

# After 2 hours
curl -X POST http://localhost:8010/scan
# Alert sent again (cooldown expired)
```

## Troubleshooting

### Redis Connection Failed

**Error**:
```
⚠️  Redis unavailable (ConnectionError) — using in-memory cache fallback
```

**Solution**:
1. Verify Redis is running: `redis-cli ping`
2. Check REDIS_URL in `.env`
3. Verify firewall/networking to Redis host
4. System will continue with in-memory cache

### Cache Not Working

**Check**:
```bash
# Verify Redis has keys
redis-cli KEYS "jarvis:signal:*"
redis-cli KEYS "jarvis:cooldown:*"
```

**Debug**:
```bash
# Watch cache operations
curl http://localhost:8010/cache/status
# hit_rate_percent should increase on repeated pipeline calls
```

## Dependencies

**Added to requirements-core.txt**:
```
redis[hiredis]==5.2.1     # Redis async client (hiredis optional for faster parsing)
```

- `redis` — async Redis client for Python
- `hiredis` — optional C parser for faster protocol parsing (pure Python fallback available)

## Summary

Redis caching is now fully integrated with:
- ✅ Signal pipeline caching (30 min)
- ✅ WhatsApp alert cooldown (2 hours)
- ✅ Technical indicator caching (5 min)
- ✅ Graceful Redis fallback to in-memory
- ✅ Cache statistics and hit/miss tracking
- ✅ `/cache/status` endpoint for monitoring
- ✅ Non-blocking initialization and shutdown

The system never crashes due to Redis unavailability and continues operating with in-memory cache.

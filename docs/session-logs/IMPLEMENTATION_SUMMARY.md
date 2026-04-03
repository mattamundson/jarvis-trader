# US-103: Price Caching and Polygon Rate Limit Handling

## Implementation Summary

Added in-memory price caching with TTL and exponential backoff retry logic to handle Polygon.io rate limits (429 "Too Many Requests" errors).

## Files Modified

### 1. **engine/data/price_cache.py** (NEW)
   - `PriceCache` class: Thread-safe in-memory cache with 60-second TTL
   - `retry_with_backoff()` function: Retry logic with exponential backoff (1s, 2s, 4s)
   - Handles 429 errors by returning expired cache as fallback
   - Graceful degradation on other errors with up to 3 retries
   - No external dependencies (stdlib only: asyncio, time, dict)

### 2. **engine/routers/prices_router.py**
   - Updated `/prices/snapshot` endpoint to use caching
   - Integrated `PriceCache` for automatic caching with TTL
   - Added retry logic with exponential backoff for transient errors
   - Cache hit logging for monitoring
   - Uses `functools.partial` to safely bind loop variables

### 3. **engine/config.py**
   - Added `FRED_API_KEY` field to `TradingConfig` for Federal Reserve data

### 4. **engine/.env.example**
   - Added `FRED_API_KEY` configuration with documentation
   - Added note about Polygon rate limiting and caching

### 5. **engine/main.py**
   - Imported `PriceCache` from `data.price_cache`
   - Instantiate `price_cache = PriceCache()` during startup
   - Pass cache to `inject_prices_deps(price_cache)` for dependency injection

### 6. **engine/tests/test_price_cache.py** (NEW)
   - 8 comprehensive tests covering:
     - Basic cache set/get
     - Cache misses
     - Cache expiration (TTL)
     - Fallback to expired cache
     - Successful retry
     - 429 rate limit handling with expired cache fallback
     - Transient error retry
     - Cache clearing

## Architecture

### Caching Strategy
- **TTL**: 60 seconds per symbol
- **Storage**: In-memory dict `{symbol: {data: {...}, timestamp: float}}`
- **Thread-safe**: Uses asyncio.Lock for concurrent access
- **Fallback**: Returns expired cache on 429 errors if available

### Retry Logic
- **Max retries**: 3 attempts
- **Delays**: [1s, 2s, 4s] exponential backoff
- **429 handling**: Special case — stops retrying, returns expired cache
- **Other errors**: Retries with full backoff sequence

## Key Features

1. **Automatic Caching**
   - All `/prices/snapshot` calls cached for 60 seconds
   - Second call within 60s returns cached data instantly
   - No manual cache invalidation needed (TTL-based auto-expiry)

2. **Rate Limit Resilience**
   - 429 errors trigger expired cache fallback
   - Prevents cascading failures when API is rate-limited
   - Logs warnings when rate limit encountered

3. **Transient Error Handling**
   - Connection timeouts, network errors automatically retried
   - Exponential backoff prevents overwhelming the API
   - Max 3 retries (1s + 2s + 4s = 7 seconds total wait)

4. **Clean Code**
   - Zero external dependencies (stdlib only)
   - Follows coding-style.md (async with fallback, ruff-clean, 50-line functions max)
   - Comprehensive test coverage (8 tests, all passing)
   - Proper logging at all decision points

## Test Results

All 8 new tests pass:
- `test_price_cache_set_and_get` — Basic cache operations
- `test_price_cache_miss` — Returns None on miss
- `test_price_cache_expired` — TTL expiration
- `test_price_cache_get_expired_fallback` — Expired cache retrieval
- `test_retry_with_backoff_success` — First-attempt success
- `test_retry_with_backoff_rate_limit_429` — 429 error fallback
- `test_retry_with_backoff_transient_error` — Transient error retry
- `test_cache_clear` — Clearing cache

## Safety & Compliance

- No changes to `engine/risk/safety_layer.py` (as required)
- All code passes `ruff check` (0 errors)
- No security issues — no credentials in cache
- Thread-safe with asyncio.Lock for concurrent calls
- Graceful degradation on all error paths

## Usage Example

```python
# First call: fetches from yfinance, caches result
response = client.get("/prices/snapshot?symbols=SPY,MES")
# Result: {"SPY": {...}, "MES": {...}}

# Second call within 60s: serves from cache
response = client.get("/prices/snapshot?symbols=SPY,MES")
# Result: Same data, instant response (no API call)

# If Polygon returns 429: fallback to expired cache
# Prevents "Too Many Requests" errors from breaking the app
```

## FRED_API_KEY Configuration

Added optional `FRED_API_KEY` field to support Federal Reserve Economic Data API:
- Used for VIX, yield curve, and economic indicators
- Falls back to yfinance if not set
- Documented in `.env.example` with setup instructions

## Files Changed Summary

| File | Changes | Lines Added |
|------|---------|------------|
| `engine/data/price_cache.py` | New file | 140 |
| `engine/routers/prices_router.py` | Complete refactor with caching | 110 |
| `engine/config.py` | Added FRED_API_KEY field | 1 |
| `engine/.env.example` | Added FRED docs | 3 |
| `engine/main.py` | Injected cache dependency | 2 |
| `engine/tests/test_price_cache.py` | New test file | 180 |
| **Total** | **6 files** | **~436 lines** |

## Next Steps

1. Deploy changes to paper trading environment
2. Monitor cache hit/miss rates via logs
3. Verify Polygon 429 errors are handled gracefully
4. Consider adding cache metrics to dashboard health check

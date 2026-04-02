# Quick Start — Route Verification Guide

## Run Verification

```bash
cd engine
python3 scripts/verify_routes_static.py
```

**Expected Output** (last 50 lines):
```
✅ Route count OK: 75 >= 75
✅ All critical routes present
✅ Multiple HTTP methods detected
```

## What Was Verified

- **75 API routes** across 25 routers
- **4 HTTP methods**: GET (51), POST (22), PUT (1), DELETE (1)
- **3 critical routes**:
  - GET /health
  - GET /portfolio/summary
  - GET /safety/loss-tracker/status

## Files

| File | Purpose |
|------|---------|
| `engine/scripts/verify_routes_static.py` | ⭐ Main verification script — **USE THIS** |
| `engine/tests/test_routes_wired.py` | Pytest suite (requires full app import) |
| `docs/reports/endpoint_verification_report.md` | Full verification report |

## Key Routers (25 total)

**Critical**:
- health_router — System health
- safety_router — Loss tracking
- portfolio_router — Holdings & capital
- pipeline_router — Pipeline execution

**Trading**:
- backtest_router — Backtesting
- analysis_router — Technical analysis
- strategy_router — Strategy management
- strategies_router — RL training

**Data**:
- market_router — Earnings, session
- sentiment_router — News, Reddit
- macro_router — Macro series
- crypto_router — Crypto positions

**Execution**:
- pipeline_router — Pipeline execution
- decisions_router — Trade decisions
- options_router — Options module
- polymarket_router — Prediction markets

**Infrastructure**:
- settings_router — Risk settings
- reports_router — Performance reports
- journal_router — Trade journal
- watchlist_router — Watchlist mgmt
- websocket_router — Real-time events
- notifications_router — Alerts
- webhook_router — TradingView webhooks
- validation_router — Validation progress
- prices_router — Price data
- thinkscript_router — ThinkScript

## Adding New Routes

1. Create endpoint in router file:
   ```python
   @router.get("/my-endpoint")
   async def my_endpoint():
       return {"status": "ok"}
   ```

2. Ensure router is included in `engine/main.py`:
   ```python
   app.include_router(my_router)  # without prefix
   # OR
   app.include_router(my_router, prefix="/api")  # with prefix
   ```

3. Verify:
   ```bash
   python3 scripts/verify_routes_static.py
   ```

## Verification Criteria

✅ **PASS** when:
- Total routes >= 75
- All 3 critical routes present
- At least 2 HTTP methods

❌ **FAIL** when:
- Total routes < 75
- Missing critical routes
- Only 1 HTTP method

## Reports

**Static Analysis Output**: 304 lines, ~1 second runtime
- All routes grouped by HTTP method
- Routes grouped by prefix
- Critical route validation
- Summary statistics

**See**: `docs/reports/endpoint_verification_report.md`

## Troubleshooting

**Script fails to import?**
- Use `verify_routes_static.py` — it doesn't require app import
- If pytest test fails, check that unrelated modules load cleanly

**Route not showing up?**
- Check `@router.get/post/etc(path)` decorator
- Ensure router is included in `main.py`
- Check router prefix definitions

**Route count too low?**
- List all routes: `python3 scripts/verify_routes_static.py | grep -E "^  " | wc -l`
- Add missing routes to routers

## Integration

**CI/CD Command**:
```bash
cd engine && python3 scripts/verify_routes_static.py || exit 1
```

**Pre-deployment Check**:
```bash
bash -c 'cd engine && python3 scripts/verify_routes_static.py && echo "✅ Routes verified"'
```

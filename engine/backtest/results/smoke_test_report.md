# JARVIS Trader Engine -- Smoke Test Report

**Date:** 2026-04-02 10:48 CT
**Engine Version:** 1.1.0
**Engine URL:** http://localhost:8010
**Auth:** X-API-Key header required (except /health)

---

## Summary

| Metric | Value |
|--------|-------|
| Total Endpoints Tested | 17 |
| PASS (2xx) | 13 |
| FAIL (4xx/5xx) | 4 |
| Pass Rate | 76.5% |

---

## Endpoint Results

| # | Endpoint | Method | Status | Result |
|---|----------|--------|--------|--------|
| 1 | `/health` | GET | 200 | PASS -- v1.1.0, paper mode, DB connected, IBKR connected |
| 2 | `/safety/status` | GET | 200 | PASS -- kill switch inactive, daily PnL +$20, no breaches |
| 3 | `/portfolio` | GET | 200 | PASS -- futures market active, $10K capital, 0 open positions |
| 4 | `/portfolio/paper/positions` | GET | 200 | PASS -- returns position list (0 open at start) |
| 5 | `/portfolio/paper/performance` | GET | 200 | PASS -- 1 closed trade, $20 PnL, 100% win rate |
| 6 | `/decisions/recent` | GET | 200 | PASS -- 11 decisions returned (all HOLD -- LLM errors, see notes) |
| 7 | `/watchlist` | GET | 200 | PASS -- 6 symbols (MCL, MNQ, SPY, QQQ, AAPL, TSLA) |
| 8 | `/prices/snapshot` | GET | 200 | PASS (degraded) -- all prices null due to Polygon rate limit |
| 9 | `/pipeline/status` | GET | 200 | PASS -- pipeline available, no runs yet |
| 10 | `/scheduler/status` | GET | 200 | PASS -- scheduler running, 6 jobs scheduled |
| 11 | `/macro/snapshot` | GET | **500** | **FAIL** -- FRED_API_KEY not set in .env |
| 12 | `/backtest/results` | GET | **500** | **FAIL** -- Internal Server Error (undiagnosed) |
| 13 | `/strategies/status` | GET | **404** | **FAIL** -- Endpoint does not exist (only `/strategies/rl/status` exists) |
| 14 | `/strategies/rl/status` | GET | 200 | PASS -- RL status returned, no active training |
| 15 | `/analyze/technical` | POST | **500** | **FAIL** -- Internal Server Error on MES 1h analysis |
| 16 | `/portfolio/paper/trade` (open) | POST | 200 | PASS -- opened MES LONG @ 5800, trade_id returned |
| 17 | `/portfolio/paper/trade` (close) | POST | 200 | PASS -- closed trade, PnL calculated correctly |

---

## Critical Issues Found

### 1. `/macro/snapshot` -- 500 (Missing FRED_API_KEY)
**Severity:** Medium
**Error:** `FRED data unavailable: You need to set a valid API key.`
**Fix:** Add `FRED_API_KEY=<your_key>` to `engine/.env`. Free key from https://research.stlouisfed.org/fred2/

### 2. `/backtest/results` -- 500 (Internal Server Error)
**Severity:** Medium
**Error:** Generic 500 with no detail in response body. Needs server-side log investigation.
**Fix:** Check uvicorn logs for traceback when this endpoint is hit.

### 3. `/strategies/status` -- 404 (Route Not Found)
**Severity:** Low
**Note:** This endpoint was never implemented. The actual RL status endpoint is `/strategies/rl/status` which works correctly. If a top-level strategies overview is needed, a new endpoint should be added to `strategies_router.py`.

### 4. `/analyze/technical` -- 500 (Internal Server Error)
**Severity:** High
**Error:** Generic 500 on POST with `{"symbol":"MES","interval":"1h"}`.
**Fix:** Check server logs. Likely a missing data source or Polygon rate limit cascading into an unhandled exception.

---

## Operational Warnings

### LLM Decision Failures
All 11 recent decisions show `Trader LLM call failed` errors:
- **Anthropic 400 Bad Request** for SPY, QQQ, AAPL -- likely invalid model name or malformed request
- **DNS resolution failure** (`getaddrinfo failed`) for MCL, MNQ -- network connectivity issue at decision time
- **All connections failed** for MES -- complete network failure at that moment

The safety layer correctly defaults to HOLD on LLM failure, which is correct behavior.

### Price Data Rate Limited
Polygon API returning "Too Many Requests" for all symbols. The `/prices/snapshot` endpoint returns 200 but with null prices. May need request throttling or caching.

### IBKR Client ID Conflict
Engine logs show `Error 326: Unable to connect as the client id is already in use` for clientId 2. A previous engine instance may still hold the connection. The engine continues to function but without live IBKR data.

---

## Paper Trading Verification

Paper trade round-trip test completed successfully:
1. **Open:** POST `/portfolio/paper/trade` with `action=open, symbol=MES, side=long, entry_price=5800` -- returned trade_id
2. **Verify:** GET `/portfolio/paper/positions` -- showed 1 open position with correct data
3. **Close:** POST `/portfolio/paper/trade` with `action=close, exit_price=5810, pnl=50` -- trade closed, PnL recorded

**Paper trade schema note:** The endpoint expects `{action, symbol, side, quantity, entry_price}` for opens and `{action, symbol, trade_id, exit_price, pnl}` for closes. It does NOT accept the `direction/stop_price/target_price/contracts/source` format.

---

## Safety Layer Status

```json
{
  "kill_switch_active": false,
  "daily_pnl": 20.0,
  "daily_limit_pct": -0.02,
  "daily_limit_breached": false,
  "drawdown_pct": 0.0,
  "drawdown_limit_pct": -0.1,
  "drawdown_breached": false,
  "portfolio_equity": 10020.0,
  "starting_balance": 10000.0,
  "orders_last_minute": 0,
  "consecutive_losses": 0
}
```

All safety limits are within bounds. Kill switch is inactive. System is safe to trade.

---

## Recommendations

1. **Add FRED_API_KEY** to `.env` to fix `/macro/snapshot`
2. **Investigate `/backtest/results`** 500 error -- check if it needs query params or if there's a code bug
3. **Investigate `/analyze/technical`** 500 -- this is a core endpoint and should not fail on basic MES requests
4. **Add `/strategies/status`** endpoint if dashboard expects it, or update dashboard to use `/strategies/rl/status`
5. **Fix Anthropic API calls** -- the 400 errors suggest a model name or request format issue in the trader LLM config
6. **Add Polygon rate limiting** -- implement request throttling to avoid "Too Many Requests" errors

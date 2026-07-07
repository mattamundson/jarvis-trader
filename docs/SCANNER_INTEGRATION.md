# Signal Scanner & API Key Validation Integration Guide

## Overview

This document describes how to integrate:
1. **SignalScanner** — Scheduled signal scanning during market hours
2. **API Key Validation** — Startup validation of external service credentials
3. **Scanner Router** — REST API for controlling the scanner

**Status**: main.py has a syntax corruption (missing `@asynccontextmanager` function definition at line 109-110). This guide assumes main.py is fixed first.

## Files Created

### Signal Scanner Module
- `engine/scanner/__init__.py` — Module entry point
- `engine/scanner/signal_scanner.py` — Background scanner (385 lines)
  - `SignalScanner` class: manages background scanning
  - `_is_futures_market_hours()` helper: checks if US futures markets are open
  - Scans MCL and MNQ on 60-min schedule
  - Creates pending approvals when signals fire
  - Respects REQUIRE_HUMAN_APPROVAL=True

### Scanner Router
- `engine/routers/scanner_router.py` — REST API (165 lines)
  - `GET /scanner/status` — Current scanner state
  - `POST /scanner/trigger` — Manual scan
  - `POST /scanner/pause` — Pause scanning
  - `POST /scanner/resume` — Resume scanning

### API Key Validation
- `engine/validation/__init__.py` — Module entry point
- `engine/validation/api_keys.py` — Validation logic (132 lines)
  - `validate_api_keys(config)` — Checks all API keys
  - Returns status dict with capabilities breakdown
  - Logs clearly which features are disabled

## Integration Steps

### Step 1: Fix main.py Syntax Error

The file has a corrupted function definition around line 109. Should look like:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and teardown on startup/shutdown"""
    global \
        data_manager, \
        safety_layer, \
        # ... etc
```

The `@asynccontextmanager` decorator is missing. Fix by adding it before line 109.

### Step 2: Add Imports to main.py

Add these imports in the router section (around line 63):

```python
from routers.scanner_router import router as scanner_router
from routers.scanner_router import inject_dependencies as inject_scanner_deps
from scanner.signal_scanner import SignalScanner
```

Add this import in the validation section (new, after config imports):

```python
from validation.api_keys import validate_api_keys
```

### Step 3: Add Scanner to Global State

In the `_global_state` dict (around line 91), add:

```python
"signal_scanner": None,
```

And in the global declarations (around line 111), add to the list:

```python
signal_scanner, \
```

### Step 4: Initialize SignalScanner in lifespan()

Inside the `lifespan()` function, after the trading pipeline is initialized (around line 305), add:

```python
# Signal Scanner — background market surveillance
signal_scanner = None
if trading_pipeline and db_manager:
    signal_scanner = SignalScanner(
        trading_pipeline=trading_pipeline,
        db_manager=db_manager,
        symbols=["MCL", "MNQ"],  # Validated instruments only
        scan_interval_minutes=60,
    )
    try:
        await signal_scanner.start()
        logger.info("✅ Signal Scanner initialized and started (MCL, MNQ every 60min)")
    except Exception as e:
        logger.warning(f"Signal Scanner startup failed (non-fatal): {e}")
        signal_scanner = None
else:
    logger.warning("Signal Scanner skipped — pipeline or database not available")
```

### Step 5: Inject Scanner into Router

After all router injections (around line 400), add:

```python
inject_scanner_deps(signal_scanner)
```

### Step 6: Add Scanner Router to App

In the `lifespan()` function yield block, where routers are added (around line 700+), add:

```python
app.include_router(scanner_router)
```

### Step 7: Add API Key Validation

In `lifespan()`, right after `setup_logging()` (around line 131), add:

```python
# Validate API keys — fail loud if critical keys missing
validation_result = validate_api_keys(settings)
if not validation_result["valid"]:
    logger.error("Startup blocked — missing critical API keys:")
    for key_desc in validation_result["missing_critical"]:
        logger.error(f"  {key_desc}")
    raise RuntimeError("Critical API keys missing — see logs above")
```

### Step 8: Stop Scanner on Shutdown

In the `lifespan()` function yield block, after all startup code but before yield, the scanner will be automatically stopped when the context manager exits. To explicitly ensure cleanup:

```python
try:
    yield
finally:
    # Shutdown handlers
    if signal_scanner:
        try:
            await signal_scanner.stop()
            logger.info("Signal Scanner stopped")
        except Exception as e:
            logger.warning(f"Error stopping scanner: {e}")
```

## API Endpoints

### GET /scanner/status
Returns current scanner state.

**Response:**
```json
{
  "active": true,
  "symbols": ["MCL", "MNQ"],
  "scan_interval_minutes": 60,
  "last_scan_at": "2026-04-02T14:30:00+00:00",
  "next_scan_at": "2026-04-02T15:30:00+00:00",
  "total_scans": 42,
  "approvals_created": 3,
  "errors": 0
}
```

### POST /scanner/trigger
Manually trigger one scan immediately.

**Response:**
```json
{
  "action": "trigger",
  "status": "success",
  "message": "Scan started in background"
}
```

### POST /scanner/pause
Pause automatic scanning (task still running, logic skipped).

**Response:**
```json
{
  "action": "pause",
  "status": "success",
  "message": "Scanner paused — no new scans will run"
}
```

### POST /scanner/resume
Resume from paused state.

**Response:**
```json
{
  "action": "resume",
  "status": "success",
  "message": "Scanner resumed — will run next cycle"
}
```

## Market Hours Logic

The scanner only runs during US futures market hours:
- **Sunday 5:00 PM - Friday 4:00 PM CT** (Chicago Time)
- Outside these hours, checks are skipped, but the background task continues running

## Configuration

Scanner parameters can be customized in the initialization code:

```python
signal_scanner = SignalScanner(
    trading_pipeline=trading_pipeline,
    db_manager=db_manager,
    symbols=["MCL", "MNQ"],        # Change symbols here
    scan_interval_minutes=60,       # Change interval here
)
```

**Recommended:**
- **symbols**: Only scan active instruments (approved via gate v2, Tier-3 2026-05-24)
  - MES (micro S&P, 1h, p_edge=0.75) — APPROVED
  - MGC (micro gold, 1h, p_edge=0.6842) — APPROVED
  - DO NOT scan MCL/MNQ (HALTED) or M2K (REJECTED)
- **scan_interval_minutes**: 60 (balances latency vs API/broker load)

## Safety & Compliance

All safety rules from `.claude/rules/safety.md` are enforced:
- `REQUIRE_HUMAN_APPROVAL = True` — scanner creates pending approvals, never auto-trades
- `LIVE_TRADING_ENABLED = False` — paper mode only
- Scanner respects kill switch — if active, no scans run
- All signals logged to database for audit trail

## API Key Validation

The `validate_api_keys()` function checks:

**Critical (startup fails if missing):**
- `API_KEY` — FastAPI X-API-Key header

**Optional (warnings logged if missing):**
- `ANTHROPIC_API_KEY` — LLM agent pipeline
- `POLYGON_API_KEY` — Market data (Tier 2)
- `FRED_API_KEY` — Economic indicators
- `FINNHUB_API_KEY` — Alternative market data
- `TWILIO_*` — WhatsApp alerts (all 4 keys required)

**Output Example:**
```
API Key Validation Results:
  LLM Agents:           ENABLED
  Polygon Market Data:  DISABLED
  FRED Economic Data:   DISABLED
  Finnhub Market Data:  DISABLED
  WhatsApp Alerts:      DISABLED
```

## Testing

After integration, test with:

```bash
# 1. Check scanner status
curl -X GET http://localhost:8010/scanner/status

# 2. Manual trigger (test during market hours)
curl -X POST http://localhost:8010/scanner/trigger

# 3. Pause/resume
curl -X POST http://localhost:8010/scanner/pause
curl -X POST http://localhost:8010/scanner/resume

# 4. Check pending approvals created by scanner
curl -X GET http://localhost:8010/pipeline/pending-approvals
```

## Troubleshooting

**Scanner shows 0 scans:**
- Outside market hours? Check if it's Sun 5pm-Fri 4pm CT
- Is pipeline initialized? Check logs for `TradingPipeline ready`
- Is scanner paused? Call `/scanner/resume`

**Scans running but no approvals created:**
- Signals firing but being rejected by risk layer
- Check `/safety/status` for kill switch / circuit breaker state
- Review pipeline logs for analyzer errors

**API Key warnings but need a feature:**
- Add the missing key to `.env`
- Restart engine with `./restart_engine.ps1`
- Logs will show feature re-enabled

## Future Enhancements

1. **Multiple scan profiles** — Different intervals for different symbol groups
2. **Batch signal processing** — Queue signals for bulk approval review
3. **Performance metrics** — Track scan latency, signal quality by instrument
4. **Market-hours scheduling** — APScheduler can handle this natively
5. **Scan result webhooks** — POST signals to external systems

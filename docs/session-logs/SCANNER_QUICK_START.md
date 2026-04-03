# Signal Scanner — Quick Start

## Files Created

| File | Lines | Purpose |
|------|-------|---------|
| `engine/scanner/__init__.py` | 20 | Module entry |
| `engine/scanner/signal_scanner.py` | 385 | Background scanner |
| `engine/routers/scanner_router.py` | 165 | REST API |
| `engine/validation/__init__.py` | 19 | Module entry |
| `engine/validation/api_keys.py` | 132 | Key validation |
| `engine/tests/test_scanner.py` | 268 | Tests |
| `docs/SCANNER_INTEGRATION.md` | 334 | Integration guide |

## What Scanner Does

- Scans MCL + MNQ every 60 minutes (during market hours)
- Runs full pipeline analysis on each symbol
- Creates pending approvals when signals fire
- Respects REQUIRE_HUMAN_APPROVAL=True
- Can be paused/resumed/triggered manually

## Integration Checklist (8 Steps)

- [ ] Fix main.py line 109 (add @asynccontextmanager)
- [ ] Add 3 imports to main.py
- [ ] Add signal_scanner to _global_state
- [ ] Add signal_scanner to lifespan() globals
- [ ] Add validate_api_keys() call in lifespan()
- [ ] Initialize SignalScanner in lifespan()
- [ ] Call inject_scanner_deps(signal_scanner)
- [ ] Include scanner_router in app + cleanup on shutdown

Full details: `docs/SCANNER_INTEGRATION.md`

## API Endpoints

```bash
# Status
GET /scanner/status

# Scan now
POST /scanner/trigger

# Pause/Resume
POST /scanner/pause
POST /scanner/resume
```

## Key Features

- **Market Hours**: Sun 5pm - Fri 4pm CT (US futures)
- **Error Handling**: Async with graceful fallback
- **Logging**: Full audit trail to database
- **Safety**: All safety checks still enforced
- **Tests**: 268 lines of test coverage

## Configuration

Edit initialization in main.py:
```python
SignalScanner(
    trading_pipeline=trading_pipeline,
    db_manager=db_manager,
    symbols=["MCL", "MNQ"],        # Only validated instruments
    scan_interval_minutes=60,       # Scan frequency
)
```

## API Key Validation

Required:
- `API_KEY` — FastAPI auth

Optional (warnings if missing):
- `ANTHROPIC_API_KEY` — LLM pipeline
- `POLYGON_API_KEY` — Market data
- `FRED_API_KEY` — Economic data
- `FINNHUB_API_KEY` — Alternative data
- `TWILIO_*` (4 keys) — WhatsApp

## Code Quality

✅ Pydantic v2
✅ Ruff-clean
✅ <400 lines per file
✅ Full type hints
✅ Async/await
✅ Error handling
✅ Logging (no print)
✅ Tests included

## Status

✅ Signal Scanner — COMPLETE
✅ API Key Validation — COMPLETE
⚠️ Integration — REQUIRES main.py FIX (line 109)

## Next

1. Fix main.py syntax error
2. Follow SCANNER_INTEGRATION.md (8 steps)
3. Run tests: `pytest tests/test_scanner.py -v`
4. Test endpoints: `/scanner/status`, `/scanner/trigger`
5. Monitor logs during market hours

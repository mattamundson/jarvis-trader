# Testing Rules — JARVIS TRADER

## Requirements (non-negotiable)

- **Engine**: `cd engine && pytest tests/ -v` must pass with 0 failures before any PR
- **Dashboard**: `cd dashboard && pnpm run build` must produce 16/16 routes, 0 TypeScript errors
- **Safety layer tests are sacred**: `engine/tests/test_safety_layer.py` must always pass — never skip or comment out
- **Integration tests**: `engine/tests/test_integration.py` — 28 tests, all must pass

## Test Locations

- `engine/tests/` — 7 test files covering safety, pipeline, signals, database, integration
- Dashboard has no tests yet — add when making breaking changes

## Running Tests

```bash
# Full engine test suite
cd engine && .venv/Scripts/python -m pytest tests/ -v

# Single test file
cd engine && .venv/Scripts/python -m pytest tests/test_safety_layer.py -v

# Dashboard build check (equivalent to type check)
cd dashboard && pnpm run build
```

## When Adding New Features

1. Add test for the new functionality first (TDD where practical)
2. Run full suite before declaring done
3. Safety-related code always needs a test — no exceptions

# Playbook: Test

Use for: adding missing test coverage, fixing failing tests, writing tests for new features, improving CI reliability.

---

## Test Suite Overview

```
engine/tests/            18 test files — all run with pytest
├── SACRED
│   └── test_safety_layer.py     Must ALWAYS pass. Never skip. Never comment out.
│
├── INTEGRATION (run these to validate the full system)
│   ├── test_integration.py      28 tests — full pipeline integration
│   └── test_pipeline_e2e.py     End-to-end with mocked LLM
│
├── UNIT (fast, isolated)
│   ├── test_signals.py          STC signal logic, INSTRUMENT_PARAMS validation
│   ├── test_foundation.py       Config, init, env vars
│   ├── test_loss_tracker.py     ConsecutiveLossTracker
│   ├── test_routes_wired.py     All 24 routers registered in main.py
│   ├── test_auth_and_rate_limit.py  API key + rate limit middleware
│   ├── test_api_contract_minimal.py  Response shapes
│   └── test_llm_client.py       LLM cost tracker, Anthropic client
│
├── MODULE (market framework, learning system)
│   ├── test_market_modules.py   Multi-market modules
│   ├── test_orchestrator.py     Market orchestrator
│   ├── test_learning.py         Learning system (4 modules)
│   ├── test_paper_validation.py Paper trading workflow
│   ├── test_rolling_wfe.py      Walk-forward evaluation
│   ├── test_rl_module.py        RL module
│   └── test_integration_rl_endpoints.py  RL API
│
└── conftest.py                  Shared fixtures and test client setup
```

Dashboard tests: none yet. Dashboard coverage is done via `pnpm run build` (TypeScript type check).

---

## Running Tests

```bash
# Full suite
cd engine && .venv/Scripts/python -m pytest tests/ -v

# Sacred tests only
cd engine && .venv/Scripts/python -m pytest tests/test_safety_layer.py -v

# Integration only (slower)
cd engine && .venv/Scripts/python -m pytest tests/test_integration.py -v

# One test by name
cd engine && .venv/Scripts/python -m pytest tests/test_signals.py -v -k "test_mcl_params"

# With output (don't suppress print in tests)
cd engine && .venv/Scripts/python -m pytest tests/ -v -s

# Dashboard type check
cd dashboard && pnpm run build
```

---

## Step 1 — Find What's Missing

```bash
# See which tests are currently passing/failing
cd engine && .venv/Scripts/python -m pytest tests/ -v 2>&1 | grep -E "PASSED|FAILED|ERROR"

# Coverage (if pytest-cov is installed)
cd engine && .venv/Scripts/python -m pytest tests/ --cov=. --cov-report=term-missing 2>&1 | head -60
```

Look especially for:
- Any new file in `engine/` that has no corresponding test file
- Any safety-related code path without a test (mandatory)
- Any agent with no test in `test_pipeline_e2e.py` or `test_integration.py`

---

## Step 2 — Understand the Test Fixtures

```python
# conftest.py provides:
# - test_client: httpx.AsyncClient against the FastAPI app
# - mock_agents: dict of mocked agent instances
# - mock_safety_layer: SafetyLayer with kill switch disabled
# - db_manager: in-memory SQLite DatabaseManager

# Typical test structure:
async def test_endpoint_returns_200(test_client):
    response = await test_client.get(
        "/health",
        headers={"X-API-Key": "test-key"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
```

---

## Step 3 — Write New Tests

**Rules for new tests:**

- Test the behavior, not the implementation
- Safety-related tests: cover both the passing case AND the rejection case
- New agents: add to `test_pipeline_e2e.py` — mock the LLM, test the pipeline shape
- New endpoints: add to `test_api_contract_minimal.py` — test response shape
- New risk logic: add to `test_safety_layer.py` — SACRED file, treat with care

**Test naming convention:**
```
test_<module>_<behavior>_<outcome>
test_safety_layer_daily_loss_triggers_kill_switch
test_pipeline_missing_analyst_degrades_gracefully
test_signal_mcl_params_match_canonical
```

---

## Step 4 — Safety Layer Tests (Special Rules)

`test_safety_layer.py` is SACRED. When adding tests here:

1. Never remove or comment out existing tests
2. Cover both the approval path and each rejection path
3. Test that the kill switch cannot be bypassed
4. Test that LLM output cannot override safety decisions

Minimum coverage for any new `SafetyLayer` feature:
- [ ] Happy path: order passes all 6 checks → approved
- [ ] Failure path: order fails each check individually → rejected with correct reason
- [ ] Kill switch: trading halted → all orders rejected regardless of parameters

---

## Step 5 — Fix Failing Tests

If a test is failing:

1. Read the error message carefully
2. Determine: is the test wrong, or is the code wrong?
3. If the test was previously passing and the code changed → code is wrong, revert or fix the code
4. If a new test was just written and fails → either the test or the implementation is wrong
5. Never delete a failing test to make CI green — fix the underlying issue

---

## Step 6 — Verify

```bash
# Before declaring done: must pass completely
cd engine && .venv/Scripts/python -m pytest tests/ -v

# Dashboard still types correctly
cd dashboard && pnpm run build
```

---

## Commit

```
test: <short description of what tests were added or fixed>
```

---

## Deliverable

```
test files modified: <list>
tests added:         <count and what they cover>
tests fixed:         <count and what was wrong>
full suite result:   PASSED N / N
safety suite result: PASSED M / M (sacred)
```

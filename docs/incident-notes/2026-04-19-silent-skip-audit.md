# Silent-Skip Audit — Negative Finding

**Date**: 2026-04-19
**Triggered by**: Commit `e094861` (`fix(rl-health): align /strategies/rl/health schema + unblock 58 tests`)
**Outcome**: No additional silent-skip bugs found. The RL probe was an isolated miss.

---

## Background

Commit `e094861` fixed a three-layer stealth failure in `engine/tests/test_integration_rl_endpoints.py`:

1. The `/strategies/rl/health` endpoint returned the wrong schema shape (bare `gymnasium`/`stable_baselines3` keys instead of the `*_available` + `ready` shape the dashboard and tests expected).
2. The `jarvis_rl_integration_ready()` probe in `engine/tests/live_engine_probe.py` hit `/rl/health` instead of the real mounted path `/strategies/rl/health` (router prefix miss).
3. The `jarvis_engine_ready()` session fixture had `timeout=3`, too tight for engine startup latency.

Effect: 12 RL integration tests had been silently skipping with a misleading "engine not available" reason for the entire lifetime of that test file, even on healthy engines. The suite reported green while never exercising the RL surface.

The class of bug: **a `pytest.skip()` guarded by a probe whose claim is always false on a healthy engine**. The test runner reports a pass (skipped = not failed), the author never sees the failure, and the test is effectively dead code that consumes runtime but returns no signal.

This audit was commissioned to confirm whether other test files had the same class of bug.

---

## Methodology

1. Enumerate every probe function in `engine/tests/live_engine_probe.py` (the central probe module imported by the integration test files).
2. For each probe, extract the endpoint path(s) it hits via `_get_json(base, "<path>")`.
3. Cross-reference each path against route registrations in `engine/routers/*.py` and `engine/main.py`, accounting for `APIRouter(prefix="/foo")` declarations which mount routes under a prefix.
4. Any mismatch between the probed path and the actual mounted route → a potential stealth skip.
5. Also audit `pytest.mark.skipif(...)` predicates for tautologies, and `ConnectionError → pytest.skip()` wrappers where the wrapped endpoint might be mis-spelled.

---

## Findings

### Probe functions in `live_engine_probe.py`

| Probe function                         | Endpoint(s) probed                                   | Actual route       | Status                         |
| -------------------------------------- | ---------------------------------------------------- | ------------------ | ------------------------------ |
| `jarvis_engine_ready()`                | `/health`, `/safety/status`, `/portfolio/summary`    | same               | ✓ verified                     |
| `session4_api_ready()`                 | `/portfolio/stats/session-today`, `/analytics/*`     | same               | ✓ verified                     |
| `live_analytics_contract_ready()`      | `/analytics/performance`                             | same               | ✓ verified                     |
| `jarvis_rl_integration_ready()`        | `/strategies/rl/health`                              | same (post-fix)    | ✓ fixed in `e094861`           |
| `rl_evaluate_contract_ready()`         | `/strategies/rl/evaluate` (accepts 200/400/405/422)  | same (post-fix)    | ✓ verified                     |

All five probe functions are correct after `e094861`. No additional mis-routed probes exist.

### `pytest.mark.skipif` predicates

- `test_cache_contamination_audit.py:38` — skips when `CACHE_DIR` is empty. Legitimate CI guard; not always true.
- `test_stop_loss_invariants.py:39, 64` — skips when persistent trade DB/JSONL is absent. Legitimate CI guard.
- `test_integration_rl_endpoints.py:688` — skips when `rl_evaluate_contract_ready()` is false. Uses the fixed probe, so now correctly only skips when the endpoint is genuinely unreachable.

No suspicious skip predicates.

### `ConnectionError → pytest.skip()` wrappers

- `test_ib_gateway_connector_safety_wiring.py:40, 42, 73, 75, 100, 102` — wraps `IBGatewayManager.connect()` and skips on exception. Targets `127.0.0.1:4002` (IB Gateway), not an HTTP service. Correct detection of IB Gateway absence, not an HTTP routing bug.
- `test_integration_rl_endpoints.py:74, 88` — catches `ConnectionError`/`Timeout` from `requests.get/post` and skips. Targets `http://localhost:8010/*`. Uses generic "engine not running" skip, which is the correct behavior when the engine is genuinely down.

Both patterns are legitimate.

---

## Result

**No code changes required.** The RL probe fix in `e094861` was the only bug of this class in the repository. The audit is a deliberate negative finding: it closes the loop that the next session-closer left open in `handoff-2026-04-17-1607.md` ("worth auditing more stealth-skips").

---

## Next-audit heuristic

When adding a new `*_ready()` probe function to `engine/tests/live_engine_probe.py`, also add a sanity test that asserts the probed endpoint returns a non-404 on a healthy engine. This prevents the class of bug at the probe-write moment, not after the probe has been silently skipping tests for months. One-line fixture idea:

```python
def test_live_engine_probe_endpoints_exist(probe_function, expected_path):
    """Sanity: every probe function must target a real mounted endpoint."""
    resp = requests.get(f"{BASE_URL}{expected_path}", timeout=5)
    assert resp.status_code != 404, (
        f"Probe {probe_function.__name__} targets {expected_path}, "
        f"but engine returns 404 — route prefix likely wrong."
    )
```

This test runs on the same live engine the suite already requires, so it adds no new infrastructure.
